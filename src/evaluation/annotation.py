"""Human-controlled annotation state and evidence snapshot helpers."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


QUEUE_STATUSES = {
    "annotation_queue": {"draft"},
    "review_queue": {"annotated"},
    "completed_queue": {"reviewed"},
}


def records_for_queue(records: list[dict[str, Any]], queue: str) -> list[dict[str, Any]]:
    """Route only records in the explicit human workflow state to a queue."""
    if queue not in QUEUE_STATUSES:
        raise ValueError(f"unknown annotation queue: {queue}")
    return [row for row in records if row.get("annotation_status", "draft") in QUEUE_STATUSES[queue]]


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def make_evidence_snapshot(corpus_by_id: dict[str, dict[str, Any]], chunk_ids: list[str]) -> list[dict[str, Any]]:
    """Snapshot only IDs explicitly selected by a human in the workbench."""
    snapshots: list[dict[str, Any]] = []
    for chunk_id in dict.fromkeys(chunk_ids):
        row = corpus_by_id.get(chunk_id)
        if row is None:
            raise ValueError(f"unknown Evaluation Corpus chunk: {chunk_id}")
        if row.get("retrieval_role") not in {"retrieval", "context_only"}:
            raise ValueError(f"excluded chunk cannot be snapshotted as Gold evidence: {chunk_id}")
        text = str(row.get("text") or "")
        snapshots.append({
            "chunk_id": chunk_id,
            "document_id": row.get("document_id"),
            "page": row.get("page_start"),
            "page_end": row.get("page_end"),
            "content_checksum": row.get("content_checksum"),
            "text_snapshot": text,
            "snapshot_sha256": sha256_text(text),
            "retrieval_role": row.get("retrieval_role"),
            "duplicate_status": row.get("duplicate_status"),
        })
    return snapshots


def validate_annotation_transition(
    record: dict[str, Any],
    target_status: str,
    *,
    annotator: str | None,
    reviewer: str | None,
    question_verified: bool,
    evidence_verified: bool,
    reviewer_confirmations: dict[str, bool] | None = None,
    review_notes: str | None = None,
) -> list[str]:
    """Validate the human workflow without promoting state automatically."""
    errors: list[str] = []
    allowed = {"draft", "annotated", "reviewed", "blocked"}
    if target_status not in allowed:
        errors.append("development workbench cannot set locked or unknown status")
        return errors
    if target_status == "annotated":
        if not str(record.get("question") or "").strip():
            errors.append("annotated requires a human-written question")
        if record.get("answerable") not in {True, False}:
            errors.append("annotated requires an answerability decision")
        if record.get("expected_abstention") not in {True, False}:
            errors.append("annotated requires an abstention decision")
        if not record.get("category_verified"):
            errors.append("annotated requires a confirmed category")
        if not record.get("difficulty") or record.get("difficulty_verified") is not True:
            errors.append("annotated requires a confirmed difficulty decision")
        if record.get("species") and record.get("species_verified") is not True:
            errors.append("annotated species requires explicit evidence confirmation")
        if record.get("answerable") is True:
            if not str(record.get("gold_answer") or "").strip():
                errors.append("answerable annotation requires a human-authored gold_answer")
            if not (record.get("gold_chunks") or record.get("required_chunks") or record.get("acceptable_chunks")):
                errors.append("answerable annotation requires manually selected evidence")
        if not annotator:
            errors.append("annotated requires annotator identity")
    if target_status == "reviewed":
        if record.get("annotation_status") != "annotated":
            errors.append("reviewed must transition from annotated")
        if not annotator:
            errors.append("reviewed requires annotator identity")
        if not reviewer or reviewer.strip() == (annotator or "").strip():
            errors.append("reviewed requires a different reviewer")
        if not question_verified:
            errors.append("reviewed requires question_verified=true")
        if not evidence_verified:
            errors.append("reviewed requires evidence_verified=true")
        if not str(review_notes or "").strip():
            errors.append("reviewed requires review_notes")
        required_checks = {
            "question_supported", "gold_answer_supported", "required_chunks_reasonable",
            "acceptable_chunks_reasonable", "species_within_evidence",
            "category_reasonable", "difficulty_reasonable",
        }
        confirmations = reviewer_confirmations or {}
        for check in sorted(required_checks):
            if confirmations.get(check) is not True:
                errors.append(f"reviewed requires reviewer confirmation: {check}")
    return errors


def atomic_write_jsonl(path: str | Path, rows: list[dict[str, Any]]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows), encoding="utf-8", newline="\n")
    tmp.replace(path)
