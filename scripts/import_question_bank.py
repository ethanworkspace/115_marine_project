"""Import fish test workbooks as candidate-only Gold annotation inputs."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.evaluation.question_bank_import import ROOT, save_import


if __name__ == "__main__":
    result = save_import(ROOT / "fish test", root=ROOT)
    print(f"Imported question candidates: {result['records']}")
    print(f"Mapping report: {ROOT / 'reports' / 'evaluation' / 'question_bank_mapping.json'}")
