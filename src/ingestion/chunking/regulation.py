"""Article-aware regulation chunks with explicit parent article and child clauses."""

from __future__ import annotations

import re
from typing import Any

from .common import ChunkFactory, TextUnit, configured_ranges


ARTICLE_RE = re.compile(r"第\s*[〇零一二三四五六七八九十百千\d]+\s*條")
CHAPTER_RE = re.compile(r"第.{1,24}章")
SECTION_RE = re.compile(r"第.{1,24}節")
CLAUSE_RE = re.compile(r"(?m)^\s*(?:第\s*[〇零一二三四五六七八九十\d]+\s*項|[一二三四五六七八九十]+、|（[一二三四五六七八九十]+）|\([一二三四五六七八九十]+\))")


def chunk_regulation(document: dict[str, Any], unit: TextUnit, factory: ChunkFactory) -> None:
    text = unit.text
    articles = list(ARTICLE_RE.finditer(text))
    if not articles:
        # The router normally requires article markers; keep a defensive, visible fallback.
        from .fallback import chunk_fallback_unit
        chunk_fallback_unit(document, unit, factory, warning="regulation strategy found no article marker; isolated fallback used")
        return
    prefix_end = articles[0].start()
    if text[:prefix_end].strip():
        parent = factory.add_text(document=document, unit=unit, start=0, end=prefix_end,
                                  strategy="regulation", chunk_type="parent", section="前言",
                                  warning="content before first article retained as preamble")
        if parent:
            for child_start, child_end in configured_ranges(unit, 0, prefix_end, factory.config):
                factory.add_text(document=document, unit=unit, start=child_start, end=child_end,
                                 strategy="regulation", chunk_type="child", parent_chunk_id=parent["chunk_id"],
                                 section="前言", warning="preamble child")
    for idx, match in enumerate(articles):
        start = match.start()
        end = articles[idx + 1].start() if idx + 1 < len(articles) else len(text)
        value = text[start:end]
        if not value.strip():
            continue
        chapter_matches = list(CHAPTER_RE.finditer(text, 0, start))
        section_matches = list(SECTION_RE.finditer(text, 0, start))
        chapter = chapter_matches[-1].group(0).strip() if chapter_matches else None
        section = section_matches[-1].group(0).strip() if section_matches else None
        article = match.group(0).replace(" ", "")
        parent = factory.add_text(document=document, unit=unit, start=start, end=end,
                                  strategy="regulation", chunk_type="parent", chapter=chapter,
                                  section=section, article=article)
        if not parent:
            continue
        clauses = [m.start() for m in CLAUSE_RE.finditer(text, start + len(match.group(0)), end)]
        boundaries = [start, *clauses, end]
        ranges = [(boundaries[i], boundaries[i + 1]) for i in range(len(boundaries) - 1)]
        # If the article has no clauses, recursive splitting is still scoped within this one article.
        if len(ranges) == 1:
            ranges = configured_ranges(unit, start, end, factory.config)
        else:
            split_ranges: list[tuple[int, int]] = []
            for clause_start, clause_end in ranges:
                split_ranges.extend(configured_ranges(unit, clause_start, clause_end, factory.config))
            ranges = split_ranges
        for child_start, child_end in ranges:
            factory.add_text(
                document=document, unit=unit, start=child_start, end=child_end,
                strategy="regulation", chunk_type="child", parent_chunk_id=parent["chunk_id"],
                chapter=chapter, section=section, article=article,
            )
