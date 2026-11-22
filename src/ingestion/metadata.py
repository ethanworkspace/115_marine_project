"""Validation and two-stage metadata merging for documents and chunks."""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse
from uuid import UUID


LEGAL_STATUSES = ("current", "superseded", "repealed", "historical", "draft", "unknown")
DOCUMENT_REQUIRED_FIELDS = (
    "document_id",
    "title",
    "source_id",
    "organization",
    "source_url",
    "source_tier",
    "publication_date",
    "download_date",
    "effective_date",
    "expiry_date",
    "version",
    "legal_status",
    "species",
    "topics",
    "document_type",
    "language",
    "checksum",
    "file_path",
    "file_size",
    "parser_version",
    "ingestion_status",
)
CHUNK_REQUIRED_FIELDS = (
    "chunk_id",
    "document_id",
    "parent_chunk_id",
    "species",
    "topic",
    "disease",
    "chapter",
    "section",
    "page_start",
    "page_end",
    "content_checksum",
    "extraction_confidence",
    "embedding_model",
    "embedding_version",
    "embedding_dimension",
)
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class MetadataValidationError(ValueError):
    """Raised when manifest or chunk metadata violates the declared contract."""


def _require_fields(record: Mapping[str, Any], fields: tuple[str, ...], kind: str) -> None:
    missing = [field for field in fields if field not in record]
    if missing:
        raise MetadataValidationError(f"{kind} metadata missing required fields: {', '.join(missing)}")


def _validate_date(value: Any, field: str) -> None:
    if value is None:
        return
    if not isinstance(value, str):
        raise MetadataValidationError(f"{field} must be an ISO date string or null")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise MetadataValidationError(f"{field} must use YYYY-MM-DD format")
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise MetadataValidationError(f"{field} must use YYYY-MM-DD format") from exc


def validate_document_metadata(record: Mapping[str, Any]) -> None:
    _require_fields(record, DOCUMENT_REQUIRED_FIELDS, "document")
    if not isinstance(record["document_id"], str) or not record["document_id"].strip():
        raise MetadataValidationError("document_id must be a non-empty string")
    try:
        UUID(record["document_id"])
    except (ValueError, AttributeError) as exc:
        raise MetadataValidationError("document_id must be a UUID string") from exc
    if not isinstance(record["title"], str) or not record["title"].strip():
        raise MetadataValidationError("title must be a non-empty string")
    if not isinstance(record["source_id"], str) or not record["source_id"].strip():
        raise MetadataValidationError("source_id must be a non-empty string")
    for field in ("organization", "source_url", "version", "language"):
        if record[field] is not None and not isinstance(record[field], str):
            raise MetadataValidationError(f"{field} must be a string or null")
    source_url = record["source_url"]
    if source_url is not None:
        parsed_url = urlparse(source_url)
        if parsed_url.scheme not in ("http", "https") or not parsed_url.netloc:
            raise MetadataValidationError("source_url must be an absolute HTTP(S) URL or null")
    if record["legal_status"] not in LEGAL_STATUSES:
        raise MetadataValidationError(
            f"legal_status must be one of: {', '.join(LEGAL_STATUSES)}"
        )
    if record["source_tier"] is not None and (
        isinstance(record["source_tier"], bool) or record["source_tier"] not in (1, 2, 3, 4)
    ):
        raise MetadataValidationError("source_tier must be 1, 2, 3, 4, or null when unverified")
    for field in ("publication_date", "download_date", "effective_date", "expiry_date"):
        _validate_date(record[field], field)
    if not isinstance(record["species"], list) or not all(
        isinstance(value, str) for value in record["species"]
    ):
        raise MetadataValidationError("species must be a list of strings")
    if not isinstance(record["topics"], list) or not all(
        isinstance(value, str) for value in record["topics"]
    ):
        raise MetadataValidationError("topics must be a list of strings")
    if not isinstance(record["document_type"], str) or not record["document_type"].strip():
        raise MetadataValidationError("document_type must be a non-empty string")
    if not isinstance(record["checksum"], str) or not _SHA256_PATTERN.fullmatch(record["checksum"]):
        raise MetadataValidationError("checksum must be a lowercase SHA-256 hex digest")
    if not isinstance(record["file_path"], str) or not record["file_path"].strip():
        raise MetadataValidationError("file_path must be a non-empty relative path")
    if Path(record["file_path"]).is_absolute() or record["file_path"].startswith(("/", "\\")):
        raise MetadataValidationError("file_path must be repository-relative")
    if not isinstance(record["file_size"], int) or isinstance(record["file_size"], bool) or record["file_size"] < 0:
        raise MetadataValidationError("file_size must be a non-negative integer")
    if not isinstance(record["parser_version"], str) or not record["parser_version"].strip():
        raise MetadataValidationError("parser_version must be a non-empty string")
    if record["ingestion_status"] not in ("registered", "indexed", "failed"):
        raise MetadataValidationError("ingestion_status must be registered, indexed, or failed")
    duplicate_of = record.get("duplicate_of")
    if duplicate_of is not None:
        try:
            UUID(duplicate_of)
        except (ValueError, TypeError, AttributeError) as exc:
            raise MetadataValidationError("duplicate_of must be a UUID string or null") from exc


