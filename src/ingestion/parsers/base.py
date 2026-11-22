"""Common parser protocol and provenance helpers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from ..checksum import sha256_file
from ..models import ParsedDocument


class ParserError(RuntimeError):
    pass


class UnsupportedFormatError(ParserError):
    pass


class Parser(ABC):
    name = "base"
    version = "1"
    extensions: tuple[str, ...] = ()

    @abstractmethod
    def parse(self, path: Path, manifest: dict[str, Any]) -> ParsedDocument:
        raise NotImplementedError

    @staticmethod
    def provenance(path: Path, manifest: dict[str, Any]) -> tuple[str, str, list[str]]:
        actual_checksum = sha256_file(path)
        document_id = str(manifest.get("document_id") or "")
        if not document_id:
            raise ParserError(f"manifest has no document_id for {path}")
        warnings: list[str] = []
        expected = manifest.get("checksum")
        if expected and expected != actual_checksum:
            warnings.append("manifest_checksum_mismatch: source file changed after manifest generation")
        return document_id, actual_checksum, warnings


class ParserInterface:
    """Structural type hint for callers that do not need a concrete base class."""

    name: str
    version: str
    extensions: tuple[str, ...]

    def parse(self, path: Path, manifest: dict[str, Any]) -> ParsedDocument:
        raise NotImplementedError
