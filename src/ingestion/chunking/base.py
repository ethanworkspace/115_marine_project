"""Shared interfaces and strategy routing types."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class StrategyDecision:
    strategy: str
    warning: str | None = None
    evidence: tuple[str, ...] = ()


class TextChunker(Protocol):
    def chunk_document(self, document: dict[str, Any], pages: list[dict[str, Any]], factory: Any) -> None:
        """Append records to a ChunkFactory without mutating source records."""