def validate_chunk_metadata(record: Mapping[str, Any]) -> None:
    _require_fields(record, CHUNK_REQUIRED_FIELDS, "chunk")
    for field in ("chunk_id", "document_id"):
        if not isinstance(record[field], str) or not record[field].strip():
            raise MetadataValidationError(f"{field} must be a non-empty string")
    try:
        UUID(record["document_id"])
    except (ValueError, AttributeError) as exc:
        raise MetadataValidationError("document_id must be a UUID string") from exc
    parent_id = record["parent_chunk_id"]
    if parent_id is not None and not isinstance(parent_id, str):
        raise MetadataValidationError("parent_chunk_id must be a string or null")
    for field in ("species", "topic", "disease"):
        if not isinstance(record[field], list) or not all(
            isinstance(value, str) for value in record[field]
        ):
            raise MetadataValidationError(f"{field} must be a list of strings")
    for field in ("page_start", "page_end"):
        value = record[field]
        if value is not None and (not isinstance(value, int) or isinstance(value, bool) or value < 1):
            raise MetadataValidationError(f"{field} must be a positive integer or null")
    start, end = record["page_start"], record["page_end"]
    if start is not None and end is not None and end < start:
        raise MetadataValidationError("page_end cannot be earlier than page_start")
    confidence = record["extraction_confidence"]
    if confidence is not None and (
        not isinstance(confidence, (int, float)) or isinstance(confidence, bool) or not 0 <= confidence <= 1
    ):
        raise MetadataValidationError("extraction_confidence must be between 0 and 1 or null")
    checksum = record["content_checksum"]
    if not isinstance(checksum, str) or not _SHA256_PATTERN.fullmatch(checksum):
        raise MetadataValidationError("content_checksum must be a lowercase SHA-256 hex digest")
    dimension = record["embedding_dimension"]
    if dimension is not None and (
        not isinstance(dimension, int) or isinstance(dimension, bool) or dimension < 1
    ):
        raise MetadataValidationError("embedding_dimension must be a positive integer or null")
    for field in ("chapter", "section", "embedding_model", "embedding_version"):
        if record[field] is not None and not isinstance(record[field], str):
            raise MetadataValidationError(f"{field} must be a string or null")


def merge_document_chunk_metadata(
    document_metadata: Mapping[str, Any], chunk_metadata: Mapping[str, Any]
) -> dict[str, Any]:
    """Inherit document defaults; explicit non-null chunk values take precedence.

    An explicit empty list is preserved, allowing a curator to mark a chunk as
    intentionally untagged instead of silently inheriting document-wide tags.
    """
    merged = dict(document_metadata)
    if "topics" in merged and "topic" not in chunk_metadata:
        merged["topic"] = list(merged["topics"] or [])
    for field, value in chunk_metadata.items():
        if value is not None:
            merged[field] = value
    return merged
