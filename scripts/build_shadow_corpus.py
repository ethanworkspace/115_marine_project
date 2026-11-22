"""Build the isolated Chunking v2 shadow corpus from Phase 5/6 parser reports."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.ingestion.chunking.pipeline import build_shadow_corpus


if __name__ == "__main__":
    result = build_shadow_corpus()
    summary_keys = (
        "input_pages", "eligible_pages", "excluded_pages", "documents_with_eligible_pages",
        "total_chunks", "parent_chunks", "child_chunks", "table_chunks", "regulation_chunks",
        "manual_chunks", "disease_chunks", "fallback_chunks", "chunkable", "indexable",
        "exact_duplicates", "near_duplicate_candidates", "provenance_missing",
    )
    print(json.dumps({key: result.get(key) for key in summary_keys}, ensure_ascii=False, indent=2))
