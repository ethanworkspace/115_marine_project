"""Run Phase 12 E1 BM25 and E2 BGE-M3 Grounded Silver baselines."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.evaluation.grounded_baselines import run_phase12, write_json  # noqa: E402


if __name__ == "__main__":
    result = run_phase12(ROOT)
    write_json(ROOT / "reports/evaluation/experiments/E1_vs_E2_grounded_v1/phase12_execution.json", result)
    summary = {
        "status": result.get("status"),
        "report_directory": result.get("report_directory"),
        "question_count": (result.get("freeze") or {}).get("question_count"),
        "corpus_profile": result.get("corpus_profile"),
        "compatibility": result.get("compatibility"),
    }
    if result.get("status") == "completed":
        summary["paired_required_evidence_hits"] = result.get("paired_hits")
        summary["runtime"] = (result.get("E2") or {}).get("index_manifest", {}).get("model")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
