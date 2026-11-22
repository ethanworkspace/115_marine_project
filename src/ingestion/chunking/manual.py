"""Heading-aware manual chunks; children are split only inside one heading node."""

from __future__ import annotations

import re
from typing import Any

from .common import ChunkFactory, TextUnit, configured_ranges


HEADING_RE = re.compile(
    r"(?m)^\s*(?P<heading>(?:第\s*[^\n]{0,24}[編章節][^\n]{0,80}|#{1,6}\s+[^\n]{1,100}|[一二三四五六七八九十]+、[^\n]{1,80}|（[一二三四五六七八九十]+）[^\n]{1,80}))\s*$"
)
CHAPTER_RE = re.compile(r"第\s*[^\n]{0,24}[編章]")
SECTION_RE = re.compile(r"第\s*[^\n]{0,24}節|#{1,6}\s+[^\n]{1,100}")


def _kind(value: str) -> str:
    if re.search(r"第\s*[^\n]{0,24}[編章]", value):
        return "chapter"
    if "節" in value or value.startswith("#"):
        return "section"
    return "subsection"


def chunk_manual(document: dict[str, Any], unit: TextUnit, factory: ChunkFactory) -> None:
    text = unit.text
    headings = list(HEADING_RE.finditer(text))
    if not headings:
        from .fallback import chunk_fallback_unit
        chunk_fallback_unit(document, unit, factory, warning="manual strategy found no heading; isolated fallback used")
        return
    nodes: list[tuple[int, int, str, str | None, str | None]] = []
    if text[:headings[0].start()].strip():
        nodes.append((0, headings[0].start(), "前言", None, "前言"))
    chapter: str | None = None
    section: str | None = None
    for idx, heading in enumerate(headings):
        value = heading.group("heading").strip()
        kind = _kind(value)
        if kind == "chapter":
            chapter, section = value, None
        elif kind == "section":
            section = value
        else:
            section = value
        end = headings[idx + 1].start() if idx + 1 < len(headings) else len(text)
        nodes.append((heading.start(), end, value, chapter, section))
    for start, end, label, chapter_value, section_value in nodes:
        parent = factory.add_text(document=document, unit=unit, start=start, end=end,
                                  strategy="manual", chunk_type="parent", chapter=chapter_value,
                                  section=section_value or label)
        if not parent:
            continue
        ranges = configured_ranges(unit, start, end, factory.config)
        for child_start, child_end in ranges:
            factory.add_text(document=document, unit=unit, start=child_start, end=child_end,
                             strategy="manual", chunk_type="child", parent_chunk_id=parent["chunk_id"],
                             chapter=chapter_value, section=section_value or label)
