"""Structured table extraction helpers with conservative quality flags."""

from __future__ import annotations

import hashlib
import re
import uuid
from typing import Any, Iterable

from ..models import TableRecord


_TABLE_NAMESPACE = uuid.UUID("cc4d8948-b5cf-5c1a-bfa4-aedc047b6bd4")
_UNIT_RE = re.compile(r"(?:%|‰|mg\s*/\s*(?:L|kg)|g\s*/\s*(?:L|kg)|kg|g|mm|cm|m|ppm|ppb|°\s*[CF]|℃|℉|尾\s*/\s*(?:kg|m[³3]))", re.I)
_FOOTNOTE_RE = re.compile(r"^\s*(?:註|附註|備註|說明|note\b|notes\b|\*+|\d+[.)、])", re.I)


def _cell(value: Any) -> str:
    return "" if value is None else str(value).replace("\r", " ").replace("\n", " ").strip()


def _markdown(headers: list[str], rows: list[list[str]]) -> str:
    columns = max(len(headers), max((len(row) for row in rows), default=0))
    if columns == 0:
        return ""
    normalized_headers = (headers + [""] * columns)[:columns]
    values = [normalized_headers, *[(row + [""] * columns)[:columns] for row in rows]]
    escape = lambda value: value.replace("|", "\\|")
    return "\n".join("| " + " | ".join(escape(value) for value in row) + " |" for row in values[:1]) + "\n| " + " | ".join("---" for _ in range(columns)) + " |" + (
        "\n" + "\n".join("| " + " | ".join(escape(value) for value in row) + " |" for row in values[1:])
        if len(values) > 1 else ""
    )


def _units(headers: list[str]) -> list[str | None]:
    result: list[str | None] = []
    for header in headers:
        match = _UNIT_RE.search(header)
        result.append(match.group(0).strip() if match else None)
    return result


def _footnotes(page: Any, table_bottom: float, max_distance: float) -> list[str]:
    notes: list[tuple[float, str]] = []
    try:
        data = page.get_text("dict", sort=True)
        for block in data.get("blocks", []):
            for line in block.get("lines", []):
                text = "".join(span.get("text", "") for span in line.get("spans", [])).strip()
                bbox = line.get("bbox")
                if not text or not bbox:
                    continue
                distance = float(bbox[1]) - table_bottom
                if -1 <= distance <= max_distance and _FOOTNOTE_RE.match(text):
                    notes.append((float(bbox[1]), text))
    except Exception:
        return []
    return [text for _, text in sorted(notes)]


