"""Fail-closed ingestion eligibility helpers for the experimental parser v2 flow."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any


INGESTION_STATUSES = {"accepted", "accepted_with_warning", "review", "rejected"}


def _mapping(record: Any) -> dict[str, Any]:
    if isinstance(record, dict):
        return record
    if is_dataclass(record):
        return asdict(record)
    raise TypeError("record must be a dictionary or dataclass instance")


def can_index(record: Any) -> bool:
    """Return whether a record is eligible for a future chunking stage."""
    status = _mapping(record).get("ingestion_status")
    if status not in INGESTION_STATUSES:
        return False
    return status in {"accepted", "accepted_with_warning"}


def apply_ingestion_status(
    record: dict[str, Any], status: str, reasons: list[str] | None = None
) -> dict[str, Any]:
    """Attach gate fields while leaving review identity/time unset until human review."""
    if status not in INGESTION_STATUSES:
        raise ValueError(f"unsupported ingestion_status: {status}")
    record["ingestion_status"] = status
    record["review_reason"] = list(dict.fromkeys(reasons or []))
    record.setdefault("reviewed_by", None)
    record.setdefault("reviewed_at", None)
    return record


def evaluate_page(record: dict[str, Any], *, high_risk_legal_topic: bool = False) -> tuple[str, list[str]]:
    """Classify one parser page without promoting uncertain or missing extraction."""
    reasons: list[str] = []
    classification = record.get("classification")
    method = record.get("extraction_method")
    quality = record.get("ocr_quality_status", "not_run")
    native_text = str(record.get("native_text") or "")
    ocr_text = str(record.get("ocr_text") or "")
    selected_text = str(record.get("selected_text") or record.get("text") or "")

    if not record.get("document_id") or not record.get("file_checksum"):
        reasons.append("missing_document_provenance")
    if high_risk_legal_topic and record.get("legal_status", record.get("document_metadata", {}).get("legal_status")) != "current":
        reasons.append("high_risk_legal_topic_legal_status_not_verified_current")
    source_id = record.get("source_id") or record.get("document_metadata", {}).get("source_id")
    source_url = record.get("source_url") or record.get("document_metadata", {}).get("source_url")
    if not source_id or source_id == "unverified" or not source_url:
        reasons.append("source_provenance_unverified")

    if classification == "parser_error" or method == "failed":
        reasons.append("parser_or_conversion_failure")
        return "review", reasons
    if quality in {"backend_unavailable", "failed", "review"}:
        reasons.append(f"ocr_status_{quality}")
        return "review", reasons
    if classification == "blank":
        reasons.append("page_classified_as_blank")
        return "rejected", reasons
    if quality == "reject":
        reasons.append("ocr_quality_gate_rejected_text")
        return "rejected", reasons
    if classification in {"image_or_chart", "manual_review"}:
        reasons.append("image_or_chart_or_manual_content_requires_human_review")
        return "review", reasons
    if classification == "ocr_candidate" and quality != "pass":
        reasons.append("image_or_ocr_content_not_cleared_by_quality_gate")
        return "review", reasons
    if record.get("needs_review"):
        reasons.append("parser_marked_page_for_review")
        reasons.extend(str(item) for item in record.get("warnings", [])[:10])
        return "review", reasons
    if not selected_text.strip():
        reasons.append("no_selected_text; extraction state requires human review")
        return "review", reasons
    if high_risk_legal_topic and record.get("legal_status", record.get("document_metadata", {}).get("legal_status")) != "current":
        return "review", reasons
    if method == "ocr" or quality == "pass":
        reasons.append("ocr_text_passed_quality_gate; human source verification still pending")
        return "accepted_with_warning", reasons
    if native_text.strip() and method == "native":
        if len(reasons):
            return "accepted_with_warning", reasons
        return "accepted", []
    if method in {"converted_doc", "odt", "manual"}:
        reasons.append("converted_or_manual_extraction_requires_provenance_review")
        return "accepted_with_warning", reasons
    reasons.append("unrecognized_extraction_state")
    return "review", reasons


def aggregate_document(page_statuses: list[str], *, conversion_status: str = "not_required", source_verified: bool = False) -> tuple[str, list[str]]:
    """Aggregate page outcomes conservatively to one document-level gate status."""
    reasons: list[str] = []
    if conversion_status in {"failed", "unavailable"}:
        return "review", ["legacy_doc_conversion_requires_manual_recovery"]
    if not page_statuses:
        return "review", ["document_has_no_page_records"]
    if all(status == "rejected" for status in page_statuses):
        return "rejected", ["all_pages_rejected"]
    if "review" in page_statuses:
        reasons.append("one_or_more_pages_require_review")
        return "review", reasons
    if "rejected" in page_statuses:
        reasons.append("one_or_more_pages_rejected")
        return "review", reasons
    if "accepted_with_warning" in page_statuses or not source_verified:
        if not source_verified:
            reasons.append("source_verification_pending")
        return "accepted_with_warning", reasons
    return "accepted", []
