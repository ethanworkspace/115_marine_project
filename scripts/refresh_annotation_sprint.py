"""Refresh annotation progress, sprint metrics, Gold lint, and readiness reports."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.evaluation.development import refresh_reports


if __name__ == "__main__":
    reports = refresh_reports(ROOT)
    sprint = reports["sprint"]
    readiness = sprint["phase_9a_readiness"]
    print(f"Sprint report: {ROOT / 'reports' / 'evaluation' / 'annotation_sprint.json'}")
    print(f"Complete reviewed Gold: {readiness['reviewed_gold_count']}")
    print(f"Phase 9A ready: {readiness['smoke_test_ready']}")
    print("Benchmark executed: false")
