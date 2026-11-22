"""Build evaluation-only Silver v2 source and evidence mappings.

This script reads the frozen corpus and Silver v1 and writes only new v2 and
mapping report artifacts. It never runs a retriever.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.evaluation.silver import sha256_file  # noqa: E402
from src.evaluation.source_mapping import expand_silver_mapping, write_mapping_artifacts  # noqa: E402


def main() -> int:
    frozen = (
        ROOT / "data/evaluation/corpus_v1.jsonl",
        ROOT / "data/shadow/chunks_v2.jsonl",
        ROOT / "data/evaluation/silver/questions_v1.jsonl",
        ROOT / "rag_store.sqlite3",
    )
    before = {path: sha256_file(path) for path in frozen}
    result = expand_silver_mapping(ROOT)
    write_mapping_artifacts(result, ROOT)
    after = {path: sha256_file(path) for path in frozen}
    if before != after:
        raise RuntimeError("A frozen input changed while building Silver v2 mapping")
    report = {
        "inputs_unchanged": True,
        "frozen_sha256": {path.relative_to(ROOT).as_posix(): value for path, value in before.items()},
        "summary": result["summary"],
    }
    output = ROOT / "reports/evaluation/silver_v2_mapping_run.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
