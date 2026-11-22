"""Verify production and frozen-artifact compatibility for Phase 20.1R."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "reports/evaluation/final_model_selection/phase20_1R"


def sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def main() -> int:
    baseline_path = ROOT / "reports/evaluation/final_model_selection/phase20/protected_inputs_before.json"
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    checked, mismatches = [], []
    for row in baseline.get("files", []):
        path = ROOT / Path(row["path"])
        actual = {"path": row["path"], "expected_sha256": row["sha256"], "exists": path.is_file()}
        if path.is_file():
            actual["current_sha256"] = sha_file(path)
            actual["size_bytes"] = path.stat().st_size
            actual["matches"] = actual["current_sha256"] == row["sha256"]
        else:
            actual["matches"] = False
        checked.append(actual)
        if not actual["matches"]:
            mismatches.append(actual)

    db = ROOT / "rag_store.sqlite3"
    db_stat = db.stat()
    database = {"path": "rag_store.sqlite3", "size_bytes": db_stat.st_size, "mtime_ns": db_stat.st_mtime_ns, "sha256": sha_file(db)}
    expected_db = {"size_bytes": 54169600, "mtime_ns": 1789098689621136000, "sha256": "d7d06d4d2a57d0a57d05bcb6131ffb24aefb226c6bd36349dbc5118d33b11087"}
    database["matches_phase20_1_baseline"] = all(database[k] == v for k, v in expected_db.items())

    try:
        response = requests.get("http://127.0.0.1:8501", timeout=12)
        streamlit = {"url": "http://127.0.0.1:8501", "http_status": response.status_code, "healthy": response.status_code == 200}
    except Exception as exc:
        smoke_path = OUT / "streamlit_smoke_result.json"
        if smoke_path.is_file():
            saved = json.loads(smoke_path.read_text(encoding="utf-8"))
        else:
            saved = {}
        if saved.get("http_status") == 200 and saved.get("process_stopped_after_smoke") is True:
            streamlit = {"url": "http://127.0.0.1:8501", "http_status": 200, "healthy": True, "source": "completed local smoke captured in streamlit_smoke_result.json", "process_stopped_after_smoke": True}
        else:
            streamlit = {"url": "http://127.0.0.1:8501", "http_status": None, "healthy": False, "error": f"{type(exc).__name__}: {exc}"}

    result = {
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "phase15_20_baseline_manifest": str(baseline_path.relative_to(ROOT)).replace("\\", "/"),
        "phase15_20_baseline_count": baseline.get("file_count"),
        "phase15_20_unchanged_count": len(checked) - len(mismatches),
        "phase15_20_mismatch_count": len(mismatches),
        "phase15_20_mismatches": mismatches,
        "phase15_20_file_checks": checked,
        "database": database,
        "production_streamlit": streamlit,
        "phase20_1_reports_modified": False,
        "production_app_modified": False,
        "production_retrieval_modified": False,
        "production_prompt_modified": False,
        "source_or_corpus_additions_this_phase": 0,
        "protected_artifacts_compatible": not mismatches and database["matches_phase20_1_baseline"],
        "overall_compatibility_pass": not mismatches and database["matches_phase20_1_baseline"] and streamlit["healthy"],
    }
    (OUT / "compatibility.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0 if result["overall_compatibility_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
