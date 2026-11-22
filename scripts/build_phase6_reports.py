"""Refresh Parser v2 reports and Phase 6 governance reports without indexing."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.ingestion.parsers.pipeline import build_parser_reports
from src.ingestion.phase6 import build_phase6_reports


def main() -> None:
    parser_report = build_parser_reports(
        ROOT / "reports" / "document_manifest.jsonl",
        ROOT / "config" / "parsing.yaml",
        ROOT / "reports" / "parsing",
        ROOT / "my_data",
        ROOT,
    )
    phase6 = build_phase6_reports(ROOT)
    print(json.dumps({
        "parser": {
            "documents": parser_report["total_documents"],
            "pdf_pages": parser_report["total_pages"],
            "ocr_candidates": parser_report["ocr_candidate_pages"],
            "legacy_doc_total": parser_report["legacy_doc_total"],
            "table_candidates": parser_report["table_count"],
            "indexing_performed": False,
        },
        "eligibility": {key: value for key, value in phase6["eligibility"].items() if key not in {"notes", "generated_at_utc"}},
        "table_classification_counts": phase6["table_summary"]["classification_counts"],
        "ocr_status_counts": phase6["ocr_quality"]["status_counts"],
        "source_priority_counts": phase6["source_priority_counts"],
        "gold_sample_candidates": phase6["gold_sample_candidates"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
