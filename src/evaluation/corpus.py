"""Build a frozen evaluation view from the Phase 7 shadow corpus."""

from __future__ import annotations

import json
import hashlib
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[2]
LEGAL_STATUSES = {"current", "superseded", "repealed", "historical", "draft", "unknown"}
HIGH_RISK_TERMS = (
    "法規", "法令", "法律", "法規命令", "用藥", "藥物", "動物用藥", "停藥期", "休藥期",
    "劑量", "dosage", "dose", "withdrawal", "安全界線", "安全標準", "水質標準", "法定標準",
    "安全水質",
)
LEGAL_TERMS = ("法規", "法令", "法律", "法規命令", "法條", r"第\s*[一二三四五六七八九十百0-9]+\s*條")


def read_jsonl(path: str | Path) -> list[dict[str, Any]]:
    file = Path(path)
    if not file.exists():
        return []
    return [json.loads(line) for line in file.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_jsonl(path: str | Path, rows: Iterable[dict[str, Any]]) -> None:
    file = Path(path)
    file.parent.mkdir(parents=True, exist_ok=True)
    tmp = file.with_name(file.name + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    tmp.replace(file)


def write_json(path: str | Path, value: dict[str, Any]) -> None:
    file = Path(path)
    file.parent.mkdir(parents=True, exist_ok=True)
    tmp = file.with_name(file.name + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(file)


def _truth(value: Any) -> bool:
    return value is True


def _doc_rank(record: dict[str, Any]) -> tuple[Any, ...]:
    tier = record.get("source_tier")
    return (
        record.get("duplicate_of") is not None,
        not _truth(record.get("source_verified")),
        tier if isinstance(tier, int) and not isinstance(tier, bool) else 99,
        record.get("ingestion_status") not in {"accepted", "accepted_with_warning", "indexed"},
        str(record.get("document_id", "")),
    )


def canonical_document_map(manifests: list[dict[str, Any]]) -> dict[str, str]:
    """Choose one stable document per checksum, honoring explicit duplicate_of links."""
    by_id = {str(row["document_id"]): row for row in manifests if row.get("document_id")}

    def explicit_root(doc_id: str) -> str:
        seen: set[str] = set()
        current = doc_id
        while current in by_id:
            parent = by_id[current].get("duplicate_of")
            if not parent or str(parent) not in by_id or current in seen:
                break
            seen.add(current)
            current = str(parent)
        return current

    groups: dict[str, list[str]] = defaultdict(list)
    for doc_id, row in by_id.items():
        checksum = row.get("checksum") or row.get("file_checksum")
        if checksum:
            groups[str(checksum)].append(doc_id)

    mapping = {doc_id: doc_id for doc_id in by_id}
    for ids in groups.values():
        explicit_roots = sorted({explicit_root(doc_id) for doc_id in ids})
        eligible_roots = [root for root in explicit_roots if root in by_id]
        winner = min(eligible_roots or ids, key=lambda key: _doc_rank(by_id[key]))
        for doc_id in ids:
            mapping[doc_id] = winner
    # Honor a valid duplicate link even if a checksum was absent in one manifest row.
    for doc_id in by_id:
        root = explicit_root(doc_id)
        if root in by_id:
            mapping[doc_id] = root
    return mapping


def _risk_fields(chunk: dict[str, Any], document: dict[str, Any]) -> tuple[str, str, bool]:
    metadata_fields = [
        chunk.get("chunk_strategy"), chunk.get("chunk_type"), chunk.get("topic"), chunk.get("disease"),
        chunk.get("section"), chunk.get("chapter"), document.get("title"), document.get("document_type"),
        " ".join(str(x) for x in document.get("topics", []) if x),
    ]
    metadata_labels = " ".join(str(x) for x in metadata_fields if x).casefold()
    body = str(chunk.get("text") or "").casefold()
    high = chunk.get("chunk_strategy") == "regulation" or any(term.casefold() in metadata_labels for term in HIGH_RISK_TERMS)
    high = high or any(term.casefold() in body for term in HIGH_RISK_TERMS)
    high = high or bool(re.search(
        r"(?:mg/l|mg/kg|ppm|ppt|℃|°c).{0,16}(?:安全|標準|界線|上限|下限|不得|不可超過)|"
        r"(?:安全|標準|界線|上限|下限|不得|不可超過).{0,16}(?:mg/l|mg/kg|ppm|ppt|℃|°c)",
        body, flags=re.IGNORECASE,
    ))
    legal_required = chunk.get("chunk_strategy") == "regulation" or any(
        re.search(term, metadata_labels + " " + body, flags=re.IGNORECASE) for term in LEGAL_TERMS
    )
    if high:
        requirement = "source_verified=true; legal_status=current when legal effect or currency is asserted"
        return "high", requirement, legal_required
    return "normal", "source verification pending; retrieval results are experimental only", False


def _retrieval_role(chunk: dict[str, Any]) -> str:
    status = chunk.get("ingestion_status")
    if (
        not chunk.get("chunkable")
        or status not in {"accepted", "accepted_with_warning"}
        or not str(chunk.get("text") or "").strip()
        or not chunk.get("document_id")
        or not chunk.get("source_span_ids")
        or not isinstance(chunk.get("page_start"), int)
        or not isinstance(chunk.get("page_end"), int)
    ):
        return "excluded"
    if chunk.get("chunk_type") == "parent":
        return "context_only"
    if chunk.get("chunk_type") == "child":
        return "retrieval"
    if chunk.get("chunk_strategy") == "fallback" and not chunk.get("parent_chunk_id"):
        return "retrieval"
    if chunk.get("chunk_strategy") == "table" and chunk.get("chunk_type") not in {"parent", "child"}:
        return "retrieval"
    return "excluded"


def _chunk_rank(row: dict[str, Any], canonical_docs: dict[str, str], doc_by_id: dict[str, dict[str, Any]]) -> tuple[Any, ...]:
    doc_id = str(row.get("document_id", ""))
    doc = doc_by_id.get(doc_id, {})
    return (
        doc_id != canonical_docs.get(doc_id, doc_id),
        not _truth(row.get("source_verified")),
        doc.get("source_tier") if isinstance(doc.get("source_tier"), int) else 99,
        doc_id,
        row.get("page_start") if isinstance(row.get("page_start"), int) else 10**9,
        row.get("page_end") if isinstance(row.get("page_end"), int) else 10**9,
        str(row.get("chunk_strategy", "")),
        str(row.get("chunk_type", "")),
        str(row.get("chunk_id", "")),
    )


def build_corpus(
    chunks: list[dict[str, Any]],
    manifests: list[dict[str, Any]],
    *,
    spans: list[dict[str, Any]] | None = None,
    excluded_pages: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """Return corpus rows, excluded audit rows, and a deterministic summary."""
    doc_by_id = {str(row.get("document_id")): row for row in manifests if row.get("document_id")}
    canonical_docs = canonical_document_map(manifests)
    span_by_id = {str(row.get("source_span_id")): row for row in (spans or []) if row.get("source_span_id")}
    prepared: list[dict[str, Any]] = []
    for original in chunks:
        row = dict(original)
        document_id = str(row.get("document_id", ""))
        doc = doc_by_id.get(document_id, {})
        role = _retrieval_role(row)
        canonical_doc = canonical_docs.get(document_id, document_id)
        duplicate_status = "none"
        if canonical_doc != document_id:
            duplicate_status = "duplicate_source"
            role = "excluded"
        risk, requirement, legal_required = _risk_fields(row, doc)
        verified = _truth(row.get("source_verified"))
        legal_status = row.get("legal_status") if row.get("legal_status") in LEGAL_STATUSES else "unknown"
        legal_ok = not legal_required or legal_status == "current"
        eligible = bool(
            role == "retrieval"
            and duplicate_status != "duplicate_source"
            and (risk == "normal" or (verified and legal_ok))
        )
        source_verification_status = "verified" if verified else "pending"
        item = {
            **row,
            "canonical_chunk_id": row.get("chunk_id"),
            "canonical_document_id": canonical_doc,
            "retrieval_role": role,
            "duplicate_status": duplicate_status,
            "source_verified": verified,
            "legal_status": legal_status,
            "risk_level": risk,
            "verification_requirement": requirement,
            "benchmark_eligible": eligible,
            "source_verification_status": source_verification_status,
            "source_title": doc.get("title"),
            "source_checksum": doc.get("checksum"),
            "source_url": doc.get("source_url"),
            "source_id": doc.get("source_id"),
            "source_tier": doc.get("source_tier"),
            "source_spans": [span_by_id[key] for key in row.get("source_span_ids", []) if key in span_by_id],
        }
        if role == "excluded" and duplicate_status == "none":
            item["benchmark_eligible"] = False
        prepared.append(item)

    exact_groups: dict[tuple[str, str], list[int]] = defaultdict(list)
    for index, row in enumerate(prepared):
        checksum = row.get("content_checksum")
        # Parent and child roles are deliberately separated to avoid treating the
        # expected parent-child content overlap as a duplicate.
        dedup_role = "context_only" if row["retrieval_role"] == "context_only" else "retrieval"
        if checksum and row["retrieval_role"] != "excluded":
            exact_groups[(str(checksum), dedup_role)].append(index)

    for _, indices in exact_groups.items():
        if len(indices) < 2:
            continue
        winner_i = min(indices, key=lambda i: _chunk_rank(prepared[i], canonical_docs, doc_by_id))
        winner_id = str(prepared[winner_i]["chunk_id"])
        for index in indices:
            row = prepared[index]
            row["canonical_chunk_id"] = winner_id
            if index == winner_i:
                row["duplicate_status"] = "canonical"
            else:
                row["duplicate_status"] = "exact_duplicate"
                row["retrieval_role"] = "excluded"
                row["benchmark_eligible"] = False

    # For duplicate-source copies, point at the same-checksum chunk in the
    # canonical document when one exists; otherwise use the deterministic
    # content/role winner, without changing any provenance.
    by_doc_checksum_role: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    by_checksum_role: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in prepared:
        original_role = _retrieval_role(row)
        dedup_role = "context_only" if original_role == "context_only" else "retrieval"
        if row.get("content_checksum"):
            by_doc_checksum_role[(row["canonical_document_id"], str(row["content_checksum"]), dedup_role)].append(row)
            by_checksum_role[(str(row["content_checksum"]), dedup_role)].append(row)
    for row in prepared:
        if row["duplicate_status"] != "duplicate_source":
            continue
        original_role = "context_only" if row.get("chunk_type") == "parent" else "retrieval"
        matches = by_doc_checksum_role.get((row["canonical_document_id"], str(row.get("content_checksum")), original_role), [])
        if not matches:
            matches = by_checksum_role.get((str(row.get("content_checksum")), original_role), [])
        if matches:
            winner = min(matches, key=lambda candidate: _chunk_rank(candidate, canonical_docs, doc_by_id))
            row["canonical_chunk_id"] = winner["chunk_id"]

    corpus = sorted(prepared, key=lambda row: str(row.get("chunk_id", "")))
    excluded = [
        {**row, "exclusion_reason": row["duplicate_status"] if row["duplicate_status"] in {"exact_duplicate", "duplicate_source"} else "invalid_or_review_record"}
        for row in corpus if row["retrieval_role"] == "excluded"
    ]
    for page in excluded_pages or []:
        page_document_id = str(page.get("document_id") or "")
        page_doc = doc_by_id.get(page_document_id, {})
        excluded.append({
            "record_type": "page", "document_id": page_document_id or None,
            "canonical_document_id": canonical_docs.get(page_document_id, page_document_id or None),
            "page_start": page.get("page_number"), "page_end": page.get("page_number"),
            "source_checksum": page_doc.get("checksum"), "source_title": page_doc.get("title"),
            "file_path": page_doc.get("file_path"), "source_url": page_doc.get("source_url"),
            "source_spans": [],
            "retrieval_role": "excluded", "duplicate_status": "none",
            "benchmark_eligible": False, "ingestion_status": page.get("ingestion_status"),
            "review_reason": page.get("review_reason"), "exclusion_reason": "page_not_chunked_due_to_ingestion_gate",
        })
    summary = summarize_corpus(corpus)
    summary["excluded_page_records"] = len(excluded_pages or [])
    summary["total_excluded_audit_records"] = len(excluded)
    summary["canonical_document_count"] = len(set(canonical_docs.values()))
    summary["canonical_documents_in_shadow_corpus"] = len({str(row.get("canonical_document_id")) for row in corpus if row.get("canonical_document_id")})
    summary["duplicate_source_documents"] = sum(1 for key, value in canonical_docs.items() if key != value)
    return corpus, excluded, summary


def summarize_corpus(corpus: list[dict[str, Any]]) -> dict[str, Any]:
    role_counts = Counter(row["retrieval_role"] for row in corpus)
    duplicate_counts = Counter(row["duplicate_status"] for row in corpus)
    risk_counts = Counter(row["risk_level"] for row in corpus)
    eligible_counts = Counter(bool(row["benchmark_eligible"]) for row in corpus)
    verified_counts = Counter(bool(row["source_verified"]) for row in corpus)
    by_document: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in corpus:
        by_document[str(row.get("canonical_document_id") or row.get("document_id") or "unknown")].append(row)
    verified_document_count = sum(1 for rows in by_document.values() if rows and all(_truth(row.get("source_verified")) for row in rows))
    strategy_roles: dict[str, Counter[str]] = defaultdict(Counter)
    for row in corpus:
        strategy_roles[str(row.get("chunk_strategy") or "unknown")][row["retrieval_role"]] += 1
    return {
        "schema_version": "evaluation-corpus-v1",
        "total_shadow_chunks": len(corpus),
        "retrieval_chunks": role_counts["retrieval"],
        "context_only_chunks": role_counts["context_only"],
        "excluded_chunks": role_counts["excluded"],
        "canonical_chunks": sum(count for status, count in duplicate_counts.items() if status in {"canonical", "none"}),
        "duplicate_chunks": duplicate_counts["exact_duplicate"] + duplicate_counts["duplicate_source"],
        "exact_duplicate_chunks": duplicate_counts["exact_duplicate"],
        "duplicate_source_chunks": duplicate_counts["duplicate_source"],
        "duplicate_status_counts": dict(sorted(duplicate_counts.items())),
        "benchmark_eligible": eligible_counts[True],
        "benchmark_ineligible": eligible_counts[False],
        "normal_risk": risk_counts["normal"],
        "high_risk": risk_counts["high"],
        "high_risk_blocked": sum(1 for row in corpus if row["risk_level"] == "high" and not row["benchmark_eligible"]),
        "verified_sources": verified_document_count,
        "unverified_sources": len(by_document) - verified_document_count,
        "source_counts_scope": "Unique canonical documents represented by the Shadow Corpus; chunk-level counts are reported separately.",
        "verified_chunks": verified_counts[True],
        "unverified_chunks": verified_counts[False],
        "source_verification_status_counts": dict(sorted(Counter(row["source_verification_status"] for row in corpus).items())),
        "missing_document_id": sum(not row.get("document_id") for row in corpus),
        "missing_page": sum(not isinstance(row.get("page_start"), int) or not isinstance(row.get("page_end"), int) for row in corpus),
        "missing_source_span_ids": sum(not row.get("source_span_ids") for row in corpus),
        "missing_source_span_records": sum(len(row.get("source_spans", [])) != len(row.get("source_span_ids", [])) for row in corpus),
        "missing_source_file_checksum": sum(not row.get("source_checksum") for row in corpus),
        "strategy_roles": {strategy: dict(sorted(counts.items())) for strategy, counts in sorted(strategy_roles.items())},
        "quality_claim": "No retrieval quality comparison was performed; this is a corpus and annotation framework only.",
    }


def build_from_root(root: str | Path = ROOT) -> dict[str, Any]:
    root = Path(root)
    chunks = read_jsonl(root / "data" / "shadow" / "chunks_v2.jsonl")
    manifests = read_jsonl(root / "reports" / "document_manifest.jsonl")
    spans = read_jsonl(root / "data" / "shadow" / "source_spans_v2.jsonl")
    excluded_pages = read_jsonl(root / "reports" / "chunking" / "excluded_pages.jsonl")
    corpus, excluded, summary = build_corpus(chunks, manifests, spans=spans, excluded_pages=excluded_pages)
    write_jsonl(root / "data" / "evaluation" / "corpus_v1.jsonl", corpus)
    write_jsonl(root / "data" / "evaluation" / "excluded_records.jsonl", excluded)
    write_json(root / "reports" / "evaluation" / "corpus_v1_summary.json", summary)
    def sha256(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    shadow_path = root / "data" / "shadow" / "chunks_v2.jsonl"
    manifest_path = root / "reports" / "document_manifest.jsonl"
    spans_path = root / "data" / "shadow" / "source_spans_v2.jsonl"
    corpus_path = root / "data" / "evaluation" / "corpus_v1.jsonl"
    excluded_path = root / "data" / "evaluation" / "excluded_records.jsonl"
    write_json(root / "data" / "evaluation" / "corpus_manifest.json", {
        "corpus_id": "evaluation-corpus-v1",
        "created_from": "data/shadow/chunks_v2.jsonl",
        "source_manifest": "reports/document_manifest.jsonl",
        "source_spans": "data/shadow/source_spans_v2.jsonl",
        "generated_by": "src/evaluation/corpus.py",
        "source_shadow_sha256": sha256(shadow_path),
        "source_manifest_sha256": sha256(manifest_path),
        "source_spans_sha256": sha256(spans_path),
        "evaluation_corpus_sha256": sha256(corpus_path),
        "excluded_records_sha256": sha256(excluded_path),
        "total_shadow_chunks": len(chunks),
        "corpus_records": len(corpus),
        "excluded_page_records": len(excluded_pages),
        "source_verification_policy": "Preserve existing status; never infer verification from filename, content, or registry membership.",
        "canonicalization_policy": "SHA-256 document duplicates honor duplicate_of, then deterministic source-verification/tier/status/document-id ordering; chunk duplicates group by checksum and corpus role.",
        "retrieval_role_policy": "parent=context_only; child=retrieval; fallback standalone=retrieval; invalid/review and noncanonical duplicates=excluded; table parent/context and row children/retrieval.",
        "benchmark_policy": "Normal-risk eligible rows are experimental retrieval only while source verification is pending. High-risk rows require verified source and, when legal currency matters, legal_status=current.",
        "summary": summary,
    })
    return summary
