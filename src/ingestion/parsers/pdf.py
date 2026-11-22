"""Page-oriented PDF parsing with native text and visual-layout provenance."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

try:
    import pymupdf as fitz
except ImportError:  # pragma: no cover
    import fitz  # type: ignore[no-redef]

from ..models import ImageRecord, PageRecord, ParsedDocument
from .base import Parser, ParserError
from .tables import extract_pdf_tables


class PDFParser(Parser):
    name = "pymupdf"
    version = getattr(fitz, "VersionBind", "unknown")
    extensions = (".pdf",)

    def __init__(self, config: dict[str, Any] | None = None):
        self.config = config or {}

    def parse(self, path: Path, manifest: dict[str, Any]) -> ParsedDocument:
        document_id, checksum, doc_warnings = self.provenance(path, manifest)
        pages: list[PageRecord] = []
        try:
            document = fitz.open(path)
        except Exception as exc:
            page = PageRecord(
                document_id=document_id,
                file_checksum=checksum,
                page_number=None,
                text="",
                native_text="",
                ocr_text="",
                extraction_method="failed",
                extraction_confidence=0.0,
                tables=[],
                images=[],
                parser_name=self.name,
                parser_version=self.version,
                warnings=[*doc_warnings, f"pdf_open_failed:{type(exc).__name__}:{exc}"],
                needs_review=True,
                classification="parser_error",
            )
            return ParsedDocument(document_id, manifest.get("file_path", path.name), checksum, self.name, self.version, [page], [*doc_warnings, "PDF could not be opened"], True, source_extension=".pdf")

        with document:
            for index, source_page in enumerate(document, 1):
                pages.append(self._parse_page(source_page, index, document_id, checksum, doc_warnings))
        needs_review = any(page.needs_review for page in pages) or bool(doc_warnings)
        warnings = list(dict.fromkeys(doc_warnings + [warning for page in pages for warning in page.warnings]))
        return ParsedDocument(
            document_id=document_id,
            file_path=manifest.get("file_path", path.name),
            file_checksum=checksum,
            parser_name=self.name,
            parser_version=self.version,
            pages=pages,
            warnings=warnings,
            needs_review=needs_review,
            source_extension=".pdf",
        )

    def _parse_page(self, page: Any, page_number: int, document_id: str, checksum: str, inherited_warnings: list[str]) -> PageRecord:
        warnings = list(inherited_warnings)
        try:
            # Match the project's previous PyMuPDF default extraction order so
            # Phase 0's empty-page count remains directly comparable.
            native_text = page.get_text("text") or ""
        except Exception as exc:
            native_text = ""
            warnings.append(f"native_text_extraction_failed:{type(exc).__name__}:{exc}")

        image_infos: list[dict[str, Any]] = []
        try:
            image_infos = page.get_image_info(xrefs=True)
        except Exception as exc:
            warnings.append(f"image_inventory_failed:{type(exc).__name__}:{exc}")
            try:
                image_infos = [{"xref": item[0], "width": item[2], "height": item[3]} for item in page.get_images(full=True)]
            except Exception as fallback_exc:
                warnings.append(f"image_inventory_fallback_failed:{type(fallback_exc).__name__}:{fallback_exc}")

        page_rect = page.rect
        page_area = max(0.0, float(page_rect.width) * float(page_rect.height))
        image_rects: list[tuple[float, float, float, float]] = []
        for info in image_infos:
            bbox = info.get("bbox")
            if bbox and len(bbox) == 4:
                x0, y0, x1, y1 = map(float, bbox)
                x0, y0 = max(x0, float(page_rect.x0)), max(y0, float(page_rect.y0))
                x1, y1 = min(x1, float(page_rect.x1)), min(y1, float(page_rect.y1))
                if x1 > x0 and y1 > y0:
                    image_rects.append((x0, y0, x1, y1))
        coverage = _rect_union_area(image_rects) / page_area if page_area else 0.0
        coverage = max(0.0, min(1.0, coverage))

        image_records: list[ImageRecord] = []
        for image_index, info in enumerate(image_infos):
            bbox = info.get("bbox")
            image_records.append(
                ImageRecord(
                    image_index=image_index,
                    xref=int(info["xref"]) if info.get("xref") else None,
                    width=int(info["width"]) if info.get("width") else None,
                    height=int(info["height"]) if info.get("height") else None,
                    bbox=tuple(float(value) for value in bbox) if bbox and len(bbox) == 4 else None,
                    coverage_ratio=_single_rect_ratio(bbox, page_rect, page_area) if bbox else None,
                )
            )

        try:
            drawings = page.get_drawings()
            drawing_count = len(drawings)
        except Exception as exc:
            drawing_count = 0
            warnings.append(f"vector_drawing_inventory_failed:{type(exc).__name__}:{exc}")

        pdf_config = self.config.get("pdf", self.config)
        table_records = []
        if pdf_config.get("extract_tables", True) and hasattr(page, "find_tables"):
            table_records, table_warnings = extract_pdf_tables(
                page=page,
                document_id=document_id,
                page_number=page_number,
                parser_name=self.name,
                min_rows=int(pdf_config.get("table_min_rows", 2)),
                min_columns=int(pdf_config.get("table_min_columns", 2)),
                min_nonempty_ratio=float(pdf_config.get("table_min_nonempty_ratio", 0.45)),
                min_header_ratio=float(pdf_config.get("table_min_header_ratio", 0.5)),
                association_max_distance=float(pdf_config.get("table_association_max_distance_points", 72)),
            )
            warnings.extend(table_warnings)
        elif pdf_config.get("extract_tables", True):
            warnings.append("table_extraction_unavailable_in_installed_pymupdf")

        page_config = pdf_config
        min_chars = int(page_config.get("native_text_min_chars", 40))
        candidate_coverage = float(page_config.get("ocr_candidate_image_coverage_min", 0.25))
        chart_coverage = float(page_config.get("image_chart_coverage_min", 0.02))
        min_drawings = int(page_config.get("vector_chart_min_drawings", 15))
        blank_drawings = int(page_config.get("blank_max_drawings", 1))
        char_count = len(native_text.strip())
        parser_failed = any(warning.startswith("native_text_extraction_failed") for warning in warnings)
        if parser_failed:
            classification = "parser_error"
        elif char_count >= min_chars:
            classification = "native_text"
        elif image_records and coverage >= candidate_coverage:
            classification = "ocr_candidate"
        elif (image_records and coverage >= chart_coverage) or drawing_count >= min_drawings:
            classification = "image_or_chart"
        elif not native_text.strip() and not image_records and drawing_count <= blank_drawings:
            classification = "blank"
        else:
            classification = "manual_review"

        extraction_method = "failed" if parser_failed else "native"
        confident_chars = max(min_chars, int(pdf_config.get("native_text_confident_chars", 600)))
        confidence = 0.0 if parser_failed else (
            0.65 + 0.3 * min(1.0, char_count / confident_chars) if char_count else 0.65
        )
        needs_review = (
            classification in {"ocr_candidate", "image_or_chart", "parser_error", "manual_review"}
            or bool(inherited_warnings)
            or any(table.needs_review for table in table_records)
        )
        if classification == "ocr_candidate":
            warnings.append("OCR candidate; native text is too short and page image coverage passed configured threshold")
        elif classification == "image_or_chart":
            warnings.append("Sparse text with image or vector drawing content; manually inspect visual region")
        elif classification == "manual_review":
            warnings.append("Sparse native text could not be classified as blank or image-heavy")
        if table_records and any(table.needs_review for table in table_records):
            warnings.append("one or more detected tables need manual structural review")

        return PageRecord(
            document_id=document_id,
            file_checksum=checksum,
            page_number=page_number,
            text=native_text,
            native_text=native_text,
            ocr_text="",
            extraction_method=extraction_method,
            extraction_confidence=confidence,
            tables=table_records,
            images=image_records,
            parser_name=self.name,
            parser_version=self.version,
            warnings=list(dict.fromkeys(warnings)),
            needs_review=needs_review,
            classification=classification,
            page_width=float(page_rect.width),
            page_height=float(page_rect.height),
            image_count=len(image_records),
            image_coverage=coverage,
            drawing_count=drawing_count,
        )


def _single_rect_ratio(bbox: Any, page_rect: Any, page_area: float) -> float | None:
    if not bbox or page_area <= 0:
        return None
    x0, y0, x1, y1 = map(float, bbox)
    area = max(0.0, min(x1, float(page_rect.x1)) - max(x0, float(page_rect.x0))) * max(
        0.0, min(y1, float(page_rect.y1)) - max(y0, float(page_rect.y0))
    )
    return max(0.0, min(1.0, area / page_area))


def _rect_union_area(rects: list[tuple[float, float, float, float]]) -> float:
    """Calculate rectangle union area so overlapping image placements aren't double counted."""
    if not rects:
        return 0.0
    xs = sorted({x for rect in rects for x in (rect[0], rect[2])})
    area = 0.0
    for left, right in zip(xs, xs[1:]):
        if right <= left:
            continue
        intervals = sorted((y0, y1) for x0, y0, x1, y1 in rects if x0 < right and x1 > left)
        covered = 0.0
        if intervals:
            start, end = intervals[0]
            for next_start, next_end in intervals[1:]:
                if next_start <= end:
                    end = max(end, next_end)
                else:
                    covered += end - start
                    start, end = next_start, next_end
            covered += end - start
        area += (right - left) * covered
    return max(0.0, area)
