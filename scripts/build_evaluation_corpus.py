from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.evaluation.corpus import build_from_root
from src.evaluation.pilot import build_pilot_outputs


def main() -> None:
    summary = build_from_root(ROOT)
    pilot = build_pilot_outputs(ROOT)
    print({"corpus": summary, "pilot": pilot})


if __name__ == "__main__":
    main()
