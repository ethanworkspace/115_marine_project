"""Deterministic, evaluation-only source and fact mapping for Silver v2.

Mapping confidence describes correspondence to the frozen corpus. It does not
verify the authority, currency, or correctness of a workbook source.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from .corpus import read_jsonl, write_json
from .question_bank_import import read_xlsx_sheets
from .silver import sha256_file

ROOT = Path(__file__).resolve().parents[2]
CONFIDENCE = ("exact", "high", "medium", "low", "unmapped")
STATUS_ORDER = {"unmapped": 0, "low_confidence": 1, "medium_confidence": 2, "high_confidence": 3, "exact": 4}
SPECIES = ("虱目魚", "吳郭魚", "石斑魚", "鱸魚", "烏魚", "鰻魚")
CATEGORIES = ("fact", "water_quality", "disease", "climate", "sop", "calculation", "multi_document", "safety_boundary")


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


@lru_cache(maxsize=200_000)
def _normalize_cached(value: str) -> str:
    return re.sub(r"[\W_]+", "", value.casefold(), flags=re.UNICODE)


def normalize_text(value: Any) -> str:
    return _normalize_cached(str(value or ""))


def normalize_url(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    parts = urlsplit(value.strip())
    if not parts.scheme or not parts.netloc:
        return None
    return urlunsplit((parts.scheme.casefold(), parts.netloc.casefold(), parts.path.rstrip("/"), parts.query, ""))


@lru_cache(maxsize=200_000)
def _terms(value: str) -> frozenset[str]:
    result: set[str] = set()
    for match in re.finditer(r"[a-z0-9]+(?:[./_%+\-][a-z0-9]+)*|[\u3400-\u9fff]+", value.casefold()):
        token = match.group(0)
        if re.fullmatch(r"[\u3400-\u9fff]+", token):
            result.update(token[i:i + 2] for i in range(len(token) - 1))
            if len(token) == 1:
                result.add(token)
        else:
            result.add(token)
    return frozenset(result)


def _similarity(query: str, body: str) -> float:
    q, b = _terms(query), _terms(body)
    if not q or not b:
        return 0.0
    overlap = len(q & b)
    recall = overlap / len(q)
    jaccard = overlap / len(q | b)
    return round(0.78 * recall + 0.22 * jaccard, 6)


def _source_rows(rows: list[tuple[int, list[Any]]]) -> list[dict[str, Any]]:
    header_at = next((i for i, (_, values) in enumerate(rows[:16]) if "來源ID" in values), None)
    if header_at is None:
        return []
    headers = [str(value).strip() if value is not None else "" for value in rows[header_at][1]]
    output = []
    for row_number, values in rows[header_at + 1:]:
        item = {header: values[index] if index < len(values) else None for index, header in enumerate(headers) if header}
        if _clean(item.get("來源ID")):
            item["_row_number"] = row_number
            output.append(item)
    return output


def _fact_rows(rows: list[tuple[int, list[Any]]]) -> list[dict[str, Any]]:
    header_at = next((i for i, (_, values) in enumerate(rows[:16]) if "事實ID" in values), None)
    if header_at is None:
        return []
    headers = [str(value).strip() if value is not None else "" for value in rows[header_at][1]]
    output = []
    for row_number, values in rows[header_at + 1:]:
        item = {header: values[index] if index < len(values) else None for index, header in enumerate(headers) if header}
        if _clean(item.get("事實ID")):
            item["_row_number"] = row_number
            output.append(item)
    return output


def _excel_year(value: Any) -> int | None:
    if isinstance(value, (int, float)):
        try:
            return (datetime(1899, 12, 30) + timedelta(days=float(value))).year
        except (OverflowError, ValueError):
            return None
    match = re.search(r"(?:19|20)\d{2}", str(value or ""))
    return int(match.group(0)) if match else None


def _document_records(corpus: list[dict[str, Any]], manifests: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, str]]:
    manifest_by_id = {str(item.get("document_id")): item for item in manifests if item.get("document_id")}
    canonical_by_id = {
        str(item.get("document_id")): str(item.get("duplicate_of"))
        for item in manifests if item.get("document_id") and item.get("duplicate_of")
    }
    corpus_by_id: dict[str, dict[str, Any]] = {}
    for row in corpus:
        canonical = str(row.get("canonical_document_id") or row.get("document_id") or "")
        if canonical and canonical not in corpus_by_id:
            corpus_by_id[canonical] = row
        if row.get("document_id") and row.get("canonical_document_id"):
            canonical_by_id[str(row["document_id"])] = str(row["canonical_document_id"])
    # Alias identities must resolve to documents that actually exist in the frozen
    # Evaluation Corpus. Manifest-only files may enrich a corpus document but are not
    # standalone corpus targets.
    all_ids = set(corpus_by_id)
    documents = []
    for document_id in sorted(all_ids):
        canonical = canonical_by_id.get(document_id, document_id)
        if document_id != canonical:
            continue
        manifest = manifest_by_id.get(document_id, {})
        row = corpus_by_id.get(document_id, {})
        path_stem = Path(str(manifest.get("file_path") or "")).stem
        title = _clean(row.get("source_title")) or _clean(manifest.get("title")) or path_stem
        aliases = list(dict.fromkeys(value for value in (
            title, _clean(manifest.get("title")), path_stem,
        ) if value))
        verified = row.get("source_verified") if "source_verified" in row else manifest.get("source_verified")
        documents.append({
            "document_id": document_id,
            "canonical_document_id": canonical,
            "document_title": title,
            "title_aliases": aliases,
            "source_id": row.get("source_id") or manifest.get("source_id"),
            "source_url": row.get("source_url") or manifest.get("source_url"),
            "organization": row.get("organization") or manifest.get("organization"),
            "checksum": row.get("source_checksum") or manifest.get("checksum"),
            "publication_date": row.get("publication_date") or manifest.get("publication_date"),
            "duplicate_of": manifest.get("duplicate_of"),
            "source_verified": verified if isinstance(verified, bool) else None,
        })
    return documents, canonical_by_id


def match_source_identity(source: dict[str, Any], documents: list[dict[str, Any]], canonical_by_id: dict[str, str] | None = None) -> dict[str, Any]:
    """Apply identity checks in the specified order and retain a complete trace."""
    canonical_by_id = canonical_by_id or {}
    trace: list[dict[str, Any]] = []
    selected: dict[str, Any] | None = None
    method = "unmapped"
    score = 0.0
    source_checksum = next((_clean(source.get(key)) for key in ("checksum", "SHA256", "sha256", "文件雜湊") if _clean(source.get(key))), None)
    source_id = _clean(source.get("來源ID") or source.get("excel_source_id"))
    source_title = _clean(source.get("文件／頁面") or source.get("文件/頁面") or source.get("excel_source_title"))
    source_url = normalize_url(source.get("URL") or source.get("excel_source_url"))
    organization = normalize_text(source.get("機關") or source.get("organization"))
    year = _excel_year(source.get("日期") or source.get("publication_date"))

    steps = ["checksum_identity", "known_duplicate_mapping", "exact_source_id_alias", "exact_normalized_url", "exact_normalized_title", "title_plus_organization", "title_plus_year", "strong_lexical_title"]

    def record(step: str, candidate: Any, candidate_score: float, reason: str, outcome: str) -> None:
        trace.append({"step": step, "candidate": candidate, "score": round(float(candidate_score), 6), "reason": reason, "outcome": outcome})

    checksum_matches = [doc for doc in documents if source_checksum and doc.get("checksum") == source_checksum]
    if checksum_matches:
        selected, method, score = checksum_matches[0], "checksum_identity", 1.0
        record(steps[0], selected["document_id"], score, "source checksum exactly matches the frozen document manifest", "matched")
    else:
        record(steps[0], None, 0, "source checksum not present or no checksum match", "not_matched")

    if selected is None:
        # A source row may carry a previously established document ID / duplicate target.
        known_id = _clean(source.get("document_id") or source.get("duplicate_of"))
        known = next((doc for doc in documents if doc["document_id"] == known_id), None) if known_id else None
        canonical_id = canonical_by_id.get(known_id, known_id) if known_id else None
        canonical_doc = next((doc for doc in documents if doc["document_id"] == canonical_id), None) if canonical_id else None
        if canonical_doc and ((known and known.get("duplicate_of")) or canonical_id != known_id):
            selected, method, score = canonical_doc or known, "known_duplicate_mapping", 1.0
            record(steps[1], {"source_document_id": known_id, "canonical_document_id": selected["document_id"]}, score, "document manifest already records this duplicate relationship", "matched")
        else:
            record(steps[1], known_id, 0, "no known duplicate reference in source row or manifest", "not_matched")
    else:
        record(steps[1], None, 0, "skipped after earlier decisive identity match", "skipped")

    if selected is None:
        id_matches = [doc for doc in documents if source_id and doc.get("source_id") not in (None, "", "unverified") and str(doc.get("source_id")) == source_id]
        if id_matches:
            selected, method, score = id_matches[0], "exact_source_id_alias", 1.0
            record(steps[2], selected["document_id"], score, "non-placeholder source ID matches existing corpus metadata", "matched")
        else:
            record(steps[2], None, 0, "no non-placeholder source ID alias in frozen corpus", "not_matched")
    else:
        record(steps[2], None, 0, "skipped after earlier decisive identity match", "skipped")

    if selected is None:
        url_matches = [doc for doc in documents if source_url and normalize_url(doc.get("source_url")) == source_url]
        if url_matches:
            selected, method, score = url_matches[0], "exact_normalized_url", 1.0
            record(steps[3], selected["document_id"], score, "normalized source URL exactly matches frozen corpus metadata", "matched")
        else:
            record(steps[3], None, 0, "no exact normalized URL match", "not_matched")
    else:
        record(steps[3], None, 0, "skipped after earlier decisive identity match", "skipped")

    title_norm = normalize_text(source_title)
    exact_titles = [doc for doc in documents if title_norm and any(normalize_text(alias) == title_norm for alias in doc.get("title_aliases", []))]
    if selected is None and exact_titles:
        selected, method, score = exact_titles[0], "exact_normalized_title", 1.0
        record(steps[4], selected["document_id"], score, "normalized source title exactly matches a frozen document title alias", "matched")
    else:
        record(steps[4], selected["document_id"] if selected else None, 1.0 if selected and method == steps[4] else 0, "exact title match" if exact_titles else "no exact normalized title match", "matched" if exact_titles and selected and method == steps[4] else ("skipped" if selected else "not_matched"))

    title_org_matches = []
    for doc in documents:
        if not title_norm or not organization or normalize_text(doc.get("organization")) != organization:
            continue
        if any(normalize_text(alias) == title_norm for alias in doc.get("title_aliases", [])):
            title_org_matches.append(doc)
    if selected is None and title_org_matches:
        selected, method, score = title_org_matches[0], "title_plus_organization", 1.0
        record(steps[5], selected["document_id"], score, "exact normalized title and organization match", "matched")
    else:
        record(steps[5], selected["document_id"] if selected and method == steps[5] else None, 1.0 if selected and method == steps[5] else 0, "exact title plus organization" if title_org_matches else "organization/title pair unavailable", "matched" if selected and method == steps[5] else ("skipped" if selected else "not_matched"))

    title_year_matches = []
    for doc in documents:
        doc_year = _excel_year(doc.get("publication_date"))
        if title_norm and year and doc_year == year and any(normalize_text(alias) == title_norm for alias in doc.get("title_aliases", [])):
            title_year_matches.append(doc)
    if selected is None and title_year_matches:
        selected, method, score = title_year_matches[0], "title_plus_year", 0.95
        record(steps[6], selected["document_id"], score, "exact normalized title and publication year match", "matched")
    else:
        record(steps[6], selected["document_id"] if selected and method == steps[6] else None, 0.95 if selected and method == steps[6] else 0, "exact title plus year" if title_year_matches else "publication year/title pair unavailable", "matched" if selected and method == steps[6] else ("skipped" if selected else "not_matched"))

    if selected is None and source_title:
        ranked = []
        for doc in documents:
            best = max((_similarity(source_title, alias) for alias in doc.get("title_aliases", [])), default=0.0)
            ranked.append((best, doc["document_id"], doc))
        ranked.sort(key=lambda item: (-item[0], item[1]))
        best_score, _, best_doc = ranked[0] if ranked else (0.0, "", None)
        second_score = ranked[1][0] if len(ranked) > 1 else 0.0
        margin = best_score - second_score
        title_length = len(normalize_text(source_title))
        if best_doc and best_score >= 0.68 and margin >= 0.10 and title_length >= 8:
            selected, method, score = best_doc, "strong_lexical_title_match", best_score
            confidence = "high"
            reason = f"unique strong lexical title match (margin={margin:.3f})"
        elif best_doc and best_score >= 0.40 and margin >= 0.08 and title_length >= 5:
            selected, method, score = best_doc, "strong_lexical_title_match", best_score
            confidence = "medium"
            reason = f"unique partial lexical title match (margin={margin:.3f})"
        elif best_doc and best_score >= 0.15:
            selected, method, score = best_doc, "weak_lexical_title_candidate", best_score
            confidence = "low"
            reason = f"weak or ambiguous lexical title match (margin={margin:.3f})"
        else:
            confidence = "unmapped"
            reason = "no lexical title candidate clears the minimum signal"
        record(steps[7], {"document_id": best_doc["document_id"] if best_doc else None, "title": best_doc["document_title"] if best_doc else None, "margin": round(margin, 6)}, best_score, reason, "matched" if confidence != "unmapped" else "not_matched")
        if confidence == "unmapped":
            selected = None
    else:
        confidence = "exact" if method in {"checksum_identity", "known_duplicate_mapping", "exact_source_id_alias", "exact_normalized_url", "exact_normalized_title", "title_plus_organization"} else ("high" if method == "title_plus_year" or method == "strong_lexical_title_match" and score >= 0.68 else "medium" if method == "strong_lexical_title_match" else "unmapped")
        record(steps[7], selected["document_id"] if selected else None, score if selected else 0, "skipped after earlier decisive identity match", "skipped")

    if selected is None:
        confidence = "unmapped"
    elif method in {"checksum_identity", "known_duplicate_mapping", "exact_source_id_alias", "exact_normalized_url", "exact_normalized_title", "title_plus_organization"}:
        confidence = "exact"
    elif method == "title_plus_year" or (method == "strong_lexical_title_match" and score >= 0.68):
        confidence = "high"
    elif method == "strong_lexical_title_match" and score >= 0.40:
        confidence = "medium"
    else:
        confidence = "low"
    source_verified = selected.get("source_verified") if selected else None
    return {
        "document_id": selected.get("document_id") if selected else None,
        "document_title": selected.get("document_title") if selected else None,
        "mapping_method": method if selected else "unmapped",
        "mapping_score": round(score, 6) if selected else None,
        "mapping_confidence": confidence,
        "source_verified": source_verified,
        "identity_match_trace": trace,
        "notes": "Identity correspondence only; does not verify source authority or currency.",
    }


def _registry_and_workbook_data(candidates: list[dict[str, Any]], documents: list[dict[str, Any]], canonical_by_id: dict[str, str]) -> tuple[list[dict[str, Any]], dict[str, dict[str, dict[str, Any]]], dict[str, dict[str, dict[str, Any]]]]:
    workbooks = sorted({str(item.get("source_workbook") or "") for item in candidates if item.get("source_workbook")})
    sources_by_workbook: dict[str, dict[str, dict[str, Any]]] = {}
    facts_by_workbook: dict[str, dict[str, dict[str, Any]]] = {}
    aliases = []
    for workbook in workbooks:
        path = ROOT / Path(workbook)
        try:
            sheets = read_xlsx_sheets(path)
        except (OSError, KeyError, ValueError, Exception) as exc:
            sources_by_workbook[workbook], facts_by_workbook[workbook] = {}, {}
            continue
        srcs = _source_rows(sheets.get("資料來源", []))
        facts = _fact_rows(sheets.get("事實資料庫", []))
        src_index = {str(row.get("來源ID")): row for row in srcs if row.get("來源ID")}
        fact_index = {str(row.get("事實ID")): row for row in facts if row.get("事實ID")}
        sources_by_workbook[workbook] = src_index
        facts_by_workbook[workbook] = fact_index
        species = next((fish for fish in SPECIES if fish in Path(workbook).name), None)
        for source_id, row in sorted(src_index.items()):
            identity = match_source_identity(row, documents, canonical_by_id)
            aliases.append({
                "source_key": f"{workbook}::{source_id}",
                "source_workbook": workbook,
                "species_candidate": species,
                "excel_source_id": source_id,
                "excel_source_title": _clean(row.get("文件／頁面") or row.get("文件/頁面")),
                "excel_source_url": _clean(row.get("URL")),
                "excel_organization": _clean(row.get("機關")),
                "excel_publication_date": row.get("日期"),
                "document_id": identity["document_id"],
                "document_title": identity["document_title"],
                "mapping_method": identity["mapping_method"],
                "mapping_score": identity["mapping_score"],
                "mapping_confidence": identity["mapping_confidence"],
                "source_verified": identity["source_verified"],
                "identity_match_trace": identity["identity_match_trace"],
                "notes": identity["notes"],
            })
    aliases.sort(key=lambda row: (row["source_workbook"], row["excel_source_id"]))
    return aliases, sources_by_workbook, facts_by_workbook


def _eligible_retrieval(row: dict[str, Any]) -> bool:
    return (
        row.get("retrieval_role") == "retrieval"
        and row.get("duplicate_status") not in {"exact_duplicate", "duplicate_source"}
        and row.get("chunk_id") == row.get("canonical_chunk_id")
        and row.get("document_id") == row.get("canonical_document_id")
        and row.get("ingestion_status") in {"accepted", "accepted_with_warning"}
    )


def _fact_source_ids(fact: dict[str, Any]) -> list[str]:
    value = fact.get("來源ID") or fact.get("source_id") or fact.get("source_ids") or ""
    if isinstance(value, list):
        return list(dict.fromkeys(str(item).strip() for item in value if str(item).strip()))
    return list(dict.fromkeys(part.strip() for part in re.split(r"[;,，；、\s]+", str(value)) if part.strip()))


def map_fact(
    fact: dict[str, Any], workbook: str, sources: dict[str, dict[str, Any]],
    aliases: dict[str, dict[str, Any]], corpus: list[dict[str, Any]],
    excluded_corpus: list[dict[str, Any]] | None = None,
    ocr_candidates: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    fact_id = _clean(fact.get("事實ID") or fact.get("fact_id"))
    statement = _clean(fact.get("可核對事實（已改寫）") or fact.get("可核對事實(已改寫)") or fact.get("statement")) or ""
    source_ids = _fact_source_ids(fact)
    linked_aliases = [aliases.get(f"{workbook}::{source_id}") for source_id in source_ids]
    linked_aliases = [item for item in linked_aliases if item]
    identity_confidences = [item.get("mapping_confidence", "unmapped") for item in linked_aliases]
    # If a fact declares multiple source IDs, aggregate confidence is bounded by
    # its weakest source correspondence.
    best_identity = min(identity_confidences, key=lambda value: {"unmapped": 0, "low": 1, "medium": 2, "high": 3, "exact": 4}.get(value, 0), default="unmapped")
    all_sources_high = bool(linked_aliases) and all(item.get("mapping_confidence") in {"exact", "high"} for item in linked_aliases)
    high_doc_ids = sorted({str(item["document_id"]) for item in linked_aliases if item.get("document_id") and item.get("mapping_confidence") in {"exact", "high"}}) if all_sources_high else []
    eligible = [row for row in corpus if _eligible_retrieval(row)]
    search_pool = [row for row in eligible if not high_doc_ids or str(row.get("document_id")) in high_doc_ids]

    exact_rows = []
    query_norm = normalize_text(statement)
    if query_norm:
        exact_rows = [row for row in search_pool if query_norm in normalize_text(row.get("text"))]
    scored = [(1.0, row) for row in exact_rows]
    method = "exact_normalized_text"
    if not scored and statement:
        scored = [(_similarity(statement, str(row.get("text") or "")), row) for row in search_pool]
        scored = [(score, row) for score, row in scored if score > 0]
        scored.sort(key=lambda pair: (-pair[0], str(pair[1].get("document_id") or ""), int(pair[1].get("page_start") or 0), str(pair[1].get("chunk_id") or "")))
        method = "high_overlap_text_match" if scored and scored[0][0] >= 0.60 else "page_local_lexical_match" if scored and scored[0][0] >= 0.35 else "general_lexical_similarity"

    # Aggregate candidate chunks by source document and page for stable page-local evidence.
    page_scores: dict[tuple[str, int], float] = {}
    page_rows: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for row in search_pool:
        start = row.get("page_start")
        end = row.get("page_end") or start
        if not isinstance(start, int):
            continue
        for page in range(start, int(end) + 1):
            key = (str(row.get("document_id")), page)
            page_rows[key].append(row)
    for key, rows in page_rows.items():
        joined = " ".join(str(row.get("text") or "") for row in sorted(rows, key=lambda item: str(item.get("chunk_id") or "")))
        page_scores[key] = 1.0 if query_norm and query_norm in normalize_text(joined) else _similarity(statement, joined)
    ranked_pages = sorted(((score, doc_id, page) for (doc_id, page), score in page_scores.items() if score > 0), key=lambda item: (-item[0], item[1], item[2]))
    best_chunk_score = scored[0][0] if scored else 0.0
    best_page_score = ranked_pages[0][0] if ranked_pages else 0.0
    if best_chunk_score == 0 and best_page_score > 0:
        method = "page_local_exact_text" if best_page_score == 1.0 and query_norm else "page_local_lexical_match"

    # Map to evidence-bearing retrieval chunks on the best page(s); parent/context-only
    # rows and duplicate copies never enter this list.
    mapped_pages = []
    mapped_documents = []
    mapped_chunks = []
    if best_page_score >= 0.25:
        selected_pages = [item for item in ranked_pages if item[0] >= max(0.25, best_page_score - 0.08)][:4]
        for score, document_id, page in selected_pages:
            mapped_pages.append({"document_id": document_id, "page": page, "mapping_score": round(score, 6)})
            if document_id not in mapped_documents:
                mapped_documents.append(document_id)
            rows = page_rows[(document_id, page)]
            chunk_scores = [(_similarity(statement, str(row.get("text") or "")), row) for row in rows]
            chunk_scores = [(value, row) for value, row in chunk_scores if value >= 0.30 or query_norm and query_norm in normalize_text(row.get("text"))]
            chunk_scores.sort(key=lambda pair: (-pair[0], str(pair[1].get("chunk_id") or "")))
            for chunk_score, row in chunk_scores[:4]:
                item = {
                    "chunk_id": row.get("chunk_id"),
                    "canonical_chunk_id": row.get("canonical_chunk_id"),
                    "document_id": row.get("document_id"),
                    "canonical_document_id": row.get("canonical_document_id"),
                    "page": page,
                    "page_end": row.get("page_end"),
                    "chunk_score": round(chunk_score, 6),
                }
                if not any(existing["chunk_id"] == item["chunk_id"] for existing in mapped_chunks):
                    mapped_chunks.append(item)

    evidence_score = best_chunk_score
    exact_fact = evidence_score == 1.0 and bool(query_norm)
    if not mapped_chunks:
        status = "unmapped"
    elif exact_fact and best_identity == "exact":
        status = "exact"
    elif best_identity in {"exact", "high"} and evidence_score >= 0.72 and len(_terms(statement)) >= 4:
        status = "high_confidence"
    elif evidence_score >= 0.42 or best_identity == "medium" and evidence_score >= 0.30:
        status = "medium_confidence"
    elif evidence_score >= 0.18:
        status = "low_confidence"
    else:
        status = "unmapped"
    reason = "fact text matched within a high-confidence source document" if status == "high_confidence" else (
        "fact text matched but source identity is not high-confidence" if mapped_chunks else "no retrieval-eligible fact evidence found"
    )
    if high_doc_ids and any(doc_id not in high_doc_ids for doc_id in mapped_documents):
        # This should not happen (candidate search was restricted), but retain a guard.
        mapped_chunks = [item for item in mapped_chunks if item["document_id"] in high_doc_ids]
        mapped_pages = [item for item in mapped_pages if item["document_id"] in high_doc_ids]
        mapped_documents = high_doc_ids
    excluded_review_candidate = False
    if not mapped_chunks and statement:
        review_rows = [
            row for row in (excluded_corpus or [])
            if row.get("ingestion_status") in {"review", "rejected"}
            or row.get("exclusion_reason") == "page_not_chunked_due_to_ingestion_gate"
        ]
        if high_doc_ids:
            review_rows = [row for row in review_rows if str(row.get("canonical_document_id") or row.get("document_id")) in high_doc_ids]
        excluded_review_candidate = any(
            query_norm and query_norm in normalize_text(row.get("text"))
            or _similarity(statement, str(row.get("text") or "")) >= 0.42
            for row in review_rows
        )
    source_doc_ids = high_doc_ids or sorted({str(item["document_id"]) for item in linked_aliases if item.get("document_id") and item.get("mapping_confidence") in {"high", "medium"}})
    ocr_missing_candidate = not mapped_chunks and not excluded_review_candidate and any(
        str(row.get("document_id")) in source_doc_ids
        and (not row.get("ocr_text") or row.get("ocr_quality_status") in {"backend_unavailable", "reject", "review"})
        for row in (ocr_candidates or [])
    )
    return {
        "fact_id": fact_id,
        "statement": statement,
        "source_ids": source_ids,
        "source_identity_confidence": best_identity,
        "source_verified": True if linked_aliases and all(alias.get("source_verified") is True for alias in linked_aliases) else False if any(alias.get("source_verified") is False for alias in linked_aliases) else None,
        "source_verification_by_source": {str(alias.get("excel_source_id")): alias.get("source_verified") for alias in linked_aliases},
        "mapping_status": status,
        "mapping_method": method if mapped_chunks else "no_match",
        "mapping_score": round(evidence_score, 6) if mapped_chunks else None,
        "page_mapping_score": round(best_page_score, 6) if mapped_pages else None,
        "mapping_reason": reason,
        "mapped_documents": sorted(set(mapped_documents)),
        "mapped_pages": sorted(mapped_pages, key=lambda item: (item["document_id"], item["page"])),
        "mapped_chunks": sorted(mapped_chunks, key=lambda item: (item["document_id"], item["page"], item["chunk_id"])),
        "page_identity_present": bool(mapped_pages),
        "chunk_granularity_present": bool(mapped_chunks),
        "review_page_excluded_candidate": excluded_review_candidate,
        "ocr_missing_candidate": ocr_missing_candidate,
    }


def _status_for_question(fact_mappings: list[dict[str, Any]]) -> tuple[str, bool]:
    if not fact_mappings:
        return "unmapped", False
    statuses = [item.get("mapping_status", "unmapped") for item in fact_mappings]
    complete = all(item.get("mapped_chunks") for item in fact_mappings)
    if not complete:
        if any(status in {"high_confidence", "exact", "medium_confidence", "low_confidence"} for status in statuses):
            return "medium_confidence", False
        return "unmapped", False
    if all(status == "exact" for status in statuses):
        return "exact", True
    if all(status in {"exact", "high_confidence"} for status in statuses):
        return "high_confidence", True
    if any(status in {"high_confidence", "medium_confidence"} for status in statuses):
        return "medium_confidence", True
    return "low_confidence", True


def validate_silver_v2_question(question: dict[str, Any], corpus_by_chunk: dict[str, dict[str, Any]]) -> None:
    required = (
        "question_id", "original_question", "original_reference_answer", "expected_sources",
        "expected_facts", "mapped_documents", "mapped_pages", "mapped_chunks",
        "evidence_mapping_status", "mapping_method", "mapping_score",
    )
    missing = [key for key in required if key not in question]
    if missing:
        raise ValueError(f"Silver v2 question missing fields: {', '.join(missing)}")
    for mapped in question.get("mapped_chunks", []):
        chunk_id = str(mapped.get("chunk_id") or "")
        row = corpus_by_chunk.get(chunk_id)
        if row is None:
            raise ValueError(f"Mapped chunk does not exist in Evaluation Corpus: {chunk_id}")
        if not _eligible_retrieval(row):
            raise ValueError(f"Mapped chunk is not canonical retrieval evidence: {chunk_id}")
        if mapped.get("document_id") != row.get("document_id"):
            raise ValueError(f"Mapped chunk document ID mismatch: {chunk_id}")


def _mapping_reason(old_status: str, status: str, facts: list[dict[str, Any]], sources: list[dict[str, Any]]) -> str:
    if status == "high_confidence":
        return "source identity and every linked fact have deterministic high-confidence corpus evidence"
    if status == "exact":
        return "exact source identity and exact normalized fact evidence"
    if not sources:
        return "question bank row has no source identity metadata"
    if not sources or not all(source.get("mapping_confidence") in {"exact", "high"} for source in sources):
        return "source identity is missing or below high confidence"
    if not facts or any(not item.get("mapped_chunks") for item in facts):
        return "one or more linked facts lack retrieval-eligible chunk evidence"
    return f"fact or source mapping remains below high confidence (previous={old_status})"


def _coverage(rows: list[dict[str, Any]]) -> dict[str, Any]:
    def counts(subset: list[dict[str, Any]]) -> dict[str, int]:
        result = {key: 0 for key in ("exact", "high_confidence", "medium_confidence", "low_confidence", "unmapped")}
        for row in subset:
            status = row.get("evidence_mapping_status")
            if status in result:
                result[status] += 1
        return result
    by_species = {fish: counts([row for row in rows if row.get("species_candidate") == fish]) for fish in SPECIES}
    by_category = {category: counts([row for row in rows if row.get("category") == category]) for category in CATEGORIES}
    return {"overall": counts(rows), "by_species": by_species, "by_category": by_category}


def _unmapped_reason(question: dict[str, Any], fact_mappings: list[dict[str, Any]], source_aliases: list[dict[str, Any]]) -> str:
    if not question.get("expected_sources") and not question.get("expected_facts"):
        return "question_bank_source_missing"
    if source_aliases and all(alias.get("mapping_confidence") == "unmapped" for alias in source_aliases):
        if any(alias.get("excel_source_title") or alias.get("excel_source_url") for alias in source_aliases):
            return "source_not_in_corpus"
        return "document_identity_missing"
    if not question.get("expected_sources"):
        return "metadata_missing"
    if any(fact.get("review_page_excluded_candidate") for fact in fact_mappings):
        return "review_page_excluded"
    if any(fact.get("ocr_missing_candidate") for fact in fact_mappings):
        return "ocr_missing"
    if any(not fact.get("statement") for fact in fact_mappings):
        return "metadata_missing"
    if fact_mappings and all(not fact.get("mapped_chunks") for fact in fact_mappings):
        if any(fact.get("mapping_method") == "ocr_missing" for fact in fact_mappings):
            return "ocr_missing"
        return "fact_not_found"
    if any(fact.get("mapped_chunks") for fact in fact_mappings):
        return "lexical_mismatch"
    return "unknown"


def _jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def expand_silver_mapping(root: str | Path = ROOT) -> dict[str, Any]:
    root = Path(root)
    corpus_path = root / "data/evaluation/corpus_v1.jsonl"
    silver_v1_path = root / "data/evaluation/silver/questions_v1.jsonl"
    manifest_path = root / "reports/document_manifest.jsonl"
    corpus = read_jsonl(corpus_path)
    silver_v1 = read_jsonl(silver_v1_path)
    manifests = read_jsonl(manifest_path)
    excluded_path = root / "data/evaluation/excluded_records.jsonl"
    excluded_corpus = read_jsonl(excluded_path) if excluded_path.exists() else []
    ocr_path = root / "reports/parsing/ocr_candidates.jsonl"
    ocr_candidates = read_jsonl(ocr_path) if ocr_path.exists() else []
    documents, canonical_by_id = _document_records(corpus, manifests)
    aliases, sources_by_workbook, facts_by_workbook = _registry_and_workbook_data(silver_v1, documents, canonical_by_id)
    aliases_by_key = {row["source_key"]: row for row in aliases}
    corpus_by_chunk = {str(row.get("chunk_id")): row for row in corpus if row.get("chunk_id")}

    questions_v2 = []
    medium_analysis = []
    unmapped_analysis = []
    fact_mapping_cache: dict[tuple[str, str], dict[str, Any]] = {}
    alias_by_workbook_id = {(row["source_workbook"], row["excel_source_id"]): row for row in aliases}
    for old in silver_v1:
        workbook = str(old.get("source_workbook") or "")
        source_table = sources_by_workbook.get(workbook, {})
        fact_table = facts_by_workbook.get(workbook, {})
        original_sources = old.get("expected_sources") or []
        original_facts = old.get("expected_facts") or []
        source_ids = list(dict.fromkeys(
            str(item.get("source_id")) for item in original_sources if item.get("source_id")
        ))
        facts = []
        source_mappings = []
        for source_id in source_ids:
            raw = source_table.get(source_id, {})
            alias = alias_by_workbook_id.get((workbook, source_id))
            if alias:
                source_mappings.append(alias)
        fact_mappings = []
        fact_records = []
        for old_fact in original_facts:
            fact_id = str(old_fact.get("fact_id") or "")
            fact = fact_table.get(fact_id, old_fact)
            cache_key = (workbook, fact_id or str(old_fact.get("statement") or ""))
            if cache_key not in fact_mapping_cache:
                fact_mapping_cache[cache_key] = map_fact(fact, workbook, source_table, aliases_by_key, corpus, excluded_corpus, ocr_candidates)
            mapped = fact_mapping_cache[cache_key]
            fact_mappings.append(mapped)
            fact_records.append({
                **old_fact,
                "source_ids": mapped["source_ids"],
                "mapping_status": mapped["mapping_status"],
                "mapping_method": mapped["mapping_method"],
                "mapping_score": mapped["mapping_score"],
                "mapping_reason": mapped["mapping_reason"],
                "mapped_documents": mapped["mapped_documents"],
                "mapped_pages": mapped["mapped_pages"],
                "mapped_chunks": mapped["mapped_chunks"],
                "page_mapping_score": mapped["page_mapping_score"],
                "source_identity_confidence": mapped["source_identity_confidence"],
                "source_verified": mapped["source_verified"],
                "source_verification_by_source": mapped["source_verification_by_source"],
                "review_page_excluded_candidate": mapped["review_page_excluded_candidate"],
                "ocr_missing_candidate": mapped["ocr_missing_candidate"],
            })
        status, complete = _status_for_question(fact_mappings)
        methods = list(dict.fromkeys(item["mapping_method"] for item in fact_mappings if item.get("mapped_chunks")))
        scores = [item["mapping_score"] for item in fact_mappings if isinstance(item.get("mapping_score"), (float, int))]
        mapped_chunks = []
        mapped_pages = []
        mapped_documents = []
        for fact_mapping in fact_mappings:
            for item in fact_mapping["mapped_chunks"]:
                if item["chunk_id"] not in {value["chunk_id"] for value in mapped_chunks}:
                    mapped_chunks.append(item)
            for item in fact_mapping["mapped_pages"]:
                if item not in mapped_pages:
                    mapped_pages.append(item)
            mapped_documents.extend(fact_mapping["mapped_documents"])
        mapped_chunks.sort(key=lambda item: (item["document_id"], item["page"], item["chunk_id"]))
        mapped_pages.sort(key=lambda item: (item["document_id"], item["page"]))
        mapping_score = min(scores) if scores else None
        reason = _mapping_reason(old.get("evidence_mapping_status", "unmapped"), status, fact_mappings, source_mappings)

        expected_sources = []
        for source in original_sources:
            source_id = str(source.get("source_id") or "")
            alias = alias_by_workbook_id.get((workbook, source_id), {})
            expected_sources.append({
                **source,
                "excel_source_id": source_id or None,
                "document_id": alias.get("document_id"),
                "matched_document_title": alias.get("document_title"),
                "source_mapping_confidence": alias.get("mapping_confidence", "unmapped"),
                "source_mapping_method": alias.get("mapping_method", "unmapped"),
                "source_verified": alias.get("source_verified"),
            })

        v2 = {
            **old,
            "original_evidence_mapping_status": old.get("evidence_mapping_status"),
            "question_id": old.get("question_id"),
            "original_question": old.get("question"),
            "original_reference_answer": old.get("reference_answer"),
            "expected_sources": expected_sources,
            "expected_facts": fact_records,
            "mapped_documents": sorted(set(mapped_documents)),
            "mapped_pages": mapped_pages,
            "mapped_chunks": mapped_chunks,
            "evidence_mapping_status": status,
            "mapping_method": methods[0] if len(methods) == 1 else methods or ["no_match"],
            "mapping_score": mapping_score,
            "mapping_reason": reason,
            "mapping_complete": complete,
            "source_mapping_confidence": min((item.get("mapping_confidence", "unmapped") for item in source_mappings), key=lambda value: {"unmapped": 0, "low": 1, "medium": 2, "high": 3, "exact": 4}.get(value, 0), default="unmapped"),
            "evaluation_mapping_version": "source-fact-map-v2",
            "mapping_is_source_verification": False,
        }
        validate_silver_v2_question(v2, corpus_by_chunk)
        questions_v2.append(v2)

        if old.get("evidence_mapping_status") == "medium_confidence":
            medium_analysis.append({
                "question_id": old.get("question_id"),
                "species_candidate": old.get("species_candidate"),
                "category": old.get("category"),
                "previous_mapping_status": old.get("evidence_mapping_status"),
                "current_mapping_status": status,
                "mapping_reason": reason,
                "missing_source_identity": not any(item.get("mapping_confidence") in {"exact", "high"} for item in source_mappings),
                "missing_page_identity": not any(item.get("mapped_pages") for item in fact_mappings),
                "missing_fact_text": not any(item.get("statement") for item in fact_mappings),
                "missing_chunk_granularity": not any(item.get("mapped_chunks") for item in fact_mappings),
                "missing_metadata": not bool(original_sources or original_facts),
                "deterministic_upgrade_to_high_possible": status == "high_confidence" and complete,
                "mapping_methods": methods,
                "mapping_score": mapping_score,
            })
        if old.get("evidence_mapping_status") == "unmapped":
            source_aliases = [alias_by_workbook_id.get((workbook, source_id), {}) for source_id in source_ids]
            reason_code = _unmapped_reason({**old, "expected_sources": original_sources}, fact_mappings, source_aliases)
            unmapped_analysis.append({
                "question_id": old.get("question_id"),
                "species_candidate": old.get("species_candidate"),
                "category": old.get("category"),
                "previous_mapping_status": old.get("evidence_mapping_status"),
                "current_mapping_status": status,
                "reason": reason_code,
                "reason_detail": reason,
                "source_identity_present": bool(original_sources),
                "fact_text_present": any(item.get("statement") for item in fact_mappings),
                "page_identity_present": any(item.get("mapped_pages") for item in fact_mappings),
                "retrieval_chunk_present": bool(mapped_chunks),
                "source_verified": True if source_mappings and all(item.get("source_verified") is True for item in source_mappings) else False if any(item.get("source_verified") is False for item in source_mappings) else None,
            })

    questions_v2.sort(key=lambda row: str(row.get("question_id") or ""))
    medium_analysis.sort(key=lambda row: str(row.get("question_id") or ""))
    unmapped_analysis.sort(key=lambda row: (row["reason"], str(row.get("question_id") or "")))
    coverage = _coverage(questions_v2)
    primary = [row for row in questions_v2 if row["evidence_mapping_status"] in {"exact", "high_confidence"} and row.get("mapping_complete") and row.get("mapped_chunks")]
    primary_species = sorted({row.get("species_candidate") for row in primary if row.get("species_candidate")})
    primary_categories = sorted({row.get("category") for row in primary if row.get("category")})
    readiness = {
        "dataset_version": "silver-questions-v2",
        "total_questions": len(questions_v2),
        "exact_questions": coverage["overall"]["exact"],
        "high_confidence_questions": coverage["overall"]["high_confidence"],
        "primary_evaluable_questions": len(primary),
        "required_primary_questions": 40,
        "primary_evaluable_species": primary_species,
        "primary_evaluable_species_count": len(primary_species),
        "required_species_count": 4,
        "primary_evaluable_categories": primary_categories,
        "primary_evaluable_category_count": len(primary_categories),
        "required_category_count": 4,
        "silver_v2_benchmark_readiness": len(primary) >= 40 and len(primary_species) >= 4 and len(primary_categories) >= 4,
        "mapping_confidence_is_source_verification": False,
        "note": "Readiness is an evidence-mapping coverage gate only; it does not assert answer truth or source verification.",
    }

    alias_counts = Counter(row.get("mapping_confidence") for row in aliases)
    alias_verification = Counter("true" if row.get("source_verified") is True else "false" if row.get("source_verified") is False else "unknown" for row in aliases)
    fact_map_counts = Counter(item.get("mapping_status") for row in questions_v2 for item in row.get("expected_facts", []))
    unique_fact_mapping = {}
    for (workbook_key, fact_id), mapped in fact_mapping_cache.items():
        if fact_id:
            unique_fact_mapping[(workbook_key, fact_id)] = mapped.get("mapping_status", "unmapped")
    unique_fact_counts = Counter(unique_fact_mapping.values())
    unmapped_counts = Counter(row["reason"] for row in unmapped_analysis)
    transitions = Counter((row.get("original_evidence_mapping_status"), row.get("evidence_mapping_status")) for row in questions_v2)
    species_summary = {species: sum(row.get("species_candidate") == species for row in questions_v2) for species in SPECIES}
    category_summary = {category: sum(row.get("category") == category for row in questions_v2) for category in CATEGORIES}

    out = {
        "aliases": aliases,
        "questions": questions_v2,
        "medium_analysis": medium_analysis,
        "unmapped_analysis": unmapped_analysis,
        "coverage": coverage,
        "readiness": readiness,
        "summary": {
            "source_alias_total": len(aliases),
            "source_alias_successful_mapping": sum(alias_counts[key] for key in ("exact", "high", "medium")),
            "source_alias_confidence": {key: alias_counts.get(key, 0) for key in CONFIDENCE},
            "source_alias_source_verified": {key: alias_verification.get(key, 0) for key in ("true", "false", "unknown")},
            "fact_mapping_status": {key: fact_map_counts.get(key, 0) for key in ("exact", "high_confidence", "medium_confidence", "low_confidence", "unmapped")},
            "fact_mapping_occurrences": sum(fact_map_counts.values()),
            "unique_fact_count": len(unique_fact_mapping),
            "unique_fact_mapping_status": {key: unique_fact_counts.get(key, 0) for key in ("exact", "high_confidence", "medium_confidence", "low_confidence", "unmapped")},
            "question_mapping_status": coverage["overall"],
            "question_mapping_transitions": {f"{old or 'unknown'}->{new}": count for (old, new), count in sorted(transitions.items())},
            "medium_upgrade_to_high": sum(row.get("original_evidence_mapping_status") == "medium_confidence" and row.get("evidence_mapping_status") in {"exact", "high_confidence"} for row in questions_v2),
            "low_or_unmapped_upgrade": sum(row.get("original_evidence_mapping_status") in {"low_confidence", "unmapped"} and STATUS_ORDER.get(row.get("evidence_mapping_status"), 0) > STATUS_ORDER.get(row.get("original_evidence_mapping_status"), 0) for row in questions_v2),
            "low_or_unmapped_upgrade_by_previous_status": {
                previous: sum(row.get("original_evidence_mapping_status") == previous and STATUS_ORDER.get(row.get("evidence_mapping_status"), 0) > STATUS_ORDER.get(previous, 0) for row in questions_v2)
                for previous in ("low_confidence", "unmapped")
            },
            "by_species_total": species_summary,
            "by_category_total": category_summary,
            "unmapped_reason_distribution": {key: unmapped_counts.get(key, 0) for key in ("source_not_in_corpus", "document_identity_missing", "fact_not_found", "ocr_missing", "review_page_excluded", "metadata_missing", "question_bank_source_missing", "lexical_mismatch", "unknown")},
            "primary_evaluable_questions": len(primary),
            "readiness": readiness,
        },
    }
    return out


def write_mapping_artifacts(result: dict[str, Any], root: str | Path = ROOT) -> None:
    root = Path(root)
    _jsonl(root / "data/evaluation/source_alias_registry.jsonl", result["aliases"])
    _jsonl(root / "data/evaluation/silver/questions_v2.jsonl", result["questions"])
    _jsonl(root / "reports/evaluation/medium_mapping_analysis.jsonl", result["medium_analysis"])
    write_json(root / "reports/evaluation/unmapped_analysis.json", {
        "baseline_unmapped_total": len(result["unmapped_analysis"]),
        "reason_distribution": result["summary"]["unmapped_reason_distribution"],
        "questions": result["unmapped_analysis"],
    })
    write_json(root / "reports/evaluation/silver_v2_coverage.json", result["coverage"])
    write_json(root / "reports/evaluation/silver_v2_benchmark_readiness.json", result["readiness"])
    write_json(root / "reports/evaluation/source_alias_summary.json", result["summary"])
