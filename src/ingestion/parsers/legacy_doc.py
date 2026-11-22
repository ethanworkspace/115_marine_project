"""Conservative legacy binary DOC conversion; never guesses text encodings."""

from __future__ import annotations

import tempfile
import hashlib
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from ..models import ParsedDocument
from .base import Parser
from .office import failed_document
from .pdf import PDFParser


class WordCOMUnavailableError(RuntimeError):
    pass


class LegacyDOCConverter:
    """Word COM conversion adapter. The rest of the parser pipeline has no COM dependency."""

    name = "word-com"

    def __init__(self):
        self._availability: tuple[bool, str] | None = None

    def available(self) -> tuple[bool, str]:
        if self._availability is not None:
            return self._availability
        try:
            import pythoncom
            import win32com.client
        except Exception as exc:
            self._availability = (False, f"pywin32 unavailable: {type(exc).__name__}: {exc}")
            return self._availability
        app = None
        initialized = False
        try:
            pythoncom.CoInitialize()
            initialized = True
            app = win32com.client.DispatchEx("Word.Application")
            app.Visible = False
            version = str(app.Version)
            self._availability = (True, f"Word COM available; version {version}")
        except Exception as exc:
            self._availability = (False, f"Word COM activation unavailable: {type(exc).__name__}: {exc}")
        finally:
            if app is not None:
                try:
                    app.Quit()
                except Exception:
                    pass
            if initialized:
                pythoncom.CoUninitialize()
        return self._availability

    def convert_to_pdf(self, source: Path, output_dir: Path) -> Path:
        available, reason = self.available()
        if not available:
            raise WordCOMUnavailableError(reason)
        try:
            import pythoncom
            import win32com.client
        except Exception as exc:
            raise RuntimeError(f"Word COM dependencies unavailable: {type(exc).__name__}: {exc}") from exc
        destination = output_dir / f"{source.stem}.pdf"
        app = None
        document = None
        initialized = False
        try:
            pythoncom.CoInitialize()
            initialized = True
            app = win32com.client.DispatchEx("Word.Application")
            app.Visible = False
            app.DisplayAlerts = 0
            document = app.Documents.Open(
                str(source.resolve()), ReadOnly=True, AddToRecentFiles=False,
                ConfirmConversions=False, NoEncodingDialog=True,
            )
            document.SaveAs2(str(destination), FileFormat=17)
            document.Close(False)
            document = None
            if not destination.is_file() or destination.stat().st_size == 0:
                raise RuntimeError("Word reported successful conversion but the PDF is missing or empty")
            return destination
        finally:
            if document is not None:
                try:
                    document.Close(False)
                except Exception:
                    pass
            if app is not None:
                try:
                    app.Quit()
                except Exception:
                    pass
            if initialized:
                pythoncom.CoUninitialize()


class LibreOfficeConverter:
    """LibreOffice headless DOC-to-PDF adapter used after Word COM."""

    name = "libreoffice-headless"

    def __init__(self, executable: str | None = None):
        self.executable = executable or shutil.which("soffice") or shutil.which("libreoffice")

    def available(self) -> tuple[bool, str]:
        if not self.executable:
            return False, "LibreOffice/soffice executable not found on PATH"
        try:
            result = subprocess.run(
                [self.executable, "--version"], capture_output=True, text=True,
                timeout=10, check=False,
            )
            if result.returncode:
                return False, f"LibreOffice version probe failed: {result.stderr.strip()[:300]}"
            return True, (result.stdout or result.stderr).strip()
        except Exception as exc:
            return False, f"LibreOffice probe failed: {type(exc).__name__}: {exc}"

    def convert_to_pdf(self, source: Path, output_dir: Path) -> Path:
        available, message = self.available()
        if not available:
            raise RuntimeError(message)
        result = subprocess.run(
            [self.executable, "--headless", "--convert-to", "pdf", "--outdir", str(output_dir), str(source.resolve())],
            capture_output=True, text=True, timeout=180, check=False,
        )
        destination = output_dir / f"{source.stem}.pdf"
        if result.returncode != 0 or not destination.is_file() or destination.stat().st_size == 0:
            detail = (result.stderr or result.stdout).strip()
            raise RuntimeError(f"LibreOffice conversion failed ({result.returncode}): {detail[:500]}")
        return destination
