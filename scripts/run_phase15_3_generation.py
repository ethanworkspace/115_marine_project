from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.evaluation.generation.runner_v22 import run_phase15_3


if __name__ == "__main__":
    run_phase15_3()

