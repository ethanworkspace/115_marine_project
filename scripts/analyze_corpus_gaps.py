"""Build Phase 9C local-only corpus/source recovery reports; no retrieval runs."""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.evaluation.corpus import read_jsonl, write_json, write_jsonl  # noqa: E402
from src.evaluation.corpus_gaps import (  # noqa: E402
    classify_fact_gap, classify_missing_source, identity_authority_status,
    mapping_counts, medium_reason, normalize_for_match, priority_score,
    stable_alias_id,
)
from src.evaluation.question_bank_import import read_xlsx_sheets  # noqa: E402
from src.evaluation.source_mapping import (  # noqa: E402
    _excel_year, _fact_rows, _similarity, _source_rows, normalize_url,
)


SPECIES = ("虱目魚", "吳郭魚", "石斑魚", "鱸魚", "烏魚", "鰻魚")
HIGH_RISK_TERMS = ("法規", "用藥", "停藥", "休藥", "劑量", "法律", "安全界線", "安全標準")
UNMAPPED_QUESTION_REASONS = {
    row["question_id"]: row
    for row in json.loads((ROOT / "reports/evaluation/unmapped_analysis.json").read_text(encoding="utf-8"))["questions"]
}


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _dedupe(values: list[Any]) -> list[Any]:
    return sorted({str(x) for x in values if x not in (None, "")})


def _file_ext(doc: dict[str, Any]) -> str:
    return Path(str(doc.get("file_path") or "")).suffix.casefold()


def _source_fields(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_id": str(row.get("來源ID") or row.get("excel_source_id") or "").strip() or None,
        "title": str(row.get("文件／頁面") or row.get("文件/頁面") or row.get("excel_source_title") or "").strip() or None,
        "url": str(row.get("URL") or row.get("excel_source_url") or "").strip() or None,
        "organization": str(row.get("機關") or row.get("organization") or "").strip() or None,
        "year": _excel_year(row.get("日期") or row.get("publication_date")),
        "checksum": row.get("checksum") or row.get("SHA256") or row.get("sha256"),
    }


def _canonical_map(manifests: list[dict[str, Any]]) -> dict[str, str]:
    by_id = {str(d.get("document_id")): d for d in manifests if d.get("document_id")}
    result = {key: key for key in by_id}
    for doc_id, doc in by_id.items():
        parent = doc.get("duplicate_of")
        if parent in by_id:
            result[doc_id] = str(parent)
    return result


