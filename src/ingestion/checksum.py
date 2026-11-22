"""Stable document identifiers and SHA-256 duplicate detection."""

from __future__ import annotations

import hashlib
import unicodedata
import uuid
from collections.abc import Iterable
from pathlib import Path


# Fixed namespace: IDs are UUIDv5 values derived from a normalized root-relative path.
_DOCUMENT_NAMESPACE = uuid.UUID("0e225aa6-7e57-5dcc-b43d-0e4b8c3f8a12")


def normalize_document_path(path: str | Path) -> str:
    """Normalize a repository-relative path for stable IDs across OS path styles."""
    normalized = unicodedata.normalize("NFC", str(path).replace("\\", "/"))
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized.casefold()


def stable_document_id(path: str | Path) -> str:
    """Return the same UUID for the same logical relative path on every run."""
    logical_path = normalize_document_path(path)
    if not logical_path or logical_path.startswith("/") or ":/" in logical_path:
        raise ValueError("document ID requires a non-empty relative file path")
    return str(uuid.uuid5(_DOCUMENT_NAMESPACE, f"marine-rag-document:{logical_path}"))


def sha256_file(path: str | Path, chunk_size: int = 1024 * 1024) -> str:
    """Compute a file checksum without loading the entire document into memory."""
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for block in iter(lambda: source.read(chunk_size), b""):
            digest.update(block)
    return digest.hexdigest()


def find_duplicate_files(paths: Iterable[str | Path]) -> dict[str, str]:
    """Map each duplicate path to the first path with identical file bytes.

    Paths are processed in their supplied order. The caller should pass a sorted
    sequence to make the canonical copy deterministic. No files are deleted.
    """
    seen: dict[str, str] = {}
    duplicates: dict[str, str] = {}
    for path in paths:
        value = str(path)
        checksum = sha256_file(path)
        if checksum in seen:
            duplicates[value] = seen[checksum]
        else:
            seen[checksum] = value
    return duplicates
