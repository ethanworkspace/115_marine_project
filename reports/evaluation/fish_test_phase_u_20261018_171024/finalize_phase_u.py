from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "reports/evaluation/fish_test_phase_u_20261018_171024"
PHASE_T = ROOT / "reports/evaluation/fish_test_phase_t_20261017_174751"


def load_json(path, default=None):
    return json.loads(path.read_text(encoding="utf-8-sig")) if path.exists() else default


def load_jsonl(path):
    if not path.exists():
        return []
    return [json.loads(x) for x in path.read_text(encoding="utf-8-sig").splitlines() if x.strip()]


def save_json(name, value):
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def save_jsonl(name, rows):
    with (OUT / name).open("w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def main():
    inventory = load_jsonl(OUT / "source_inventory_records.jsonl")
    decisions = load_jsonl(OUT / "source_admission_approval_matrix.jsonl")
    gov = load_jsonl(OUT / "government_data_source_records.jsonl")
    species = load_json(OUT / "species_source_coverage.json", {})
    baseline = load_json(OUT / "baseline_reconciliation.json", {})
    frozen = load_json(OUT / "frozen_baseline_recheck.json", {})
    workbook_validation = load_json(OUT / "workbook_validation.json", {})
    t_elig = load_jsonl(PHASE_T / "question_eligibility_v3.jsonl")
    t_ret = load_jsonl(PHASE_T / "retrieval_results_v3.jsonl")
    t_readiness = load_json(PHASE_T / "rag_evaluation_readiness.json", {})

    unique_hashes = len({x.get("checksum_sha256") for x in inventory if x.get("checksum_sha256")})
    duplicate_groups = defaultdict(list)
    for x in inventory:
        if x.get("checksum_sha256"):
            duplicate_groups[x["checksum_sha256"]].append(x["original_path"])
    duplicate_groups = {k: v for k, v in duplicate_groups.items() if len(v) > 1}
    status_counts = Counter(x.get("new_corpus_admission_decision") for x in decisions)
    formats = Counter((x.get("content_parse") or {}).get("file_format") for x in inventory)
    version_missing = sum(not x.get("version") for x in inventory)
    url_missing = sum(not x.get("url") for x in inventory)
    publisher_missing = sum(not x.get("publisher") for x in inventory)
    parse_errors = sum(bool((x.get("content_parse") or {}).get("parse_error")) for x in inventory)
    cats = Counter(x.get("category") for x in t_elig)
    fish = Counter(x.get("species") for x in t_elig)
    eligibility = Counter(bool(x.get("benchmark_eligible_v3")) for x in t_elig)
    retrieve = Counter(x.get("retrieval_status") for x in t_ret)

    s08 = {"source_key": "fish test/鱸魚_AI測試題庫_2026_1003.xlsx::S08", "source_id": "S08",
           "registered_resource": "漁業署養殖漁業放養量查詢服務", "url": "https://fadopen.fa.gov.tw/fadopen/service/qryBreedPredictReport.htmx",
           "detached_wrong_document": "養殖漁業防寒須知(農業部漁業署)", "correction": "remove service-to-cold-advisory document link; keep service as separate identity",
           "admission_status": "not_admitted", "content_version_status": "not captured"}
    s10 = {"source_key": "fish test/鱸魚_AI測試題庫_2026_1003.xlsx::S10", "source_id": "S10",
           "registered_resource": "中央氣象署 Open Data API Swagger documentation", "url": "https://opendata.cwa.gov.tw/dist/opendata-swagger.html",
           "detached_wrong_document": "訂定總說明與逐條說明（110.4.27）", "correction": "remove API page-to-legal explanation document link; keep source identities separate",
           "admission_status": "not_admitted", "content_version_status": "no Phase U page snapshot"}
    crosswalk = load_json(OUT / "source_crosswalk_overlay.json", {})
    crosswalk["phase_u_applied_corrections"] = [s08, s10]
    (OUT / "source_crosswalk_overlay.json").write_text(json.dumps(crosswalk, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    save_json("source_registry_corrected.json", {
        "registry_version": "phase_u_source_registry_overlay_v1",
        "input_registry": "Phase T source_registry_corrected.json (history preserved)",
        "immutable_history": True,
        "applied_crosswalk_overlays": [s08, s10],
        "source_records": inventory,
        "admission_policy": "No new source approved in Phase U. Existing DGBAS 2020 admission remains narrow and not ingested.",
    })

    admission_decisions = []
    for rec in decisions:
        admission_decisions.append({"source_record_id": rec.get("source_record_id"), "source_id": rec.get("source_id"),
                                    "title": rec.get("title"), "decision": rec.get("new_corpus_admission_decision"),
                                    "owner_decision": rec.get("owner_decision"), "remaining_blockers": rec.get("risk_and_blockers"),
                                    "candidate_species_signals": rec.get("expected_species_and_categories", {}).get("species_candidates", []),
                                    "candidate_category_signals": rec.get("expected_species_and_categories", {}).get("category_candidates", [])})
    save_jsonl("source_admission_decisions.jsonl", admission_decisions)

    data_integrity = {
        "inventory_scope": ["my_data", "data/recovery/raw_sources", "Step3I verified open-data raw directory", "Step3E saved disease PDF directory"],
        "saved_source_files": len(inventory), "sha256_unique_files": unique_hashes, "duplicate_hash_groups": len(duplicate_groups),
        "format_counts": dict(formats), "parse_errors": parse_errors, "source_versions_missing": version_missing,
        "source_urls_missing": url_missing, "publishers_missing": publisher_missing,
        "source_content_inspection": "read-only PDF text extraction, XML parsing with DTD/entity declarations rejected, CSV header/row reading, HTML byte decode only",
        "scope_warning": "Species/category keyword pages are candidate locators only, not proof of scientific applicability or authorization.",
        "dgbas_2020_sha256": "31c4cdb6fc3cdcd58abc4a5ba8a1cde908f1ca12f9f338fb39da4d4bf494dd31",
        "dgbas_2020_authorization": "previously admitted, limited to 2020 descriptive Fact rows; corpus inclusion remains not_ingested",
        "excluded_or_not_reused": ["Phase T candidate index as formal Corpus v3", "all unapproved documents", "all benchmark questions/answers/rubrics/traces"],
        "frozen_manifest": {"entries": frozen.get("manifest_rows"), "matching": frozen.get("status_counts", {}).get("MATCH", 0),
                            "mismatch": frozen.get("status_counts", {}).get("MISMATCH", 0), "unreadable": frozen.get("status_counts", {}).get("UNREADABLE", 0),
                            "sqlite_matches_expected": frozen.get("protected_sqlite_matches")},
    }
    (OUT / "source_integrity_report.md").write_text(
        "# Phase U 來源完整性與範圍檢查\n\n"
        f"唯讀盤點 {len(inventory)} 個原始檔案，涵蓋 {unique_hashes} 個不同 SHA-256；有 {len(duplicate_groups)} 組重複 checksum。"
        f"解析錯誤 {parse_errors}。文件版本未確認 {version_missing} 份，來源 URL 未確認 {url_missing} 份，發布者未確認 {publisher_missing} 份。\n\n"
        "PDF 頁數、可抽取文字量與關鍵字頁面僅用於定位候選內容。它們沒有替代逐頁表格、數值、來源權利或物種適用性核驗。"
        "現有水試所手冊等原件可供研究閱讀的決策，不等同新 Corpus 的正式 Source Admission。\n\n"
        "DGBAS-79395 2020 XML checksum 與既有正式有限範圍 Admission 相符；其使用仍限 2020 單年度、原始統計分類和 Fact。"
        "DGBAS 2015 與其他開放資料集均未因這項核准而獲准納入。\n\n"
        f"Frozen Manifest 本輪逐筆重算：{frozen.get('status_counts', {}).get('MATCH', 0)}/{frozen.get('manifest_rows')} 相符；"
        f"SQLite SHA-256 相符：{frozen.get('protected_sqlite_matches')}。\n", encoding="utf-8")

    (OUT / "rag_corpus_v3_build_report.md").write_text(
        "# Corpus v3 建置結果\n\n"
        "狀態：NO-GO，未執行建置。\n\n"
        "Phase T 的候選索引為 1,502 個 chunk，來源限動物用藥品管理法與 DGBAS 2020 資料，並非本階段的正式 Corpus v3。"
        "其 180 題資格表為 0/180，歷史檢索有 20 題形成 reranked Top-5 候選、160 題沒有符合凍結範圍的候選；候選段落不等於充分答案證據。"
        "Phase U 未複製或重用該索引。\n\n"
        "目前已正式 Admission 的 DGBAS 2020 來源仍 `corpus_inclusion_status=not_ingested`。其他水產技術、疾病、水質、寒害及計算文件尚未完成逐來源核准。"
        "因此沒有建立 chunk、embedding、BM25、SQLite、RRF 或 E4-Final 索引。\n\n"
        "下一個建置門檻：研究負責人對來源逐件作明確 Admission 決策；確認版本、checksum、可處理範圍、署名條件、魚種及類別適用性；然後凍結 allowlist，才可建置一個新版 Corpus。\n", encoding="utf-8")

    rag_integration = {
        "phase_u_gate_status": "BLOCKED_BEFORE_NEW_CORPUS",
        "gate1_reranker": {"phase_t_status": "PASS", "model": "BAAI/bge-reranker-v2-m3", "revision": "953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e",
                            "phase_u_new_reorder_test": "NOT_RUN_NO_NEW_INDEX"},
        "gate2_source_coverage": {"status": "FAIL", "saved_files": len(inventory), "new_sources_admitted": 0,
                                  "specialist_sources_admitted_for_new_corpus": 0, "six_target_species_verified_admitted_technical_sources": 0,
                                  "reason": "Documents exist locally but new-corpus source admission and complete version/species/use metadata are pending."},
        "gate3_system_integration": {"status": "NOT_ACCEPTED_FOR_720", "candidate_index_reused": False,
                                     "new_retrievals": 0, "new_generations": 0,
                                     "prior_phase_t_unit_tests": "3/3 PASS", "prior_phase_t_mock_streamlit": "PASS (fail-closed mock)",
                                     "phase_u_canonical_test_suite": "601 passed, 6 skipped, 8 subtests passed; see pytest_validation.json",
                                     "phase_u_new_corpus_e2e": "NOT_RUN because corpus admission/build blocked"},
        "gate4_question_eligibility": {"status": "FAIL", "questions": len(t_elig), "eligible": sum(bool(x.get("benchmark_eligible_v3")) for x in t_elig),
                                       "answer_verified": sum(bool(x.get("answer_verified")) for x in t_elig), "reason": "Phase T qualification baseline remains 0 and no new corpus evidence was admitted."},
        "formal_model_scoring": False, "winner": None,
    }
    save_json("rag_integration_validation.json", rag_integration)

    coverage = {"question_count": len(t_elig), "eligible_count": sum(bool(x.get("benchmark_eligible_v3")) for x in t_elig),
                "historical_rag_ready": 25, "phase_t_candidate_corpus_eligible": 0,
                "question_counts_by_species": dict(fish), "question_counts_by_category": dict(cats),
                "category_targets": {"Fact": 35, "Water Quality": 35, "Disease": 35, "Climate/Cold": 20, "Medication/Law": 20, "Calculation": 35},
                "all_species_specific_eligible_counts": {sp: 0 for sp in ["虱目魚", "吳郭魚", "石斑魚", "鱸魚", "烏魚", "鰻魚"]},
                "note": "Phase T records are preserved as historical qualification decisions; Phase U's zero eligibility is not a retroactive rewrite. Corpus v3 was not built.",
                "gate_version": "benchmark_gate_v2", "corpus_version": None}
    save_json("question_coverage_v3.json", coverage)

    pytest_status = {
        "command": "C:\\Users\\ethan\\anaconda3\\python.exe -m pytest tests -q -p no:cacheprovider --basetemp=<PhaseU>\\pytest_basetemp_with_venv",
        "suite_scope": "canonical repository tests/ tree only (290 test_*.py files discovered; pytest test cases collected internally)",
        "environment_note": "PYTHONPATH temporarily included project .venv Lib/site-packages because the selected pytest interpreter lacked python-docx and PyMuPDF; no packages installed and no system settings changed.",
        "initial_collection_attempt": "7 collection errors from missing python-docx/PyMuPDF in the chosen interpreter; rerun using already-installed project .venv packages passed.",
        "result": "PASS", "passed": 601, "skipped": 6, "subtests_passed": 8, "failed": 0, "collection_errors": 0,
        "phase_u_guardrail_tests": {"result": "PASS", "passed": 5, "failed": 0, "artifact": "test_phase_u_guardrails.py"},
        "full_repo_root_collection": "not claimed; Phase T root collection attempted and failed on inaccessible existing temp dirs (80 collection errors / WinError 5). This phase used the actual tests/ tree rather than recursively collecting reports and staging.",
        "isolated_basetemp": "reports/evaluation/fish_test_phase_u_20261018_171024/pytest_basetemp_with_venv",
        "security_settings_changed": False}
    save_json("pytest_validation.json", pytest_status)

    # Corpus-level invariants relevant to future build approval.
    entry_tests = [
        ("allowlist_exact_paths_only", "No recursive ingestion; precise file path, source ID, checksum and version required."),
        ("dgbas_2020_scope_only", "DGBAS 2020 single-year descriptive Fact only; no 2015 or biological species inference."),
        ("new_sources_require_owner_admission", "Every non-DGBAS source remains pending or blocked; no implicit approval."),
        ("benchmark_assets_excluded", "Fish Test, answers, rubrics, holdout, model outputs, traces and reports are excluded from ingestion."),
        ("source_span_round_trip", "Future chunks must return exact source/page/record locators and checksum-bound text."),
        ("species_scope_fail_closed", "Unknown or conflicting applicability must not pass as species-specific evidence."),
        ("retrieval_eligibility_separate", "Context-only/excluded material cannot appear as retrieval-eligible evidence."),
        ("model_context_parity", "A future run must freeze identical Top-5 context per question across all four models."),
        ("no_corpus_v2_mixing", "Corpus versions may not be mixed within one model comparison."),
        ("index_manifest_hashes", "Future chunk, embedding, BM25 and database artifacts need deterministic hashes and row counts."),
        ("admission_not_corpus_build", "Source admission does not itself authorize Corpus v3 or E4-Final construction."),
        ("no_generation_before_gates", "No Generator call until source, corpus, system and eligibility gates pass."),
    ]
    save_json("corpus_v3_build_entry_tests.json", {"status": "DESIGN_CHECKS_DEFINED_NOT_BUILD_EXECUTED", "tests": [{"test_id": k, "requirement": v, "phase_u_result": "NOT_EXECUTED_CORPUS_NOT_BUILT"} for k, v in entry_tests]})

    # Exact availability statuses and formal result counts.
    metrics = {"run_status": "NOT_RUN_BLOCKED_BEFORE_GENERATION", "corpus_version": None, "model_generation_count": 0,
               "metrics": {name: {"value": None, "n": 0, "status": "NOT_EVALUATED", "reason": "No Phase U retrieval/generation and no frozen eligible reference set."}
                           for name in ["faithfulness", "judge_answer_relevance", "bge_m3_cosine_similarity", "structured_ifr", "ttft", "tps", "system_ram", "dedicated_vram", "context_precision_at_5", "logical_accuracy", "arithmetic_accuracy"]},
               "formal_weighted_score": None, "winner": None}
    save_json("evaluation_metrics_v3_final.json", metrics)

    # Final compatibility is computed only over this phase's known state.
    compatibility = {"phase": "U", "status": "STOPPED_AT_SOURCE_ADMISSION_AND_CORPUS_GATE", "historical_data_mutated": False,
                     "phase_t_baseline_read": True, "source_crosswalk_overlay_scoped_to_phase_u": True,
                     "new_formal_source_admissions": 0, "dgbas_2020_limited_admission_preserved": True,
                     "new_corpus_built": False, "new_e4_final_built": False, "new_retrieval_rows_are_not_run_markers": True,
                     "new_generator_calls": 0, "formal_model_scoring": False, "winner": None,
                     "workbook_validation": workbook_validation.get("status", "NOT_CREATED"),
                     "workbooks_reopened": bool(workbook_validation.get("workbooks")) and all(x.get("reopened") for x in workbook_validation.get("workbooks", [])),
                     "frozen_manifest": {"expected": 636, "matched": frozen.get("status_counts", {}).get("MATCH", 0),
                                         "mismatch": frozen.get("status_counts", {}).get("MISMATCH", 0), "all_match": frozen.get("all_636_match"),
                                         "sqlite_sha256": frozen.get("protected_sqlite_sha256"), "sqlite_matches_expected": frozen.get("protected_sqlite_matches")},
                     "note": "Full new-system E2E is not claimed because corpus creation was not authorized/feasible before new-source admission decisions."}
    save_json("compatibility.json", compatibility)

    top_blockers = [
        "No formal Source Admission for the locally saved aquaculture manuals, disease resources, climate files, and other open-data assets.",
        "For 47/57 source files the version field is absent; for 46/57 source files the URL is absent; for 46/57 publisher is absent in combined structured manifests.",
        "The Phase T candidate corpus contains only statute text and DGBAS statistics, not sufficient six-species husbandry evidence.",
        "No newly built Corpus v3 means no Phase U final Top-5, no frozen answer evidence/rubrics, and no defensible 720-generation run.",
        "Full-root pytest collection remains blocked by historical restricted temp directories; canonical tests/ suite passes when invoked explicitly with isolated basetemp and dependencies already present in .venv.",
    ]
    report = f"""# Phase U 最終報告

## 本輪實際完成

- 以唯讀方式盤點 `my_data`、原始來源區及既有政府資料 raw 目錄，共 {len(inventory)} 個來源檔案，{unique_hashes} 個不同 checksum，{len(duplicate_groups)} 組相同 checksum。
- 文件格式：{dict(formats)}；內容解析錯誤 {parse_errors}。
- 結構化來源登錄中，{version_missing} 個檔案缺版本、{url_missing} 個缺 URL、{publisher_missing} 個缺發布者。逐字命中魚種／類別只用於候選頁面定位，沒有視為物種適用性或證據核驗。
- Phase T 的 180 題、1,502 個候選 chunks、20 個 reranked Top-5 與 160 個無候選紀錄均保留為歷史資料；Phase U 沒有重用作新 Corpus 或新檢索結果。
- 建立 Phase U 專用 S08/S10 crosswalk overlay，將放養量服務與防寒須知分開，將氣象 API 文件與法規說明分開；不修改歷史 registry 或 Production。
- DGBAS 2020 的有限 Admission 保持原範圍，Corpus inclusion 仍為 `not_ingested`；本輪沒有新增 Source Admission。

## Gate 結果

- **Gate 1 Reranker：** Phase T 已驗證 BAAI/bge-reranker-v2-m3 權重與實際載入。本輪沒有新 Corpus，故沒有重新執行 180 題重排序。
- **Gate 2 來源：** 未通過。當地存在水產養殖、疾病、水質及寒害資料，但大部分缺正式來源版本／發布者／URL與新的 Source Admission。DGBAS 只支持單年度統計 Fact，不能充當魚種養殖技術來源。
- **Gate 3 系統：** 部分可驗證。Phase T 的 3/3 隔離單元測試及 mock fail-closed Streamlit smoke test 為歷史通過；本輪 `tests/` 標準測試集 {pytest_status['passed']} passed、{pytest_status['skipped']} skipped、{pytest_status['subtests_passed']} subtests passed。新 Corpus 的端到端檢索／生成／Streamlit 流程未執行，因此不宣稱新版整合驗收通過。
- **Gate 4 題目資格：** Phase T 指定 Corpus v3 的資格基線為 {sum(bool(x.get('benchmark_eligible_v3')) for x in t_elig)}/{len(t_elig)}。本輪沒有新的指定 Corpus，未重寫歷史資格，也沒有新題通過。
- 新版 Corpus v3：未建立（0 chunks、0 embeddings）。新檢索：0/180；本輪 720 次生成：0；11 項指標均 N=0 / NOT_EVALUATED；沒有總分或 Winner。

## 來源核准矩陣摘要

57 個來源檔案目前分為：{dict(status_counts)}。已存在的 DGBAS 2020 admission 只是既有窄範圍核准，不代表 Corpus v3 ingestion 核准；其他來源均未由 Codex 核准。請在工作簿逐件檢視來源、checksum、檔案格式、候選物種／類別定位、版本、權利、風險及 owner decision 欄位。

政府資料目前不應自動整批准入：DGBAS 2015 不在已核准的 2020 範圍；FA-STOCKING 參考年度缺失；MOA species code 有 metadata 日期衝突且分類層級須保留；MOA production 的養殖口徑仍待確認；WRA 水量資料沒有魚種欄位且不能支持水質優劣。具體資源與授權資訊見 source inventory／approval matrix。

## 阻塞與下一步

""" + "\n".join(f"- {x}" for x in top_blockers) + "\n\n"
    report += "在研究負責人逐來源決定新 Source Admission 範圍，並核實所選來源版本、使用依據、來源定位及物種適用性後，才能建置單一 Corpus v3。其後須重新凍結 180 題答案／rubric與模型設定，再執行新檢索、端到端驗收及 720 次生成。\n"
    (OUT / "phase_u_final_report.md").write_text(report, encoding="utf-8")
    readiness = {
        "phase_u": "NO_GO_BEFORE_CORPUS_BUILD",
        "dgbas_2020_admission_preserved": True,
        "new_source_admissions": 0,
        "formal_corpus_v3_built": False,
        "species_specific_technical_source_coverage_in_new_corpus": {sp: 0 for sp in ["虱目魚", "吳郭魚", "石斑魚", "鱸魚", "烏魚", "鰻魚"]},
        "question_eligibility": {"eligible": 0, "total": len(t_elig)},
        "ready_for_720_generations": False,
        "blockers": top_blockers,
        "owner_decision_required": ["逐件核准新來源的處理範圍與可納入內容", "Source Admission 決策", "Corpus v3 建置批准", "E4-Final 建置批准"],
    }
    save_json("rag_source_admission_readiness.json", readiness)

    # Validate every JSON/JSONL deliverable presently written.
    json_files = list(OUT.glob("*.json"))
    jsonl_files = list(OUT.glob("*.jsonl"))
    parse_report = {"json_files": {}, "jsonl_files": {}, "errors": []}
    for p in json_files:
        try:
            json.loads(p.read_text(encoding="utf-8-sig"))
            parse_report["json_files"][p.name] = "valid"
        except Exception as e:
            parse_report["errors"].append({"file": p.name, "error": str(e)})
    for p in jsonl_files:
        count = 0
        try:
            for line_no, line in enumerate(p.read_text(encoding="utf-8-sig").splitlines(), 1):
                if line.strip():
                    json.loads(line)
                    count += 1
            parse_report["jsonl_files"][p.name] = {"status": "valid", "records": count}
        except Exception as e:
            parse_report["errors"].append({"file": p.name, "line": line_no, "error": str(e)})
    parse_report["status"] = "PASS" if not parse_report["errors"] else "FAIL"
    save_json("phase_u_artifact_validation.json", parse_report)
    print(json.dumps({"inventory": len(inventory), "unique_hashes": unique_hashes,
                      "decision_counts": dict(status_counts), "eligibility": dict(eligibility),
                      "retrieval_historical": dict(retrieve), "json_valid": parse_report["status"],
                      "json_files": len(json_files), "jsonl_files": len(jsonl_files)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
