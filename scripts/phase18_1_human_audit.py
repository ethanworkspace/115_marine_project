"""Prepare/report frozen human audit; intentionally no generator/judge/retriever calls."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.evaluation.human_support.workflow import prepare, report

if __name__ == '__main__':
    if '--report' not in sys.argv:
        prepare()
    result = report()
    print(json.dumps(result['status'], ensure_ascii=True), flush=True)
