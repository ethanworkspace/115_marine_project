"""Disease/entity-aware chunks using only explicit headings and labels."""

from __future__ import annotations

import re
from typing import Any

from .common import ChunkFactory, TextUnit, configured_ranges


DISEASE_HEADING_RE = re.compile(r"(?m)^\s*(?P<name>[^\n。；;]{2,48}(?:病|疾病))\s*$")
ENUM_PREFIX_RE = re.compile(r"^(?:[（(]\s*[一二三四五六七八九十A-Ga-g\d]+\s*[）)]|[一二三四五六七八九十]+[、.])\s*(?P<entity>.+)$")
LABEL_RE = re.compile(
    r"(?m)^\s*(?:\d{1,2}[.、)]\s*)?(?P<label>病原|宿主|病徵|症狀|診斷|防治|治療|預防|病因|流行病學|病理)(?:\s*[:：][^\n]*)?\s*$"
)
GENERIC_NAMES = {"疾病", "病害", "疾病防治", "病害防治", "魚病", "常見病害", "寄生蟲病", "細菌性疾病"}
BROAD_CATEGORY_MARKERS = ("常見", "五大類", "疾病概述", "病害資料")


def _explicit_disease_heading(text: str, match: re.Match[str]) -> str | None:
    raw = match.group("name").strip()
    if any(marker in raw for marker in BROAD_CATEGORY_MARKERS):
        return None
    enumeration = ENUM_PREFIX_RE.match(raw)
    if enumeration:
        name = enumeration.group("entity").strip()
        return name if name not in GENERIC_NAMES else None
    # An unnumbered entity is accepted only as a short standalone heading separated from prose.
    if len(raw) <= 12 and raw not in GENERIC_NAMES and not re.search(r"[，,。：；;]", raw):
        before = text[max(0, match.start() - 4):match.start()]
        after = text[match.end():min(len(text), match.end() + 4)]
        if re.search(r"\n\s*\n\s*$", before) or re.match(r"\s*\n\s*\n", after):
            return raw
    return None


def _emit_page_scoped(document: dict[str, Any], unit: TextUnit, factory: ChunkFactory,
                      start: int, end: int, section: str) -> None:
    """Keep unclassified disease prose page-local until entity headings are verified."""
    for page_start, page_end, _page in unit.boundaries:
        left, right = max(start, page_start), min(end, page_end)
        if left >= right or not unit.text[left:right].strip():
            continue
        parent = factory.add_text(document=document, unit=unit, start=left, end=right,
                                  strategy="disease", chunk_type="parent", section=section,
                                  warning="disease entity is not explicit; disease metadata left unknown")
        if not parent:
            continue
        for child_start, child_end in configured_ranges(unit, left, right, factory.config):
            factory.add_text(document=document, unit=unit, start=child_start, end=child_end,
                             strategy="disease", chunk_type="child", parent_chunk_id=parent["chunk_id"],
                             section=section, warning="disease entity requires review")


def chunk_disease(document: dict[str, Any], unit: TextUnit, factory: ChunkFactory) -> None:
    text = unit.text
    entities = [(m, _explicit_disease_heading(text, m)) for m in DISEASE_HEADING_RE.finditer(text)]
    entities = [(m, name) for m, name in entities if name]
    if not entities:
        # No specific entity means metadata stays unknown and parent context is page-local.
        broad = next((m for m in DISEASE_HEADING_RE.finditer(text)
                      if ENUM_PREFIX_RE.match(m.group("name").strip()) and
                      any(marker in m.group("name") for marker in BROAD_CATEGORY_MARKERS)), None)
        if broad:
            _emit_page_scoped(document, unit, factory, 0, broad.start(), "未標示疾病段落")
            _emit_page_scoped(document, unit, factory, broad.start(), len(text), broad.group("name").strip())
        else:
            _emit_page_scoped(document, unit, factory, 0, len(text), "未標示疾病段落")
        return
    prefix_end = entities[0][0].start()
    segments: list[tuple[int, int, str | None]] = []
    if text[:prefix_end].strip():
        _emit_page_scoped(document, unit, factory, 0, prefix_end, "未標示疾病段落")
    for idx, (entity, name) in enumerate(entities):
        end = entities[idx + 1][0].start() if idx + 1 < len(entities) else len(text)
        segments.append((entity.start(), end, name))
    for start, end, disease in segments:
        parent = factory.add_text(document=document, unit=unit, start=start, end=end,
                                  strategy="disease", chunk_type="parent", disease=disease,
                                  warning="disease entity is explicit heading" if disease else "introductory text; disease unknown")
        if not parent:
            continue
        labels = [m for m in LABEL_RE.finditer(text, start, end)]
        if labels:
            child_ranges: list[tuple[int, int, str]] = []
            if text[start:labels[0].start()].strip():
                child_ranges.extend((child_start, child_end, "概述") for child_start, child_end in configured_ranges(
                    unit, start, labels[0].start(), factory.config))
            for idx, label in enumerate(labels):
                label_end = labels[idx + 1].start() if idx + 1 < len(labels) else end
                for child_start, child_end in configured_ranges(unit, label.start(), label_end, factory.config):
                    child_ranges.append((child_start, child_end, label.group("label")))
        else:
            child_ranges = [(a, b, disease or "未標示疾病段落") for a, b in configured_ranges(
                unit, start, end, factory.config)]
        for child_start, child_end, section in child_ranges:
            factory.add_text(document=document, unit=unit, start=child_start, end=child_end,
                             strategy="disease", chunk_type="child", parent_chunk_id=parent["chunk_id"],
                             disease=disease, section=section)
