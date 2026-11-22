"""Human Gold Annotation sprint reporting and Phase 9A readiness."""

from __future__ import annotations

from collections import Counter
from typing import Any

from .gold_lint import lint_question


MINIMUM_PHASE_9A_REVIEWED = 24
REVIEWER_CONFIRMATIONS = (
    "question_supported",
    "gold_answer_supported",
    "required_chunks_reasonable",
    "acceptable_chunks_reasonable",
    "species_within_evidence",
    "category_reasonable",
    "difficulty_reasonable",
)


def _review_metadata_complete(row: dict[str, Any]) -> bool:
    confirmations = row.get("reviewer_confirmations") or {}
    evidence_ids = {
        str(chunk_id)
        for field in ("gold_chunks", "required_chunks", "acceptable_chunks")
        for chunk_id in (row.get(field) or [])
    }
    snapshot_ids = {
        str(snapshot.get("chunk_id"))
        for snapshot in (row.get("gold_evidence_snapshot") or [])
        if isinstance(snapshot, dict) and snapshot.get("chunk_id")
    }
    return (
        row.get("annotation_status") == "reviewed"
        and bool(str(row.get("question") or "").strip())
        and row.get("answerable") in {True, False}
        and row.get("expected_abstention") in {True, False}
        and row.get("answerable") != row.get("expected_abstention")
        and bool(row.get("category"))
        and row.get("category_verified") is True
        and bool(row.get("difficulty"))
        and row.get("difficulty_verified") is True
        and (not row.get("species") or row.get("species_verified") is True)
        and (row.get("answerable") is not True or bool(str(row.get("gold_answer") or "").strip()))
        and (row.get("answerable") is not True or bool(row.get("required_chunks") or row.get("acceptable_chunks") or row.get("gold_chunks")))
        and evidence_ids.issubset(snapshot_ids)
        and bool(str(row.get("annotator") or "").strip())
        and bool(str(row.get("reviewer") or "").strip())
        and row.get("reviewer") != row.get("annotator")
        and bool(str(row.get("review_notes") or "").strip())
        and bool(row.get("reviewed_at"))
        and row.get("question_verified") is True
        and row.get("evidence_verified") is True
        and all(confirmations.get(key) is True for key in REVIEWER_CONFIRMATIONS)
    )


def _scope(row: dict[str, Any]) -> str:
    documents = row.get("gold_documents") or []
    if len(set(documents)) > 1:
        return "multi_document"
    if len(set(documents)) == 1:
        return "single_document"
    fallback = row.get("document_scope")
    if fallback in {"single-document", "single_document"}:
        return "single_document_pending_evidence"
    if fallback in {"multi-document", "multi_document"}:
        return "multi_document_pending_evidence"
    return "unknown"


def _counts_by(rows: list[dict[str, Any]], key_fn) -> dict[str, int]:
    return dict(sorted(Counter(str(key_fn(row) or "unknown") for row in rows).items()))


def _verified_counter(rows: list[dict[str, Any]], field: str) -> dict[str, int]:
    true_count = sum(row.get(field) is True for row in rows)
    false_count = sum(row.get(field) is False for row in rows)
    return {"true": true_count, "false": false_count, "pending": len(rows) - true_count - false_count}


