"""Typed records shared by the experimental, provenance-aware parser pipeline."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal
import re


ExtractionMethod = Literal["native", "ocr", "converted_doc", "odt", "manual", "failed"]
PageClassification = Literal[
    "native_text", "ocr_candidate", "blank", "image_or_chart", "parser_error", "manual_review"
]
OCRQualityStatus = Literal[
    "not_run", "pass", "review", "reject", "backend_unavailable", "failed"
]
IngestionStatus = Literal["accepted", "accepted_with_warning", "review", "rejected"]
TableClassification = Literal[
    "simple_table", "merged_cell_table", "multi_page_table", "image_table",
    "complex_layout", "false_positive", "unknown",
]


def _check_confidence(value: float | None, field_name: str) -> None:
    if value is not None and (isinstance(value, bool) or not 0.0 <= value <= 1.0):
        raise ValueError(f"{field_name} must be between 0.0 and 1.0 or None")


@dataclass(slots=True)
class ImageRecord:
    image_index: int
    xref: int | None
    width: int | None
    height: int | None
    bbox: tuple[float, float, float, float] | None
    coverage_ratio: float | None = None
    warnings: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.image_index < 0:
            raise ValueError("image_index must be non-negative")
        _check_confidence(self.coverage_ratio, "coverage_ratio")


@dataclass(slots=True)
class TableRecord:
    table_id: str
    document_id: str
    page_number: int | None
    caption: str | None
    headers: list[str]
    rows: list[list[str]]
    markdown: str
    parser_name: str
    confidence: float | None
    warnings: list[str] = field(default_factory=list)
    units: list[str | None] = field(default_factory=list)
    footnotes: list[str] = field(default_factory=list)
    needs_review: bool = False
    row_count: int = 0
    column_count: int = 0
    ingestion_status: IngestionStatus = "review"
    review_reason: list[str] = field(default_factory=list)
    reviewed_by: str | None = None
    reviewed_at: str | None = None
    classification: TableClassification | None = None
    classification_reason: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.table_id or not self.document_id:
            raise ValueError("table_id and document_id are required")
        if self.page_number is not None and self.page_number < 1:
            raise ValueError("page_number must be positive or None")
        _check_confidence(self.confidence, "confidence")
        if self.units and len(self.units) != len(self.headers):
            raise ValueError("units must be empty or have one entry per header")
        self.row_count = len(self.rows)
        self.column_count = max(len(self.headers), max((len(row) for row in self.rows), default=0))
        _check_ingestion_status(self.ingestion_status)
        if self.classification is not None and self.classification not in {
            "simple_table", "merged_cell_table", "multi_page_table", "image_table",
            "complex_layout", "false_positive", "unknown",
        }:
            raise ValueError(f"unsupported table classification: {self.classification}")


@dataclass(slots=True)
class PageRecord:
    document_id: str
    file_checksum: str
    page_number: int | None
    text: str
    native_text: str
    ocr_text: str
    extraction_method: ExtractionMethod
    extraction_confidence: float | None
    tables: list[TableRecord]
    images: list[ImageRecord]
    parser_name: str
    parser_version: str
    warnings: list[str] = field(default_factory=list)
    needs_review: bool = False
    classification: PageClassification = "manual_review"
    page_width: float | None = None
    page_height: float | None = None
    image_count: int = 0
    image_coverage: float = 0.0
    drawing_count: int = 0
    ocr_confidence: float | None = None
    ocr_backend: str | None = None
    ocr_backend_version: str | None = None
    ocr_quality_status: OCRQualityStatus = "not_run"
    ocr_languages: list[str] = field(default_factory=list)
    selected_text: str = ""
    ingestion_status: IngestionStatus = "review"
    review_reason: list[str] = field(default_factory=list)
    reviewed_by: str | None = None
    reviewed_at: str | None = None

    def __post_init__(self) -> None:
        if not self.document_id:
            raise ValueError("document_id is required")
        if not re.fullmatch(r"[0-9a-fA-F]{64}", self.file_checksum):
            raise ValueError("file_checksum must be a 64-character SHA-256 hex digest")
        if self.page_number is not None and self.page_number < 1:
            raise ValueError("page_number must be positive or None")
        if self.extraction_method not in {"native", "ocr", "converted_doc", "odt", "manual", "failed"}:
            raise ValueError(f"unsupported extraction_method: {self.extraction_method}")
        if self.classification not in {
            "native_text", "ocr_candidate", "blank", "image_or_chart", "parser_error", "manual_review"
        }:
            raise ValueError(f"unsupported page classification: {self.classification}")
        if self.ocr_quality_status not in {
            "not_run", "pass", "review", "reject", "backend_unavailable", "failed"
        }:
            raise ValueError(f"unsupported OCR quality status: {self.ocr_quality_status}")
        _check_confidence(self.extraction_confidence, "extraction_confidence")
        _check_confidence(self.ocr_confidence, "ocr_confidence")
        _check_confidence(self.image_coverage, "image_coverage")
        _check_ingestion_status(self.ingestion_status)
        if not self.selected_text and self.text:
            self.selected_text = self.text
        if self.page_number is None and not self.needs_review:
            raise ValueError("records without a physical page number must be marked needs_review")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ParsedDocument:
    document_id: str
    file_path: str
    file_checksum: str
    parser_name: str
    parser_version: str
    pages: list[PageRecord]
    warnings: list[str] = field(default_factory=list)
    needs_review: bool = False
    conversion_status: Literal["not_required", "success", "failed", "unavailable"] = "not_required"
    source_extension: str = ""
    document_metadata: dict[str, Any] = field(default_factory=dict)
    ingestion_status: IngestionStatus = "review"
    review_reason: list[str] = field(default_factory=list)
    reviewed_by: str | None = None
    reviewed_at: str | None = None
    conversion_backend: str | None = None
    conversion_attempts: list[str] = field(default_factory=list)
    conversion_output_path: str | None = None

    def __post_init__(self) -> None:
        if not self.document_id or not self.file_path:
            raise ValueError("document_id and file_path are required")
        if not re.fullmatch(r"[0-9a-fA-F]{64}", self.file_checksum):
            raise ValueError("file_checksum must be a 64-character SHA-256 hex digest")
        for page in self.pages:
            if page.document_id != self.document_id or page.file_checksum != self.file_checksum:
                raise ValueError("every page must match its document ID and source file checksum")
        _check_ingestion_status(self.ingestion_status)


def merge_accepted_ocr(page: PageRecord, ocr_text: str) -> None:
    """Keep source fields separate and expose accepted OCR via the primary text field."""
    page.ocr_text = ocr_text
    selected = f"{page.native_text.rstrip()}\n{ocr_text.strip()}".strip() if page.native_text.strip() else ocr_text
    page.selected_text = selected
    page.text = selected


def _check_ingestion_status(value: str) -> None:
    if value not in {"accepted", "accepted_with_warning", "review", "rejected"}:
        raise ValueError(f"unsupported ingestion_status: {value}")
