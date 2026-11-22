"""Typed data model for shadow chunks; this is not the production index schema."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


ChunkType = Literal["parent", "child"]


@dataclass(slots=True)
class ChunkRecord:
    chunk_id: str
    document_id: str
    parent_chunk_id: str | None
    chunk_type: ChunkType
    chunk_strategy: str
    chunk_version: str
    text: str
    species: str | None
    topic: str | None
    disease: str | None
    chapter: str | None
    section: str | None
    article: str | None
    page_start: int
    page_end: int
    source_span_ids: list[str]
    parser_name: str
    parser_version: str
    extraction_method: str
    extraction_confidence: float | None
    ingestion_status: str
    source_verified: bool
    legal_status: str
    chunkable: bool
    indexable: bool
    content_checksum: str
    warnings: list[str] = field(default_factory=list)
    table_data: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if not self.chunk_id or not self.document_id or not self.text.strip():
            raise ValueError("chunk_id, document_id and non-empty text are required")
        if self.page_start < 1 or self.page_end < self.page_start:
            raise ValueError("chunk pages must be positive and ordered")
        if not self.source_span_ids:
            raise ValueError("every chunk requires at least one source span")
        if self.chunk_type not in {"parent", "child"}:
            raise ValueError("chunk_type must be parent or child")
        if self.chunk_type == "child" and not self.parent_chunk_id:
            raise ValueError("child chunks must reference a parent")
        if self.indexable and not self.chunkable:
            raise ValueError("indexable chunks must be chunkable")
        if self.extraction_confidence is not None and not 0 <= self.extraction_confidence <= 1:
            raise ValueError("extraction_confidence must be between 0 and 1")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
