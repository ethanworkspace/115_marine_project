"""Build experimental parser v2 inventory and quality reports without indexing."""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

try:
    import pymupdf as fitz
except ImportError:  # pragma: no cover
    import fitz  # type: ignore[no-redef]

from ..quality import read_manifest
from ..models import PageRecord, ParsedDocument
from .ocr import apply_ocr_image, discover_ocr_backends, selected_ocr_backend
from .router import ParserRouter, load_parser_config


def build_parser_reports(
    manifest_path: str | Path,
    config_path: str | Path,
    output_dir: str | Path,
    data_dir: str | Path,
    repo_root: str | Path,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    manifest_path, output_dir, data_dir, repo_root = map(Path, (manifest_path, output_dir, data_dir, repo_root))
    records = read_manifest(manifest_path)
    config = load_parser_config(config_path)
    router = ParserRouter(config)
    backend_status = discover_ocr_backends(config)
    backend = selected_ocr_backend(config)
    legacy_backend_status = router.route("probe.doc").backend_status()
    parsed_documents: list[ParsedDocument] = []

    for index, manifest in enumerate(records, 1):
        relative = Path(str(manifest["file_path"]).replace("/", "\\"))
        source = (repo_root / relative).resolve()
        if not source.is_relative_to(repo_root.resolve()):
            raise ValueError(f"manifest path escapes repository root: {manifest['file_path']}")
        if not source.exists():
            raise FileNotFoundError(f"manifest file is missing: {manifest['file_path']}")
        parsed = router.parse(source, manifest)
        parsed.document_metadata = {
            field: manifest.get(field)
            for field in (
                "title", "source_id", "organization", "source_url", "source_tier",
                "publication_date", "download_date", "effective_date", "expiry_date",
                "version", "legal_status", "species", "topics", "document_type", "language",
            )
        }
        parsed_documents.append(parsed)
        if progress:
            progress(f"parsed {index}/{len(records)}: {manifest['file_path']}")

    ocr_config = config.get("ocr", {})
    dpi = int(ocr_config.get("render_dpi", 250))
    if dpi < 72 or dpi > 600:
        raise ValueError("OCR render_dpi must be between 72 and 600")
    for parsed in parsed_documents:
        if parsed.source_extension.lower() != ".pdf":
            continue
        candidates = [page for page in parsed.pages if page.classification == "ocr_candidate"]
        if not candidates:
            continue
        source = (repo_root / Path(parsed.file_path.replace("/", "\\"))).resolve()
        try:
            with fitz.open(source) as pdf:
                for page_record in candidates:
                    if page_record.page_number is None:
                        page_record.ocr_quality_status = "failed"
                        page_record.needs_review = True
                        page_record.warnings.append("OCR was not started because source page number is missing")
                        continue
                    if backend is None:
                        apply_ocr_image(page_record, b"", None, config)
                        continue
                    try:
                        pixmap = pdf[page_record.page_number - 1].get_pixmap(dpi=dpi, alpha=False)
                        quality = apply_ocr_image(page_record, pixmap.tobytes("png"), backend, config)
                        if quality is not None:
                            page_record.warnings.append(f"ocr_quality:{quality.status}")
                    except Exception as exc:
                        page_record.ocr_quality_status = "failed"
                        page_record.needs_review = True
                        page_record.warnings.append(f"ocr_render_failed:{type(exc).__name__}:{exc}")
        except Exception as exc:
            for page_record in candidates:
                page_record.ocr_quality_status = "failed"
                page_record.needs_review = True
                page_record.warnings.append(f"ocr_source_open_failed:{type(exc).__name__}:{exc}")

    output_dir.mkdir(parents=True, exist_ok=True)
    page_records = [page for document in parsed_documents for page in document.pages]
    document_by_id = {document.document_id: document for document in parsed_documents}
    manifest_by_id = {record["document_id"]: record for record in records}

    inventory: list[dict[str, Any]] = []
    ocr_candidates: list[dict[str, Any]] = []
    manual_review: list[dict[str, Any]] = []
    for document in parsed_documents:
        manifest = manifest_by_id[document.document_id]
        for page in document.pages:
            item = page.to_dict()
            item.update({
                "file_path": document.file_path,
                "title": manifest.get("title"),
                "source_id": manifest.get("source_id"),
                "source_url": manifest.get("source_url"),
                "document_metadata": document.document_metadata,
                "physical_page_number_available": page.page_number is not None,
                "source_extension": document.source_extension,
                "conversion_status": document.conversion_status,
                "conversion_backend": document.conversion_backend,
                "conversion_attempts": document.conversion_attempts,
                "conversion_output_path": document.conversion_output_path,
            })
            inventory.append(item)
            if page.classification == "ocr_candidate":
                ocr_candidates.append(item)
            if page.needs_review:
                manual_review.append({"review_type": "page", **item})
            for table in page.tables:
                if table.needs_review:
                    manual_review.append({
                        "review_type": "table",
                        "document_id": table.document_id,
                        "file_checksum": document.file_checksum,
                        "file_path": document.file_path,
                        "page_number": table.page_number,
                        "table": _table_dict(table),
                    })
        for warning in document.warnings:
            if document.needs_review and not document.pages:
                manual_review.append({"review_type": "document", "document_id": document.document_id,
                                      "file_checksum": document.file_checksum, "file_path": document.file_path,
                                      "warning": warning})

    _write_jsonl(output_dir / "page_inventory.jsonl", inventory)
    _write_jsonl(output_dir / "ocr_candidates.jsonl", ocr_candidates)
    _write_jsonl(output_dir / "manual_review.jsonl", manual_review)

    physical_pdf_pages = [
        page for document in parsed_documents if document.source_extension.lower() == ".pdf"
        for page in document.pages if page.page_number is not None
    ]
    no_native_pdf_pages = [page for page in physical_pdf_pages if not page.native_text.strip()]
    classification_counts = Counter(page.classification for page in physical_pdf_pages)
    ocr_status_counts = Counter(page.ocr_quality_status for page in physical_pdf_pages)
    all_tables = [table for page in page_records for table in page.tables]
    legacy_docs = [document for document in parsed_documents if document.source_extension.lower() == ".doc"]
    page_numbers = [page.page_number for page in page_records if page.page_number is not None]
    failed_page_records = [page for page in page_records if page.classification == "parser_error"]
    report = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "parser_config": config_path.as_posix(),
        "classification_thresholds": config.get("pdf", {}),
        "ocr_quality_thresholds": config.get("ocr", {}),
        "manifest_path": manifest_path.as_posix(),
        "data_directory": data_dir.as_posix(),
        "indexing_performed": False,
        "total_documents": len(parsed_documents),
        "total_pages": len(physical_pdf_pages),
        "page_inventory_record_count": len(page_records),
        "native_text_pages": sum(bool(page.native_text.strip()) for page in physical_pdf_pages),
        "no_native_text_pages": len(no_native_pdf_pages),
        "ocr_candidate_pages": classification_counts["ocr_candidate"],
        "ocr_success_pages": ocr_status_counts["pass"],
        "ocr_review_pages": ocr_status_counts["review"],
        "ocr_reject_pages": ocr_status_counts["reject"],
        "ocr_failed_pages": ocr_status_counts["failed"],
        "ocr_backend_unavailable_pages": ocr_status_counts["backend_unavailable"],
        "blank_pages": classification_counts["blank"],
        "image_or_chart_pages": classification_counts["image_or_chart"],
        "parser_error_pages": sum(page.page_number is not None for page in failed_page_records),
        "document_level_parser_errors": sum(page.page_number is None for page in failed_page_records),
        "manual_review_pages": sum(page.page_number is not None and page.needs_review for page in physical_pdf_pages),
        "classification_manual_review_pages": classification_counts["manual_review"],
        "unpaginated_records_needing_review": sum(page.page_number is None and page.needs_review for page in page_records),
        "legacy_doc_total": len(legacy_docs),
        "legacy_doc_conversion_success": sum(document.conversion_status == "success" for document in legacy_docs),
        "legacy_doc_conversion_failed": sum(document.conversion_status in {"failed", "unavailable"} for document in legacy_docs),
        "legacy_doc_conversion_unavailable": sum(document.conversion_status == "unavailable" for document in legacy_docs),
        "legacy_doc_conversion_backend": legacy_backend_status,
        "table_count": len(all_tables),
        "table_parse_success": sum(not table.needs_review for table in all_tables),
        "table_parse_review": sum(table.needs_review for table in all_tables),
        "pages_missing_number": sum(page.page_number is None for page in page_records),
        "parser_warning_count": sum(len(page.warnings) for page in page_records) + sum(len(document.warnings) for document in parsed_documents),
        "manual_review_record_count": len(manual_review),
        "ocr_backend": backend_status,
        "original_no_native_text_page_classifications": dict(sorted(Counter(page.classification for page in no_native_pdf_pages).items())),
        "original_no_native_text_pages": [
            {"document_id": page.document_id, "file_checksum": page.file_checksum,
             "file_path": document_by_id[page.document_id].file_path, "page_number": page.page_number,
             "classification": page.classification, "native_text_length": len(page.native_text),
             "image_count": page.image_count, "image_coverage": page.image_coverage,
             "page_width": page.page_width, "page_height": page.page_height,
             "drawing_count": page.drawing_count, "ocr_quality_status": page.ocr_quality_status,
             "needs_review": page.needs_review}
            for page in no_native_pdf_pages
        ],
        "source_extension_counts": dict(sorted(Counter(document.source_extension for document in parsed_documents).items())),
        "pdf_page_scan_errors": [
            {"file_path": document.file_path, "warning": warning}
            for document in parsed_documents if document.source_extension.lower() == ".pdf"
            for warning in document.warnings if "pdf_open_failed" in warning
        ],
        "notes": [
            "total_pages counts PDF physical pages; page_inventory_record_count also includes unpaginated Office/text documents and file-level error records.",
            "original_no_native_text_page_classifications classifies pages with empty native PDF text, matching the Phase 0–4 coverage concept.",
            "Page extraction confidence and table confidence are heuristic indicators, not calibrated probabilities.",
            "This parser pipeline is experimental and does not create or modify the production vector database.",
        ],
    }
    _write_json(output_dir / "parser_quality.json", report)
    return report


def _table_dict(table: Any) -> dict[str, Any]:
    return {
        "table_id": table.table_id,
        "document_id": table.document_id,
        "page_number": table.page_number,
        "caption": table.caption,
        "headers": table.headers,
        "rows": table.rows,
        "markdown": table.markdown,
        "parser_name": table.parser_name,
        "confidence": table.confidence,
        "warnings": table.warnings,
        "units": table.units,
        "footnotes": table.footnotes,
        "needs_review": table.needs_review,
        "row_count": table.row_count,
        "column_count": table.column_count,
    }


def _write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    payload = "".join(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n" for record in records)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(payload, encoding="utf-8", newline="\n")
    temporary.replace(path)


def _write_json(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    temporary.replace(path)
