from __future__ import annotations
import datetime as dt
import json
from pathlib import Path

WORK = Path(__file__).resolve().parent


def load_json(name):
    return json.loads((WORK / name).read_text(encoding="utf-8"))


def load_jsonl(name):
    rows = []
    for i, line in enumerate((WORK / name).read_text(encoding="utf-8-sig").splitlines(), 1):
        if line.strip():
            rows.append(json.loads(line))
    return rows


def main():
    required_files = [
        "approved_official_sources_v3.json", "official_raw_data_integrity_report.json", "source_admission_v3.json",
        "corpus_v3_manifest.json", "corpus_v3_quality_report.md", "corpus_v3_source_coverage.json",
        "retrieval_results_v3_180.jsonl", "retrieved_context_relevance_labels.jsonl", "evidence_support_verification_180.jsonl",
        "question_eligibility_180.jsonl", "verified_reference_answers_180.jsonl", "evaluation_rubrics_v3.json",
        "six_species_evidence_coverage.json", "rag_v3_real_e2e_validation.json", "streamlit_v3_validation.json",
        "repository_pytest_results.json", "evaluation_readiness_v3.json", "evaluation_readiness_v3.xlsx",
        "phase_corpus_v3_integration_final_report.md", "compatibility.json", "previous_reference_candidates_revalidation_15.jsonl",
        "corpus_v3_integrity_validation.json", "protected_manifest_recheck_post.json", "workbook_reopen_validation.json",
    ]
    missing = [n for n in required_files if not (WORK / n).exists() or (WORK / n).stat().st_size == 0]
    rows = {
        "retrieval_results_v3_180.jsonl": load_jsonl("retrieval_results_v3_180.jsonl"),
        "retrieved_context_relevance_labels.jsonl": load_jsonl("retrieved_context_relevance_labels.jsonl"),
        "evidence_support_verification_180.jsonl": load_jsonl("evidence_support_verification_180.jsonl"),
        "question_eligibility_180.jsonl": load_jsonl("question_eligibility_180.jsonl"),
        "verified_reference_answers_180.jsonl": load_jsonl("verified_reference_answers_180.jsonl"),
        "previous_reference_candidates_revalidation_15.jsonl": load_jsonl("previous_reference_candidates_revalidation_15.jsonl"),
        "generator_smoke_results.jsonl": load_jsonl("generator_smoke_results.jsonl"),
    }
    json_files = [
        "approved_official_sources_v3.json", "official_raw_data_integrity_report.json", "source_admission_v3.json",
        "corpus_v3_manifest.json", "corpus_v3_source_coverage.json", "evaluation_rubrics_v3.json",
        "six_species_evidence_coverage.json", "rag_v3_real_e2e_validation.json", "streamlit_v3_validation.json",
        "repository_pytest_results.json", "evaluation_readiness_v3.json", "compatibility.json",
        "corpus_v3_integrity_validation.json", "protected_manifest_recheck_post.json", "workbook_reopen_validation.json",
    ]
    json_parse = {}
    for n in json_files:
        try:
            json.loads((WORK / n).read_text(encoding="utf-8"))
            json_parse[n] = "PASS"
        except Exception as exc:
            json_parse[n] = f"FAIL: {exc}"

    integrity = load_json("corpus_v3_integrity_validation.json")
    workbook = load_json("workbook_reopen_validation.json")
    xlsx_sheets = workbook.get("sheet_inspection", {}).get("recordCount")
    content = workbook.get("content_checks", {})
    row_checks = {
        "question_sheet_181_rows": content.get("Question_Eligibility", {}).get("usedRangeRows") == 181,
        "retrieval_sheet_181_rows": content.get("Retrieval_Coverage", {}).get("usedRangeRows") == 181,
        "evidence_sheet_793_rows": content.get("Evidence_Diagnostics", {}).get("usedRangeRows") == 793,
        "xlsx_reopened": workbook.get("reopened") is True,
        "xlsx_sheet_count_11": xlsx_sheets == 11,
    }
    row_counts = {n: len(v) for n, v in rows.items()}
    row_checks.update({
        "180_retrieval_rows": row_counts["retrieval_results_v3_180.jsonl"] == 180,
        "792_context_label_rows": row_counts["retrieved_context_relevance_labels.jsonl"] == 792,
        "792_support_rows": row_counts["evidence_support_verification_180.jsonl"] == 792,
        "180_eligibility_rows": row_counts["question_eligibility_180.jsonl"] == 180,
        "180_reference_rows": row_counts["verified_reference_answers_180.jsonl"] == 180,
        "15_prior_candidate_rows": row_counts["previous_reference_candidates_revalidation_15.jsonl"] == 15,
        "8_smoke_rows": row_counts["generator_smoke_results.jsonl"] == 8,
        "20_consistency_checks_pass": integrity.get("all_automated_checks_pass") is True and len(integrity.get("automated_checks", [])) == 20,
        "636_manifest_unchanged": integrity.get("protected_baseline", {}).get("unchanged") == 636,
        "production_sqlite_hash_match": integrity.get("protected_baseline", {}).get("production_sqlite", {}).get("matches") is True,
    })
    result = {
        "validated_at_local": dt.datetime.now().astimezone().isoformat(),
        "required_files_missing_or_empty": missing,
        "json_files_parse_status": json_parse,
        "jsonl_row_counts": row_counts,
        "xlsx_sheet_count": xlsx_sheets,
        "xlsx_content_row_checks": row_checks,
        "all_checks_pass": not missing and all(v == "PASS" for v in json_parse.values()) and all(row_checks.values()),
        "note": "XLSX reopened and sampled through the artifact-tool spreadsheet engine; no openpyxl installation was available.",
    }
    (WORK / "final_deliverable_validation.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    compat = load_json("compatibility.json")
    compat["workbook_reopened_and_validated"] = result["all_checks_pass"]
    compat["xlsx_sheet_count"] = xlsx_sheets
    compat["required_deliverables_validated"] = result["all_checks_pass"]
    (WORK / "compatibility.json").write_text(json.dumps(compat, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report_path = WORK / "phase_corpus_v3_integration_final_report.md"
    with report_path.open("a", encoding="utf-8") as f:
        f.write("\n\n## 交付檔案驗證\n\n")
        f.write(f"JSON 格式、JSONL 筆數與工作簿重新開啟核對：{'通過' if result['all_checks_pass'] else '未完全通過'}。工作簿含 {xlsx_sheets} 張工作表，涵蓋 180 題、180 筆檢索、792 筆段落診斷及逐筆核對清單。\n")
    print(json.dumps({"all_checks_pass": result["all_checks_pass"], "missing": missing, "row_counts": row_counts, "xlsx_sheet_count": xlsx_sheets, "failed_rows": [k for k,v in row_checks.items() if not v]}, ensure_ascii=True))


if __name__ == "__main__":
    main()