class LegacyDOCParser(Parser):
    name = "legacy-doc-converter+pymupdf"
    version = "1"
    extensions = (".doc",)

    def __init__(
        self,
        pdf_parser: PDFParser | None = None,
        converter: Any | None = None,
        fallbacks: Sequence[Any] | None = None,
        recovery_dir: str | Path | None = None,
    ):
        self.pdf_parser = pdf_parser or PDFParser()
        if converter is not None:
            self.converters = [converter, *(fallbacks or [])]
        elif fallbacks is not None:
            self.converters = [LegacyDOCConverter(), *fallbacks]
        else:
            self.converters = [LegacyDOCConverter(), LibreOfficeConverter()]
        self.converter = self.converters[0]
        self.recovery_dir = Path(recovery_dir) if recovery_dir is not None else None

    def backend_status(self) -> dict[str, Any]:
        backends = []
        for converter in self.converters:
            availability = getattr(converter, "available", None)
            if availability is None:
                backends.append({"backend": getattr(converter, "name", type(converter).__name__), "available": "unknown", "message": "custom converter does not expose a capability probe"})
                continue
            available, message = availability()
            backends.append({"backend": getattr(converter, "name", type(converter).__name__), "available": available, "message": message})
        selected = next((item for item in backends if item["available"] is True), None)
        return {"backend": selected["backend"] if selected else None, "available": bool(selected), "message": selected["message"] if selected else "; ".join(str(item["message"]) for item in backends), "backends": backends}

    def parse(self, path: Path, manifest: dict[str, Any]) -> ParsedDocument:
        doc_id, checksum, provenance_warnings = self.provenance(path, manifest)
        attempts: list[str] = []
        unavailable_count = 0
        with tempfile.TemporaryDirectory(prefix="marine-rag-doc-convert-") as directory:
            for converter in self.converters:
                name = getattr(converter, "name", type(converter).__name__)
                availability = getattr(converter, "available", None)
                if availability is not None:
                    available, message = availability()
                    if not available:
                        attempts.append(f"{name}: unavailable: {message}")
                        unavailable_count += 1
                        continue
                try:
                    converted = converter.convert_to_pdf(path, Path(directory))
                    durable_output: Path | None = None
                    if self.recovery_dir is not None:
                        self.recovery_dir.mkdir(parents=True, exist_ok=True)
                        durable_output = self.recovery_dir / f"{doc_id}_{checksum[:12]}.pdf"
                        temporary_output = durable_output.with_suffix(".pdf.tmp")
                        shutil.copyfile(converted, temporary_output)
                        temporary_output.replace(durable_output)
                        output_checksum = hashlib.sha256(durable_output.read_bytes()).hexdigest()
                        sidecar = durable_output.with_suffix(".provenance.json")
                        sidecar.write_text(json.dumps({
                            "document_id": doc_id,
                            "source_file_path": manifest.get("file_path", path.name),
                            "source_file_checksum": checksum,
                            "conversion_backend": name,
                            "conversion_backend_version": getattr(converter, "version", None),
                            "converted_file_path": durable_output.as_posix(),
                            "converted_file_checksum": output_checksum,
                            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
                            "parser_name": self.name,
                            "parser_version": self.version,
                        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                        converted = durable_output
                    converted_manifest = dict(manifest)
                    converted_manifest["checksum"] = None
                    parsed = self.pdf_parser.parse(converted, converted_manifest)
                    for page in parsed.pages:
                        page.file_checksum = checksum
                        if page.extraction_method != "failed":
                            page.extraction_method = "converted_doc"
                        page.parser_name = self.name
                        page.parser_version = f"{self.version}+pymupdf-{self.pdf_parser.version}"
                        page.warnings.extend([*provenance_warnings, f"page layout is from a temporary {name} conversion"])
                    return ParsedDocument(
                        document_id=doc_id,
                        file_path=manifest.get("file_path", path.name),
                        file_checksum=checksum,
                        parser_name=self.name,
                        parser_version=f"{self.version}+pymupdf-{self.pdf_parser.version}",
                        pages=parsed.pages,
                        warnings=[*provenance_warnings, f"legacy DOC was converted via {name}"],
                        needs_review=any(page.needs_review for page in parsed.pages),
                        conversion_status="success",
                        source_extension=".doc",
                        conversion_backend=name,
                        conversion_attempts=attempts + [f"{name}: success"],
                        conversion_output_path=durable_output.as_posix() if durable_output else None,
                    )
                except Exception as exc:
                    attempts.append(f"{name}: failed: {type(exc).__name__}: {exc}")
            status = "unavailable" if (
                unavailable_count == len(self.converters)
                or (attempts and all("unavailable" in item.casefold() for item in attempts))
            ) else "failed"
            reason = "legacy_doc_manual_conversion_required; " + "; ".join(attempts)
            failed = failed_document(path, manifest, self.name, self.version, reason, provenance_warnings, status)
            failed.warnings.append("No binary decoding, encoding guessing, or regex text extraction was attempted")
            failed.warnings.append("Manual conversion required because supported conversion backends did not complete")
            for page in failed.pages:
                page.warnings.append("No binary decoding, encoding guessing, or regex text extraction was attempted")
                page.warnings.append("Manual conversion required because supported conversion backends did not complete")
            failed.conversion_status = status
            failed.conversion_attempts = attempts
            return failed
