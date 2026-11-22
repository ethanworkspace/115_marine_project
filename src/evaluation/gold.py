"""Validation helpers for human-authored Pilot Gold records."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


GOLD_STATUSES = {"draft", "annotated", "reviewed", "blocked", "locked"}
SOURCE_STATUSES = {"not_required", "pending", "verified", "failed"}


def validate_gold_record(record: dict[str, Any], corpus_by_id: dict[str, dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    required = ("question_id", "question", "species", "category", "difficulty", "answerable", "expected_abstention",
                "gold_answer", "gold_documents", "gold_pages", "gold_chunks", "required_chunks", "acceptable_chunks",
                "supporting_claims", "conflicting_chunks", "source_verification_required", "source_verification_status",
                "annotation_status", "annotator", "reviewer", "notes")
    for field in required:
        if field not in record:
            errors.append(f"missing field: {field}")
    if record.get("annotation_status") not in GOLD_STATUSES:
        errors.append("invalid annotation_status")
    if record.get("source_verification_status") not in SOURCE_STATUSES:
        errors.append("invalid source_verification_status")
    refs = set(corpus_by_id)
    corpus_documents = {str(row.get("document_id")) for row in corpus_by_id.values() if row.get("document_id")}
    corpus_pages = {
        (str(row.get("document_id")), page)
        for row in corpus_by_id.values()
        if row.get("document_id")
        for page in range(row.get("page_start") or 0, (row.get("page_end") or row.get("page_start") or 0) + 1)
    }
    for field in ("gold_chunks", "required_chunks", "acceptable_chunks", "conflicting_chunks"):
        values = record.get(field, [])
        if not isinstance(values, list):
            errors.append(f"{field} must be an array")
            continue
        for chunk_id in values:
            if chunk_id not in refs:
                errors.append(f"{field} references missing corpus chunk: {chunk_id}")
            elif field in {"gold_chunks", "required_chunks", "acceptable_chunks", "conflicting_chunks"} and corpus_by_id[chunk_id].get("retrieval_role") not in {"retrieval", "context_only"}:
                errors.append(f"{field} references excluded chunk: {chunk_id}")
    for document_id in record.get("gold_documents", []) or []:
        if document_id not in corpus_documents:
            errors.append(f"gold_documents references missing corpus document: {document_id}")
    for page in record.get("gold_pages", []) or []:
        if not isinstance(page, dict) or (str(page.get("document_id")), page.get("page")) not in corpus_pages:
            errors.append(f"gold_pages references missing corpus page: {page}")
    acceptable = set(record.get("acceptable_chunks", []) or [])
    for chunk_id in record.get("gold_chunks", []) or []:
        if chunk_id in corpus_by_id and corpus_by_id[chunk_id].get("retrieval_role") == "context_only" and chunk_id not in acceptable:
            errors.append(f"gold_chunks context-only evidence must be explicitly acceptable: {chunk_id}")
    for claim in record.get("supporting_claims", []) or []:
        if not isinstance(claim, dict):
            errors.append("supporting_claims entries must be objects")
            continue
        for chunk_id in claim.get("chunk_ids", []) or []:
            if chunk_id not in refs:
                errors.append(f"supporting_claims references missing corpus chunk: {chunk_id}")
            elif chunk_id not in set(record.get("gold_chunks", []) or []):
                errors.append(f"supporting_claims evidence must be listed in gold_chunks: {chunk_id}")
    if record.get("annotation_status") == "locked":
        if not record.get("gold_answer") or not record.get("gold_chunks"):
            errors.append("locked records require gold_answer and gold evidence")
        if not record.get("gold_documents") or not record.get("gold_pages"):
            errors.append("locked records require gold_documents and gold_pages")
        if not record.get("supporting_claims"):
            errors.append("locked records require supporting_claims")
        if not isinstance(record.get("answerable"), bool) or not isinstance(record.get("expected_abstention"), bool):
            errors.append("locked records require answerability and abstention decisions")
        if not record.get("annotator") or not record.get("reviewer"):
            errors.append("locked records require annotator and reviewer")
        if record.get("source_verification_required") and record.get("source_verification_status") != "verified":
            errors.append("locked high-risk records require verified source status")
    if record.get("annotation_status") == "blocked" and record.get("risk_level") == "high":
        # A blocked record intentionally has no gold answer/evidence yet.
        pass
    for chunk_id in record.get("required_chunks", []) or []:
        if chunk_id in corpus_by_id and corpus_by_id[chunk_id].get("retrieval_role") != "retrieval":
            accepted = set(record.get("acceptable_chunks", []) or [])
            if chunk_id not in accepted:
                errors.append(f"required chunk is not retrieval evidence: {chunk_id}")
    return errors


def load_schema(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))