def extract_pdf_tables(
    page: Any,
    document_id: str,
    page_number: int,
    parser_name: str,
    min_rows: int,
    min_columns: int,
    min_nonempty_ratio: float,
    min_header_ratio: float,
    association_max_distance: float = 72,
) -> tuple[list[TableRecord], list[str]]:
    records: list[TableRecord] = []
    warnings: list[str] = []
    try:
        finder = page.find_tables()
        found = finder.tables
    except Exception as exc:
        return [], [f"table_detection_failed:{type(exc).__name__}:{exc}"]

    for index, table in enumerate(found, 1):
        table_warnings: list[str] = []
        try:
            raw_rows = [[_cell(value) for value in row] for row in table.extract()]
        except Exception as exc:
            raw_rows = []
            table_warnings.append(f"table_cells_unavailable:{type(exc).__name__}:{exc}")

        raw_headers: list[str] = []
        header = getattr(table, "header", None)
        if header is not None:
            try:
                raw_headers = [_cell(value) for value in (header.names or [])]
            except Exception:
                raw_headers = []
        header_ratio = sum(bool(value) for value in raw_headers) / max(1, len(raw_headers))
        if not raw_headers or header_ratio < min_header_ratio:
            table_warnings.append("header_not_reliably_extracted")
            headers: list[str] = []
            rows = raw_rows
        else:
            headers = raw_headers
            rows = raw_rows if bool(getattr(header, "external", False)) else raw_rows[1:]

        columns = max(len(headers), max((len(row) for row in raw_rows), default=0))
        cell_count = sum(len(row) for row in raw_rows)
        populated = sum(bool(value) for row in raw_rows for value in row)
        nonempty_ratio = populated / max(1, cell_count)
        confidence = max(0.0, min(1.0, 0.55 * nonempty_ratio + 0.45 * header_ratio))
        if len(rows) < min_rows:
            table_warnings.append("too_few_body_rows")
        if columns < min_columns:
            table_warnings.append("too_few_columns")
        if nonempty_ratio < min_nonempty_ratio:
            table_warnings.append("sparse_or_empty_cells")
        if len(headers) != columns:
            table_warnings.append("header_column_count_mismatch")

        caption = None
        try:
            bbox = table.bbox
            possible: list[tuple[float, str]] = []
            for block in page.get_text("dict", sort=True).get("blocks", []):
                for line in block.get("lines", []):
                    text = "".join(span.get("text", "") for span in line.get("spans", [])).strip()
                    line_bbox = line.get("bbox")
                    if not text or not line_bbox or not re.match(r"^表\s*[\d一二三四五六七八九十.、]", text):
                        continue
                    gap = float(bbox[1]) - float(line_bbox[3])
                    if -2 <= gap <= association_max_distance:
                        possible.append((abs(gap), text))
            if possible:
                caption = min(possible, key=lambda candidate: candidate[0])[1]
        except Exception:
            bbox = None

        footnotes = _footnotes(page, float(bbox[3]), association_max_distance) if bbox else []
        if not footnotes:
            table_warnings.append("footnotes_not_associated; inspect surrounding page text")

        source_payload = f"{document_id}:{page_number}:{index}:{raw_rows!r}:{headers!r}"
        table_id = str(uuid.uuid5(_TABLE_NAMESPACE, hashlib.sha256(source_payload.encode("utf-8")).hexdigest()))
        record = TableRecord(
            table_id=table_id,
            document_id=document_id,
            page_number=page_number,
            caption=caption,
            headers=headers,
            rows=rows,
            markdown=_markdown(headers, rows),
            parser_name=parser_name,
            confidence=confidence,
            warnings=table_warnings,
            units=_units(headers),
            footnotes=footnotes,
            needs_review=bool(table_warnings),
        )
        records.append(record)
    return records, warnings


def make_office_table_record(
    document_id: str,
    page_number: int | None,
    table_index: int,
    headers: Iterable[str],
    rows: Iterable[Iterable[str]],
    parser_name: str,
) -> TableRecord:
    normalized_headers = [_cell(value) for value in headers]
    normalized_rows = [[_cell(value) for value in row] for row in rows]
    payload = f"{document_id}:{page_number}:{table_index}:{normalized_headers!r}:{normalized_rows!r}"
    table_id = str(uuid.uuid5(_TABLE_NAMESPACE, hashlib.sha256(payload.encode("utf-8")).hexdigest()))
    populated = sum(bool(value) for row in normalized_rows for value in row)
    count = sum(len(row) for row in normalized_rows)
    header_ratio = sum(bool(value) for value in normalized_headers) / max(1, len(normalized_headers))
    confidence = 0.55 * (populated / max(1, count)) + 0.45 * header_ratio
    warnings = ["physical_page_not_available_for_office_flow_document"]
    if not normalized_headers or not normalized_rows:
        warnings.append("table_structure_incomplete")
    return TableRecord(
        table_id=table_id,
        document_id=document_id,
        page_number=page_number,
        caption=None,
        headers=normalized_headers,
        rows=normalized_rows,
        markdown=_markdown(normalized_headers, normalized_rows),
        parser_name=parser_name,
        confidence=max(0.0, min(1.0, confidence)),
        warnings=warnings,
        units=_units(normalized_headers),
        footnotes=[],
        needs_review=True,
    )
