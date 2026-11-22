"""Versioned helpers for Phase 10 corpus recovery artifacts.

This module is evaluation/recovery-only. It does not touch the production index
or any frozen v1/v2 artifact.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable


MAPPING_STATUSES = ("exact", "high_confidence", "medium_confidence", "low_confidence", "unmapped")
STATUS_RANK = {status: index for index, status in enumerate(MAPPING_STATUSES)}
STATUS_RANK = {"unmapped": 0, "low_confidence": 1, "medium_confidence": 2,
               "high_confidence": 3, "exact": 4}


def read_jsonl(path: str | Path) -> list[dict[str, Any]]:
    file = Path(path)
    if not file.exists():
        return []
    return [json.loads(line) for line in file.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_jsonl(path: str | Path, rows: Iterable[dict[str, Any]]) -> None:
    file = Path(path)
    file.parent.mkdir(parents=True, exist_ok=True)
    temp = file.with_name(file.name + ".tmp")
    temp.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
                    encoding="utf-8", newline="\n")
    temp.replace(file)


def write_json(path: str | Path, row: dict[str, Any]) -> None:
    file = Path(path)
    file.parent.mkdir(parents=True, exist_ok=True)
    temp = file.with_name(file.name + ".tmp")
    temp.write_text(json.dumps(row, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8", newline="\n")
    temp.replace(file)


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def deterministic_priority_score(*, questions: int, facts: int, species: int, categories: int,
                                 source_quality: int, recoverability: int) -> int:
    """Stable transparent score; counts are capped nowhere and booleans are not accepted."""
    values = (questions, facts, species, categories, source_quality, recoverability)
    if any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in values):
        raise ValueError("priority inputs must be non-negative integers")
    return questions * 5 + facts * 4 + species * 3 + categories * 2 + source_quality * 2 + recoverability * 2


def build_recovery_work_queue(*, local_sources: list[dict[str, Any]], missing_sources: list[dict[str, Any]],
                              fact_gaps: list[dict[str, Any]], local_impact: dict[str, Any],
                              ocr_priority: dict[str, Any], legacy_documents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Prioritize the prescribed work classes, then score candidates deterministically."""
    queue: list[dict[str, Any]] = []
    stage_rank = {"A_local_corpus_omission": 0, "B_missing_source": 1, "C_table_or_review_page": 2,
                  "D_targeted_ocr": 3, "E_legacy_doc": 4}
    for source in local_sources:
        score = deterministic_priority_score(
            questions=int(source.get("affected_question_count", len(source.get("affected_questions", [])))), facts=int(source.get("affected_fact_count", len(source.get("affected_facts", [])))),
            species=len(source.get("species", [])), categories=len(source.get("categories", [])),
            source_quality=int(source.get("source_quality", 2)), recoverability=int(source.get("recoverability", 2)))
        queue.append({**source, "work_type": "A_local_corpus_omission", "priority_score": score})
    for source in missing_sources:
        score = deterministic_priority_score(
            questions=int(source.get("affected_question_count", len(source.get("affected_questions", [])))), facts=int(source.get("affected_fact_count", len(source.get("affected_facts", [])))),
            species=len(source.get("species", [])), categories=len(source.get("categories", [])),
            source_quality=int(source.get("source_quality", 1)), recoverability=int(source.get("recoverability", 1)))
        queue.append({**source, "work_type": "B_missing_source", "priority_score": score})
    artifacts = local_impact.get("artifacts", {})
    for artifact_name, work_type in (("review_table", "C_table_or_review_page"), ("review_page", "C_table_or_review_page")):
        for item in artifacts.get(artifact_name, {}).get("documents", []):
            if not item.get("affected_question_count") and not item.get("affected_fact_count"):
                continue
            queue.append({**item, "work_type": work_type, "artifact_type": artifact_name,
                          "priority_score": deterministic_priority_score(
                              questions=int(item.get("affected_question_count", 0)), facts=int(item.get("affected_fact_count", 0)),
                              species=len(item.get("species", [])), categories=len(item.get("categories", [])),
                              source_quality=2, recoverability=1)})
    # OCR entries describe possible exposure only; they must not be counted as predicted recoveries.
    for item in ocr_priority.get("top_documents", []):
        if not item.get("affected_question_count") and not item.get("affected_fact_count"):
            continue
        queue.append({**item, "work_type": "D_targeted_ocr", "priority_score": deterministic_priority_score(
            questions=int(item.get("affected_question_count", 0)), facts=int(item.get("affected_fact_count", 0)),
            species=len(item.get("species", [])), categories=len(item.get("categories", [])),
            source_quality=2, recoverability=0), "potential_only": True})
    for item in legacy_documents:
        if not item.get("affected_question_count") and not item.get("affected_fact_count"):
            continue
        queue.append({**item, "work_type": "E_legacy_doc", "priority_score": deterministic_priority_score(
            questions=int(item.get("affected_question_count", 0)), facts=int(item.get("affected_fact_count", 0)),
            species=len(item.get("species", [])), categories=len(item.get("categories", [])),
            source_quality=1, recoverability=0)})
    queue.sort(key=lambda row: (stage_rank[row["work_type"]], -int(row["priority_score"]),
                                str(row.get("document_id") or row.get("source_alias_id") or row.get("source_id") or "")))
    for rank, row in enumerate(queue, 1):
        row["queue_rank"] = rank
    return queue


