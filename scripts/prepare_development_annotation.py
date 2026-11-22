from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.evaluation.development import build_worklist


if __name__ == "__main__":
    result = build_worklist(ROOT)
    print({"eligible_candidates": result["eligible_candidates"], "work_items": result["work_items"],
           "by_category": result["progress"]["by_category"], "lint_errors": result["lint"]["error_count"]})
