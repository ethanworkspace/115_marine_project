"""Output protocol, citation recovery, and repeatability helpers for Phase 15.1."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections import Counter
from difflib import SequenceMatcher
from typing import Any


CONTEXT_ID_RE = re.compile(r"^C[1-9][0-9]*$")
V2_ALLOWED_FIELDS = {"question_id", "status", "answer", "citations"}


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def validate_v2_output(parsed: Any, question_id: str) -> list[str]:
    """Return validation errors; generation_error is intentionally not a model status."""
    errors: list[str] = []
    if not isinstance(parsed, dict):
        return ["output_not_object"]
    if set(parsed) != V2_ALLOWED_FIELDS:
        errors.append("schema_fields_mismatch")
    if parsed.get("question_id") != question_id:
        errors.append("question_id_mismatch")
    status = parsed.get("status")
    if status not in {"answered", "insufficient_evidence"}:
        errors.append("invalid_status")
    answer = parsed.get("answer")
    if not isinstance(answer, str):
        errors.append("answer_not_string")
    elif status == "answered" and not answer.strip():
        errors.append("answered_with_empty_answer")
    citations = parsed.get("citations")
    if not isinstance(citations, list):
        errors.append("citations_not_list")
    else:
        if status == "answered" and not citations:
            errors.append("answered_without_citations")
        for citation in citations:
            if not isinstance(citation, str):
                errors.append("malformed_citation")
            elif not CONTEXT_ID_RE.fullmatch(citation):
                errors.append("citation_not_context_id")
    return errors


def context_map(contexts: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    mapping = {str(row["context_id"]): row for row in contexts}
    if len(mapping) != len(contexts):
        raise ValueError("Context IDs must be unique within a question")
    return mapping


def resolve_citations(citations: Any, contexts: list[dict[str, Any]], *,
                      corpus_chunk_ids: set[str] | None = None,
                      status: str | None = None) -> dict[str, Any]:
    """Resolve v2 string IDs or forensic v1 citation objects without mutating inputs."""
    by_context = context_map(contexts)
    by_chunk = {str(row["chunk_id"]): row for row in contexts}
    all_chunk_ids = corpus_chunk_ids or set()
    counts: Counter[str] = Counter()
    resolved: list[dict[str, Any]] = []
    seen_targets: set[str] = set()
    missing = status == "answered" and (not isinstance(citations, list) or not citations)
    if not isinstance(citations, list):
        citations = []
        if status not in (None, "insufficient_evidence"):
            counts["malformed_citation"] += 1

    for item in citations:
        if isinstance(item, dict):
            raw_id = item.get("context_id")
            is_v1_object = True
        elif isinstance(item, str):
            raw_id = item
            is_v1_object = False
        else:
            raw_id = None
            is_v1_object = False

        if not isinstance(raw_id, str) or not raw_id:
            counts["malformed_citation"] += 1
            resolved.append({"raw_citation": item, "category": "malformed_citation",
                             "strict_valid": False, "recoverable_valid": False,
                             "recovered_context_id": None})
            continue

        context = by_context.get(raw_id)
        category: str
        recovered_context_id: str | None = None
        strict_valid = False
        recoverable_valid = False
        if context is not None:
            recovered_context_id = raw_id
            strict_valid = True
            if is_v1_object:
                strict_valid = _v1_provenance_matches(item, context)
            recoverable_valid = strict_valid
            category = "valid_context_id" if strict_valid else "malformed_citation"
        elif raw_id in by_chunk:
            context = by_chunk[raw_id]
            recovered_context_id = str(context["context_id"])
            recoverable_valid = not is_v1_object or _v1_provenance_matches(item, context)
            category = "chunk_id_in_context" if recoverable_valid else "malformed_citation"
        elif raw_id in all_chunk_ids:
            category = "out_of_context_chunk_id"
        else:
            category = "unknown_context_id"

        target = str(context["chunk_id"]) if context is not None else raw_id
        is_duplicate = target in seen_targets
        if is_duplicate:
            counts["duplicate_citation"] += 1
        else:
            seen_targets.add(target)
            counts[category] += 1
        resolved.append({
            "raw_citation": item,
            "category": "duplicate_citation" if is_duplicate else category,
            "base_category": category,
            "strict_valid": strict_valid,
            "recoverable_valid": recoverable_valid,
            "recovered_context_id": recovered_context_id,
            "chunk_id": str(context["chunk_id"]) if context is not None else None,
            "document_id": str(context["document_id"]) if context is not None else None,
            "page": int(context["page"]) if context is not None else None,
        })
    if missing:
        counts["missing_citation"] += 1
    attempted = len(citations)
    strict_count = sum(bool(row["strict_valid"]) for row in resolved)
    recoverable_count = sum(bool(row["recoverable_valid"]) for row in resolved)
    return {
        "citations": resolved,
        "citation_count": attempted,
        "strict_valid_count": strict_count,
        "recoverable_valid_count": recoverable_count,
        "strict_validity_rate": strict_count / attempted if attempted else None,
        "recoverable_validity_rate": recoverable_count / attempted if attempted else None,
        "missing_citation": missing,
        "error_taxonomy_counts": dict(sorted(counts.items())),
    }


def _v1_provenance_matches(citation: dict[str, Any], context: dict[str, Any]) -> bool:
    try:
        return (
            str(citation.get("chunk_id")) == str(context["chunk_id"])
            and str(citation.get("document_id")) == str(context["document_id"])
            and int(citation.get("page")) == int(context["page"])
        )
    except (TypeError, ValueError):
        return False


def required_citation_recall(*, required_chunk_ids: list[str], contexts: list[dict[str, Any]],
                             citations: list[dict[str, Any]], status: str) -> dict[str, Any]:
    required = set(map(str, required_chunk_ids))
    available = required & {str(row["chunk_id"]) for row in contexts}
    strict_cited = {str(row["chunk_id"]) for row in citations if row.get("strict_valid") and row.get("chunk_id")}
    recoverable_cited = {str(row["chunk_id"]) for row in citations if row.get("recoverable_valid") and row.get("chunk_id")}
    denominator_all = len(required)
    denominator_present = len(available)
    denominator_answered = denominator_present if available and status == "answered" and required <= {str(row["chunk_id"]) for row in contexts} else 0
    return {
        "required_chunk_count_all_questions": denominator_all,
        "required_chunk_count_present": denominator_present,
        "required_chunk_count_present_and_answered": denominator_answered,
        "strict_cited_required_chunk_count": len(required & strict_cited),
        "recoverable_cited_required_chunk_count": len(required & recoverable_cited),
        "strict_recall_all_questions": len(required & strict_cited) / denominator_all if denominator_all else None,
        "recoverable_recall_all_questions": len(required & recoverable_cited) / denominator_all if denominator_all else None,
        "strict_recall_present": len(available & strict_cited) / denominator_present if denominator_present else None,
        "recoverable_recall_present": len(available & recoverable_cited) / denominator_present if denominator_present else None,
        "strict_recall_present_and_answered": len(available & strict_cited) / denominator_answered if denominator_answered else None,
        "recoverable_recall_present_and_answered": len(available & recoverable_cited) / denominator_answered if denominator_answered else None,
        "all_required_evidence_present": bool(required) and required <= {str(row["chunk_id"]) for row in contexts},
        "available_required_chunk_ids": sorted(available),
        "question_strict_any_required_cited": bool(available & strict_cited),
        "question_recoverable_any_required_cited": bool(available & recoverable_cited),
        "question_strict_all_available_required_cited": bool(available) and available <= strict_cited,
        "question_recoverable_all_available_required_cited": bool(available) and available <= recoverable_cited,
    }


def normalize_answer(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", str(text or "")).casefold().split())


def normalized_answer_similarity(left: str, right: str) -> float:
    return SequenceMatcher(None, normalize_answer(left), normalize_answer(right)).ratio()


def jaccard(left: set[str], right: set[str]) -> float:
    union = left | right
    return len(left & right) / len(union) if union else 1.0
