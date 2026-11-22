"""Deterministic, evaluation-only corpus-gap analysis helpers.

This module classifies local evidence gaps. It does not verify a source's
authority, change mapping confidence thresholds, or run retrieval.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any


MISSING_SOURCE_REASONS = {
    "truly_missing", "metadata_mismatch", "duplicate_document",
    "different_version", "review_only_document",
    "source_identifier_missing", "unknown",
}
FACT_GAP_REASONS = {
    "ocr_missing", "review_page", "table_unparsed", "legacy_doc",
    "parser_loss", "chunking_loss", "fact_paraphrase", "source_mismatch",
    "unknown",
}
MEDIUM_REASONS = {
    "source_identity_incomplete", "fact_match_incomplete", "page_unknown",
    "chunk_ambiguous", "duplicate_source", "paraphrase_only",
    "metadata_missing", "other",
}


def stable_alias_id(source_key: str) -> str:
    return "alias_" + hashlib.sha256(source_key.encode("utf-8")).hexdigest()[:20]


def classify_missing_source(evidence: dict[str, Any]) -> str:
    """Classify with explicit local evidence flags; never infer from question text."""
    if evidence.get("known_duplicate"):
        return "duplicate_document"
    if evidence.get("different_version"):
        return "different_version"
    if evidence.get("review_only"):
        return "review_only_document"
    if evidence.get("metadata_mismatch"):
        return "metadata_mismatch"
    if not evidence.get("source_identifier") and not evidence.get("source_title") and not evidence.get("source_url"):
        return "source_identifier_missing"
    if not evidence.get("identity_fields_present"):
        return "unknown"
    if evidence.get("local_identity_match"):
        return "metadata_mismatch"
    return "truly_missing"


def classify_fact_gap(evidence: dict[str, Any]) -> str:
    """Return the strongest supported local recovery lead, not a causal claim."""
    for key, reason in (
        ("legacy_doc", "legacy_doc"),
        ("ocr_candidate", "ocr_missing"),
        ("review_table", "table_unparsed"),
        ("review_page", "review_page"),
        ("accepted_page_match", "chunking_loss"),
        ("parser_error", "parser_loss"),
        ("paraphrase_candidate", "fact_paraphrase"),
        ("source_mismatch", "source_mismatch"),
    ):
        if evidence.get(key):
            return reason
    return "unknown"


def identity_authority_status(
    *, identity_basis: str | None, source_verified: bool | None,
    legal_status: str | None = None, source_tier: int | None = None,
) -> tuple[str, str]:
    """Keep document identity and source authority as independent attributes."""
    if identity_basis in {"checksum", "exact_source_id", "exact_url", "known_duplicate"}:
        identity = "verified"
    elif identity_basis in {"exact_title", "title_organization", "title_year", "strong_title"}:
        identity = "likely"
    else:
        identity = "unresolved"

    legal = str(legal_status or "unknown").casefold()
    if legal == "superseded":
        authority = "superseded"
    elif legal in {"historical", "repealed"}:
        authority = "historical"
    elif source_verified is True and source_tier == 1:
        authority = "verified_official"
    elif source_verified is False:
        authority = "unverified"
    else:
        authority = "unknown"
    return identity, authority


def priority_score(
    *, affected_questions: int, affected_facts: int, species_count: int,
    category_count: int, high_risk: bool, feasibility: int,
) -> int:
    """Stable priority heuristic: impact, risk, and local recoverability."""
    return (
        10 * affected_questions + 5 * affected_facts
        + 3 * species_count + 2 * category_count
        + (8 if high_risk else 0) + max(0, min(int(feasibility), 6))
    )


def medium_reason(question: dict[str, Any]) -> str:
    facts = question.get("expected_facts") or []
    sources = question.get("expected_sources") or []
    if not facts or not sources:
        return "metadata_missing"
    if any(f.get("duplicate_source_candidate") for f in facts):
        return "duplicate_source"
    if any(not f.get("mapped_chunks") for f in facts):
        if any(f.get("mapped_pages") for f in facts):
            return "chunk_ambiguous"
        if any(f.get("statement") for f in facts):
            return "fact_match_incomplete"
        return "metadata_missing"
    if any(not isinstance(chunk.get("page"), int) for f in facts for chunk in f.get("mapped_chunks", [])):
        return "page_unknown"
    if any(s.get("source_mapping_confidence") not in {"exact", "high"} for s in sources):
        return "source_identity_incomplete"
    if any(f.get("mapping_method") in {"general_lexical_similarity", "page_local_lexical_match"} for f in facts):
        return "paraphrase_only"
    return "other"


def silver_v3_has_material_improvement(v2: list[dict[str, Any]], v3: list[dict[str, Any]]) -> bool:
    """Require actual evidence mapping changes before emitting a v3 copy."""
    by_id = {str(row.get("question_id")): row for row in v2}
    for row in v3:
        old = by_id.get(str(row.get("question_id")))
        if old is None:
            continue
        if row.get("evidence_mapping_status") != old.get("evidence_mapping_status"):
            return True
        old_chunks = sorted(str(x.get("chunk_id")) for x in old.get("mapped_chunks", []))
        new_chunks = sorted(str(x.get("chunk_id")) for x in row.get("mapped_chunks", []))
        if old_chunks != new_chunks:
            return True
    return False


def mapping_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts = {key: 0 for key in ("exact", "high_confidence", "medium_confidence", "low_confidence", "unmapped")}
    for row in rows:
        status = row.get("evidence_mapping_status")
        if status in counts:
            counts[status] += 1
    return counts


def normalize_for_match(value: Any) -> str:
    return re.sub(r"[\W_]+", "", str(value or "").casefold(), flags=re.UNICODE)
