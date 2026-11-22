"""Optional OCR adapters and a conservative OCR text quality gate."""

from __future__ import annotations

import importlib.util
import re
import shutil
import subprocess
import tempfile
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

try:
    import pymupdf as fitz
except ImportError:  # pragma: no cover
    import fitz  # type: ignore[no-redef]

from ..models import PageRecord, merge_accepted_ocr


QualityStatus = Literal["pass", "review", "reject"]


@dataclass(slots=True)
class OCRResult:
    text: str
    confidence: float | None
    backend: str
    backend_version: str
    warnings: list[str]
    languages: list[str] | None = None


@dataclass(slots=True)
class OCRQualityReport:
    status: QualityStatus
    text_length: int
    replacement_character_ratio: float
    control_character_ratio: float
    repeated_character_ratio: float
    language_character_ratio: float
    confidence: float | None
    reasons: list[str]
    number_token_count: int = 0
    unit_token_count: int = 0
    domain_terms_found: list[str] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "text_length": self.text_length,
            "replacement_character_ratio": self.replacement_character_ratio,
            "control_character_ratio": self.control_character_ratio,
            "repeated_character_ratio": self.repeated_character_ratio,
            "language_character_ratio": self.language_character_ratio,
            "confidence": self.confidence,
            "reasons": self.reasons,
            "number_token_count": self.number_token_count,
            "unit_token_count": self.unit_token_count,
            "domain_term_matches": len(self.domain_terms_found or []),
            "domain_terms_found": self.domain_terms_found or [],
        }


class OCRBackend:
    name = "abstract"
    version = "unknown"

    def available(self) -> tuple[bool, str]:
        raise NotImplementedError

    def recognize(self, image_bytes: bytes) -> OCRResult:
        raise NotImplementedError


class TesseractCLIBackend(OCRBackend):
    name = "tesseract"

    def __init__(self, executable: str | None = None, language: str = "chi_tra+eng"):
        self.executable = executable or shutil.which("tesseract")
        self.language = language
        self.version = "unknown"
        if self.executable:
            try:
                result = subprocess.run(
                    [self.executable, "--version"], capture_output=True, text=True,
                    timeout=10, check=False,
                )
                self.version = (result.stdout or result.stderr).splitlines()[0].strip()
            except Exception:
                self.version = "installed; version query failed"

    def available(self) -> tuple[bool, str]:
        if not self.executable:
            return False, "Tesseract executable not found on PATH"
        try:
            result = subprocess.run(
                [self.executable, "--list-langs"], capture_output=True, text=True,
                timeout=10, check=False,
            )
            languages = set((result.stdout + result.stderr).split())
            required = set(self.language.split("+"))
            missing = sorted(required - languages)
            if missing:
                return False, f"Tesseract language data missing: {', '.join(missing)}"
            return True, "available"
        except Exception as exc:
            return False, f"Tesseract check failed: {type(exc).__name__}: {exc}"

    def recognize(self, image_bytes: bytes) -> OCRResult:
        if not self.executable:
            raise RuntimeError("Tesseract executable is unavailable")
        with tempfile.TemporaryDirectory(prefix="marine-rag-ocr-") as directory:
            image_path = Path(directory) / "page.png"
            image_path.write_bytes(image_bytes)
            result = subprocess.run(
                [self.executable, str(image_path), "stdout", "-l", self.language, "tsv"],
                capture_output=True,
                text=True,
                timeout=180,
                check=False,
            )
            if result.returncode != 0:
                detail = (result.stderr or result.stdout).strip()
                raise RuntimeError(f"Tesseract exited {result.returncode}: {detail[:500]}")
            text, confidences = _parse_tesseract_tsv(result.stdout)
            confidence = sum(confidences) / len(confidences) if confidences else None
            return OCRResult(text, confidence, self.name, self.version, [], self.language.split("+"))