def _source_matches(
    source: dict[str, Any], manifests: list[dict[str, Any]], corpus_ids: set[str],
    prior_alias: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Match local manifest candidates conservatively; lexical matches stay likely."""
    fields = _source_fields(source)
    candidates: list[dict[str, Any]] = []
    method = "unresolved"
    score = 0.0
    trace: list[dict[str, Any]] = []

    def exact_matches(kind: str) -> list[dict[str, Any]]:
        found = []
        for doc in manifests:
            title = str(doc.get("title") or "")
            stem = Path(str(doc.get("file_path") or "")).stem
            checksum = doc.get("checksum") or doc.get("file_checksum")
            if kind == "checksum" and fields["checksum"] and checksum == fields["checksum"]:
                found.append(doc)
            elif kind == "exact_source_id" and fields["source_id"] and doc.get("source_id") not in (None, "", "unverified") and str(doc.get("source_id")) == fields["source_id"]:
                found.append(doc)
            elif kind == "exact_url" and fields["url"] and normalize_url(fields["url"]) == normalize_url(doc.get("source_url")):
                found.append(doc)
            elif kind == "exact_title" and fields["title"] and normalize_for_match(fields["title"]) in {normalize_for_match(title), normalize_for_match(stem)}:
                found.append(doc)
        return sorted(found, key=lambda d: str(d.get("document_id")))

    step_reasons = {
        "checksum": "compare workbook checksum with local manifest checksums",
        "exact_source_id": "compare explicit non-placeholder local source IDs",
        "exact_url": "compare normalized source URLs",
        "exact_title": "compare normalized titles and local file stems",
    }
    for check in ("checksum", "exact_source_id", "exact_url", "exact_title"):
        found = exact_matches(check)
        trace.append({
            "step": check, "candidate_document_ids": [str(d.get("document_id")) for d in found],
            "score": 1.0 if found else 0.0, "outcome": "matched" if found else "not_matched",
            "reason": step_reasons[check],
        })
        if found:
            candidates = found
            method = check
            score = 1.0
            break

    if not candidates and fields["title"]:
        ranked = sorted(
            ((_similarity(fields["title"], str(doc.get("title") or Path(str(doc.get("file_path") or "")).stem)), doc) for doc in manifests),
            key=lambda item: (-item[0], str(item[1].get("document_id"))),
        )
        if ranked and ranked[0][0] >= 0.68 and (len(ranked) == 1 or ranked[0][0] - ranked[1][0] >= 0.10):
            candidates, score, method = [ranked[0][1]], ranked[0][0], "strong_title"
            trace.append({"step": "strong_lexical_title", "candidate_document_ids": [str(ranked[0][1].get("document_id"))], "score": round(score, 6), "outcome": "likely_candidate", "reason": "strong unique title similarity; retained as likely identity only"})
        elif ranked:
            trace.append({"step": "strong_lexical_title", "candidate_document_ids": [str(doc.get("document_id")) for score0, doc in ranked[:3]], "candidate_scores": [round(float(score0), 6) for score0, _doc in ranked[:3]], "score": round(float(ranked[0][0]), 6), "outcome": "no_match", "reason": "no candidate met the existing deterministic strong-title threshold"})
        else:
            trace.append({"step": "strong_lexical_title", "candidate_document_ids": [], "score": 0.0, "outcome": "no_match", "reason": "no local manifest documents available"})

    if not candidates and prior_alias and prior_alias.get("document_id"):
        prior = next((d for d in manifests if str(d.get("document_id")) == str(prior_alias["document_id"])), None)
        if prior:
            candidates, method = [prior], "prior_mapping_candidate"
            score = float(prior_alias.get("mapping_score") or 0.0)
            trace.append({"step": "prior_v2_mapping_candidate", "candidate_document_ids": [str(prior.get("document_id"))], "score": round(score, 6), "outcome": "candidate_only", "reason": "retained for impact analysis; not treated as verified identity"})

    canonical = _canonical_map(manifests)
    resolved = []
    for doc in candidates:
        doc_id = str(doc.get("document_id") or "")
        canonical_id = canonical.get(doc_id, doc_id)
        resolved.append({
            "document_id": doc_id,
            "canonical_document_id": canonical_id,
            "title": doc.get("title"),
            "file_path": doc.get("file_path"),
            "file_extension": _file_ext(doc),
            "duplicate_of": doc.get("duplicate_of"),
            "in_evaluation_corpus": canonical_id in corpus_ids,
            "source_verified": doc.get("source_verified"),
            "legal_status": doc.get("legal_status") or "unknown",
            "source_tier": doc.get("source_tier"),
            "organization": doc.get("organization"),
            "publication_date": doc.get("publication_date"),
            "checksum": doc.get("checksum"),
        })
    identity_basis = method if method in {"checksum", "exact_source_id", "exact_url", "known_duplicate"} else method
    status, authority = identity_authority_status(
        identity_basis=identity_basis,
        source_verified=(resolved[0].get("source_verified") if resolved else None),
        legal_status=(resolved[0].get("legal_status") if resolved else None),
        source_tier=(resolved[0].get("source_tier") if resolved else None),
    )
    return {
        **fields,
        "mapping_method": method,
        "mapping_score": round(score, 6) if candidates else None,
        "identity_status": status,
        "authority_status": authority,
        "source_verified": resolved[0].get("source_verified") if resolved else None,
        "identity_match_trace": trace,
        "local_documents": resolved,
        "corpus_document_ids": _dedupe([d["canonical_document_id"] for d in resolved if d["in_evaluation_corpus"]]),
    }


def _load_workbooks(question_rows: list[dict[str, Any]], prior_aliases: list[dict[str, Any]], manifests: list[dict[str, Any]], corpus_ids: set[str]):
    workbook_names = sorted({str(row.get("source_workbook")) for row in question_rows if row.get("source_workbook")})
    alias_by_key = {str(row.get("source_key")): row for row in prior_aliases}
    sources: dict[str, dict[str, Any]] = {}
    facts: dict[str, dict[str, Any]] = {}
    alias_records: dict[str, dict[str, Any]] = {}
    for workbook in workbook_names:
        path = ROOT / Path(workbook)
        if not path.exists():
            continue
        sheets = read_xlsx_sheets(path)
        for row in _source_rows(sheets.get("資料來源", [])):
            fields = _source_fields(row)
            key = f"{workbook}::{fields['source_id']}"
            sources[key] = row
            prior = alias_by_key.get(key)
            record = _source_matches(row, manifests, corpus_ids, prior)
            record.update({
                "source_alias_id": stable_alias_id(key),
                "source_key": key,
                "source_workbook": workbook,
                "prior_mapping_confidence": prior.get("mapping_confidence") if prior else None,
                "prior_document_id": prior.get("document_id") if prior else None,
                "prior_source_verified": prior.get("source_verified") if prior else None,
            })
            alias_records[key] = record
        for row in _fact_rows(sheets.get("事實資料庫", [])):
            fact_id = str(row.get("事實ID") or "").strip()
            if fact_id:
                facts[f"{workbook}::{fact_id}"] = row
    return sources, facts, alias_records


def _fact_source_ids(fact: dict[str, Any], mapped_fact: dict[str, Any] | None = None) -> list[str]:
    value = fact.get("來源ID") or fact.get("source_id") or (mapped_fact or {}).get("source_ids") or ""
    if isinstance(value, list):
        return _dedupe(value)
    return _dedupe(re.split(r"[;,，；、\s]+", str(value)))


def _fact_statement(fact: dict[str, Any], mapped_fact: dict[str, Any] | None = None) -> str:
    return str(
        (mapped_fact or {}).get("statement")
        or fact.get("可核對事實（已改寫）")
        or fact.get("可核對事實(已改寫)")
        or fact.get("事實內容") or ""
    ).strip()


def _risk(question: dict[str, Any], title: str = "") -> bool:
    text = " ".join([str(question.get("category") or ""), str(question.get("risk_level") or ""), title])
    return question.get("risk_level") == "high" or any(term in text for term in HIGH_RISK_TERMS)


def _records_for_question(question: dict[str, Any], source_rows: dict[str, dict[str, Any]], fact_rows: dict[str, dict[str, Any]], aliases: dict[str, dict[str, Any]]):
    workbook = str(question.get("source_workbook") or "")
    qfacts = question.get("expected_facts") or []
    output = []
    for mapped in qfacts:
        fid = str(mapped.get("fact_id") or "")
        fact = fact_rows.get(f"{workbook}::{fid}", {})
        source_ids = _fact_source_ids(fact, mapped)
        source_keys = [f"{workbook}::{sid}" for sid in source_ids]
        source_evidence = [aliases[key] for key in source_keys if key in aliases]
        docs = []
        for alias in source_evidence:
            docs.extend(alias.get("local_documents") or [])
            # A prior mapping is retained only as a candidate when the manifest match is unresolved.
            prior_id = alias.get("prior_document_id")
            if prior_id and not alias.get("local_documents"):
                docs.append({"document_id": prior_id, "canonical_document_id": prior_id, "in_evaluation_corpus": False, "candidate_basis": "prior_mapping"})
        expected_sources = question.get("expected_sources") or []
        for expected in expected_sources:
            if expected.get("excel_source_id") in source_ids and expected.get("document_id"):
                docs.append({"document_id": expected["document_id"], "canonical_document_id": expected["document_id"], "in_evaluation_corpus": str(expected["document_id"]) in {d for a in aliases.values() for d in a.get("corpus_document_ids", [])}, "candidate_basis": "silver_v2_expected_source"})
        unique_docs = {str(d.get("document_id")): d for d in docs if d.get("document_id")}
        output.append({
            "fact_id": fid or None,
            "statement": _fact_statement(fact, mapped),
            "source_ids": source_ids,
            "source_keys": source_keys,
            "source_aliases": source_evidence,
            "documents": [unique_docs[key] for key in sorted(unique_docs)],
            "mapped_fact": mapped,
            "workbook_fact": fact,
        })
    return output


def _analyze_fact_gap(fact: dict[str, Any], question: dict[str, Any], pages_by_doc: dict[str, list[dict[str, Any]]], ocr_by_doc: dict[str, list[dict[str, Any]]], tables_by_doc: dict[str, list[dict[str, Any]]], corpus_by_doc: dict[str, list[dict[str, Any]]], legacy_ids: set[str], parser_error_ids: set[str]) -> dict[str, Any]:
    docs = fact["documents"]
    doc_ids = _dedupe([value for d in docs for value in (d.get("document_id"), d.get("canonical_document_id"))])
    all_pages = [p for doc_id in doc_ids for p in pages_by_doc.get(doc_id, [])]
    ocr_pages = [p for doc_id in doc_ids for p in ocr_by_doc.get(doc_id, [])]
    review_pages = [p for p in all_pages if p.get("ingestion_status") == "review"]
    review_tables = [t for doc_id in doc_ids for t in tables_by_doc.get(doc_id, []) if t.get("ingestion_status") == "review"]
    corpus_rows = [r for doc_id in doc_ids for r in corpus_by_doc.get(doc_id, [])]
    statement = fact["statement"]
    norm = normalize_for_match(statement)
    exact_page_match = any(norm and norm in normalize_for_match(p.get("native_text")) for p in all_pages)
    exact_corpus_match = any(norm and norm in normalize_for_match(r.get("text")) for r in corpus_rows)
    best_page_score = max((_similarity(statement, str(p.get("native_text") or "")) for p in all_pages), default=0.0)
    best_chunk_score = max((_similarity(statement, str(r.get("text") or "")) for r in corpus_rows), default=0.0)
    page_hints = {
        int(item.get("page")) for item in (fact.get("mapped_fact", {}).get("mapped_pages") or [])
        if isinstance(item.get("page"), int)
    }
    for key, value in fact.get("workbook_fact", {}).items():
        if "頁" in str(key) and value is not None:
            match = re.search(r"\d+", str(value))
            if match:
                page_hints.add(int(match.group(0)))
    ocr_page_numbers = {int(p["page_number"]) for p in ocr_pages if isinstance(p.get("page_number"), int)}
    linked_ocr_pages = ocr_page_numbers & page_hints
    linked_review_pages = [
        p for p in review_pages
        if p.get("page_number") in page_hints or (norm and norm in normalize_for_match(p.get("native_text")))
    ]
    linked_tables = [
        t for t in review_tables
        if t.get("page_number") in page_hints
        or (statement and _similarity(statement, str(t.get("markdown") or "")) >= 0.25)
    ]
    numeric_or_table_topic = bool(re.search(r"\d|mg/L|ppm|ppt|℃|%|水質|疾病|用藥|劑量", statement, re.I)) or question.get("category") in {"calculation", "water_quality", "drug", "regulation"}
    evidence = {
        "legacy_doc": any(str(d.get("document_id")) in legacy_ids or str(d.get("canonical_document_id")) in legacy_ids for d in docs),
        "ocr_candidate": bool(linked_ocr_pages),
        "review_page": bool(linked_review_pages),
        "review_table": bool(linked_tables and numeric_or_table_topic),
        "accepted_page_match": (exact_page_match or best_page_score >= 0.42) and any(p.get("ingestion_status") in {"accepted", "accepted_with_warning"} for p in all_pages) and not exact_corpus_match,
        "parser_error": any(doc_id in parser_error_ids for doc_id in doc_ids) or (bool(doc_ids) and not all_pages),
        "paraphrase_candidate": best_page_score >= 0.22 or best_chunk_score >= 0.22,
        "source_mismatch": not bool(doc_ids),
    }
    reason = classify_fact_gap(evidence)
    return {
        "question_id": question.get("question_id"),
        "fact_id": fact.get("fact_id"),
        "workbook": question.get("source_workbook"),
        "species": question.get("species_candidate"),
        "category": question.get("category"),
        "source_ids": fact.get("source_ids", []),
        "candidate_document_ids": doc_ids,
        "fact_statement": statement,
        "fact_gap_reason": reason,
        "reason_is_candidate_not_causal_proof": True,
        "evidence_flags": evidence,
        "candidate_page_records": len(all_pages),
        "review_page_records": len(review_pages),
        "page_hints": sorted(page_hints),
        "ocr_candidate_pages": len(ocr_pages),
        "ocr_page_linked_candidates": len(linked_ocr_pages),
        "review_table_candidates": len(review_tables),
        "page_linked_review_tables": len(linked_tables),
        "exact_extracted_page_match": exact_page_match,
        "best_page_lexical_score": round(best_page_score, 6),
        "best_chunk_lexical_score": round(best_chunk_score, 6),
        "requested_page_hint_present": bool(fact.get("mapped_fact", {}).get("mapped_pages")),
    }


def _source_recovery_reason(source: dict[str, Any], affected_questions: list[dict[str, Any]]) -> str:
    original_reasons = {UNMAPPED_QUESTION_REASONS.get(q["question_id"], {}).get("reason") for q in affected_questions}
    if "source_not_in_corpus" in original_reasons:
        return "source_not_in_corpus"
    return "fact_not_found" if "fact_not_found" in original_reasons else "mapping_gap"


def main() -> int:
    output_dir = ROOT / "reports/corpus_gap"
    output_dir.mkdir(parents=True, exist_ok=True)
    manifests = read_jsonl(ROOT / "reports/document_manifest.jsonl")
    manifest_by_id = {str(row.get("document_id")): row for row in manifests if row.get("document_id")}
    corpus = read_jsonl(ROOT / "data/evaluation/corpus_v1.jsonl")
    silver = read_jsonl(ROOT / "data/evaluation/silver/questions_v2.jsonl")
    prior_aliases = read_jsonl(ROOT / "data/evaluation/source_alias_registry.jsonl")
    pages = read_jsonl(ROOT / "reports/parsing/page_inventory.jsonl")
    ocr_candidates = read_jsonl(ROOT / "reports/parsing/ocr_candidates.jsonl")
    tables = read_jsonl(ROOT / "reports/tables/table_inventory.jsonl")
    legacy = read_json(ROOT / "reports/recovery/legacy_doc.json")
    parser_quality = read_json(ROOT / "reports/parsing/parser_quality.json")
    table_summary = read_json(ROOT / "reports/tables/table_summary.json")
    corpus_ids = {str(row.get("canonical_document_id") or row.get("document_id")) for row in corpus}
    corpus_source_by_doc = {}
    for row in corpus:
        corpus_source_by_doc.setdefault(str(row.get("canonical_document_id") or row.get("document_id")), row)
    eligibility_by_doc = {str(row.get("document_id")): row for row in read_jsonl(ROOT / "reports/parsing/document_eligibility.jsonl")}
    for manifest in manifests:
        doc_id = str(manifest.get("document_id") or "")
        corpus_row = corpus_source_by_doc.get(doc_id, {})
        eligibility = eligibility_by_doc.get(doc_id, {})
        if "source_verified" not in manifest:
            manifest["source_verified"] = corpus_row.get("source_verified", eligibility.get("source_verified"))
        if manifest.get("legal_status") in (None, ""):
            manifest["legal_status"] = corpus_row.get("legal_status", eligibility.get("legal_status", "unknown"))
    corpus_by_doc: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in corpus:
        corpus_by_doc[str(row.get("canonical_document_id") or row.get("document_id"))].append(row)
    pages_by_doc: dict[str, list[dict[str, Any]]] = defaultdict(list)
    ocr_by_doc: dict[str, list[dict[str, Any]]] = defaultdict(list)
    tables_by_doc: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in pages:
        if row.get("document_id"):
            pages_by_doc[str(row["document_id"])].append(row)
    for row in ocr_candidates:
        if row.get("document_id"):
            ocr_by_doc[str(row["document_id"])].append(row)
    for row in tables:
        if row.get("document_id"):
            tables_by_doc[str(row["document_id"])].append(row)
    legacy_docs = legacy.get("documents", [])
    legacy_ids = {str(d.get("document_id")) for d in legacy_docs if d.get("document_id")}
    parser_error_ids = {
        str(row.get("document_id")) for row in pages
        if row.get("classification") == "parser_error" and row.get("document_id")
    }

    source_rows, fact_rows, aliases = _load_workbooks(silver, prior_aliases, manifests, corpus_ids)
    alias_by_id = {row["source_alias_id"]: row for row in aliases.values()}

    # Review all 75 medium mappings, preserving their original status.
    medium_questions = [q for q in silver if q.get("evidence_mapping_status") == "medium_confidence"]
    medium_report = []
    for q in medium_questions:
        reason = medium_reason(q)
        medium_report.append({
            "question_id": q["question_id"], "species": q.get("species_candidate"),
            "category": q.get("category"), "current_mapping_status": q.get("evidence_mapping_status"),
            "medium_reason": reason,
            "source_ids": _dedupe([s.get("excel_source_id") or s.get("source_id") for s in q.get("expected_sources", [])]),
            "what_is_missing": {
                "source_identity": any(s.get("source_mapping_confidence") not in {"exact", "high"} for s in q.get("expected_sources", [])),
                "fact_text": any(not f.get("statement") for f in q.get("expected_facts", [])),
                "page_identity": any(not f.get("mapped_pages") for f in q.get("expected_facts", [])),
                "chunk_granularity": any(not f.get("mapped_chunks") for f in q.get("expected_facts", [])),
                "duplicate_source_review": any(s.get("duplicate_source_candidate") for s in q.get("expected_sources", [])),
                "metadata": not bool(q.get("expected_sources") and q.get("expected_facts")),
            },
            "additional_evidence_to_reach_high": [
                item for item, missing in (
                    ("exact source identity or explicit canonical duplicate link", any(s.get("source_mapping_confidence") not in {"exact", "high"} for s in q.get("expected_sources", []))),
                    ("fact text directly present in a retrieval-eligible chunk", any(not f.get("mapped_chunks") for f in q.get("expected_facts", []))),
                    ("page identity linked to each evidence chunk", any(not f.get("mapped_pages") for f in q.get("expected_facts", []))),
                ) if missing
            ],
            "confidence_changed": False,
        })
    write_jsonl(output_dir / "medium_mapping_analysis_v2.jsonl", medium_report)

    # Fact-level local recovery hypotheses for the 30 original fact_not_found questions.
    old_fact_qids = {qid for qid, row in UNMAPPED_QUESTION_REASONS.items() if row.get("reason") == "fact_not_found"}
    q_by_id = {str(q.get("question_id")): q for q in silver}
    fact_gap_rows = []
    q_fact_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for qid in sorted(old_fact_qids):
        q = q_by_id.get(qid)
        if not q:
            continue
        for fact in _records_for_question(q, source_rows, fact_rows, aliases):
            row = _analyze_fact_gap(fact, q, pages_by_doc, ocr_by_doc, tables_by_doc, corpus_by_doc, legacy_ids, parser_error_ids)
            fact_gap_rows.append(row)
            q_fact_rows[qid].append(row)
    write_jsonl(output_dir / "fact_gaps.jsonl", fact_gap_rows)
    fact_reason_counts = Counter(row["fact_gap_reason"] for row in fact_gap_rows)
    question_reason_counts = Counter(
        next((reason for reason in ("legacy_doc", "ocr_missing", "table_unparsed", "review_page", "chunking_loss", "parser_loss", "fact_paraphrase", "source_mismatch") if any(r["fact_gap_reason"] == reason for r in q_fact_rows[qid])), "unknown")
        for qid in old_fact_qids if qid in q_fact_rows
    )
    write_json(output_dir / "fact_gap_summary.json", {
        "source_question_count": len(old_fact_qids),
        "analyzed_question_count": len(q_fact_rows),
        "fact_record_count": len(fact_gap_rows),
        "question_reason_distribution": dict(sorted(question_reason_counts.items())),
        "fact_reason_distribution": dict(sorted(fact_reason_counts.items())),
        "page_linked_review_page_facts": sum(bool(row.get("evidence_flags", {}).get("review_page")) for row in fact_gap_rows),
        "page_linked_review_table_facts": sum(bool(row.get("evidence_flags", {}).get("review_table")) for row in fact_gap_rows),
        "page_linked_ocr_facts": sum(bool(row.get("evidence_flags", {}).get("ocr_candidate")) for row in fact_gap_rows),
        "counts_are_recovery_candidates_not_causal_proof": True,
    })

    # Missing-source analysis by source alias among the original 31 source_not_in_corpus questions.
    old_source_qids = {qid for qid, row in UNMAPPED_QUESTION_REASONS.items() if row.get("reason") == "source_not_in_corpus"}
    alias_questions: dict[str, set[str]] = defaultdict(set)
    alias_facts_by_question: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    alias_species: dict[str, set[str]] = defaultdict(set)
    alias_categories: dict[str, set[str]] = defaultdict(set)
    alias_high_risk: dict[str, bool] = defaultdict(bool)
    question_facts_cache: dict[str, list[dict[str, Any]]] = {}
    for qid in sorted({q["question_id"] for q in silver}):
        q = q_by_id[qid]
        qfacts = _records_for_question(q, source_rows, fact_rows, aliases)
        question_facts_cache[qid] = qfacts
        for fact in qfacts:
            for key in fact["source_keys"]:
                alias_questions[key].add(qid)
                fact_ref = f"{q.get('source_workbook')}::{fact.get('fact_id')}"
                alias_facts_by_question[key][qid].add(fact_ref)
                if q.get("species_candidate"):
                    alias_species[key].add(str(q["species_candidate"]))
                if q.get("category"):
                    alias_categories[key].add(str(q["category"]))
                alias_high_risk[key] = alias_high_risk[key] or _risk(q, aliases.get(key, {}).get("title") or "")

    missing_records = []
    for key in sorted({k for qid in old_source_qids for fact in question_facts_cache.get(qid, []) for k in fact["source_keys"]}):
        alias = aliases.get(key)
        if not alias:
            missing_records.append({"source_alias_id": stable_alias_id(key), "source_key": key, "classification": "source_identifier_missing", "affected_questions": sorted(alias_questions.get(key, set()) & old_source_qids)})
            continue
        docs = alias.get("local_documents", [])
        exact_id_present = bool(alias.get("source_id"))
        title = alias.get("title")
        url = alias.get("url")
        review_only = bool(docs) and not any(doc.get("in_evaluation_corpus") for doc in docs)
        known_duplicate = any(doc.get("duplicate_of") and doc.get("canonical_document_id") in corpus_ids for doc in docs)
        date_year = alias.get("year")
        different_version = any(date_year and _excel_year(doc.get("publication_date")) and date_year != _excel_year(doc.get("publication_date")) for doc in docs)
        metadata_mismatch = bool(docs) and any(
            (url and doc.get("source_url") and normalize_url(url) != normalize_url(doc.get("source_url")))
            or (alias.get("organization") and doc.get("organization") and normalize_for_match(alias["organization"]) != normalize_for_match(doc["organization"]))
            for doc in docs
        )
        reason = classify_missing_source({
            "known_duplicate": known_duplicate,
            "different_version": different_version,
            "review_only": review_only,
            "metadata_mismatch": metadata_mismatch,
            "source_identifier": exact_id_present,
            "source_title": title,
            "source_url": url,
            "identity_fields_present": bool(title or url or exact_id_present),
            "local_identity_match": bool(docs),
        })
        impacted_qids = sorted(alias_questions.get(key, set()) & old_source_qids)
        impacted = [q_by_id[qid] for qid in impacted_qids]
        impacted_fact_refs = sorted({fact_ref for qid in impacted_qids for fact_ref in alias_facts_by_question[key].get(qid, set())})
        missing_records.append({
            "source_alias_id": alias["source_alias_id"], "source_key": key,
            "excel_source_id": alias.get("source_id"), "source_title": title,
            "source_url": url, "organization": alias.get("organization"), "publication_year": date_year,
            "prior_mapping_confidence": alias.get("prior_mapping_confidence"),
            "local_identity_method": alias.get("mapping_method"), "local_identity_score": alias.get("mapping_score"),
            "identity_status": alias.get("identity_status"), "authority_status": alias.get("authority_status"),
            "source_verified": alias.get("source_verified"),
            "identity_match_trace": alias.get("identity_match_trace", []),
            "classification": reason,
            "candidate_local_documents": docs,
            "evaluation_corpus_document_ids": alias.get("corpus_document_ids", []),
            "affected_questions": impacted_qids,
            "affected_facts": impacted_fact_refs,
            "species": sorted(alias_species.get(key, set())),
            "categories": sorted(alias_categories.get(key, set())),
            "evidence_fields_checked": ["source_id", "title", "URL", "organization", "year", "checksum", "duplicate_of", "Evaluation Corpus membership"],
            "authority_verified": False,
        })
    write_jsonl(output_dir / "missing_sources.jsonl", missing_records)
    missing_summary = Counter(row.get("classification", "unknown") for row in missing_records)

    # Per-document exposure counts for OCR, old DOC conversion, tables, and page reviews.
    gap_question_ids = {q["question_id"] for q in silver if q.get("evidence_mapping_status") in {"medium_confidence", "low_confidence", "unmapped"}}
    local_exposure: dict[str, dict[str, set[str]]] = defaultdict(lambda: {"questions": set(), "facts": set(), "species": set(), "categories": set()})
    fact_detail_by_q: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for q in silver:
        if q["question_id"] not in gap_question_ids:
            continue
        for fact in question_facts_cache.get(q["question_id"], []):
            detail = _analyze_fact_gap(fact, q, pages_by_doc, ocr_by_doc, tables_by_doc, corpus_by_doc, legacy_ids, parser_error_ids)
            fact_detail_by_q[q["question_id"]].append(detail)
            for doc_id in detail["candidate_document_ids"]:
                impact = local_exposure[doc_id]
                impact["questions"].add(q["question_id"])
                impact["facts"].add(f"{q.get('source_workbook')}::{detail.get('fact_id')}")
                if q.get("species_candidate"):
                    impact["species"].add(str(q["species_candidate"]))
                if q.get("category"):
                    impact["categories"].add(str(q["category"]))

    ocr_doc_rows = []
    for doc_id, rows in sorted(ocr_by_doc.items()):
        impact = local_exposure.get(doc_id, {})
        ocr_doc_rows.append({
            "document_id": doc_id,
            "candidate_pages": len(rows),
            "affected_questions": sorted(impact.get("questions", set())),
            "affected_question_count": len(impact.get("questions", set())),
            "affected_facts": sorted(impact.get("facts", set())),
            "affected_fact_count": len(impact.get("facts", set())),
            "species": sorted(impact.get("species", set())),
            "categories": sorted(impact.get("categories", set())),
            "potential_only": True,
        })
    ocr_doc_rows.sort(key=lambda row: (-row["affected_question_count"], -row["affected_fact_count"], row["document_id"]))
    ocr_questions = {qid for row in ocr_doc_rows for qid in row["affected_questions"]}
    ocr_facts = {fid for row in ocr_doc_rows for fid in row["affected_facts"]}
    ocr_page_linked_questions = {
        qid for qid, details in fact_detail_by_q.items()
        if any(row.get("evidence_flags", {}).get("ocr_candidate") for row in details)
    }
    ocr_page_linked_facts = {
        f"{row.get('workbook')}::{row.get('fact_id')}"
        for details in fact_detail_by_q.values() for row in details
        if row.get("evidence_flags", {}).get("ocr_candidate")
    }
    write_json(output_dir / "ocr_priority.json", {
        "ocr_candidates": len(ocr_candidates), "ocr_success_pages": parser_quality.get("ocr_success_pages", 0),
        "backend_unavailable_pages": parser_quality.get("ocr_backend_unavailable_pages", len(ocr_candidates)),
        "backend": parser_quality.get("ocr_backend", {}).get("selected_backend"),
        "candidate_question_upper_bound": len(ocr_questions), "candidate_fact_upper_bound": len(ocr_facts),
        "page_linked_question_candidates": len(ocr_page_linked_questions),
        "page_linked_fact_candidates": len(ocr_page_linked_facts),
        "these_are_potential_exposures_not_predicted_recoveries": True,
        "top_documents": ocr_doc_rows[:30],
        "installation_advice": parser_quality.get("ocr_backend", {}).get("installation_advice"),
    })

    artifact_sets: dict[str, set[str]] = {
        "legacy_doc": legacy_ids,
        "review_table": {doc_id for doc_id, rows in tables_by_doc.items() if any(row.get("ingestion_status") == "review" for row in rows)},
        "review_page": {doc_id for doc_id, rows in pages_by_doc.items() if any(row.get("ingestion_status") == "review" for row in rows)},
    }
    artifact_reports = {}
    for artifact, doc_set in artifact_sets.items():
        docs_report = []
        for doc_id in sorted(doc_set):
            impact = local_exposure.get(doc_id, {})
            count = sum(1 for row in pages_by_doc.get(doc_id, []) if row.get("ingestion_status") == "review") if artifact == "review_page" else sum(1 for row in tables_by_doc.get(doc_id, []) if row.get("ingestion_status") == "review") if artifact == "review_table" else 1
            docs_report.append({
                "document_id": doc_id,
                "document_title": manifest_by_id.get(doc_id, {}).get("title"),
                "file_path": manifest_by_id.get(doc_id, {}).get("file_path"),
                "artifact_count": count,
                "affected_questions": sorted(impact.get("questions", set())),
                "affected_question_count": len(impact.get("questions", set())),
                "affected_facts": sorted(impact.get("facts", set())),
                "affected_fact_count": len(impact.get("facts", set())),
                "species": sorted(impact.get("species", set())), "categories": sorted(impact.get("categories", set())),
                "impact_is_candidate_only": True,
            })
        docs_report.sort(key=lambda row: (-row["affected_question_count"], -row["artifact_count"], row["document_id"]))
        affected_qids = {q for row in docs_report for q in row["affected_questions"]}
        affected_questions = [q_by_id[q] for q in sorted(affected_qids) if q in q_by_id]
        evidence_key = {"legacy_doc": "legacy_doc", "review_table": "review_table", "review_page": "review_page"}[artifact]
        page_linked_rows = [
            row for details in fact_detail_by_q.values() for row in details
            if row.get("evidence_flags", {}).get(evidence_key)
        ]
        artifact_reports[artifact] = {
            "artifact_documents": len(doc_set),
            "artifact_total": sum(row["artifact_count"] for row in docs_report),
            "candidate_questions": len(affected_qids),
            "candidate_facts": len({f for row in docs_report for f in row["affected_facts"]}),
            "page_linked_question_count": len({row["question_id"] for row in page_linked_rows}),
            "page_linked_fact_count": len({f"{row.get('workbook')}::{row.get('fact_id')}" for row in page_linked_rows}),
            "by_species": dict(sorted(Counter(q.get("species_candidate") or "unknown" for q in affected_questions).items())),
            "by_category": dict(sorted(Counter(q.get("category") or "unknown" for q in affected_questions).items())),
            "documents": docs_report,
        }
    write_json(output_dir / "local_artifact_impact.json", {
        "page_inventory_review_records": sum(p.get("ingestion_status") == "review" for p in pages),
        "ocr_candidate_pages": len(ocr_candidates),
        "legacy_doc_conversion_total": len(legacy_docs),
        "legacy_doc_conversion_success": sum(d.get("conversion_status") == "success" for d in legacy_docs),
        "review_tables": sum(t.get("ingestion_status") == "review" for t in tables),
        "table_classification_counts": table_summary.get("classification_counts", {}),
        "table_review_reason_counts": table_summary.get("classification_reason_counts", {}),
        "artifacts": artifact_reports,
        "notes": [
            "Per-question/fact values are deterministic exposure counts based on source-to-document identity candidates; they are not proof that the artifact contains the missing fact.",
            "Review page count is from page_inventory ingestion_status; parser_quality.manual_review_pages uses a narrower PDF-page classification and is not the same denominator.",
        ],
    })

    # All source/fact/species/category gap combinations with stable alias IDs.
    gap_groups: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    gap_questions = [q for q in silver if q.get("evidence_mapping_status") in {"medium_confidence", "low_confidence", "unmapped"}]
    for q in gap_questions:
        for fact in question_facts_cache.get(q["question_id"], []):
            for key in fact["source_keys"] or [f"{q.get('source_workbook')}::unknown"]:
                alias = aliases.get(key)
                alias_id = alias["source_alias_id"] if alias else stable_alias_id(key)
                fid = str(fact.get("fact_id") or "unknown")
                species = str(q.get("species_candidate") or "unknown")
                category = str(q.get("category") or "unknown")
                group_key = (alias_id, fid, species, category)
                group = gap_groups.setdefault(group_key, {
                    "source_alias_id": alias_id, "excel_source_id": alias.get("source_id") if alias else None,
                    "source_title": alias.get("title") if alias else None, "source_url": alias.get("url") if alias else None,
                    "fact_id": fid, "affected_questions": set(), "affected_facts": set(), "species": set(), "categories": set(),
                    "mapping_statuses": set(), "risk_high": False,
                })
                group["affected_questions"].add(q["question_id"])
                group["affected_facts"].add(f"{q.get('source_workbook')}::{fid}")
                group["species"].add(species)
                group["categories"].add(category)
                group["mapping_statuses"].add(str(q.get("evidence_mapping_status")))
                group["risk_high"] = group["risk_high"] or _risk(q, group.get("source_title") or "")
    gap_rows = []
    for group in gap_groups.values():
        qids = sorted(group.pop("affected_questions"))
        facts_set = sorted(group.pop("affected_facts"))
        species_set = sorted(group.pop("species"))
        category_set = sorted(group.pop("categories"))
        statuses = sorted(group.pop("mapping_statuses"))
        high_risk = group.pop("risk_high")
        source_key = next((key for key, alias in aliases.items() if alias.get("source_alias_id") == group["source_alias_id"]), "")
        alias = aliases.get(source_key, {})
        matches = alias.get("local_documents", [])
        reason = "source_identity_incomplete" if not matches or alias.get("identity_status") == "unresolved" else "fact_match_incomplete"
        if matches and any(doc.get("duplicate_of") for doc in matches):
            reason = "duplicate_source"
        feasibility = 6 if any(doc.get("in_evaluation_corpus") for doc in matches) else 5 if matches else 0
        score = priority_score(affected_questions=len(qids), affected_facts=len(facts_set), species_count=len(species_set), category_count=len(category_set), high_risk=high_risk, feasibility=feasibility)
        gap_rows.append({
            **group,
            "affected_questions": qids, "affected_facts": facts_set, "species": species_set, "categories": category_set,
            "current_mapping_status": statuses, "gap_reason": reason,
            "priority_score": score, "identity_status": alias.get("identity_status", "unresolved"),
            "authority_status": alias.get("authority_status", "unknown"),
        })
    gap_rows.sort(key=lambda row: (row["source_alias_id"], row["fact_id"], row["species"], row["categories"]))
    write_jsonl(output_dir / "gap_registry.jsonl", gap_rows)

    # Source registry with separate identity/authority labels and recovery action.
    recovery_rows = []
    identity_rows = []
    for key, alias in sorted(aliases.items()):
        qids = sorted(alias_questions.get(key, set()) & gap_question_ids)
        affected_qs = [q_by_id[qid] for qid in qids]
        affected_fact_ids = sorted({fact_ref for qid in qids for fact_ref in alias_facts_by_question[key].get(qid, set())})
        docs = alias.get("local_documents", [])
        doc_ids = _dedupe([d.get("document_id") for d in docs])
        has_ocr = any(doc_id in ocr_by_doc for doc_id in doc_ids)
        has_legacy = any(doc_id in legacy_ids for doc_id in doc_ids) or any(_file_ext(d) == ".doc" for d in docs)
        has_review_tables = any(any(t.get("ingestion_status") == "review" for t in tables_by_doc.get(doc_id, [])) for doc_id in doc_ids)
        review_only = bool(docs) and not any(d.get("in_evaluation_corpus") for d in docs)
        if has_legacy:
            action = "convert_legacy_doc"
        elif has_ocr:
            action = "run_ocr"
        elif has_review_tables:
            action = "review_table"
        elif review_only:
            action = "verify_existing_document"
        elif docs:
            action = "repair_metadata" if alias.get("mapping_method") == "exact_title" else "verify_existing_document"
        else:
            action = "add_missing_document"
        high_risk = any(_risk(q, alias.get("title") or "") for q in affected_qs)
        feasibility = 6 if any(d.get("in_evaluation_corpus") for d in docs) else 5 if docs else 0
        score = priority_score(
            affected_questions=len(qids), affected_facts=len(affected_fact_ids),
            species_count=len(alias_species.get(key, set())), category_count=len(alias_categories.get(key, set())),
            high_risk=high_risk, feasibility=feasibility,
        )
        gap_type = _source_recovery_reason(alias, affected_qs)
        recovery_rows.append({
            "source_alias_id": alias["source_alias_id"], "source_id": alias.get("source_id"),
            "title": alias.get("title"), "source_url": alias.get("url"), "gap_type": gap_type,
            "affected_questions": qids, "affected_question_count": len(qids),
            "affected_facts": affected_fact_ids, "affected_fact_count": len(affected_fact_ids),
            "recovery_action": action, "priority": score,
            "identity_status": alias.get("identity_status"), "authority_status": alias.get("authority_status"),
            "source_verified": alias.get("source_verified"), "candidate_document_ids": doc_ids,
            "local_review_only": review_only,
            "action_constraints": "Local-only this phase; add_missing_document is a plan only and does not download anything.",
        })
        identity_rows.append({
            "source_alias_id": alias["source_alias_id"], "source_key": key,
            "excel_source_id": alias.get("source_id"), "source_title": alias.get("title"), "source_url": alias.get("url"),
            "mapping_method": alias.get("mapping_method"), "mapping_score": alias.get("mapping_score"),
            "identity_status": alias.get("identity_status"), "authority_status": alias.get("authority_status"),
            "source_verified": alias.get("source_verified"), "candidate_local_documents": docs,
            "identity_match_trace": alias.get("identity_match_trace", []),
            "authority_verification_performed": False,
        })
    recovery_rows.sort(key=lambda row: (-row["priority"], row["source_alias_id"]))
    identity_rows.sort(key=lambda row: row["source_alias_id"])
    write_jsonl(ROOT / "data/recovery/source_recovery_plan.jsonl", recovery_rows)
    write_jsonl(output_dir / "source_identity_authority.jsonl", identity_rows)
    identity_summary = {
        "identity_status": dict(Counter(row["identity_status"] for row in identity_rows)),
        "authority_status": dict(Counter(row["authority_status"] for row in identity_rows)),
        "matched_local_manifest_aliases": sum(bool(row.get("candidate_local_documents")) for row in identity_rows),
        "local_manifest_but_not_evaluation_corpus": sum(bool(row.get("candidate_local_documents")) and not any(doc.get("in_evaluation_corpus") for doc in row["candidate_local_documents"]) for row in identity_rows),
        "aliases_with_duplicate_document_candidate": sum(any(doc.get("duplicate_of") for doc in row.get("candidate_local_documents", [])) for row in identity_rows),
        "manifest_duplicate_links": sum(bool(row.get("duplicate_of")) for row in manifests),
        "identity_method_counts": dict(Counter(row.get("mapping_method") for row in identity_rows)),
        "source_verified_true": sum(row.get("source_verified") is True for row in identity_rows),
        "source_verified_false": sum(row.get("source_verified") is False for row in identity_rows),
        "source_verified_unknown": sum(row.get("source_verified") is None for row in identity_rows),
        "authority_not_inferred_from_identity": True,
    }
    write_json(output_dir / "source_identity_authority_summary.json", identity_summary)

    top20 = recovery_rows[:20]
    write_json(output_dir / "recovery_priority_top20.json", {
        "formula": "10*questions + 5*facts + 3*species + 2*categories + 8 if high-risk + feasibility(0..6)",
        "deterministic": True,
        "priority_count": len(top20),
        "items": top20,
    })

    # Per-source recovery plan is also emitted as a separate user-facing gap ledger.
    write_json(output_dir / "missing_sources_summary.json", {
        "source_alias_count": len(missing_records),
        "affected_question_count": len(old_source_qids),
        "classification_counts": dict(sorted(missing_summary.items())),
        "source_presence_is_not_source_authority": True,
    })

    # Coverage distribution remains explicitly Silver v2; no v3 copy if mapping did not change.
    by_species = {fish: mapping_counts([q for q in silver if q.get("species_candidate") == fish]) for fish in SPECIES}
    all_categories = sorted({str(q.get("category") or "unknown") for q in silver})
    by_category = {category: mapping_counts([q for q in silver if q.get("category") == category]) for category in all_categories}
    write_json(output_dir / "silver_v3_status.json", {
        "silver_v2_questions": len(silver), "silver_v2_mapping": mapping_counts(silver),
        "by_species": by_species, "by_category": by_category,
        "silver_v3_built": False,
        "reason": "No local parser/OCR/conversion/table recovery created new retrieval-eligible evidence, and no source-identity overlay changed a Silver v2 mapped chunk or question mapping status. A v3 copy would duplicate v2 without a material improvement.",
        "silver_v3_readiness": False,
        "readiness_thresholds_unchanged": {"exact_plus_high_at_least": 40, "species_at_least": 4, "categories_at_least": 4},
    })

    write_json(output_dir / "phase9c_summary.json", {
        "silver_questions": len(silver), "silver_v2_mapping": mapping_counts(silver),
        "gap_registry_records": len(gap_rows),
        "questions_with_medium_low_or_unmapped_status": len(gap_question_ids),
        "v2_by_species": by_species,
        "v2_by_category": by_category,
        "old_source_not_in_corpus_questions": len(old_source_qids),
        "missing_source_alias_records": len(missing_records),
        "missing_source_classification_counts": dict(sorted(missing_summary.items())),
        "old_fact_not_found_questions": len(old_fact_qids),
        "fact_gap_records": len(fact_gap_rows),
        "fact_gap_question_reason_distribution": dict(sorted(question_reason_counts.items())),
        "fact_gap_fact_reason_distribution": dict(sorted(fact_reason_counts.items())),
        "ocr_candidate_pages": len(ocr_candidates), "ocr_success_pages": parser_quality.get("ocr_success_pages", 0),
        "ocr_questions_potential_upper_bound": len(ocr_questions), "ocr_facts_potential_upper_bound": len(ocr_facts),
        "ocr_page_linked_questions": len(ocr_page_linked_questions), "ocr_page_linked_facts": len(ocr_page_linked_facts),
        "medium_questions_reanalyzed": len(medium_report),
        "medium_reason_distribution": dict(Counter(row["medium_reason"] for row in medium_report)),
        "review_page_records": sum(p.get("ingestion_status") == "review" for p in pages),
        "review_table_records": sum(t.get("ingestion_status") == "review" for t in tables),
        "review_page_document_level_exposure": {key: artifact_reports["review_page"][key] for key in ("candidate_questions", "candidate_facts", "page_linked_question_count", "page_linked_fact_count", "by_species", "by_category")},
        "review_table_document_level_exposure": {key: artifact_reports["review_table"][key] for key in ("candidate_questions", "candidate_facts", "page_linked_question_count", "page_linked_fact_count", "by_species", "by_category")},
        "legacy_doc_total": len(legacy_docs), "legacy_doc_recovered": sum(d.get("conversion_status") == "success" for d in legacy_docs),
        "legacy_doc_candidate_question_exposure": artifact_reports["legacy_doc"]["candidate_questions"],
        "legacy_doc_candidate_fact_exposure": artifact_reports["legacy_doc"]["candidate_facts"],
        "identity_authority": identity_summary,
        "top20_recovery_priority": top20,
        "recovery_actions_executed": [],
        "external_downloads": 0,
        "retrieval_benchmark_executed": False,
        "silver_v3_built": False,
    })
    console_summary = read_json(output_dir / "phase9c_summary.json")
    console_summary.pop("top20_recovery_priority", None)
    print(json.dumps(console_summary, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
