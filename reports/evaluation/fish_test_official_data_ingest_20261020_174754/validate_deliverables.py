from __future__ import annotations

import json
from pathlib import Path

OUT = Path(__file__).resolve().parent
json_files, jsonl_files, errors = [], [], []
for path in OUT.rglob("*"):
    if not path.is_file() or "__pycache__" in path.parts:
        continue
    try:
        if path.suffix.lower() == ".json":
            json.loads(path.read_text(encoding="utf-8-sig"))
            json_files.append(str(path.relative_to(OUT)))
        elif path.suffix.lower() == ".jsonl":
            count = 0
            for i, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
                if line.strip():
                    json.loads(line)
                    count += 1
            jsonl_files.append({"path": str(path.relative_to(OUT)), "records": count})
    except Exception as exc:
        errors.append({"path": str(path.relative_to(OUT)), "error": f"{type(exc).__name__}: {exc}"})
manifest = json.loads((OUT / "official_download_manifest.json").read_text(encoding="utf-8"))
coverage = json.loads((OUT / "strict_index_v3" / "retrieval_coverage_180_v3.json").read_text(encoding="utf-8"))
baseline = json.loads((OUT / "protected_baseline_recheck_after_summary.json").read_text(encoding="utf-8"))
checks = {
    "all_json_and_jsonl_parse": not errors,
    "three_nonempty_verified_json_downloads": len(manifest["successful_downloads"]) == 3 and all(x["nonempty"] and x["json_parse"] == "PASS" and x["sha256_matches_recorded_expected"] for x in manifest["successful_downloads"]),
    "moj_zip_incomplete_and_excluded": manifest["failed_resource"]["actual_partial_bytes"] < manifest["failed_resource"]["declared_content_length_bytes"] and manifest["failed_resource"]["index_status"] == "EXCLUDED",
    "retrieval_is_180_questions": coverage["questions"] == 180,
    "frozen_baseline_636_636": baseline["manifest_rows"] == baseline["match"] == 636 and baseline["missing"] == baseline["mismatch"] == baseline["read_errors"] == 0 and baseline["formal_sqlite_match"],
}
result = {"json_files_valid": json_files, "jsonl_files_valid": jsonl_files, "parse_errors": errors, "checks": checks, "all_checks_pass": all(checks.values())}
(OUT / "deliverable_format_validation.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"valid_json": len(json_files), "valid_jsonl": len(jsonl_files), "errors": len(errors), "checks": checks, "all_checks_pass": result["all_checks_pass"]}, ensure_ascii=False))
