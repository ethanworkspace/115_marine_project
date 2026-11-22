"""Fail-closed lint rules for human-edited Gold annotation records."""

from __future__ import annotations

from collections import Counter
from typing import Any

from .annotation import sha256_text


HIGH_RISK_CATEGORIES = {"regulation", "drug", "withdrawal_period", "calculation", "safety_boundary"}
GOLD_REFERENCE_FIELDS = ("gold_chunks", "required_chunks", "acceptable_chunks", "conflicting_chunks")


def lint_question(
    record: dict[str, Any],
    corpus_by_id: dict[str, dict[str, Any]],
    *,
    current_corpus_version: str | None = None,
    current_corpus_sha256: str | None = None,
) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []

    def fail(code: str, message: str) -> None:
        errors.append({"code": code, "message": message})

    for field in GOLD_REFERENCE_FIELDS:
        values = record.get(field, []) or []
        if not isinstance(values, list):
            fail("invalid_reference_list", f"{field} must be a list")
            continue
        for chunk_id in values:
            row = corpus_by_id.get(str(chunk_id))
            if row is None:
                fail("missing_chunk", f"{field} references a chunk outside Evaluation Corpus: {chunk_id}")
                continue
            if row.get("retrieval_role") == "excluded":
                fail("excluded_chunk", f"{field} references excluded chunk: {chunk_id}")
            if row.get("duplicate_status") in {"exact_duplicate", "duplicate_source"}:
                fail("noncanonical_duplicate", f"{field} references non-canonical duplicate: {chunk_id}")

    for chunk_id in record.get("required_chunks", []) or []:
        row = corpus_by_id.get(str(chunk_id))
        if row and row.get("retrieval_role") != "retrieval":
            fail("required_not_retrieval", f"required chunk must have retrieval role: {chunk_id}")
    for field in ("required_chunks", "acceptable_chunks"):
        for chunk_id in record.get(field, []) or []:
            if chunk_id not in corpus_by_id:
                fail("missing_acceptable_evidence" if field == "acceptable_chunks" else "missing_required_evidence", f"{field} chunk does not exist: {chunk_id}")
    for chunk_id in record.get("gold_chunks", []) or []:
        if chunk_id not in corpus_by_id:
            fail("gold_chunk_not_in_corpus", f"Gold chunk does not exist in Evaluation Corpus: {chunk_id}")

    answerable = record.get("answerable")
    abstention = record.get("expected_abstention")
    if answerable is True and not (record.get("gold_chunks") or record.get("required_chunks") or record.get("acceptable_chunks")):
        fail("answerable_without_evidence", "answerable=true requires human-confirmed Gold evidence")
    if isinstance(answerable, bool) and isinstance(abstention, bool) and answerable == abstention:
        fail("answerability_abstention_conflict", "answerable and expected_abstention must be complementary")

    status = record.get("annotation_status")
    if status == "annotated":
        if not str(record.get("question") or "").strip():
            fail("incomplete_annotation", "annotated requires question")
        if record.get("answerable") is True and not str(record.get("gold_answer") or "").strip():
            fail("incomplete_annotation", "answerable annotation requires gold_answer")
        if record.get("answerable") is True and not (record.get("gold_chunks") or record.get("required_chunks") or record.get("acceptable_chunks")):
            fail("annotated_without_evidence", "answerable annotation requires Gold evidence")
        if record.get("category_verified") is not True:
            fail("category_not_verified", "annotated requires manually confirmed category")
        if not record.get("difficulty") or record.get("difficulty_verified") is not True:
            fail("difficulty_not_verified", "annotated requires manually confirmed difficulty")
        if record.get("species") and record.get("species_verified") is not True:
            fail("species_not_verified", "species cannot be recorded as Gold without evidence confirmation")
    if status in {"reviewed", "locked"} and not record.get("evidence_verified"):
        fail("review_without_evidence_verification", f"{status} requires evidence_verified=true")
    if status in {"reviewed", "locked"} and not record.get("question_verified"):
        fail("review_without_question_verification", f"{status} requires question_verified=true")
    if status in {"reviewed", "locked"} and (not record.get("reviewer") or record.get("reviewer") == record.get("annotator")):
        fail("invalid_reviewer", f"{status} requires a reviewer different from the annotator")
    if status == "reviewed":
        confirmations = record.get("reviewer_confirmations") or {}
        for key in ("question_supported", "gold_answer_supported", "required_chunks_reasonable", "acceptable_chunks_reasonable", "species_within_evidence", "category_reasonable", "difficulty_reasonable"):
            if confirmations.get(key) is not True:
                fail("missing_reviewer_confirmation", f"reviewed requires reviewer confirmation: {key}")
        if not str(record.get("review_notes") or "").strip() or not record.get("reviewed_at"):
            fail("missing_review_provenance", "reviewed requires review_notes and reviewed_at")

    referenced_rows = [corpus_by_id[key] for field in GOLD_REFERENCE_FIELDS for key in record.get(field, []) or [] if key in corpus_by_id]
    risk_high = record.get("risk_level") == "high" or record.get("category") in HIGH_RISK_CATEGORIES or any(row.get("risk_level") == "high" for row in referenced_rows)
    source_verified = record.get("source_verification_status") == "verified" and all(row.get("source_verified") is True for row in referenced_rows if row.get("risk_level") == "high")
    if status == "locked" and risk_high and not source_verified:
        fail("unverified_high_risk_locked", "high-risk records cannot be locked before source verification")
    if record.get("split") == "development" and risk_high:
        fail("high_risk_in_development", "high-risk records are excluded from this development annotation set")

    corpus_identity_matches = (
        record.get("evaluation_corpus_version") == current_corpus_version
        and record.get("evaluation_corpus_sha256") == current_corpus_sha256
    )
    snapshots = record.get("gold_evidence_snapshot", []) or []
    gold_evidence_ids = set(record.get("gold_chunks", []) or []) | set(record.get("required_chunks", []) or []) | set(record.get("acceptable_chunks", []) or [])
    for snapshot in snapshots:
        if not isinstance(snapshot, dict):
            fail("invalid_evidence_snapshot", "evidence snapshot entry must be an object")
            continue
        text = str(snapshot.get("text_snapshot") or "")
        if snapshot.get("snapshot_sha256") != sha256_text(text):
            fail("snapshot_text_checksum_mismatch", f"text snapshot checksum mismatch: {snapshot.get('chunk_id')}")
        chunk_id = str(snapshot.get("chunk_id") or "")
        current = corpus_by_id.get(chunk_id)
        if chunk_id not in gold_evidence_ids:
            fail("snapshot_not_gold_evidence", f"snapshot is not attached to selected Gold evidence: {chunk_id}")
        if current and (current.get("retrieval_role") == "excluded" or current.get("duplicate_status") in {"exact_duplicate", "duplicate_source"}):
            fail("snapshot_excluded_or_duplicate", f"snapshot points to excluded or non-canonical evidence: {chunk_id}")
        if corpus_identity_matches and current:
            if snapshot.get("content_checksum") != current.get("content_checksum"):
                fail("snapshot_source_checksum_mismatch", f"snapshot source checksum mismatch: {chunk_id}")
            if snapshot.get("document_id") != current.get("document_id") or snapshot.get("page") != current.get("page_start"):
                fail("snapshot_provenance_mismatch", f"snapshot document/page mismatch: {chunk_id}")
            if text != str(current.get("text") or ""):
                fail("snapshot_text_mismatch", f"snapshot text differs from Evaluation Corpus: {chunk_id}")
        elif corpus_identity_matches and current is None:
            fail("snapshot_chunk_not_in_corpus", f"snapshot chunk not in Evaluation Corpus: {chunk_id}")
    return errors


def lint_dataset(
    records: list[dict[str, Any]],
    corpus: list[dict[str, Any]],
    *,
    corpus_version: str | None = None,
    corpus_sha256: str | None = None,
) -> dict[str, Any]:
    by_id = {str(row.get("chunk_id")): row for row in corpus if row.get("chunk_id")}
    issues = []
    for record in records:
        for issue in lint_question(record, by_id, current_corpus_version=corpus_version, current_corpus_sha256=corpus_sha256):
            issues.append({"question_id": record.get("question_id"), **issue})
    counts = Counter(issue["code"] for issue in issues)
    return {
        "record_count": len(records),
        "error_count": len(issues),
        "issue_counts": dict(sorted(counts.items())),
        "issues": issues,
        "annotation_status_counts": dict(sorted(Counter(row.get("annotation_status", "missing") for row in records).items())),
        "gold_answers_filled": sum(bool(row.get("gold_answer")) for row in records),
        "gold_evidence_reference_count": sum(len(row.get("gold_chunks", []) or []) for row in records),
    }
