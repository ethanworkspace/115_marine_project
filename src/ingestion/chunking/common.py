"""Stable identifiers, exact page spans, metadata inheritance, and output records."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import asdict, is_dataclass
from typing import Any

from .models import ChunkRecord


CHUNK_VERSION = "2.0.0-shadow"
_NAMESPACE = uuid.UUID("54a82a36-7f14-5c31-ae65-33c49bb91a3d")
SPECIES_NAMES = ("吳郭魚", "虱目魚", "石斑魚", "鱸魚", "烏魚", "鰻魚")


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _stable_id(prefix: str, payload: Any) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"{prefix}_{uuid.uuid5(_NAMESPACE, canonical).hex}"


def stable_chunk_id(*, document_id: str, source_span_ids: list[str], strategy: str,
                    version: str, chunk_type: str, content_checksum: str,
                    parent_chunk_id: str | None) -> str:
    return _stable_id("chunk", {
        "document_id": document_id,
        "source_span_ids": sorted(source_span_ids),
        "strategy": strategy,
        "version": version,
        "chunk_type": chunk_type,
        "content_checksum": content_checksum,
        "parent_chunk_id": parent_chunk_id,
    })


def species_from_explicit_text(document: dict[str, Any], section: str | None = None) -> str | None:
    values = [document.get("title") or "", section or ""]
    raw = document.get("species") or []
    if isinstance(raw, str):
        raw = [raw]
    for value in raw:
        if value and str(value).casefold() not in {"unknown", "其他", "未知"}:
            return str(value)
    haystack = " ".join(map(str, values))
    return next((name for name in SPECIES_NAMES if name in haystack), None)


def document_topic(document: dict[str, Any], section: str | None = None) -> str | None:
    topics = document.get("topics") or []
    if isinstance(topics, str):
        topics = [topics]
    for topic in topics:
        if topic and str(topic).casefold() not in {"unknown", "其他", "未知"}:
            return str(topic)
    explicit = section or ""
    for topic in ("水質", "疾病", "病害", "飼養", "飼料", "用藥", "法規", "氣候", "管理", "繁殖"):
        if topic in explicit:
            return topic
    return None


def is_high_risk(document: dict[str, Any], strategy: str, section: str | None = None) -> bool:
    haystack = " ".join(str(value or "") for value in (
        document.get("title"), document.get("document_type"), document.get("topics"), section,
    )).casefold()
    terms = ("法規", "法令", "用藥", "藥物", "停藥期", "休藥", "water quality standard", "水質安全", "水質標準", "regulation", "medication", "withdrawal")
    return strategy == "regulation" or any(term.casefold() in haystack for term in terms)


class TextUnit:
    """Joined contiguous pages with exact offsets back to each source page."""

    def __init__(self, pages: list[dict[str, Any]]) -> None:
        self.pages = pages
        self.text = ""
        self.boundaries: list[tuple[int, int, dict[str, Any]]] = []
        cursor = 0
        parts: list[str] = []
        for idx, page in enumerate(pages):
            value = str(page.get("selected_text") or page.get("text") or "")
            if idx:
                parts.append("\n")
                cursor += 1
            start = cursor
            parts.append(value)
            cursor += len(value)
            self.boundaries.append((start, cursor, page))
        self.text = "".join(parts)

    def spans(self, start: int, end: int, registry: dict[str, dict[str, Any]]) -> list[str]:
        ids: list[str] = []
        for page_start, page_end, page in self.boundaries:
            left, right = max(start, page_start), min(end, page_end)
            if left >= right:
                continue
            source_text = self.text[left:right]
            if not source_text.strip():
                continue
            page_number = page.get("page_number")
            if not page_number:
                continue
            local_start, local_end = left - page_start, right - page_start
            payload = {
                "document_id": page["document_id"],
                "checksum": page["file_checksum"],
                "page": page_number,
                "start": local_start,
                "end": local_end,
                "text_checksum": sha256_text(source_text),
                "parser": page.get("parser_name"),
                "parser_version": page.get("parser_version"),
                "extraction_method": page.get("extraction_method"),
            }
            span_id = _stable_id("span", payload)
            registry.setdefault(span_id, {
                "source_span_id": span_id,
                "document_id": page["document_id"],
                "file_checksum": page["file_checksum"],
                "page_number": page_number,
                "start_position": local_start,
                "end_position": local_end,
                "text_checksum": sha256_text(source_text),
                "parser_name": page.get("parser_name"),
                "parser_version": page.get("parser_version"),
                "extraction_method": page.get("extraction_method"),
                "extraction_confidence": page.get("extraction_confidence"),
                "source_reference": "page_text",
            })
            ids.append(span_id)
        return ids


class ChunkFactory:
    def __init__(self, *, config: dict[str, Any], span_registry: dict[str, dict[str, Any]]) -> None:
        self.config = config
        self.span_registry = span_registry
        self.records: list[dict[str, Any]] = []

    def add_text(self, *, document: dict[str, Any], unit: TextUnit, start: int, end: int,
                 strategy: str, chunk_type: str, parent_chunk_id: str | None = None,
                 chapter: str | None = None, section: str | None = None, article: str | None = None,
                 disease: str | None = None, warning: str | None = None, prefix: str = "") -> dict[str, Any] | None:
        raw_start, raw_end = max(0, start), min(len(unit.text), end)
        while raw_start < raw_end and unit.text[raw_start].isspace():
            raw_start += 1
        while raw_end > raw_start and unit.text[raw_end - 1].isspace():
            raw_end -= 1
        raw_text = unit.text[raw_start:raw_end]
        if not raw_text.strip():
            return None
        span_ids = unit.spans(raw_start, raw_end, self.span_registry)
        if not span_ids:
            return None
        text = (prefix + raw_text).strip()
        checksum = sha256_text(text)
        spans = [self.span_registry[sid] for sid in span_ids]
        page_numbers = [int(span["page_number"]) for span in spans]
        pages = [entry[2] for entry in unit.boundaries if entry[2].get("page_number") in page_numbers]
        methods = sorted({str(p.get("extraction_method") or "unknown") for p in pages})
        confidences = [float(p["extraction_confidence"]) for p in pages if p.get("extraction_confidence") is not None]
        source_verified = bool(document.get("source_verified") is True)
        legal_status = str(document.get("legal_status") or "unknown")
        chunkable = bool(document.get("_chunkable", True))
        indexable = chunkable and source_verified and (not is_high_risk(document, strategy, section) or legal_status == "current")
        chunk_id = stable_chunk_id(
            document_id=str(document["document_id"]), source_span_ids=span_ids, strategy=strategy,
            version=str(self.config.get("chunk_version", CHUNK_VERSION)), chunk_type=chunk_type,
            content_checksum=checksum, parent_chunk_id=parent_chunk_id,
        )
        record = ChunkRecord(
            chunk_id=chunk_id,
            document_id=str(document["document_id"]),
            parent_chunk_id=parent_chunk_id,
            chunk_type=chunk_type,
            chunk_strategy=strategy,
            chunk_version=str(self.config.get("chunk_version", CHUNK_VERSION)),
            text=text,
            species=species_from_explicit_text(document, section),
            topic=document_topic(document, section),
            disease=disease,
            chapter=chapter,
            section=section,
            article=article,
            page_start=min(page_numbers),
            page_end=max(page_numbers),
            source_span_ids=span_ids,
            parser_name=str(pages[0].get("parser_name") or "unknown") if pages else "unknown",
            parser_version=str(pages[0].get("parser_version") or "unknown") if pages else "unknown",
            extraction_method=methods[0] if len(methods) == 1 else "mixed",
            extraction_confidence=min(confidences) if confidences else None,
            ingestion_status="accepted_with_warning" if any(p.get("ingestion_status") == "accepted_with_warning" for p in pages) else "accepted",
            source_verified=source_verified,
            legal_status=legal_status,
            chunkable=chunkable,
            indexable=indexable,
            content_checksum=checksum,
            warnings=[warning] if warning else [],
        ).to_dict()
        self.records.append(record)
        return record

    def add_table(self, *, document: dict[str, Any], page: dict[str, Any], table: dict[str, Any],
                  row_start: int, row_end: int, chunk_type: str,
                  parent_chunk_id: str | None = None) -> dict[str, Any] | None:
        headers = [str(v) for v in table.get("headers", [])]
        units = list(table.get("units") or [])
        rows = table.get("rows") or []
        caption = str(table.get("caption") or "Table")
        row_slice = rows[row_start:row_end]
        rendered_headers = [f"{head} ({units[i]})" if i < len(units) and units[i] else head for i, head in enumerate(headers)]
        lines = [caption, " | ".join(rendered_headers)]
        lines.extend(" | ".join(str(cell) for cell in row) for row in row_slice)
        lines.extend(f"Footnote: {note}" for note in (table.get("footnotes") or []))
        text = "\n".join(line for line in lines if line.strip())
        if not text.strip() or not page.get("page_number"):
            return None
        table_ref_id = _stable_id("span", {
            "document_id": table["document_id"], "file_checksum": page["file_checksum"],
            "page": page["page_number"], "table_id": table["table_id"],
            "row_start": row_start, "row_end": row_end,
            "text_checksum": sha256_text(text), "parser": table.get("parser_name"),
        })
        self.span_registry.setdefault(table_ref_id, {
            "source_span_id": table_ref_id,
            "document_id": table["document_id"],
            "file_checksum": page["file_checksum"],
            "page_number": page["page_number"],
            "start_position": None,
            "end_position": None,
            "text_checksum": sha256_text(text),
            "parser_name": table.get("parser_name") or page.get("parser_name"),
            "parser_version": page.get("parser_version"),
            "extraction_method": page.get("extraction_method"),
            "extraction_confidence": table.get("confidence"),
            "source_reference": "table_rows",
            "table_id": table["table_id"],
            "row_start": row_start,
            "row_end": row_end,
        })
        checksum = sha256_text(text)
        strategy = "table"
        source_verified = bool(document.get("source_verified") is True)
        legal_status = str(document.get("legal_status") or "unknown")
        chunkable = True
        indexable = source_verified and (not is_high_risk(document, strategy) or legal_status == "current")
        chunk_id = stable_chunk_id(
            document_id=table["document_id"], source_span_ids=[table_ref_id], strategy=strategy,
            version=str(self.config.get("chunk_version", CHUNK_VERSION)), chunk_type=chunk_type,
            content_checksum=checksum, parent_chunk_id=parent_chunk_id,
        )
        record = ChunkRecord(
            chunk_id=chunk_id, document_id=table["document_id"], parent_chunk_id=parent_chunk_id,
            chunk_type=chunk_type, chunk_strategy=strategy,
            chunk_version=str(self.config.get("chunk_version", CHUNK_VERSION)), text=text,
            species=species_from_explicit_text(document), topic=document_topic(document, caption), disease=None,
            chapter=None, section=caption, article=None, page_start=int(page["page_number"]),
            page_end=int(page["page_number"]), source_span_ids=[table_ref_id],
            parser_name=str(table.get("parser_name") or page.get("parser_name") or "unknown"),
            parser_version=str(page.get("parser_version") or "unknown"),
            extraction_method=str(page.get("extraction_method") or "unknown"),
            extraction_confidence=table.get("confidence"),
            ingestion_status=str(table.get("ingestion_status") or "review"),
            source_verified=source_verified, legal_status=legal_status, chunkable=chunkable,
            indexable=indexable, content_checksum=checksum,
            warnings=list(table.get("warnings") or []),
            table_data={
                "table_id": table["table_id"], "caption": caption,
                "headers": headers, "rows": row_slice, "units": units,
                "footnotes": list(table.get("footnotes") or []),
                "page_number": page["page_number"], "row_start": row_start, "row_end": row_end,
            },
        ).to_dict()
        self.records.append(record)
        return record


def contiguous_page_groups(pages: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    groups: list[list[dict[str, Any]]] = []
    for page in sorted(pages, key=lambda item: int(item.get("page_number") or 0)):
        number = page.get("page_number")
        if not number:
            continue
        if not groups or int(number) != int(groups[-1][-1]["page_number"]) + 1:
            groups.append([page])
        else:
            groups[-1].append(page)
    return groups


def text_ranges(unit: TextUnit, start: int, end: int, *, max_size: int, overlap: int,
                target_size: int | None = None, minimum_size: int = 0) -> list[tuple[int, int]]:
    """Paragraph/sentence-first splitting scoped to one already isolated structure node."""
    text = unit.text
    target_size = min(target_size or max_size, max_size)
    if end - start <= max_size:
        return [(start, end)]
    # Hard boundaries are paragraph and line ends. Sentence boundaries are the next fallback.
    boundaries = [m.end() for m in re.finditer(r"(?:\n\s*\n|\n|[。！？；!?;])", text[start:end])]
    boundaries = [start + value for value in boundaries]
    cuts: list[tuple[int, int]] = []
    cursor = start
    previous_cut = start
    while cursor < end:
        ceiling = min(end, cursor + max_size)
        candidates = [point for point in boundaries if previous_cut < point <= ceiling]
        if candidates:
            preferred = min(end, cursor + target_size)
            before_target = [point for point in candidates if point <= preferred]
            cut = max(before_target) if before_target else min(candidates)
        else:
            # Last-resort character boundary is restricted to the current section/article/page.
            cut = ceiling
        if cut <= cursor:
            cut = ceiling
        cuts.append((cursor, cut))
        previous_cut = cut
        if cut >= end:
            break
        cursor = max(start, cut - overlap)
        # Ensure progress even when overlap is larger than the produced segment.
        if cuts and cursor <= cuts[-1][0]:
            cursor = cuts[-1][1]
    # Merge a short trailing fragment into the previous child when configured bounds allow it.
    if len(cuts) > 1 and cuts[-1][1] - cuts[-1][0] < minimum_size:
        prior = cuts[-2]
        if cuts[-1][1] - prior[0] <= max_size:
            cuts[-2:] = [(prior[0], cuts[-1][1])]
    return cuts


def configured_ranges(unit: TextUnit, start: int, end: int, config: dict[str, Any]) -> list[tuple[int, int]]:
    return text_ranges(
        unit, start, end,
        max_size=int(config["max_size"]),
        overlap=int(config["overlap"]),
        target_size=int(config.get("target_size", config["max_size"])),
        minimum_size=int(config.get("minimum_size", 0)),
    )


def line_spans(text: str, start: int, end: int, pattern: re.Pattern[str]) -> list[tuple[int, int, str]]:
    matches = list(pattern.finditer(text, start, end))
    if not matches:
        return [(start, end, "")]
    result: list[tuple[int, int, str]] = []
    first = matches[0].start()
    if text[start:first].strip():
        result.append((start, first, ""))
    for index, match in enumerate(matches):
        next_start = matches[index + 1].start() if index + 1 < len(matches) else end
        result.append((match.start(), next_start, match.group(0).strip()))
    return result
