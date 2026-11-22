from __future__ import annotations

import hashlib
import json
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
RUN = HERE.parent
ROOT = HERE.parents[3]
sys.path.insert(0, str(HERE))
import phase_s_build as build


def sha(path: Path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


before = read_json(RUN / "outputs/phase_s_execution_snapshot.json")
protected_checks = []
for item in before.get("protected_file_snapshot", []):
    p = ROOT / item["path"]
    actual = sha(p) if p.is_file() else None
    protected_checks.append({"path": item["path"], "expected_sha256": item.get("sha256"), "actual_sha256": actual, "unchanged": actual == item.get("sha256")})

_, frozen = build.hash_frozen("final")
retrieval = build.read_jsonl(RUN / "retrieval_results_v2.jsonl")
eligibility = build.read_jsonl(RUN / "question_eligibility_v2.jsonl")
questions = build.read_jsonl(build.QUESTIONS_PATH)
manifest = read_json(RUN / "knowledge_base_build_manifest.json")
metrics = read_json(RUN / "metrics_v2.json")
integration = read_json(RUN / "rag_system_integration_test.json")
integration["final_frozen_recheck"] = frozen
integration["protected_preflight_file_checks"] = protected_checks
integration["all_protected_preflight_files_unchanged"] = all(r["unchanged"] for r in protected_checks)
integration["all_integrity_tests_pass"] = bool(frozen["complete"] and all(r["unchanged"] for r in protected_checks) and integration.get("generator_calls_zero") is True)
(RUN / "rag_system_integration_test.json").write_text(json.dumps(integration, ensure_ascii=False, indent=2), encoding="utf-8")

wb_path = RUN / "fish_test_integrated_rag_evaluation_v2.xlsx"
with zipfile.ZipFile(wb_path) as zf:
    book_xml = ET.fromstring(zf.read("xl/workbook.xml"))
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    sheet_names = [x.attrib["name"] for x in book_xml.findall("m:sheets/m:sheet", ns)]
    def sheet_rows(name):
        index = sheet_names.index(name) + 1
        root = ET.fromstring(zf.read(f"xl/worksheets/sheet{index}.xml"))
        return len(root.findall("m:sheetData/m:row", ns))
    required_sheets = {"Research_Dashboard", "Model_Comparison", "Question_Eligibility", "Retrieval_Results", "Context_Precision", "Faithfulness", "Answer_Relevance", "BGE_M3_Similarity", "Structured_IFR", "TTFT_TPS", "RAM_VRAM", "Logical_Accuracy", "Arithmetic_Accuracy", "Citation_Support", "Species_Comparison", "Category_Comparison", "Missing_Evidence", "Validation", "Limitations", "Provenance"}
    workbook_check = {"sheet_count": len(sheet_names), "missing_required_sheets": sorted(required_sheets - set(sheet_names)),
                      "question_rows": sheet_rows("Question_Eligibility") - 1, "context_precision_rows": sheet_rows("Context_Precision") - 1,
                      "model_comparison_data_rows": sheet_rows("Model_Comparison") - 1, "retrieval_stage_rows": sheet_rows("Retrieval_Results") - 1,
                      "xlsx_package_xml_valid": True, "openpyxl_reopen_validation": "previously passed in workbook generation step"}
workbook_check["valid"] = not workbook_check["missing_required_sheets"] and workbook_check["question_rows"] == 180 and workbook_check["context_precision_rows"] == 180

required_files = [
    "rag_data_integrity_report.md", "source_registry_corrected.json", "species_applicability_validation.json",
    "knowledge_base_rebuild_report.md", "rag_system_integration_test.json", "rag_evaluation_readiness.json",
    "retrieval_results_v2.jsonl", "generator_results_v2.jsonl", "metrics_v2.json",
    "fish_test_integrated_rag_evaluation_v2.xlsx", "research_results_v2.md", "phase_s_final_report.md", "compatibility.json",
]
missing = [name for name in required_files if not (RUN / name).is_file()]
parseable, invalid = [], []
for p in RUN.rglob("*"):
    if not p.is_file() or p.suffix.lower() not in (".json", ".jsonl"):
        continue
    try:
        if p.suffix.lower() == ".json":
            json.loads(p.read_text(encoding="utf-8-sig"))
        else:
            for ln, line in enumerate(p.read_text(encoding="utf-8-sig").splitlines(), 1):
                if line.strip(): json.loads(line)
        parseable.append(str(p.relative_to(RUN)))
    except Exception as e:
        invalid.append({"path": str(p.relative_to(RUN)), "error": str(e)})
format_report = {"json_and_jsonl_files_checked": len(parseable), "invalid_files": invalid, "all_valid": not invalid, "paths": parseable}
(RUN / "output_format_validation.json").write_text(json.dumps(format_report, ensure_ascii=False, indent=2), encoding="utf-8")

final = {
    "required_deliverables_present": not missing,
    "missing_required_deliverables": missing,
    "questions": len(questions), "retrieval_records": len(retrieval), "eligibility_records": len(eligibility),
    "final_top5_records": sum(r.get("final_top5") is not None for r in retrieval),
    "new_generations": 0, "expected_generations": 720,
    "new_metrics_all_n_zero": all(v.get("n") == 0 and v.get("value") is None for v in metrics["all_new_metric_values"].values()),
    "candidate_index_chunks": manifest["chunk_count"], "reranker_status": manifest["reranker"]["status"],
    "isolated_unit_tests": read_json(RUN / "isolated_unit_test_results.json").get("successful"),
    "streamlit_app_smoke": read_json(RUN / "streamlit_integration_status.json").get("streamlit_smoke_status"),
    "workbook": workbook_check, "json_jsonl_parseability": {"count": len(parseable), "all_valid": not invalid},
    "protected_files": {"preflight_file_count": len(protected_checks), "preflight_files_unchanged": all(r["unchanged"] for r in protected_checks),
                        "frozen_manifest_636": frozen["matching_count"] == 636, "sqlite_baseline": frozen["sqlite_matches"]},
    "evaluation_ready": False, "formal_winner": None,
}
final["phase_s_completion_status"] = "PARTIAL_SYSTEM_BUILD; evaluation blocked before final rerank/generation"
(RUN / "phase_s_final_audit.json").write_text(json.dumps(final, ensure_ascii=False, indent=2), encoding="utf-8")
compat = read_json(RUN / "compatibility.json")
compat.update({"frozen_baseline_final": frozen, "protected_preflight_files_final": protected_checks,
               "all_protected_preflight_files_unchanged": all(r["unchanged"] for r in protected_checks),
               "new_index_candidate_only": True, "new_final_top5_count": 0, "new_generator_calls": 0,
               "new_metrics_n": 0, "formal_corpus_v3_created": False, "production_switched": False})
(RUN / "compatibility.json").write_text(json.dumps(compat, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(final, ensure_ascii=False, indent=2))
