from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.evaluation.silver import build_silver_dataset, build_silver_readiness


if __name__ == "__main__":
    result = build_silver_dataset()
    readiness = build_silver_readiness()
    print(json.dumps({"manifest": result["manifest"], "coverage": result["coverage"], "readiness": readiness}, ensure_ascii=False, indent=2))
