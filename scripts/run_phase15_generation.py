"""Run the frozen Phase 15 G0/G1 generation baseline."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.evaluation.generation.runner import run_phase15  # noqa: E402


if __name__ == "__main__":
    result = run_phase15(ROOT)
    print(json.dumps({
        "protected_unchanged": result["protected_unchanged"],
        "model": result["model"].get("model_name"),
        "G0_answered": result["G0"].get("answered_count"),
        "G1_answered": result["G1"].get("answered_count"),
    }, ensure_ascii=False, indent=2))
