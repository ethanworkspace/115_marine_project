from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.evaluation.silver_benchmark import run_e1_bm25_silver
from src.evaluation.silver import build_silver_readiness


if __name__ == "__main__":
    readiness = build_silver_readiness()
    if not readiness.get("silver_benchmark_ready"):
        raise SystemExit("Silver benchmark readiness is false; E1 was not run.")
    result = run_e1_bm25_silver()
    print(json.dumps({"manifest": result["manifest"], "overall": result["overall"], "coverage": result["coverage"], "validation": result["validation"], "errors": len(result["errors"])}, ensure_ascii=False, indent=2))
