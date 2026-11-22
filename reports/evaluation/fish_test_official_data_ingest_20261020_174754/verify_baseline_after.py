from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
BEFORE = OUT / "protected_baseline_recheck_636.jsonl"
rows = [json.loads(line) for line in BEFORE.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
after = []
for row in rows:
    path = ROOT / row["path"]
    try:
        h = hashlib.sha256()
        with path.open("rb") as f:
            for block in iter(lambda: f.read(1024 * 1024), b""):
                h.update(block)
        actual = h.hexdigest()
        status = "MATCH" if actual == row["expected_sha256"] else "MISMATCH"
    except OSError as exc:
        actual = None
        status = f"ERROR:{type(exc).__name__}:{exc}"
    after.append({"path": row["path"], "expected_sha256": row["expected_sha256"], "actual_sha256": actual, "status": status})
(OUT / "protected_baseline_recheck_after_636.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in after), encoding="utf-8")
summary = {"manifest_rows": len(rows), "match": sum(r["status"] == "MATCH" for r in after), "missing": sum(r["status"].startswith("ERROR:FileNotFoundError") for r in after), "mismatch": sum(r["status"] == "MISMATCH" for r in after), "read_errors": sum(r["status"].startswith("ERROR:") and not r["status"].startswith("ERROR:FileNotFoundError") for r in after), "formal_sqlite_sha256_expected": "d7d06d4d2a57d0a57d05bcb6131ffb24aefb226c6bd36349dbc5118d33b11087", "formal_sqlite_sha256_actual": next((r["actual_sha256"] for r in after if r["path"].endswith("rag_store.sqlite3")), None)}
summary["formal_sqlite_match"] = summary["formal_sqlite_sha256_actual"] == summary["formal_sqlite_sha256_expected"]
(OUT / "protected_baseline_recheck_after_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps(summary, ensure_ascii=False))