def build_annotation_sprint_report(
    candidates: list[dict[str, Any]],
    questions: list[dict[str, Any]],
    corpus: list[dict[str, Any]],
    *,
    corpus_version: str,
    corpus_sha256: str,
    minimum_reviewed: int = MINIMUM_PHASE_9A_REVIEWED,
) -> dict[str, Any]:
    """Summarize the human annotation sprint without promoting candidate state."""
    corpus_by_id = {str(row["chunk_id"]): row for row in corpus if row.get("chunk_id")}
    lint_issues_by_id: dict[str, list[dict[str, str]]] = {}
    for row in questions:
        if row.get("annotation_status") != "reviewed":
            continue
        lint_issues_by_id[str(row.get("question_id"))] = lint_question(
            row,
            corpus_by_id,
            current_corpus_version=corpus_version,
            current_corpus_sha256=corpus_sha256,
        )

    complete_reviewed = [
        row for row in questions
        if _review_metadata_complete(row) and not lint_issues_by_id.get(str(row.get("question_id")), [])
    ]
    complete_reviewed_ids = {str(row.get("question_id")) for row in complete_reviewed}
    question_bank_ids = {str(row.get("candidate_id")) for row in candidates if row.get("candidate_id")}
    linked: dict[str, list[dict[str, Any]]] = {candidate_id: [] for candidate_id in question_bank_ids}
    for row in questions:
        candidate_id = str(row.get("question_bank_candidate_id") or "")
        if candidate_id in linked:
            linked[candidate_id].append(row)

    candidate_reviewed_ids = {
        candidate_id
        for candidate_id, rows in linked.items()
        if any(str(row.get("question_id")) in complete_reviewed_ids for row in rows)
    }
    candidate_linked_ids = {candidate_id for candidate_id, rows in linked.items() if rows}
    candidate_annotated_ids = {
        candidate_id for candidate_id, rows in linked.items()
        if any(row.get("annotation_status") == "annotated" for row in rows)
    }
    unsupported = [row for row in candidates if row.get("import_status") == "unsupported"]
    unsupported_reasons = Counter(
        str(row.get("unsupported_reason") or "missing_reason") for row in unsupported
    )

    def category(row: dict[str, Any]) -> str:
        return str(row.get("target_category") or row.get("category") or "unknown")

    def species(row: dict[str, Any]) -> str:
        return str(row.get("species") or "unknown")

    reviewed_by_category: dict[str, int] = dict(sorted(Counter(category(row) for row in complete_reviewed).items()))
    reviewed_by_species: dict[str, int] = dict(sorted(Counter(species(row) for row in complete_reviewed).items()))
    candidate_by_category = dict(sorted(Counter(str(row.get("category_candidate") or "unknown") for row in candidates).items()))

    def evidence_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
        refs = [str(value) for row in rows for value in (row.get("required_chunks") or [])]
        return {
            "references": len(refs),
            "unique_chunks": len(set(refs)),
            "questions_with_evidence": sum(bool(row.get("required_chunks")) for row in rows),
        }

    reviewer_completeness = {
        "question_count": len(questions),
        "annotator_present": sum(bool(str(row.get("annotator") or "").strip()) for row in questions),
        "reviewer_present": sum(bool(str(row.get("reviewer") or "").strip()) for row in questions),
        "reviewer_differs_from_annotator": sum(bool(row.get("reviewer")) and row.get("reviewer") != row.get("annotator") for row in questions),
        "review_notes_present": sum(bool(str(row.get("review_notes") or "").strip()) for row in questions),
        "reviewed_at_present": sum(bool(row.get("reviewed_at")) for row in questions),
        "all_reviewer_confirmations_present": sum(
            all((row.get("reviewer_confirmations") or {}).get(key) is True for key in REVIEWER_CONFIRMATIONS)
            for row in questions
        ),
        "complete_reviewed_questions": len(complete_reviewed),
        "reviewed_rows_rejected_by_lint": sum(
            row.get("annotation_status") == "reviewed" and bool(lint_issues_by_id.get(str(row.get("question_id"))))
            for row in questions
        ),
    }

    imported = len(candidates)
    candidate_reviewed = len(candidate_reviewed_ids)
    # Phase 9A readiness is based on all complete development reviews. The
    # candidate-specific count is reported separately for conversion tracking.
    readiness = len(complete_reviewed)

    return {
        "report_version": "1.0",
        "development_question_count": len(questions),
        "annotation_status_counts": dict(sorted(Counter(str(row.get("annotation_status") or "draft") for row in questions).items())),
        "candidate_metrics": {
            "imported_candidates": imported,
            "candidate_linked_to_development_count": len(candidate_linked_ids),
            "candidate_annotated_count": len(candidate_annotated_ids),
            "candidate_reviewed_count": candidate_reviewed,
            "candidate_to_development_rate": round(len(candidate_linked_ids) / imported, 6) if imported else 0.0,
            "candidate_to_reviewed_gold_conversion_rate": round(candidate_reviewed / imported, 6) if imported else 0.0,
            "unsupported_candidate_count": len(unsupported),
            "unsupported_reason_distribution": dict(sorted(unsupported_reasons.items())),
        },
        "category_distribution": {
            "all_development": _counts_by(questions, category),
            "reviewed_gold": reviewed_by_category,
            "question_bank_candidates": candidate_by_category,
        },
        "species_distribution": {
            "confirmed_gold_species": reviewed_by_species,
            "all_development_gold_species": _counts_by(questions, species),
            "question_bank_species_hints_only": dict(sorted(Counter(str(row.get("species") or "unknown") for row in candidates).items())),
            "note": "Question Bank workbook species is a candidate hint only and is excluded from confirmed Gold species counts.",
        },
        "document_scope_distribution": {
            "all_development": dict(sorted(Counter(_scope(row) for row in questions).items())),
            "reviewed_gold": dict(sorted(Counter(_scope(row) for row in complete_reviewed).items())),
        },
        "required_evidence": {
            "all_development": evidence_counts(questions),
            "reviewed_gold": evidence_counts(complete_reviewed),
        },
        "acceptable_evidence": {
            "all_development": evidence_counts([
                {"required_chunks": row.get("acceptable_chunks") or []} for row in questions
            ]),
            "reviewed_gold": evidence_counts([
                {"required_chunks": row.get("acceptable_chunks") or []} for row in complete_reviewed
            ]),
        },
        "annotator_reviewer_completeness": reviewer_completeness,
        "question_verified": {
            "all_development": _verified_counter(questions, "question_verified"),
            "reviewed_gold": _verified_counter(complete_reviewed, "question_verified"),
        },
        "evidence_verified": {
            "all_development": _verified_counter(questions, "evidence_verified"),
            "reviewed_gold": _verified_counter(complete_reviewed, "evidence_verified"),
        },
        "phase_9a_readiness": {
            "reviewed_gold_count": readiness,
            "minimum_reviewed_questions": minimum_reviewed,
            "remaining_reviewed_questions": max(0, minimum_reviewed - readiness),
            "smoke_test_ready": readiness >= minimum_reviewed,
            "benchmark_executed": False,
            "note": "Readiness only; reaching the threshold does not start a retrieval benchmark.",
        },
        "evaluation_corpus_version": corpus_version,
        "evaluation_corpus_sha256": corpus_sha256,
        "notes": [
            "Candidate import, unsupported classification, and report generation do not change annotation states.",
            "Only records with complete independent human review, verified question/evidence, and no Gold lint errors count toward readiness.",
            "Candidate-to-reviewed conversion counts unique Question Bank candidate IDs linked to complete reviewed Gold records.",
        ],
    }
