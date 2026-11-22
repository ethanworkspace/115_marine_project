import json
from pathlib import Path

ROOT = Path(__file__).parent
errors = []
checked = []
for path in sorted(ROOT.rglob("*.json")):
    if "node_modules" in path.parts:
        continue
    try:
        json.loads(path.read_text(encoding="utf-8"))
        checked.append(str(path.relative_to(ROOT)))
    except Exception as exc:
        errors.append({"path": str(path.relative_to(ROOT)), "error": str(exc)})
for path in sorted(ROOT.rglob("*.jsonl")):
    if "node_modules" in path.parts:
        continue
    try:
        with path.open(encoding="utf-8") as stream:
            for line_no, line in enumerate(stream, 1):
                if line.strip():
                    json.loads(line)
        checked.append(str(path.relative_to(ROOT)))
    except Exception as exc:
        errors.append({"path": str(path.relative_to(ROOT)), "error": str(exc)})

def count_jsonl(name):
    with (ROOT / name).open(encoding="utf-8") as stream:
        return sum(1 for line in stream if line.strip())

def read_jsonl(name):
    with (ROOT / name).open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]

workbook = json.loads((ROOT / "workbook_validation.json").read_text(encoding="utf-8"))
manifest_path = ROOT / "frozen_manifest_recheck.json"
if not manifest_path.exists():
    manifest_path = ROOT / "frozen_baseline_recheck.json"
manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
owner_rows = read_jsonl("source_owner_decision_update_57.jsonl")
checksum_rows = read_jsonl("source_checksum_recheck_57.jsonl")
admission_rows = read_jsonl("source_admission_registry_v3_final.jsonl")
rights_rows = read_jsonl("source_rights_version_scope_audit_57_final.jsonl")
fresh_frozen_rows = read_jsonl("frozen_manifest_recheck_final_636.jsonl")
assert len(owner_rows) == 57 and all(row.get("owner_decision") == "APPROVED" for row in owner_rows)
assert len({row.get("checksum_sha256") for row in owner_rows}) == 55
assert len(checksum_rows) == 57 and all(row.get("status") == "MATCH" for row in checksum_rows)
assert len(admission_rows) == 7
assert len(fresh_frozen_rows) == 636 and all(row.get("status") == "MATCH" for row in fresh_frozen_rows)
assert workbook.get("all_reopened") is True and workbook.get("all_expected_sheets_present") is True
summary = {
    "checked_structured_files": len(checked),
    "parse_errors": errors,
    "question_eligibility_rows": count_jsonl("question_eligibility_v3.jsonl"),
    "retrieval_rows": count_jsonl("retrieval_results_v3_final.jsonl"),
    "generator_rows": count_jsonl("generator_results_v3_final.jsonl"),
    "source_admission_decision_rows": count_jsonl("source_admission_decision_records_57.jsonl"),
    "owner_decision_rows": count_jsonl("source_owner_decision_update_57.jsonl"),
    "owner_approved_rows": sum(row.get("owner_decision") == "APPROVED" for row in owner_rows),
    "unique_source_sha256_count": len({row.get("checksum_sha256") for row in owner_rows}),
    "source_checksum_matches": sum(row.get("status") == "MATCH" for row in checksum_rows),
    "formal_admission_registry_rows": len(admission_rows),
    "fresh_frozen_manifest_matches": sum(row.get("status") == "MATCH" for row in fresh_frozen_rows),
    "source_rights_status_counts": {
        status: sum(row.get("source_admission_status") == status for row in rights_rows)
        for status in sorted({row.get("source_admission_status") for row in rights_rows})
    },
    "workbook_validation": workbook,
    "frozen_manifest_recheck": manifest,
    "frozen_manifest_recheck_file": manifest_path.name,
    "source_crosswalk_resolution_present": (ROOT / "source_crosswalk_resolution_v3.json").exists(),
    "source_registry_reconciliation_present": (ROOT / "phase_u_registry_reconciliation.json").exists(),
}
(ROOT / "phase_u_final_deliverable_validation.json").write_text(
    json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
)
print(json.dumps({
    "checked_structured_files": summary["checked_structured_files"],
    "parse_errors": errors,
    "question_eligibility_rows": summary["question_eligibility_rows"],
    "retrieval_rows": summary["retrieval_rows"],
    "generator_rows": summary["generator_rows"],
    "source_decision_rows": summary["source_admission_decision_rows"],
    "owner_decision_rows": summary["owner_decision_rows"],
    "owner_approved_rows": summary["owner_approved_rows"],
    "unique_source_sha256_count": summary["unique_source_sha256_count"],
    "source_checksum_matches": summary["source_checksum_matches"],
    "formal_admission_registry_rows": summary["formal_admission_registry_rows"],
    "fresh_frozen_manifest_matches": summary["fresh_frozen_manifest_matches"],
    "source_rights_status_counts": summary["source_rights_status_counts"],
    "source_crosswalk_resolution_present": summary["source_crosswalk_resolution_present"],
    "source_registry_reconciliation_present": summary["source_registry_reconciliation_present"],
}, ensure_ascii=False, indent=2))
