import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.evaluation.generation.runner_v2 import run_phase15_1


if __name__ == "__main__":
    run_phase15_1()
