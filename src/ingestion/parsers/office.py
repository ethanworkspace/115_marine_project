"""DOCX, ODT, and text parsers that explicitly retain missing physical page provenance."""

from __future__ import annotations

import re
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from docx import Document

from ..models import ImageRecord, PageRecord, ParsedDocument
from .base import Parser
from .tables import make_office_table_record


class DOCXParser(Parser):
    name = "python-docx"
    version = "1"
    extensions = (".docx",)

    def parse(self, path: Path, manifest: dict[str, Any]) -> ParsedDocument:
        doc_id, checksum, warnings = self.provenance(path, manifest)
        parser_version = getattr(__import__("docx"), "__version__", "unknown")
        try:
            document = Document(path)
            parts = [paragraph.text for paragraph in document.paragraphs if paragraph.text.strip()]
            records = []
            for table_index, table in enumerate(document.tables, 1):
                all_rows = [[cell.text for cell in row.cells] for row in table.rows]
                headers = all_rows[0] if all_rows else []
                rows = all_rows[1:] if len(all_rows) > 1 else []
                records.append(make_office_table_record(doc_id, None, table_index, headers, rows, self.name))
                parts.extend(" | ".join(row) for row in all_rows)
            images = _zip_media_records(path, "word/media/")
            text = "\n".join(parts)
            parse_warnings = [*warnings, "DOCX logical flow has no reliable physical page numbers"]
            page = PageRecord(
                document_id=doc_id, file_checksum=checksum, page_number=None, text=text,
                native_text=text, ocr_text="", extraction_method="native",
                extraction_confidence=0.85 if text.strip() else 0.65,
                tables=records, images=images, parser_name=self.name, parser_version=parser_version,
                warnings=parse_warnings, needs_review=True,
                classification="native_text" if text.strip() else "blank",
                image_count=len(images),
            )
            return ParsedDocument(doc_id, manifest.get("file_path", path.name), checksum, self.name, parser_version, [page], parse_warnings, True, source_extension=".docx")
        except Exception as exc:
            return failed_document(path, manifest, self.name, parser_version, f"docx_parse_failed:{type(exc).__name__}:{exc}", warnings)


class ODTParser(Parser):
    name = "odt-xml"
    version = "1"
    extensions = (".odt",)

    def parse(self, path: Path, manifest: dict[str, Any]) -> ParsedDocument:
        doc_id, checksum, warnings = self.provenance(path, manifest)
        ns = {
            "office": "urn:oasis:names:tc:opendocument:xmlns:office:1.0",
            "text": "urn:oasis:names:tc:opendocument:xmlns:text:1.0",
            "table": "urn:oasis:names:tc:opendocument:xmlns:table:1.0",
        }
        try:
            with zipfile.ZipFile(path) as archive:
                root = ElementTree.fromstring(archive.read("content.xml"))
                paragraphs = [
                    "".join(node.itertext()).strip()
                    for node in root.findall(".//office:body/office:text/*", ns)
                    if node.tag in {f"{{{ns['text']}}}p", f"{{{ns['text']}}}h"}
                ]
                tables = []
                for index, element in enumerate(root.findall(".//table:table", ns), 1):
                    matrix = []
                    for row in element.findall(".//table:table-row", ns):
                        values = []
                        for cell in row.findall("table:table-cell", ns):
                            values.append(" ".join(part.strip() for part in cell.itertext() if part.strip()))
                        if values:
                            matrix.append(values)
                    headers = matrix[0] if matrix else []
                    records = matrix[1:] if len(matrix) > 1 else []
                    tables.append(make_office_table_record(doc_id, None, index, headers, records, self.name))
                media_paths = [name for name in archive.namelist() if name.startswith("Pictures/")]
            content = "\n".join(item for item in paragraphs if item)
            for table in tables:
                content += "\n" + table.markdown if table.markdown else ""
            parse_warnings = [*warnings, "ODT logical flow has no reliable physical page numbers"]
            images = [ImageRecord(index, None, None, None, None, None, ["ODT image has no page geometry"])
                      for index, _ in enumerate(media_paths)]
            page = PageRecord(
                doc_id, checksum, None, content, content, "", "odt", 0.85 if content.strip() else 0.65,
                tables, images, self.name, self.version, parse_warnings, True,
                "native_text" if content.strip() else "blank", image_count=len(images),
            )
            return ParsedDocument(doc_id, manifest.get("file_path", path.name), checksum, self.name, self.version, [page], parse_warnings, True, source_extension=".odt")
        except Exception as exc:
            return failed_document(path, manifest, self.name, self.version, f"odt_parse_failed:{type(exc).__name__}:{exc}", warnings)


class PlainTextParser(Parser):
    name = "utf8-text"
    version = "1"
    extensions = (".txt", ".md")

    def parse(self, path: Path, manifest: dict[str, Any]) -> ParsedDocument:
        doc_id, checksum, warnings = self.provenance(path, manifest)
        try:
            text = path.read_text(encoding="utf-8", errors="strict")
        except Exception as exc:
            return failed_document(path, manifest, self.name, self.version, f"utf8_decode_failed:{type(exc).__name__}:{exc}", warnings)
        record_warnings = [*warnings, "plain text has no physical page coordinates"]
        page = PageRecord(doc_id, checksum, None, text, text, "", "native", 0.9 if text.strip() else 0.65,
                          [], [], self.name, self.version, record_warnings, True,
                          "native_text" if text.strip() else "blank")
        return ParsedDocument(doc_id, manifest.get("file_path", path.name), checksum, self.name, self.version, [page], record_warnings, True, source_extension=path.suffix.lower())


def failed_document(path: Path, manifest: dict[str, Any], parser_name: str, parser_version: str,
                    message: str, inherited_warnings: list[str] | None = None,
                    conversion_status: str = "not_required") -> ParsedDocument:
    doc_id, checksum, provenance_warnings = Parser.provenance(path, manifest)
    warnings = [*(inherited_warnings or []), *provenance_warnings, message]
    page = PageRecord(doc_id, checksum, None, "", "", "", "failed", 0.0, [], [], parser_name,
                      parser_version, warnings, True, "parser_error")
    return ParsedDocument(doc_id, manifest.get("file_path", path.name), checksum, parser_name,
                          parser_version, [page], warnings, True, conversion_status, path.suffix.lower())


def _zip_media_records(path: Path, prefix: str) -> list[ImageRecord]:
    try:
        with zipfile.ZipFile(path) as archive:
            paths = [name for name in archive.namelist() if name.startswith(prefix)]
    except Exception:
        return []
    return [ImageRecord(index, None, None, None, None, None, ["embedded image has no page geometry"])
            for index, _ in enumerate(paths)]
