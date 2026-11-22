from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.evaluation.generation.runner_v21 import run_phase15_2


if __name__ == "__main__":
    run_phase15_2()