def discover_ocr_backends(config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Inspect only installed capabilities; never installs or imports heavyweight OCR packages."""
    ocr_config = (config or {}).get("ocr", config or {})
    language = str(ocr_config.get("tesseract_language", "chi_tra+eng"))
    tesseract = TesseractCLIBackend(language=language)
    tesseract_ok, tesseract_message = tesseract.available()
    candidates: dict[str, dict[str, Any]] = {
        "tesseract": {
            "installed": bool(tesseract.executable),
            "available": tesseract_ok,
            "version": tesseract.version,
            "message": tesseract_message,
            "adapter_supported": True,
        }
    }
    for module_name, backend_name in (("easyocr", "easyocr"), ("paddleocr", "paddleocr"), ("ocrmypdf", "ocrmypdf")):
        try:
            installed = importlib.util.find_spec(module_name) is not None
        except (ImportError, ValueError):
            installed = False
        executable = shutil.which("ocrmypdf") if backend_name == "ocrmypdf" else None
        if executable:
            installed = True
        candidates[backend_name] = {
            "installed": installed,
            "available": installed and backend_name == "ocrmypdf" and bool(shutil.which("tesseract")),
            "version": None,
            "message": "detected but no direct page adapter is configured" if installed else "not installed",
            "adapter_supported": False,
        }
    preference = ocr_config.get("backend_preference", ["tesseract"])
    selected = next(
        (name for name in preference if name in candidates and candidates[name]["available"] and candidates[name]["adapter_supported"]),
        None,
    )
    advice = None
    if selected is None:
        advice = (
            "Install the Tesseract executable for Windows and its eng and chi_tra language packs, "
            "then rerun the experimental parser (preferred language order: chi_tra+eng). "
            "No OCR dependency was installed automatically."
        )
    return {"selected_backend": selected, "backends": candidates, "installation_advice": advice}


def selected_ocr_backend(config: dict[str, Any] | None = None) -> OCRBackend | None:
    status = discover_ocr_backends(config)
    if status["selected_backend"] == "tesseract":
        ocr_config = (config or {}).get("ocr", config or {})
        return TesseractCLIBackend(language=str(ocr_config.get("tesseract_language", "chi_tra+eng")))
    return None


def evaluate_ocr_quality(
    text: str,
    confidence: float | None,
    config: dict[str, Any] | None = None,
) -> OCRQualityReport:
    settings = (config or {}).get("ocr", config or {})
    stripped = text.strip()
    length = len(stripped)
    denominator = max(1, len(stripped))
    replacement_ratio = stripped.count("\ufffd") / denominator
    control_count = sum(
        1 for character in stripped
        if unicodedata.category(character) == "Cc" and character not in "\n\r\t"
    )
    control_ratio = control_count / denominator
    min_repeat_run = max(2, int(settings.get("repeated_character_min_run", 4)))
    run_count = sum(
        len(match.group(0))
        for match in re.finditer(rf"(.)\1{{{min_repeat_run - 1},}}", stripped)
    )
    repeated_ratio = run_count / denominator
    language_count = sum(
        1 for character in stripped
        if unicodedata.category(character)[0] in {"L", "N"}
    )
    language_ratio = language_count / denominator
    number_token_count = len(re.findall(r"(?<!\w)[+-]?(?:\d+(?:[.,]\d+)*|[.,]\d+)(?!\w)", stripped))
    unit_pattern = re.compile(r"(?<!\w)(?:mg\s*/\s*L|ppm|%|℃|°\s*C|deg\s*C|ppt|kg|g|mL|L)(?!\w)", re.I)
    unit_token_count = len(unit_pattern.findall(stripped))
    default_domain_terms = [
        "吳郭魚", "虱目魚", "石斑魚", "鱸魚", "烏魚", "鰻魚", "水質", "疾病", "病害",
        "白點病", "弧菌", "溶氧", "氨氮", "亞硝酸", "鹽度", "停藥期", "用藥", "法規",
        "養殖", "池塘", "水溫", "飼料", "TILAPIA", "MILKFISH", "GROUPER", "SEABASS",
        "MULLET", "EEL", "OXYGEN", "AMMONIA", "NITRITE", "SALINITY", "WITHDRAWAL",
    ]
    domain_terms = settings.get("domain_terms", default_domain_terms)
    found_domain_terms = sorted({str(term) for term in domain_terms if str(term).casefold() in stripped.casefold()})

    reasons: list[str] = []
    reject = False
    review = False
    if length < int(settings.get("min_text_chars_review", 5)):
        reject = True
        reasons.append("text_too_short_to_support_extraction")
    elif length < int(settings.get("min_text_chars_pass", 30)):
        review = True
        reasons.append("text_shorter_than_pass_threshold")

    replace_reject = float(settings.get("max_replacement_ratio_reject", 0.05))
    replace_pass = float(settings.get("max_replacement_ratio_pass", 0.005))
    if replacement_ratio > replace_reject:
        reject = True
        reasons.append("replacement_character_ratio_reject")
    elif replacement_ratio > replace_pass:
        review = True
        reasons.append("replacement_character_ratio_review")

    control_reject = float(settings.get("max_control_ratio_reject", 0.1))
    control_pass = float(settings.get("max_control_ratio_pass", 0.01))
    if control_ratio > control_reject:
        reject = True
        reasons.append("control_character_ratio_reject")
    elif control_ratio > control_pass:
        review = True
        reasons.append("control_character_ratio_review")

    repeated_reject = float(settings.get("max_repeated_ratio_reject", 0.4))
    repeated_pass = float(settings.get("max_repeated_ratio_pass", 0.15))
    if repeated_ratio > repeated_reject:
        reject = True
        reasons.append("repeated_character_ratio_reject")
    elif repeated_ratio > repeated_pass:
        review = True
        reasons.append("repeated_character_ratio_review")

    language_reject = float(settings.get("min_language_char_ratio_reject", 0.25))
    language_pass = float(settings.get("min_language_char_ratio_pass", 0.55))
    if length and language_ratio < language_reject:
        reject = True
        reasons.append("language_character_ratio_reject")
    elif language_ratio < language_pass:
        review = True
        reasons.append("language_character_ratio_review")

    confidence_pass = float(settings.get("min_confidence_pass", 0.55))
    confidence_review = float(settings.get("min_confidence_review", 0.35))
    if confidence is None:
        review = True
        reasons.append("backend_did_not_provide_confidence")
    elif confidence < confidence_review:
        reject = True
        reasons.append("ocr_confidence_reject")
    elif confidence < confidence_pass:
        review = True
        reasons.append("ocr_confidence_review")

    status: QualityStatus = "reject" if reject else ("review" if review else "pass")
    if not reasons:
        reasons.append("all_configured_quality_checks_passed")
    return OCRQualityReport(
        status, length, replacement_ratio, control_ratio, repeated_ratio, language_ratio,
        confidence, reasons, number_token_count, unit_token_count, found_domain_terms,
    )


def apply_ocr_image(page: PageRecord, image_bytes: bytes, backend: OCRBackend | None, config: dict[str, Any] | None = None) -> OCRQualityReport | None:
    if page.classification != "ocr_candidate":
        return None
    if backend is None:
        page.ocr_quality_status = "backend_unavailable"
        settings = (config or {}).get("ocr", config or {})
        preferences = settings.get("backend_preference", ["tesseract"])
        page.ocr_backend = str(preferences[0]) if preferences else "unavailable"
        page.ocr_backend_version = "unavailable"
        page.ocr_languages = str(settings.get("tesseract_language", "chi_tra+eng")).split("+")
        page.needs_review = True
        page.warnings.append("ocr_backend_unavailable; see parser_quality.json for installation advice")
        return None
    page.ocr_backend = getattr(backend, "name", type(backend).__name__)
    page.ocr_backend_version = getattr(backend, "version", "unknown")
    configured_languages = getattr(backend, "language", None)
    if configured_languages:
        page.ocr_languages = str(configured_languages).split("+")
    try:
        result = backend.recognize(image_bytes)
    except Exception as exc:
        page.ocr_quality_status = "failed"
        page.needs_review = True
        page.warnings.append(f"ocr_execution_failed:{type(exc).__name__}:{exc}")
        return OCRQualityReport("reject", 0, 0.0, 0.0, 0.0, 0.0, None, ["ocr_execution_failed"])
    quality = evaluate_ocr_quality(result.text, result.confidence, config)
    page.ocr_text = result.text
    page.ocr_confidence = result.confidence
    page.ocr_backend = result.backend
    page.ocr_backend_version = result.backend_version
    page.ocr_languages = list(result.languages or [])
    page.ocr_quality_status = quality.status
    if quality.status == "pass":
        merge_accepted_ocr(page, result.text)
        page.extraction_method = "ocr"
        page.extraction_confidence = result.confidence
        page.needs_review = any(table.needs_review for table in page.tables)
    elif quality.status == "review":
        page.selected_text = page.native_text
        page.extraction_method = "manual"
        page.needs_review = True
        page.warnings.append("OCR text withheld from primary text pending human review")
    else:
        page.selected_text = page.native_text
        page.extraction_method = "failed"
        page.needs_review = True
        page.warnings.append("OCR quality gate rejected text; primary text was not changed")
    page.warnings.extend(result.warnings)
    return quality


def _parse_tesseract_tsv(payload: str) -> tuple[str, list[float]]:
    lines = payload.splitlines()
    if not lines:
        return "", []
    header = lines[0].split("\t")
    try:
        text_index = header.index("text")
        confidence_index = header.index("conf")
    except ValueError:
        raise RuntimeError("Tesseract TSV response is missing text/conf columns")
    words: list[str] = []
    confidences: list[float] = []
    for line in lines[1:]:
        values = line.split("\t")
        if len(values) <= max(text_index, confidence_index):
            continue
        word = values[text_index].strip()
        if not word:
            continue
        words.append(word)
        try:
            value = float(values[confidence_index])
            if value >= 0:
                confidences.append(max(0.0, min(1.0, value / 100.0)))
        except ValueError:
            continue
    return " ".join(words), confidences
