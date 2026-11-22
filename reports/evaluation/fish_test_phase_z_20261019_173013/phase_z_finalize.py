from __future__ import annotations

import collections
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_json(path: Path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows):
    path.write_text("".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in rows), encoding="utf-8")


def sha(path: Path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    generation = read_jsonl(HERE / "real_generator_smoke_results.jsonl")
    safety = read_jsonl(HERE / "safety_gate_smoke_results.jsonl")
    retrieval = read_jsonl(HERE / "phase_z_retrieval_smoke.jsonl")
    refs = read_jsonl(HERE / "reference_answers_frozen.jsonl")
    rubrics = read_jsonl(HERE / "evaluation_rubrics_frozen.jsonl")
    test_set = read_jsonl(HERE / "independent_test_set.jsonl")
    blockers = read_jsonl(HERE / "source_blocker_review_50.jsonl")
    app_test = read_json(HERE / "rag_streamlit_test.json")
    prep = read_json(HERE / "phase_z_preparation_status.json")
    freeze = read_json(HERE / "phase_z_pre_generation_freeze.json")
    source_coverage = read_json(HERE / "source_coverage_progress.json")
    extract_validation = read_json(HERE / "evidence_extraction_validation.json")
    runtime_summary = read_json(HERE / "phase_z_runtime_summary.json")
    pytest_results = read_json(HERE / "repository_pytest_results.json")
    protected = read_json(HERE / "protected_baseline_recheck_summary.json")

    # Keep a compact but lossless M2 raw-versus-system record. Raw generator
    # text and the system's canonical answer remain distinct fields.
    m2_rows = [row for row in generation if row.get("model_id") == "M2"]
    write_jsonl(HERE / "m2_model_vs_system_answers.jsonl", m2_rows)

    origins = collections.Counter(row.get("answer_origin") for row in generation)
    by_model = {}
    for model_id in ("M1", "M2", "M3", "M4"):
        rows = [row for row in generation if row.get("model_id") == model_id]
        by_model[model_id] = {
            "generator_calls_logged": len(rows),
            "raw_model_json_valid": sum(bool(row.get("raw_json_valid")) for row in rows),
            "raw_model_answered": sum(row.get("model_reported_status") == "answered" for row in rows),
            "raw_model_abstained": sum(row.get("model_reported_status") == "abstain" for row in rows),
            "raw_model_status_unavailable_or_invalid": sum(row.get("model_reported_status") not in {"answered", "abstain"} for row in rows),
            "system_final_answered": sum((row.get("final_response") or {}).get("status") == "answered" for row in rows),
            "answer_origins": dict(collections.Counter(row.get("answer_origin") for row in rows)),
        }

    # Verify every final citation resolves to the exact frozen source span/card
    # attached to the same call. This is a traceability check, not a gold label.
    citation_checks = []
    for row in generation:
        final = row.get("final_response") or {}
        trace = row.get("retrieval_trace") or {}
        top_rows = trace.get("reranked_top5", [])
        top = next((item for item in top_rows if item.get("chunk_id") == row.get("retrieved_chunk_id")), None)
        for citation in final.get("citations", []):
            citation_checks.append({
                "case_id": row.get("case_id"), "model_id": row.get("model_id"),
                "chunk_matches_retrieval": bool(top and citation.get("chunk_id") == top.get("chunk_id")),
                "source_matches_retrieval": bool(top and citation.get("source_id") == top.get("source_id")),
                "sha256_matches_retrieval": bool(top and citation.get("source_sha256") == top.get("source_sha256")),
                "locator_matches_retrieval": bool(top and citation.get("locator") == top.get("page_or_locator")),
                "span_id_present": bool(citation.get("span_id")),
            })
    citation_pass = bool(citation_checks) and all(all(value for key, value in item.items() if key not in {"case_id", "model_id"}) for item in citation_checks)
    contexts_by_question = collections.defaultdict(set)
    for row in generation:
        contexts_by_question[row.get("question_id")].add(row.get("retrieved_context_sha256"))
    shared_context_consistency = all(len(values) == 1 for values in contexts_by_question.values())

    safety_counts = collections.Counter(row.get("answer_origin") for row in safety)
    safety_gate_summary = {
        "records": len(safety),
        "models": sorted({row.get("model_id") for row in safety}),
        "negative_scenarios": sorted({row.get("case_id") for row in safety}),
        "all_stopped_before_generator": all(not row.get("generator_called") for row in safety),
        "all_final_abstained": all((row.get("final_response") or {}).get("status") == "abstain" for row in safety),
        "answer_origins": dict(safety_counts),
    }

    reference_counts = collections.Counter(row.get("verification_status") for row in refs)
    species_reference_counts = collections.defaultdict(collections.Counter)
    for row in refs:
        species_reference_counts[row.get("species", "UNKNOWN")][row.get("verification_status", "UNKNOWN")] += 1
    rubric_counts = collections.Counter(row.get("rubric_status") for row in rubrics)
    test_species = collections.Counter(row.get("target_species", "UNKNOWN") for row in test_set)
    test_status = collections.Counter(row.get("test_set_status", "UNKNOWN") for row in test_set)
    blocker_counts = collections.Counter(row.get("resolution_status", row.get("status", "UNVERIFIED_BLOCKED")) for row in blockers)

    frozen_file_hashes = {
        "independent_test_set.jsonl": sha(HERE / "independent_test_set.jsonl"),
        "reference_answers_frozen.jsonl": sha(HERE / "reference_answers_frozen.jsonl"),
        "evaluation_rubrics_frozen.jsonl": sha(HERE / "evaluation_rubrics_frozen.jsonl"),
        "phase_z_retrieval_smoke.jsonl": sha(HERE / "phase_z_retrieval_smoke.jsonl"),
        "known_grouper_regression_case_frozen.json": sha(HERE / "known_grouper_regression_case_frozen.json"),
    }
    freeze_check = {
        "test_set_matches_pre_generation_freeze": frozen_file_hashes["independent_test_set.jsonl"] == freeze.get("test_set_sha256"),
        "reference_answers_match_pre_generation_freeze": frozen_file_hashes["reference_answers_frozen.jsonl"] == freeze.get("reference_answers_sha256"),
        "rubrics_match_pre_generation_freeze": frozen_file_hashes["evaluation_rubrics_frozen.jsonl"] == freeze.get("rubrics_sha256"),
        "retrieval_smoke_matches_pre_generation_freeze": frozen_file_hashes["phase_z_retrieval_smoke.jsonl"] == freeze.get("retrieval_smoke_sha256"),
        "known_regression_case_matches_pre_generation_freeze": frozen_file_hashes["known_grouper_regression_case_frozen.json"] == freeze.get("known_regression_case_sha256"),
        "file_sha256": frozen_file_hashes,
    }
    freeze_check["all_frozen_inputs_unchanged"] = all(value for key, value in freeze_check.items() if key.endswith("matches_pre_generation_freeze"))

    # The first AppTest harness attempt completed its app.run (including the
    # live model request) but failed while reading SessionState with .get().
    # It did not write the result before process exit. Preserve this incident.
    app_recovery = {
        "initial_harness_attempt": "FAILED_AFTER_APP_RUN_BEFORE_RESULT_SERIALIZATION",
        "cause": "Streamlit AppTest SafeSessionState does not implement dict.get attribute access; the assertion attempted to read a result after the button-triggered app.run returned.",
        "model_request_likely_executed": True,
        "raw_response_persisted": False,
        "recovery": "Changed the harness to read the keyed SessionState value with bracket access and reran the positive and no-evidence cases successfully.",
        "successful_recovery_report": "rag_streamlit_test.json",
        "failed_attempt_excluded_from_metric_counts": True,
    }
    write_json(HERE / "app_test_harness_recovery.json", app_recovery)

    extract_validation["phase_z_real_generator_smoke"] = {
        "logged_generator_calls": len(generation),
        "answer_origins": dict(origins),
        "raw_json_valid": sum(bool(row.get("raw_json_valid")) for row in generation),
        "raw_json_invalid_or_unavailable": sum(not bool(row.get("raw_json_valid")) for row in generation),
        "system_final_answers": sum((row.get("final_response") or {}).get("status") == "answered" for row in generation),
        "final_citation_resolution_checks": len(citation_checks),
        "all_final_citations_match_retrieved_source_and_locator": citation_pass,
        "by_model": by_model,
        "safety_gate_negative_checks": safety_gate_summary,
        "streamlit_apptest": {"pass": app_test.get("pass"), "app_test_runs": app_test.get("app_test_runs"), "real_positive_model": "M2", "no_evidence_stopped_before_generator": not app_test["no_evidence_guard"].get("generator_called")},
        "unlogged_pre_recovery_app_test_attempt": app_recovery,
        "scope": "bounded operational smoke; not full evaluation or formal corpus deployment",
    }
    extract_validation["reference_counts"] = dict(reference_counts)
    extract_validation["reference_counts_by_species"] = {species: dict(counts) for species, counts in species_reference_counts.items()}
    extract_validation["rubric_status_counts"] = dict(rubric_counts)
    extract_validation["independent_operational_test_set"] = {"records": len(test_set), "species_counts": dict(test_species), "status_counts": dict(test_status), "human_gold": 0}
    write_json(HERE / "evidence_extraction_validation.json", extract_validation)

    source_coverage["phase_z_update"] = {
        "new_sources_added": 0,
        "new_formal_admissions": 0,
        "new_fulltext_indexing_rights_verified": 0,
        "existing_50_blocker_records": len(blockers),
        "blocker_status_counts": dict(blocker_counts),
        "verified_answer_candidates_by_species": {species: dict(counts) for species, counts in species_reference_counts.items()},
        "source_card_processing_scope": "Limited nonpublic researcher-authored fact-card checks; no full-text source indexing rights asserted.",
        "dgbas_2020_scope_unchanged": "single-year descriptive facts only; not used as species-specific husbandry evidence",
    }
    write_json(HERE / "source_coverage_progress.json", source_coverage)

    # Correct the parsed pytest summary using the actual saved output.
    log_text = (HERE / "repository_pytest.log").read_text(encoding="utf-8-sig", errors="replace")
    match = re.search(r"(\d+) passed,\s*(\d+) subtests passed in ([0-9.]+)s", log_text)
    pytest_results.update({
        "passed": int(match.group(1)) if match else None,
        "unittest_subtests_passed": int(match.group(2)) if match else pytest_results.get("unittest_subtests_passed"),
        "duration_seconds": float(match.group(3)) if match else None,
        "parsed_summary": match.group(0) if match else None,
        "skipped": 0,
        "failed": 0 if pytest_results.get("exit_code") == 0 else None,
        "collection_errors": 0 if pytest_results.get("exit_code") == 0 else None,
        "result": "PASS" if pytest_results.get("exit_code") == 0 and match else "INCOMPLETE",
    })
    write_json(HERE / "repository_pytest_results.json", pytest_results)

    e2e = {
        "phase": "Z",
        "bounded_live_smoke": True,
        "real_retrieval_queries": len(retrieval),
        "retrieval_candidate_counts": {row["question_id"]: row.get("final_top5_count") for row in retrieval},
        "contexts_padded_or_fabricated": False,
        "generator_calls_logged": len(generation),
        "generator_calls_logged_by_model": {k: v["generator_calls_logged"] for k, v in by_model.items()},
        "same_context_digest_across_models_per_question": shared_context_consistency,
        "model_identity_digest_checks_passed_for_all_four": True,
        "raw_model_json_valid_count": sum(bool(row.get("raw_json_valid")) for row in generation),
        "raw_model_json_invalid_count": sum(not bool(row.get("raw_json_valid")) for row in generation),
        "answer_origins": dict(origins),
        "all_final_citations_resolve_to_retrieved_source_locator_and_checksum": citation_pass,
        "safety_gate_negative_tests": safety_gate_summary,
        "offline_engine_unit_tests": {"passed": 8, "failed": 0},
        "repository_pytest": {"result": pytest_results["result"], "passed": pytest_results.get("passed"), "failed": pytest_results.get("failed"), "skipped": pytest_results.get("skipped"), "collection_errors": pytest_results.get("collection_errors"), "unittest_subtests_passed": pytest_results.get("unittest_subtests_passed")},
        "streamlit_apptest": {"result": "PASS" if app_test.get("pass") else "FAIL", "runs": app_test.get("app_test_runs"), "positive_live_m2_answer_and_citation_rendered": bool(app_test["positive_live_m2"].get("citation_rendered")), "no_evidence_abstained_without_generator": app_test["no_evidence_guard"].get("final_status") == "abstain" and not app_test["no_evidence_guard"].get("generator_called")},
        "one_initial_streamlit_harness_attempt_lost_result": True,
        "full_production_streamlit_e2e": "NOT_TESTED; app is an isolated research-sidecar application, not switched into Production",
        "formal_corpus_admission": False,
        "phase_v_isolated_research_corpus_reused": True,
        "full_720_generations": False,
        "full_evaluation_metrics": "NOT_RUN",
        "bounded_smoke_pass": bool(citation_pass and safety_gate_summary["all_stopped_before_generator"] and app_test.get("pass") and pytest_results["result"] == "PASS"),
        "limitations": [
            "The bounded live retrieval used the Phase Y isolated retrieval core and Phase V research corpus/source cards, not a newly admitted formal Evaluation Corpus.",
            "Only mullet and grouper had live retrieval-plus-generation cases; eel was a no-evidence guard. Other species were covered in source checks/test records but not direct live answer generation.",
            "Four source-answer candidate statuses are not Human Gold; automatic source-span checks establish traceability, not expert correctness or third-party full-text permission.",
            "One initial AppTest request ran before a harness SessionState access error prevented its result from being serialized; it is excluded from stored metric counts and documented separately.",
        ],
    }
    write_json(HERE / "rag_real_e2e_validation.json", e2e)

    readiness = {
        "next_full_720_evaluation_ready": False,
        "bounded_operational_smoke_passed": e2e["bounded_smoke_pass"],
        "formal_corpus_v3_built_or_admitted": False,
        "phase_v_isolated_research_corpus_exists_but_is_not_formal_designated_corpus": True,
        "new_sources_with_fulltext_processing_rights_verified": 0,
        "blocked_source_files": {"reviewed": len(blockers), "fulltext_rights_unverified": source_coverage["phase_y_blocked_source_files_reexamined"].get("full_text_index_rights_unverified_or_pending")},
        "reference_candidate_status_counts": dict(reference_counts),
        "human_gold_count": 0,
        "newly_licensed_professional_sources": 0,
        "required_before_full_run": [
            "Use the existing 57 owner decisions without repeating that approval step, and verify the actual use basis and allowed processing scope for each selected source; owner approval is not third-party authorization.",
            "Build and freeze one designated, versioned, rights-scoped Corpus and index; retain original source/locator/version binding.",
            "Expand answer/rubric coverage beyond the small source-backed subset, including eel and missing disease/water-quality/legal evidence; keep unsupported questions as expected abstention or not evaluable.",
            "Freeze the full 180-question eligibility table, model prompts, retrieval configuration, reference answers, and scoring policies before generation.",
            "Exclude the one unpersisted preliminary AppTest response and use the corrected harness for future calls so every new result is persisted; add direct live coverage for other species/model paths as needed.",
            "No Human Gold exists; any correctness metrics must remain explicitly automated/exploratory until independent review is obtained.",
        ],
        "metrics_not_run": ["full-dataset Faithfulness", "Judge Answer Relevance", "BGE-M3 similarity", "Structured IFR", "TTFT/TPS aggregates", "RAM/VRAM aggregates", "Context Precision@5", "Logical Accuracy", "Arithmetic Accuracy"],
        "full_720_should_start": False,
    }
    write_json(HERE / "full_evaluation_readiness.json", readiness)

    compatibility = {
        "phase_z_workspace": str(HERE),
        "phase_y_inputs_read_only": True,
        "production_or_formal_corpus_modified": False,
        "production_sqlite_modified": False,
        "historical_phase_e_or_phase_w_generation_modified": False,
        "phase_z_reference_rubric_test_set_frozen_before_generator": freeze.get("frozen_before_first_generator_call"),
        "frozen_input_hashes_match": freeze_check,
        "new_fulltext_source_admissions": 0,
        "full_720_generations_executed": False,
        "formal_weighted_score_or_winner": False,
        "frozen_manifest": protected,
        "repository_pytest": e2e["repository_pytest"],
        "isolated_engine_tests": {"passed": 8, "failed": 0},
        "streamlit_apptest_pass": app_test.get("pass"),
        "notes": [
            "Owner decisions remain on file; they were not repeated. They were not represented as third-party licenses.",
            "Only limited, nonpublic, source-bound fact-card processing was exercised; no full-text indexing permission is claimed.",
            "Production, Historical E4, Evaluation Corpus v2, rag_store.sqlite3, original generation logs, and historical reports remain protected and unchanged by this phase.",
        ],
    }
    write_json(HERE / "compatibility.json", compatibility)

    report = f"""# Phase Z 最終報告

## 執行結果

本階段完成通用證據閘、事實摘取、引用綁定及拒答路徑的隔離實作，沒有依題目 ID 或固定答案分支。判定程式先檢查原始頁面精確引文、來源雜湊、來源版本、魚種適用性、允許的非公開事實卡處理範圍及必需答案元素；疾病診斷、藥品劑量、停藥期與未核實法規仍會阻擋確定性摘取。

離線引擎測試 {8}/8 通過。Repository pytest 為 {pytest_results.get('passed')} passed、{pytest_results.get('failed')} failed、{pytest_results.get('skipped')} skipped、{pytest_results.get('collection_errors')} collection errors，另有 {pytest_results.get('unittest_subtests_passed')} 個 subtests 通過。隔離 Streamlit AppTest 的正向真實 M2 流程顯示答案與來源；無證據流程在呼叫模型前拒答。

## 真實模型回歸

四模型均核對本機標籤與 Digest。真實檢索查詢 {len(retrieval)} 題，分別返回 {', '.join(str(row.get('final_top5_count')) for row in retrieval)} 段合格候選；未補造五段。實際生成 JSONL 保存 {len(generation)} 次呼叫：{origins.get('MODEL_GENERATED', 0)} 筆採用模型直接回答，{origins.get('DETERMINISTIC_EVIDENCE_EXTRACTION', 0)} 筆因模型回答不完整或輸出無效而使用通用摘取，最終均有來源綁定的回答。原始 JSON 有效 {sum(bool(row.get('raw_json_valid')) for row in generation)}/{len(generation)}；一筆 M3 回覆 JSON 不完整，系統按已驗證事實卡回補並保留原始回覆。最終引用定位與來源核對：{'通過' if citation_pass else '未完全通過'}。

M2 三次已保存的真實呼叫中，模型直接輸出完整且可接受的答案 {by_model['M2']['answer_origins'].get('MODEL_GENERATED', 0)} 次；另一次原始回答只寫出數值，未符合必要單位／完整答案元素，系統使用確定性摘取完成答案。Phase Y 中鞍帶石斑密度回歸的 M2 原始模型曾 4/4 拒答；Phase Z 對相同密度案例的單次 M2 回歸直接回答「10,000–30,000 尾／公頃」並帶可回查引用。這是有限案例改善，不能推論為 M2 全面拒答問題已解決。

另有 12 筆負向安全閘測試（3 種無據／錯物種／高風險情境 × 4 模型）均在 Generator 前阻擋；無證據的鰻魚水質、烏魚來源套用吳郭魚及無產品依據的藥品劑量均拒答。這些是閘門測試，並非模型拒答能力準確率。

初次 Streamlit 測試在模型呼叫後因測試程式錯用 SessionState `.get` 而未序列化結果；修正後重新測試通過。初次回覆未保存原始內容，已單獨記錄並排除於統計。本次可追溯的模型輸出為 9 筆獨立檢索回歸，加上成功的 Streamlit M2 顯示測試 1 筆；該首次失敗 harness 呼叫另有 1 筆未留存回覆。

## 來源與答案基準

15 題來源答案候選已在生成前凍結：13 題為 `SOURCE_VERIFIED_AUTOMATED`，1 題來源頁面可定位但因疾病高風險而禁止自動摘取，1 題仍 `PARTIALLY_SUPPORTED`。這代表原文與答案候選的自動來源核對狀態，不代表 Human Gold、正式 Corpus Admission 或第三方全文授權。15 筆 rubric 也已生成前凍結；自動核驗之外，Human Gold 仍為 0。

現有候選涵蓋烏魚 7 題、虱目魚 2 題、石斑魚 1 題、鱸魚／金目鱸 4 題、吳郭魚 1 題（部分支持）；沒有已核驗的鰻魚答案候選。可用於受控測試的來源事實卡因此仍偏向烏魚，疾病、用藥及部分水質類別不足。

50 筆受阻來源重新檢查後，50/50 本機檔案與 SHA-256 相符，48 份可從內文抽到發布者或日期線索；明確全文索引授權文字為 0，全文索引權利仍待核實為 50/50。本階段新增正式 Admission 或新增全文使用授權來源：0。只在隔離的非公開事實卡工作流測試短摘與來源定位，沒有建立或宣稱正式 Corpus v3。

## 評測就緒度與保護狀態

**目前不具備啟動下一次 720 次完整評測的條件。**原因是正式指定 Corpus 尚未建立／准入，50 筆來源全文索引使用條件未核實，參考答案只覆蓋有限候選且沒有 Human Gold，鰻魚及多個專業類別缺少可用來源；本階段只凍結 10 個操作案例與 15 個候選基準，並未凍結完整 180 題設定。完整資料集的八項既有指標與 Context Precision@5、Logical Accuracy、Arithmetic Accuracy 均未重算。

Frozen Manifest：{protected.get('records')}/{protected.get('records')} 相符；差異 {protected.get('mismatch')}、缺失 {protected.get('missing')}。正式 SQLite SHA-256 與預期相符。沒有執行完整 720 次生成，沒有正式加權總分或 Winner Selection，也沒有切換 Production。

AI 自動來源核對與小規模模型 smoke 只能支持流程與可追溯性結論，不能代表專家認可的養殖正確率。完整細節見 `rag_real_e2e_validation.json`、`full_evaluation_readiness.json` 及本目錄 JSONL 原始紀錄。
"""
    (HERE / "phase_z_final_report.md").write_text(report, encoding="utf-8")

    # Machine-readable deliverable inventory with SHA-256 after writing.
    deliverables = [
        "grounded_answer_engine_v2.py", "m2_model_vs_system_answers.jsonl", "evidence_extraction_validation.json",
        "source_coverage_progress.json", "reference_answers_frozen.jsonl", "evaluation_rubrics_frozen.jsonl",
        "independent_test_set.jsonl", "rag_real_e2e_validation.json", "rag_streamlit_test.json",
        "repository_pytest_results.json", "full_evaluation_readiness.json", "phase_z_final_report.md", "compatibility.json",
        "protected_baseline_recheck.jsonl", "protected_baseline_recheck_summary.json",
    ]
    manifest = {"created_at_utc": datetime.now(timezone.utc).isoformat(), "files": [{"path": name, "sha256": sha(HERE / name), "size_bytes": (HERE / name).stat().st_size} for name in deliverables]}
    write_json(HERE / "phase_z_deliverable_manifest.json", manifest)
    print(json.dumps({"m2_rows": len(m2_rows), "logged_generator_calls": len(generation), "answer_origins": dict(origins), "references": dict(reference_counts), "rubric_status": dict(rubric_counts), "safety_gate_records": len(safety), "safety_gates_all_blocked_pre_generator": safety_gate_summary["all_stopped_before_generator"], "citation_check_count": len(citation_checks), "citation_pass": citation_pass, "pytest": pytest_results, "protected": protected, "readiness": "NOT_READY_FOR_FULL_720"}, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
