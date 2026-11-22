import json
from pathlib import Path

root = Path(__file__).parent
audit_path = root / "source_rights_version_scope_audit_57_final.jsonl"
registry_path = root / "source_admission_registry_v3_final.jsonl"
audit_rows = [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines() if line.strip()]
registry_rows = [json.loads(line) for line in registry_path.read_text(encoding="utf-8").splitlines() if line.strip()]
registry_by_record = {row["source_record_id"]: row for row in registry_rows}
target_id = "SRC-9427ecc0ecf6"
audit_row = next(row for row in audit_rows if row.get("source_record_id") == target_id)
registry_row = registry_by_record[target_id]
before = audit_row.get("source_admission_status")
assert audit_row.get("admission_execution_status") == "admitted_scope_limited"
assert audit_row.get("rights_status") == "verified_statutory_text_only_under_copyright_act_art9"
assert registry_row.get("source_admission_status") == "admitted_scope_limited"
assert registry_row.get("source_sha256") == audit_row.get("source_sha256")
audit_row["source_admission_status"] = "admitted_scope_limited"
audit_row["registry_reconciliation_note"] = (
    "Corrected within this new Phase U audit output: this field previously contradicted its own "
    "admission_execution_status and the matching scope-limited registry record. The admission covers "
    "plain statutory text only; it excludes the stale 2019 annex and all product/species/dose claims."
)
audit_path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in audit_rows), encoding="utf-8")

record = {
    "reconciliation_id": "PHASE-U-ADMISSION-STATUS-RECONCILIATION-001",
    "scope": "new Phase U output only; no prior phase or frozen file changed",
    "source_record_id": target_id,
    "source_id": registry_row["source_id"],
    "field": "source_admission_status",
    "observed_inconsistency": {
        "rights_audit_value": before,
        "rights_audit_execution_status": audit_row["admission_execution_status"],
        "registry_value": registry_row["source_admission_status"],
    },
    "corrected_value": audit_row["source_admission_status"],
    "rights_scope": audit_row["rights_status"],
    "scope_limitation": "plain statutory text only; no annex, product, species-specific approval, dosage, or withdrawal-period claims",
    "basis": ["matching SHA-256 in both new Phase U records", "scope-limited admission record", "Taiwan Copyright Act Article 9 basis recorded for statutory text only"],
}
(root / "phase_u_registry_reconciliation.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(record, ensure_ascii=False, indent=2))
