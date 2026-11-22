"""Paragraph-aware recursive fallback, scoped to one page or known structure node."""

from __future__ import annotations

from typing import Any

from .common import ChunkFactory, TextUnit, configured_ranges


def chunk_fallback_unit(document: dict[str, Any], unit: TextUnit, factory: ChunkFactory,
                        warning: str | None = None) -> None:
    if not unit.text.strip():
        return
    parent = factory.add_text(document=document, unit=unit, start=0, end=len(unit.text),
                              strategy="fallback", chunk_type="parent", section=None,
                              warning=warning)
    if not parent:
        return
    ranges = configured_ranges(unit, 0, len(unit.text), factory.config)
    for start, end in ranges:
        factory.add_text(document=document, unit=unit, start=start, end=end,
                         strategy="fallback", chunk_type="child", parent_chunk_id=parent["chunk_id"],
                         warning=warning)


def chunk_fallback(document: dict[str, Any], pages: list[dict[str, Any]], factory: ChunkFactory,
                   warning: str | None = None) -> None:
    # Page-local fallback prevents overlap or context from crossing unknown structural boundaries.
    for page in pages:
        chunk_fallback_unit(document, TextUnit([page]), factory, warning=warning)
