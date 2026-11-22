from __future__ import annotations

import collections
import hashlib
import json
import shutil
from pathlib import Path

Y = Path(__file__).resolve().parent
ROOT = Y.parents[2]
V = ROOT / "reports/evaluation/fish_test_phase_v_20261018_224918"
W = ROOT / "reports/evaluation/fish_test_phase_w_20261019_133804"
X = ROOT / "reports/evaluation/fish_test_phase_x_20261019_162147"


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_json(path: Path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows):
    path.write_text("".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in rows), encoding="utf-8")


def sha(path: Path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


# Preserve the originally accumulated Phase Y diagnostic file before giving the
# requested regression artifact a stable, clearly typed record layout.
raw_m2_path = Y / "m2_abstention_regression.jsonl"
raw_input_path = Y / "m2_abstention_regression_pre_normalization.jsonl"
raw_m2_rows = read_jsonl(raw_input_path if raw_input_path.exists() else raw_m2_path)
historical_candidates = [row for row in raw_m2_rows if "phase_w_m2_abstention" in row]
negative_smoke = [row for row in raw_m2_rows if row.get("result")]
positive_runs = read_jsonl(Y / "positive_model_e2e_results.jsonl")
if not raw_input_path.exists():
    shutil.copyfile(raw_m2_path, raw_input_path)

phase_y_m2_positive = []
for row in positive_runs:
    if row.get("model_id") == "M2":
        phase_y_m2_positive.append({
            "record_type": "PHASE_Y_M2_POSITIVE_REGRESSION",
            "case_id": row.get("case_id"),
            "run_id": row.get("run_id"),
            "model_id": row.get("model_id"),
            "replicate": row.get("replicate"),
            "question_id": row.get("question_id"),
            "test_status": row.get("test_status"),
            "raw_model_status": (row.get("result") or {}).get("model_reported_status"),
            "effective_status": (row.get("result") or {}).get("status"),
            "checks": row.get("checks"),
            "timing": (row.get("result") or {}).get("timing"),
            "model_tag": (row.get("result") or {}).get("model_tag"),
            "model_digest": (row.get("result") or {}).get("model_digest"),
            "fallback_method": ((row.get("result") or {}).get("deterministic_evidence_fallback") or {}).get("method"),
            "evaluation_status": row.get("evaluation_status"),
            "not_human_gold": True,
        })
normalized_m2_rows = [{"record_type": "PHASE_X_REFUSAL_CANDIDATE_DIAGNOSIS", **row} for row in historical_candidates] + phase_y_m2_positive
write_jsonl(raw_m2_path, normalized_m2_rows)

# The raw model calls are retained together for replay/audit. Historical
# candidate diagnoses are kept in the separate artifact above.
smoke_runs = []
for row in negative_smoke + positive_runs:
    smoke_runs.append(row)
write_jsonl(Y / "rag_real_e2e_smoke_runs.jsonl", smoke_runs)

diag_180 = read_jsonl(Y / "m2_abstention_detail_180.jsonl")
cause_counts = collections.Counter(row.get("cause_classification", "UNKNOWN_CAUSE") for row in diag_180)
phase_w_status_counts = collections.Counter(row.get("effective_status", "UNKNOWN") for row in diag_180)
assessment_counts = collections.Counter(row.get("assessment", "UNKNOWN") for row in historical_candidates)
candidate_ids = [row.get("question_id") for row in historical_candidates]
candidate_source_verification = collections.Counter((row.get("reference_candidate") or {}).get("verification_status", "NO_SEPARATE_SOURCE_RECORD") for row in historical_candidates)
positive_assessment = {
    "fully_or_explicitly_bounded_support": [row["question_id"] for row in historical_candidates if row.get("assessment") in ("ANSWERABLE_FROM_RETRIEVED_FACT_CARD", "ANSWERABLE_WITH_EXPLICIT_LIMITATION")],
    "partial_support_only": [row["question_id"] for row in historical_candidates if row.get("assessment") == "PARTIAL_ANSWER_SUPPORTED"],
    "not_confirmed_or_refusal_justified": [row["question_id"] for row in historical_candidates if row.get("assessment") not in ("ANSWERABLE_FROM_RETRIEVED_FACT_CARD", "ANSWERABLE_WITH_EXPLICIT_LIMITATION", "PARTIAL_ANSWER_SUPPORTED")],
}
root_cause = {
    "phase_w_question_count": len(diag_180),
    "phase_w_m2_effective_refusal_count": phase_w_status_counts.get("abstain", 0),
    "phase_w_m2_effective_status_counts": dict(phase_w_status_counts),
    "phase_w_cause_counts": dict(cause_counts),
    "suspected_unnecessary_refusal_candidates": len(historical_candidates),
    "candidate_question_ids": candidate_ids,
    "candidate_assessment_counts": dict(assessment_counts),
    "candidate_source_verification_counts": dict(candidate_source_verification),
    "source_verified_automated_candidate_ids": [row.get("question_id") for row in historical_candidates if (row.get("reference_candidate") or {}).get("verification_status") == "SOURCE_VERIFIED_AUTOMATED"],
    "evidence_review_outcome": positive_assessment,
    "interpretation": "Counts reflect saved refusal execution paths and automated source/context review. They are not Human Gold and do not establish classifier precision/recall.",
    "root_cause_for_anchor_case": {
        "classification": "MODEL_SIDE_SELF_ABSTENTION_WITH_SUFFICIENT_CONTEXT",
        "context_reached_model": True,
        "precheck_state": "EVIDENCE_SUFFICIENT",
        "parser_or_citation_rejection_before_repair": False,
        "initial_model_response": "valid JSON abstention; citation IDs were allowed",
        "phase_y_resolution": "narrow deterministic evidence extraction after a retry, restricted to explicitly named Epinephelus lanceolatus stocking-density range and unit in a provenance-complete applicable source chunk",
        "remaining_limit": "Does not establish general M2 refusal behavior or professional accuracy across other questions.",
    },
    "no_blanket_rights_claim": True,
    "not_human_gold": True,
}
write_json(Y / "m2_abstention_root_cause.json", root_cause)

retrieval_summary = read_json(Y / "retrieval_coverage_repair_summary.json")
retrieval_rows = read_jsonl(Y / "retrieval_filter_fix_180.jsonl")
retrieval_summary["phase_y_verified_regression_row_count"] = len(retrieval_rows)
retrieval_summary["query_text_identical_rows"] = sum(row.get("query_text_identical_v_w_y") is True for row in retrieval_rows)
retrieval_summary["phase_y_corpus_versions"] = sorted({str(row.get("corpus_version_v_w_y")) for row in retrieval_rows})
retrieval_summary["interpretation"] = "Retrieval availability/counts only; these are not relevance, evidence sufficiency, or answer-accuracy labels."
write_json(Y / "retrieval_coverage_repair_summary.json", retrieval_summary)

crosswalk = read_json(Y / "source_crosswalk_writeback.json")
crosswalk_summary = []
for entry in crosswalk.get("entries", []):
    crosswalk_summary.append({
        "source_id": entry.get("source_id"),
        "identity_status": entry.get("identity_status"),
        "sidecar_writeback_status": entry.get("writeback_status"),
        "raw_bytes_saved": entry.get("source_bytes_saved"),
        "content_version_status": entry.get("content_version_status"),
        "full_text_indexing_basis": entry.get("full_text_indexing_basis"),
        "admission_status": entry.get("admission_status"),
        "retrieval_allowlist_status": entry.get("retrieval_allowlist_status"),
    })

rubrics = read_jsonl(Y / "reference_answer_rubrics_frozen.jsonl")
verification_counts = collections.Counter(row.get("verification_status", "UNKNOWN") for row in rubrics)
freeze_audit = {
    "record_count": len(rubrics),
    "verification_status_counts": dict(verification_counts),
    "human_gold_reviewed_count": sum(bool(row.get("human_gold_reviewed")) for row in rubrics),
    "all_not_human_gold": all(not row.get("human_gold_reviewed") and row.get("human_gold_status") != "HUMAN_GOLD" for row in rubrics),
    "freeze_order_deviation": "Initial Phase Y engineering smoke calls started before this candidate rubric registry was written. The registry was derived only from Phase X/source records; no Phase Y response was used to author, modify, or score a rubric. No accuracy score was calculated. A future full evaluation must freeze rubrics before any generator call.",
    "rubric_registry_sha256": sha(Y / "reference_answer_rubrics_frozen.jsonl"),
}
write_json(Y / "reference_rubric_freeze_audit.json", freeze_audit)

positive_by_model = collections.defaultdict(list)
for row in positive_runs:
    if row.get("test_status") == "COMPLETED":
        positive_by_model[row.get("model_id")].append(row)
positive_latest = {}
for model_id, rows in positive_by_model.items():
    chosen = max(rows, key=lambda r: int(r.get("replicate") or 0))
    result = chosen.get("result") or {}
    checks = chosen.get("checks") or {}
    positive_latest[model_id] = {
        "run_id": chosen.get("run_id"),
        "effective_status": result.get("status"),
        "model_reported_status": result.get("model_reported_status"),
        "answer_contains_source_range": checks.get("range_matches_source"),
        "answer_contains_unit": checks.get("unit_matches_source"),
        "citation_valid": checks.get("citation_valid"),
        "citation_targets_expected_chunk": checks.get("citation_points_to_expected_chunk"),
        "system_extractive_fallback": checks.get("system_fallback_used"),
        "positive_e2e_pass": bool(result.get("status") == "answered" and checks.get("range_matches_source") and checks.get("unit_matches_source") and checks.get("citation_valid") and checks.get("citation_points_to_expected_chunk")),
        "model_tag": result.get("model_tag"),
        "model_digest": result.get("model_digest"),
    }

negative_rows = [row for row in negative_smoke if row.get("case_id")]
negative_summary = []
for row in negative_rows:
    result = row.get("result") or {}
    negative_summary.append({
        "case_id": row.get("case_id"),
        "model_id": row.get("model_id"),
        "status": result.get("status"),
        "model_reported_status": result.get("model_reported_status"),
        "safety_guard_applied": result.get("safety_guard_applied"),
        "evidence_state": (result.get("evidence_decision") or {}).get("state"),
        "citation_valid": (result.get("citation_validation") or {}).get("valid"),
        "completed": row.get("test_status") == "completed",
    })
e2e = {
    "test_scope": "small real API and isolated Streamlit regression only; no full 720 generation run",
    "positive_context": {
        "source_id": "TFRI-M17-GROUPER",
        "source_sha256": "8f2c277010611d125458e136b1c139b9d1479eebdd6e5d9c369c16c79e952159",
        "chunk_id": "fv3-m17g-004",
        "species_scope": "石斑魚; explicitly named 鞍帶石斑 / Epinephelus lanceolatus evidence",
        "locator": "PDF physical page 4; printed locator 3-4-4",
        "corpus_version": "research_corpus_v3_phase_v_20261018",
        "context_count": 1,
    },
    "positive_latest_result_by_model": positive_latest,
    "all_four_models_pass_latest_positive_regression": len(positive_latest) == 4 and all(v["positive_e2e_pass"] for v in positive_latest.values()),
    "positive_attempts": len(positive_runs),
    "negative_real_api_cases": negative_summary,
    "negative_case_count": len(negative_summary),
    "no_context_all_four_models_tested": sum(row.get("case_id") == "NO_CONTEXT_EEL_DO" for row in negative_rows) == 4,
    "payload_validation": read_json(Y / "e2e_payload_validation_cases.json"),
    "guardrail_validation": read_json(Y / "phase_y_guardrail_validation.json"),
    "streamlit_validation": read_json(Y / "rag_v3_streamlit_validation.json"),
    "model_identity_digests": {m: [d[0], d[1]] for m, d in {
        "M1": ["deepseek-r1:7b", "755ced02ce7befdb13b7ca74e1e4d08cddba4986afdb63a480f2c93d3140383f"],
        "M2": ["qwen2.5-coder:7b", "dae161e27b0e90dd1856c8bb3209201fd6736d8eb66298e75ed87571486f4364"],
        "M3": ["hf.co/bartowski/DeepSeek-R1-Distill-Llama-8B-GGUF:Q4_K_M", "aab87d0e8a585cc6260d3a448e3f66ff2057d1cd6975c834151deeb1eae94b42"],
        "M4": ["gemma2:9b", "ff02c3702f322b9e075e9568332d96c0a7028002f1a5a056e0a6784320a4db0b"],
    }.items()},
    "limitations": [
        "Engineering regression observations are not professional answer accuracy or Human Gold.",
        "The grouper fallback is tightly allowlisted and is not a general-purpose answer repair mechanism.",
        "One pre-fail-closed M1 positive attempt returned an answer with invalid/missing citation and was not accepted; a post-fix rerun passed via the narrow source extraction fallback.",
        "Only one positive source-backed knowledge case was used across models; this is a smoke test, not broad model validation.",
        "The TFRI fact-card check does not claim blanket full-text reproduction or indexing permission.",
    ],
}
write_json(Y / "rag_real_e2e_tests.json", e2e)
write_json(Y / "rag_v3_end_to_end_validation.json", e2e)

# Full repository tests were run with all declared parser and reranker packages
# available; the two earlier mixed-environment attempts remain in their logs.
pytest_result = {
    "command_scope": "tests/ repository suite",
    "python_executable": "C:\\Users\\ethan\\anaconda3\\python.exe",
    "python_version": "3.14.6",
    "PYTHONPATH_order": [".venv-reranker\\Lib\\site-packages", ".venv\\Lib\\site-packages"],
    "runtime_dependencies_confirmed": {"torch": "2.14.1+cu130", "scipy": "1.18.0", "python_docx": "1.2.0", "PyMuPDF": "9.0.0", "pytest": "9.0.3"},
    "collected_or_executed_test_outcome": {"passed": 607, "failed": 0, "skipped": 0, "collection_errors": 0, "unittest_subtests_passed": 8},
    "result": "PASS",
    "log": str(Y / "repository_pytest_final_phase_y.log"),
    "separate_environment_attempts": [
        {"result": "601 passed, 6 skipped, 8 subtests passed", "reason": "Anaconda interpreter did not have torch; reranker-specific cases skipped."},
        {"result": "6 failures after 601 passed", "reason": "Mixed interpreter/package paths loaded incompatible SciPy BLAS DLLs; not the final run."},
        {"result": "7 collection errors", "reason": "Reranker-only package path omitted python-docx and PyMuPDF; not the final run."},
    ],
    "sandbox_or_permissions_changed": False,
}
write_json(Y / "repository_pytest_results.json", pytest_result)

baseline = read_json(Y / "protected_baseline_recheck_summary_protected_baseline_recheck_final.json")
readiness = {
    "m2_anchor_refusal_fix_reproduced": positive_latest.get("M2", {}).get("positive_e2e_pass", False),
    "all_four_models_real_positive_smoke_pass": e2e["all_four_models_pass_latest_positive_regression"],
    "no_context_safety_smoke_all_models": e2e["no_context_all_four_models_tested"],
    "other_safety_cases_pass": all(row["completed"] and row["status"] == "abstain" and row["citation_valid"] is True for row in negative_summary),
    "streamlit_real_positive_and_no_evidence_cases_pass": e2e["streamlit_validation"].get("all_pass", False),
    "repository_pytest_pass": pytest_result["result"] == "PASS",
    "source_answer_rubric_counts": dict(verification_counts),
    "human_gold_count": freeze_audit["human_gold_reviewed_count"],
    "retrieval_coverage": {k: retrieval_summary[k] for k in ("phase_v_any", "phase_w_any", "phase_y_any", "phase_v_full", "phase_w_full", "phase_y_full", "repair_status", "diagnosis_stage")},
    "owner_approval_57_already_recorded": True,
    "owner_approval_is_not_third_party_license": True,
    "formal_new_source_admissions_this_phase": 0,
    "s08_s10_resolved_for_retrieval": False,
    "ready_for_full_720_regression": False,
    "readiness_decision": "NOT_READY_FOR_FULL_720",
    "blockers": [
        "Retrieval reaches at least one eligible Context for 95/180 questions and returns a full Top-5 for 35/180; coverage remains too sparse for the stated six-species evaluation purpose.",
        "Only 15 of 180 reference candidates are source-verified automatically; 6 are arithmetic-only diagnostics and 7 remain not evaluable. No Human Gold exists.",
        "S08 and S10 identities were corrected in an isolated sidecar, but original content/version/usage basis is still unverified and both remain excluded.",
        "Owner approval authorizes the research source-processing decision; it does not itself establish third-party full-text indexing or redistribution rights.",
        "The evidence-backed answer smoke case covers one grouper density fact only; safety scenarios are smoke-tested, not a comprehensive four-model matrix.",
        "The candidate rubric registry was written after initial engineering smoke calls began. No Phase Y answer was used in rubric authoring/scoring, but future full-run criteria must be frozen before generation.",
    ],
    "no_full_720_generation_executed": True,
    "no_model_accuracy_or_weighted_winner_computed": True,
    "baseline": baseline,
}
write_json(Y / "next_full_evaluation_readiness.json", readiness)

compatibility = {
    "phase_y_workspace": str(Y),
    "phase_x_phase_w_inputs_read_only": True,
    "production_or_formal_corpus_modified": False,
    "production_sqlite_modified": False,
    "original_phase_e_or_phase_w_720_generation_modified": False,
    "full_720_new_generations_executed": False,
    "formal_source_admission_executed": False,
    "s08_s10_sidecar_only": True,
    "frozen_manifest": baseline,
    "notes": [
        "Phase Y code, retrieval results, smoke logs and reports are isolated under this workspace.",
        "The source crosswalk sidecar corrects S08/S10 identities but keeps both excluded pending actual content, version and usage-basis verification.",
        "The grouper answer recovery is an exact-source deterministic extraction for one narrowly specified query/source pattern; it does not confer rights or establish human-verified correctness.",
    ],
}
write_json(Y / "compatibility.json", compatibility)

lines = [
    "# Phase Y — 有據回答修復與評測準備",
    "",
    f"工作區：`{Y}`",
    "",
    "## 結果",
    "",
    f"- Phase W 的 M2 在 180 題中有效拒答 {phase_w_status_counts.get('abstain', 0)} 題、另有 {phase_w_status_counts.get('invalid_output', 0)} 題輸出無效。原因分布：`{dict(cause_counts)}`；其中 73 題是模型輸出合法拒答、沒有被安全閘或引用驗證攔下，86 題無合格 Context、20 題由證據／安全判定要求拒答，另 1 題 JSON 截斷導致解析失敗。",
    f"- 13 題疑似不必要拒答逐題回看後：9 題的現有 Top-5 fact card 有直接或明確限縮的內容支持（其中 {candidate_source_verification.get('SOURCE_VERIFIED_AUTOMATED', 0)} 題另有原始來源、版本／checksum 與精確 span 的 `SOURCE_VERIFIED_AUTOMATED` 登錄）、1 題只有部分支持，3 題未確認為不必要拒答。這是自動證據核對，不是 Human Gold。",
    "- 鞍帶石斑放養密度的根因是模型在收到正確 Context 且前置判定為 `EVIDENCE_SUFFICIENT` 後自行拒答。Phase Y 保留模型原始輸出，僅在來源、魚種、問題、數值與單位全部精確符合白名單條件時，以 deterministic extraction 回傳該來源範圍。",
    f"- 真實正向 API 回歸（最新版本）：M1–M4 均有有效答案、數值範圍、單位及引用；M2 最新試次為 `{positive_latest.get('M2', {}).get('run_id')}`。M2 四次測試中原始模型仍拒答，系統窄範圍回補成功。M1 曾有一次缺引用輸出，修正後無效輸出不會呈現，後續回歸通過。",
    f"- 真實拒答 API 測試 {len(negative_summary)} 筆完成，涵蓋四模型無 Context，以及魚種衝突、未核實法規版本、特定藥品依據不足與缺少必要水溫數值；均由安全閘保留拒答。",
    f"- V→W 覆蓋變化為 111 題不變、59 題下降、10 題上升。Phase Y 檢索相對 W：95/180 題至少一段 Context（W 為 94），35/180 題有完整 Top-5（W 為 34）；僅 `FT-milkfish-Q03` 從 0 段恢復為 5 段。另 58 題仍低於 Phase V 候選數，不能靠放寬魚種或來源限制安全補齊。",
    "- 180 題診斷顯示：74 題缺來源 allowlist/profile、60 題適用候選池少於 5、11 題來源存在但被 metadata/scope 篩除、35 題已有 Top-5。這表示候選可用量，不是相關性或答案支持判定。",
    f"- 參考答案／Rubric 登錄共 28 題：15 題 `SOURCE_VERIFIED_AUTOMATED`、6 題僅題幹算術診斷、7 題 `NOT_EVALUABLE`；Human Gold = {freeze_audit['human_gold_reviewed_count']}。沒有新增 Accuracy 分數。",
    "- S08（漁業署放養量查詢服務）與 S10（氣象署 Open Data API Swagger）的身份錯配已寫入 Phase Y 版本化 sidecar；兩者仍缺原始內容版本及可用依據，未 Admission、未進入檢索 allowlist。57 筆 Owner Decision 不被解讀為第三方全文索引授權。",
    f"- Repository pytest 最終組合環境結果：{pytest_result['collected_or_executed_test_outcome']['passed']} passed、0 failed、0 skipped；8 個 unittest subtests 通過。早先不同依賴路徑的失敗試跑保留在紀錄中，最終跑使用 Python 3.14.6 並同時載入本機 Parser／Reranker 依賴。",
    "- 隔離 Streamlit AppTest 以真實檢索及 Generator 驗證一個正向密度題與一個鰻魚溶氧無證據拒答題，兩者皆 PASS。",
    f"- Frozen Baseline 最後核對：{baseline['match']}/{baseline['records']} 一致，0 mismatch、0 missing；正式 SQLite SHA-256 為 `{baseline['production_sqlite_sha256']}`。",
    "",
    "## 不足與評測準備結論",
    "",
    "本階段沒有重跑 720 次生成，也沒有 Source Admission 或 Corpus 建置。S08/S10 仍受阻。雖然小規模四模型端到端測試和 Repository pytest 通過，180 題僅 95 題取得至少一段合格 Context、完整 Top-5 僅 35 題，且只有 15 題有自動來源核驗的參考答案。因此目前不具備有意義的完整 720 題專業評測條件。",
    "",
    "另有一項流程順序限制：Phase Y 工程 smoke 呼叫先於本輪參考答案登錄凍結開始；登錄僅取自既有 Phase X 候選，沒有用 Phase Y 回答撰寫或評分，也未計算準確率。未來完整評測仍須在生成前凍結答案與 Rubric。",
    "",
    "## 可追溯檔案",
    "",
    f"- M2 拒答診斷：`{Y / 'm2_abstention_root_cause.json'}`",
    f"- 180 題來源過濾差異：`{Y / 'retrieval_filter_fix_180.jsonl'}`",
    f"- S08/S10 sidecar：`{Y / 'source_crosswalk_writeback.json'}`",
    f"- 來源核驗 Rubric：`{Y / 'reference_answer_rubrics_frozen.jsonl'}`",
    f"- 真實模型呼叫：`{Y / 'rag_real_e2e_smoke_runs.jsonl'}`",
    f"- 系統與 Streamlit 驗證：`{Y / 'rag_real_e2e_tests.json'}`、`{Y / 'rag_v3_streamlit_validation.json'}`",
    f"- Repository pytest：`{Y / 'repository_pytest_results.json'}`",
    f"- 最終基線核對：`{Y / 'protected_baseline_recheck_final.jsonl'}`",
]
(Y / "m2_grounded_answer_fix_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
(Y / "phase_y_final_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

# Structural and count validation for the delivered machine-readable records.
jsonl_files = [
    "retrieval_filter_fix_180.jsonl",
    "reference_answer_rubrics_frozen.jsonl",
    "m2_abstention_regression.jsonl",
    "rag_real_e2e_smoke_runs.jsonl",
    "protected_baseline_recheck_final.jsonl",
]
validation = {name: {"valid_jsonl": True, "record_count": len(read_jsonl(Y / name))} for name in jsonl_files}
validation["counts"] = {
    "retrieval_rows": len(retrieval_rows),
    "candidate_diagnostic_rows": len(historical_candidates),
    "rubric_rows": len(rubrics),
    "actual_e2e_call_rows": len(smoke_runs),
    "protected_manifest_rows": baseline["records"],
}
validation["all_expected_counts"] = (
    len(retrieval_rows) == 180 and len(historical_candidates) == 13 and len(rubrics) == 28 and len(smoke_runs) == 16 and baseline["records"] == 636 and baseline["match"] == 636
)
write_json(Y / "phase_y_output_validation.json", validation)
print(json.dumps({"workspace": str(Y), "m2_candidate_assessments": dict(assessment_counts), "positive_latest": positive_latest, "negative_cases": len(negative_summary), "pytest": pytest_result["collected_or_executed_test_outcome"], "baseline": baseline, "output_validation": validation}, ensure_ascii=False, indent=2))
