"""Parser dispatch and CLI for the parallel experimental parser v2 pipeline."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .base import Parser, UnsupportedFormatError
from .legacy_doc import LegacyDOCParser
from .office import DOCXParser, ODTParser, PlainTextParser
from .pdf import PDFParser


ROOT = Path(__file__).resolve().parents[3]


def load_parser_config(path: str | Path = ROOT / "config" / "parsing.yaml") -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("parsing.yaml must be a readable JSON-compatible YAML 1.2 file") from exc
    if not isinstance(value, dict):
        raise ValueError("parsing config must be an object")
    return value


class ParserRouter:
    def __init__(self, config: dict[str, Any] | None = None, parsers: list[Parser] | None = None):
        self.config = config or {}
        pdf = PDFParser(self.config)
        defaults: list[Parser] = [
            pdf,
            LegacyDOCParser(pdf, recovery_dir=ROOT / "reports" / "recovery" / "converted"),
            DOCXParser(), ODTParser(), PlainTextParser(),
        ]
        self.parsers = parsers if parsers is not None else defaults
        self._by_extension: dict[str, Parser] = {}
        for parser in self.parsers:
            for extension in parser.extensions:
                normalized = extension.lower()
                if normalized in self._by_extension:
                    raise ValueError(f"multiple parsers registered for {normalized}")
                self._by_extension[normalized] = parser

    def route(self, path: str | Path) -> Parser:
        extension = Path(path).suffix.lower()
        if extension not in self._by_extension:
            raise UnsupportedFormatError(f"unsupported document format {extension or '[no extension]'}: {path}")
        return self._by_extension[extension]

    def parse(self, path: str | Path, manifest: dict[str, Any]):
        return self.route(path).parse(Path(path), manifest)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build experimental parser/OCR/page provenance reports.")
    parser.add_argument("--manifest", type=Path, default=ROOT / "reports" / "document_manifest.jsonl")
    parser.add_argument("--config", type=Path, default=ROOT / "config" / "parsing.yaml")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "reports" / "parsing")
    parser.add_argument("--data-dir", type=Path, default=ROOT / "my_data")
    args = parser.parse_args()
    from .pipeline import build_parser_reports

    report = build_parser_reports(
        args.manifest, args.config, args.output_dir, args.data_dir, ROOT,
        progress=lambda message: print(message, flush=True),
    )
    print(json.dumps({key: report[key] for key in ("total_documents", "total_pages", "no_native_text_pages", "ocr_candidate_pages", "legacy_doc_conversion_failed", "table_count")}, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