def build_missing_source_registry(gaps: list[dict[str, Any]], *, acquisitions: dict[str, dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Produce one row per workbook alias without inferring missing source values."""
    acquisitions = acquisitions or {}
    rows = []
    for gap in gaps:
        alias_id = str(gap.get("source_alias_id") or "")
        acquired = acquisitions.get(alias_id, {})
        title = gap.get("source_title")
        url = gap.get("source_url")
        rows.append({
            "source_alias_id": alias_id,
            "excel_source_id": gap.get("excel_source_id"),
            "title": title,
            "organization": acquired.get("organization") or gap.get("organization"),
            "source_url": url,
            "affected_questions": sorted(set(gap.get("affected_questions", []))),
            "affected_facts": sorted(set(gap.get("affected_facts", []))),
            "species": sorted(set(gap.get("species", []))),
            "categories": sorted(set(gap.get("categories", []))),
            "source_tier": acquired.get("source_tier"),
            "publication_year": gap.get("publication_year"),
            "publication_date": acquired.get("publication_date"),
            "identity_status": acquired.get("identity_status", gap.get("identity_status", "unresolved")),
            "authority_status": acquired.get("authority_status", gap.get("authority_status", "unknown")),
            "legal_status": acquired.get("legal_status", "unknown"),
            "effective_date": acquired.get("effective_date"),
            "version": acquired.get("version"),
            "source_verified": acquired.get("source_verified", gap.get("source_verified")),
            "acquisition_status": acquired.get("acquisition_status", "pending" if not url else "not_acquired"),
            "recovery_document_id": acquired.get("document_id"),
            "notes": acquired.get("notes"),
        })
    return sorted(rows, key=lambda row: (row["source_alias_id"], str(row.get("species") or "")))


def make_acquisition_manifest(*, document_id: str, title: str, organization: str,
                              source_url: str | None, publication_url: str | None,
                              file_path: str | Path, source_tier: int, download_date: str,
                              publication_date: str | None, version: str | None,
                              checksum: str, size: int, parser_version: str,
                              license_status: str, access_information: str,
                              identity_status: str, authority_status: str,
                              legal_status: str, effective_date: str | None = None,
                              recovery_action: str = "missing_source_acquisition") -> dict[str, Any]:
    if source_tier not in (1, 2, 3, 4):
        raise ValueError("source_tier must be 1, 2, 3, or 4")
    if len(checksum) != 64 or any(ch not in "0123456789abcdef" for ch in checksum):
        raise ValueError("checksum must be lowercase SHA-256")
    if legal_status not in {"current", "superseded", "repealed", "historical", "draft", "unknown"}:
        raise ValueError("invalid legal_status")
    return {
        "document_id": document_id, "title": title, "organization": organization,
        "source_url": source_url, "publication_url": publication_url, "source_tier": source_tier,
        "file_path": Path(file_path).as_posix(), "checksum": checksum, "file_size": size,
        "download_date": download_date, "publication_date": publication_date, "version": version,
        "effective_date": effective_date, "legal_status": legal_status,
        "identity_status": identity_status, "authority_status": authority_status,
        "license_status": license_status, "access_information": access_information,
        "parser_version": parser_version, "recovery_action": recovery_action,
    }


def merge_versioned_rows(base: list[dict[str, Any]], recovered: list[dict[str, Any]], *,
                         replace_document_ids: set[str], id_key: str, document_key: str = "document_id") -> list[dict[str, Any]]:
    """Copy the parent version, replace only explicitly reparsed documents, and deduplicate by stable ID."""
    merged: dict[str, dict[str, Any]] = {}
    for row in base:
        if str(row.get(document_key) or "") not in replace_document_ids:
            key = str(row.get(id_key) or "")
            if key:
                merged[key] = dict(row)
    for row in recovered:
        key = str(row.get(id_key) or "")
        if not key:
            raise ValueError(f"recovered record missing {id_key}")
        if key in merged and merged[key] != row:
            raise ValueError(f"conflicting stable record id: {key}")
        merged[key] = dict(row)
    return sorted(merged.values(), key=lambda row: str(row[id_key]))


def coverage_gain(previous: list[dict[str, Any]], current: list[dict[str, Any]], *,
                  recovery_actions: dict[str, str] | None = None) -> dict[str, Any]:
    """Compare question mapping without interpreting it as answer correctness."""
    before = {str(row.get("question_id")): row for row in previous}
    after = {str(row.get("question_id")): row for row in current}
    if set(before) != set(after):
        raise ValueError("Silver v2/v3 question IDs must match")
    recovery_actions = recovery_actions or {}

    def count(rows: list[dict[str, Any]]) -> dict[str, int]:
        values = Counter(str(row.get("evidence_mapping_status") or "unmapped") for row in rows)
        return {status: values[status] for status in MAPPING_STATUSES}

    def grouped(group_key: str) -> dict[str, Any]:
        groups = sorted({str(row.get(group_key) or "unknown") for row in current})
        return {group: {
            "previous": count([row for row in previous if str(row.get(group_key) or "unknown") == group]),
            "current": count([row for row in current if str(row.get(group_key) or "unknown") == group]),
        } for group in groups}

    transitions = Counter()
    upgraded: list[dict[str, Any]] = []
    downgraded: list[dict[str, Any]] = []
    actions: dict[str, set[str]] = defaultdict(set)
    for question_id in sorted(before):
        old = str(before[question_id].get("evidence_mapping_status") or "unmapped")
        new = str(after[question_id].get("evidence_mapping_status") or "unmapped")
        transitions[f"{old}->{new}"] += 1
        item = {"question_id": question_id, "from": old, "to": new}
        if STATUS_RANK.get(new, 0) > STATUS_RANK.get(old, 0):
            upgraded.append(item)
            for fact in after[question_id].get("expected_facts", []):
                for doc_id in fact.get("mapped_documents", []):
                    action = recovery_actions.get(str(doc_id))
                    if action:
                        actions[action].add(question_id)
        elif STATUS_RANK.get(new, 0) < STATUS_RANK.get(old, 0):
            downgraded.append(item)
    old_rows, new_rows = list(before.values()), list(after.values())
    return {
        "dataset_type": "AI-generated Silver Benchmark mapping coverage; not human Gold ground truth",
        "question_count": len(current),
        "previous": count(old_rows), "current": count(new_rows),
        "net_exact_high_gain": (count(new_rows)["exact"] + count(new_rows)["high_confidence"])
                              - (count(old_rows)["exact"] + count(old_rows)["high_confidence"]),
        "upgraded_questions": upgraded, "downgraded_questions": downgraded,
        "transitions": dict(sorted(transitions.items())),
        "by_species": grouped("species_candidate"), "by_category": grouped("category"),
        "gain_by_recovery_action": {key: {"upgraded_questions": len(value), "question_ids": sorted(value)}
                                    for key, value in sorted(actions.items())},
        "interpretation": "Deterministic source/fact-to-corpus mapping coverage only; no answer correctness or retrieval quality is claimed.",
    }


def validate_v3_questions(rows: list[dict[str, Any]], corpus: list[dict[str, Any]]) -> None:
    corpus_by_id = {str(row.get("chunk_id")): row for row in corpus if row.get("chunk_id")}
    for row in rows:
        if row.get("benchmark_type") != "silver" or row.get("generation_source") != "ai_question_bank":
            raise ValueError("Silver v3 questions must retain AI-generated Silver labels")
        for expected in row.get("mapped_chunks", []):
            chunk_id = str(expected.get("chunk_id") or "")
            target = corpus_by_id.get(chunk_id)
            if target is None:
                raise ValueError(f"mapped chunk does not exist in corpus v2: {chunk_id}")
            if target.get("retrieval_role") != "retrieval" or target.get("duplicate_status") in {"exact_duplicate", "duplicate_source"}:
                raise ValueError(f"mapped chunk is not canonical first-stage retrieval evidence: {chunk_id}")
            if expected.get("document_id") != target.get("document_id"):
                raise ValueError(f"mapped document does not match corpus v2 for chunk {chunk_id}")


def validate_source_provenance(chunks: list[dict[str, Any]], spans: list[dict[str, Any]],
                               manifests: list[dict[str, Any]]) -> None:
    """Fail if any chunk cannot be traced through span, page, file checksum, and manifest."""
    span_by_id = {str(row.get("source_span_id")): row for row in spans if row.get("source_span_id")}
    manifest_by_id = {str(row.get("document_id")): row for row in manifests if row.get("document_id")}
    for chunk in chunks:
        document_id = str(chunk.get("document_id") or "")
        manifest = manifest_by_id.get(document_id)
        if manifest is None:
            raise ValueError(f"chunk document missing from manifest: {document_id}")
        if not chunk.get("source_span_ids"):
            raise ValueError(f"chunk has no source spans: {chunk.get('chunk_id')}")
        for span_id in chunk["source_span_ids"]:
            span = span_by_id.get(str(span_id))
            if span is None:
                raise ValueError(f"chunk source span does not resolve: {span_id}")
            if span.get("document_id") != document_id:
                raise ValueError(f"span document mismatch for {span_id}")
            expected_checksum = manifest.get("checksum") or manifest.get("file_checksum")
            if span.get("file_checksum") != expected_checksum:
                raise ValueError(f"span checksum mismatch for {span_id}")
            page = span.get("page_number")
            if not isinstance(page, int) or page < int(chunk.get("page_start") or 1) or page > int(chunk.get("page_end") or page):
                raise ValueError(f"span page is outside chunk provenance bounds for {span_id}")
