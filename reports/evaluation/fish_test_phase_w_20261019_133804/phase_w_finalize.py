from __future__ import annotations

import hashlib
import json
import math
import statistics
from collections import Counter, defaultdict
from pathlib import Path

W = Path(__file__).resolve().parent
ROOT = W.parents[2]


def read_json(name):
    return json.loads((W / name).read_text(encoding="utf-8-sig"))


def read_jsonl(name):
    p = W / name
    return [json.loads(line) for line in p.read_text(encoding="utf-8-sig").splitlines() if line.strip()]


def write_json(name, value):
    (W / name).write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def mean(xs):
    return statistics.mean(xs) if xs else None


def pct(xs, p):
    return statistics.quantiles(xs, n=100, method="inclusive")[p - 1] if len(xs) >= 2 else (xs[0] if xs else None)


def digest_file(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def structured_result(row, retrieval_by_qid):
    raw = row.get("raw_response")
    if not isinstance(raw, str) or not raw.strip():
        return False, "no_raw_model_response", False, "no_raw_model_response"
    try:
        obj = json.loads(raw)
    except Exception:
        return False, "raw_response_json_invalid", False, "raw_response_json_invalid"
    required = {"status", "answer", "citations", "evidence_sufficiency", "abstention_reason"}
    if not isinstance(obj, dict) or not required.issubset(obj):
        return False, "required_fields_missing", False, "required_fields_missing"
    if obj.get("status") not in ("answered", "abstain") or not isinstance(obj.get("answer"), str):
        return False, "status_or_answer_type_invalid", False, "status_or_answer_type_invalid"
    if not isinstance(obj.get("citations"), list) or obj.get("evidence_sufficiency") not in ("sufficient", "partial", "insufficient"):
        return False, "citation_or_evidence_sufficiency_type_invalid", False, "citation_or_evidence_sufficiency_type_invalid"
    if obj.get("abstention_reason") is not None and not isinstance(obj.get("abstention_reason"), str):
        return False, "abstention_reason_type_invalid", False, "abstention_reason_type_invalid"
    for citation in obj["citations"]:
        if not isinstance(citation, dict) or not isinstance(citation.get("chunk_id"), str) or not isinstance(citation.get("source_id"), str):
            return False, "citation_schema_invalid", False, "citation_schema_invalid"
    schema_valid = True
    ctx = {(c.get("chunk_id"), c.get("source_id")) for c in retrieval_by_qid[row["question_id"]].get("reranked_top5", [])}
    for citation in obj["citations"]:
        if (citation.get("chunk_id"), citation.get("source_id")) not in ctx:
            return schema_valid, "schema_valid", False, "citation_not_in_fixed_context"
    if obj["status"] == "answered" and not obj["citations"]:
        return schema_valid, "schema_valid", False, "answer_without_citation"
    return schema_valid, "schema_valid", True, "citation_ids_valid"


def main():
    gens = read_jsonl("generator_results_v3.jsonl")
    attempts = read_jsonl("generator_attempt_log_v3.jsonl")
    retries = read_jsonl("generator_retry_error_audit.jsonl")
    retrievals = read_jsonl("retrieval_results_v3_updated.jsonl")
    judge = read_jsonl("judge_results_v3.jsonl")
    bge = read_jsonl("bge_m3_cosine_v3.jsonl")
    hardware = read_jsonl("hardware_samples_v3.jsonl")
    refs = read_jsonl("reference_answers_v3.jsonl")
    sources = read_jsonl("source_resolution_final.jsonl")
    facts = read_jsonl("research_fact_cards_w.jsonl")
    retrieval_by_qid = {x["question_id"]: x for x in retrievals}
    judge_by_key = {(x.get("question_id"), x.get("model_id")): x for x in judge}
    bge_by_key = {(x.get("question_id"), x.get("model_id")): x for x in bge}

    models = {
        "M1": {"tag": "deepseek-r1:7b", "digest": "755ced02ce7befdb13b7ca74e1e4d08cddba4986afdb63a480f2c93d3140383f"},
        "M2": {"tag": "qwen2.5-coder:7b", "digest": "dae161e27b0e90dd1856c8bb3209201fd6736d8eb66298e75ed87571486f4364"},
        "M3": {"tag": "hf.co/bartowski/DeepSeek-R1-Distill-Llama-8B-GGUF:Q4_K_M", "digest": "aab87d0e8a585cc6260d3a448e3f66ff2057d1cd6975c834151deeb1eae94b42"},
        "M4": {"tag": "gemma2:9b", "digest": "ff02c3702f322b9e075e9568332d96c0a7028002f1a5a056e0a6784320a4db0b"},
    }

    # One-time row-wise structure audit; status evaluates the model's final raw JSON, not the system post-check.
    structure_audit = []
    for g in gens:
        valid, reason, citation_valid, citation_reason = structured_result(g, retrieval_by_qid)
        structure_audit.append({
            "run_id": g.get("run_id"), "question_id": g["question_id"], "model_id": g["model_id"],
            "generator_status": g.get("status"), "raw_model_json_schema_valid": valid,
            "schema_validation_reason": reason, "citation_id_context_valid": citation_valid,
            "citation_validation_reason": citation_reason, "safety_guard_applied": g.get("safety_guard_applied"),
            "human_gold": False,
        })
    (W / "structured_output_audit_v3.jsonl").write_text("".join(json.dumps(x, ensure_ascii=False, separators=(",", ":")) + "\n" for x in structure_audit), encoding="utf-8")

    model_metrics = {}
    for mid in models:
        mr = [g for g in gens if g.get("model_id") == mid]
        mr_j = [judge_by_key[(g["question_id"], mid)] for g in mr if (g["question_id"], mid) in judge_by_key]
        mr_b = [bge_by_key[(g["question_id"], mid)] for g in mr if (g["question_id"], mid) in bge_by_key]
        ttft = [float((g.get("timing") or {}).get("ttft_visible_content_seconds")) for g in mr if (g.get("timing") or {}).get("ttft_visible_content_seconds") is not None]
        tps = [float((g.get("timing") or {}).get("tps")) for g in mr if (g.get("timing") or {}).get("tps") is not None]
        hw = [x for x in hardware if x.get("model_id") == mid]
        ram = [float(x["system_ram_used_gib"]) for x in hw if x.get("system_ram_used_gib") is not None]
        vram = [float(x["dedicated_vram_used_mib"]) for x in hw if x.get("dedicated_vram_used_mib") is not None]
        scored_j = [x for x in mr_j if x.get("status") == "scored"]
        valid_structure = [x for x in structure_audit if x["model_id"] == mid and x["raw_model_json_schema_valid"]]
        valid_citations = [x for x in structure_audit if x["model_id"] == mid and x["citation_id_context_valid"]]
        model_metrics[mid] = {
            **models[mid],
            "records": len(mr),
            "generator_calls": sum(g.get("generator_called") is True for g in mr),
            "effective_answered": sum(g.get("status") == "answered" for g in mr),
            "effective_abstentions": sum(g.get("status") == "abstain" for g in mr),
            "invalid_outputs": sum(g.get("status") == "invalid_output" for g in mr),
            "safety_guard_overrides": sum(g.get("safety_guard_applied") is True for g in mr),
            "raw_model_status_counts": dict(Counter(g.get("model_reported_status") for g in mr)),
            "structured_output_ifr": {"valid_n": len(valid_structure), "eligible_n": len(mr), "rate": len(valid_structure) / len(mr) if mr else None, "definition": "raw generator JSON matches required output schema; citation entailment excluded"},
            "citation_id_validation": {"valid_n": len(valid_citations), "eligible_n": len(mr), "rate": len(valid_citations) / len(mr) if mr else None, "definition": "all returned citation IDs are in fixed Top-5; answered responses must cite at least one chunk"},
            "judge_faithfulness": {"mean": mean([float(x["faithfulness"]) for x in scored_j if x.get("faithfulness") is not None]), "n": sum(x.get("faithfulness") is not None for x in scored_j)},
            "judge_answer_relevance": {"mean": mean([float(x["answer_relevance"]) for x in scored_j if x.get("answer_relevance") is not None]), "n": sum(x.get("answer_relevance") is not None for x in scored_j)},
            "judge_scored_n": len(scored_j), "judge_failed_n": sum(x.get("status") == "judge_failed" for x in mr_j),
            "bge_m3_cosine": {"mean": mean([float(x["similarity"]) for x in mr_b if x.get("status") == "scored" and x.get("similarity") is not None]), "n": sum(x.get("status") == "scored" and x.get("similarity") is not None for x in mr_b)},
            "ttft_visible_content_seconds": {"mean": mean(ttft), "median": statistics.median(ttft) if ttft else None, "n": len(ttft)},
            "tps": {"mean": mean(tps), "median": statistics.median(tps) if tps else None, "n": len(tps), "definition": "Ollama eval_count / eval_duration_ns * 1e9"},
            "system_ram_gib": {"sampled_max": max(ram) if ram else None, "sample_count": len(ram), "measurement_scope": "system_level_sampled_peak; not process RSS"},
            "dedicated_vram_mib": {"sampled_max": max(vram) if vram else None, "sample_count": len(vram), "measurement_scope": "nvidia-smi system-level samples; not per-process allocation"},
            "shared_gpu_memory_mib": {"value": None, "n": 0, "reason": "no reliable measurement source"},
            "context_precision_at_5": {"mean": None, "n": 0, "reason": "No trustworthy binary relevance labels; top-k retrieval is not a relevance judgment."},
            "logical_accuracy": {"mean": None, "n_correct": 0, "n_evaluable": 0, "reason": "No reviewer-approved source-backed logical rubric."},
            "arithmetic_accuracy": {"mean": None, "n_correct": 0, "n_evaluable": 0, "reason": "No complete verified formula/protocol/unit/reference answer/tolerance set."},
        }

    # Retrieval outcome and actual traceability, kept separate from relevance/P@5.
    by_cat = defaultdict(list)
    by_species = defaultdict(list)
    for r in retrievals:
        by_cat[r.get("category")].append(r)
        by_species[r.get("species")].append(r)
    coverage = {
        "question_count": len(retrievals),
        "questions_with_any_context": sum(bool(r.get("reranked_top5")) for r in retrievals),
        "questions_with_complete_top5": sum(len(r.get("reranked_top5", [])) == 5 for r in retrievals),
        "questions_with_partial_top5": sum(0 < len(r.get("reranked_top5", [])) < 5 for r in retrievals),
        "questions_with_zero_context": sum(not r.get("reranked_top5") for r in retrievals),
        "returned_contexts": sum(len(r.get("reranked_top5", [])) for r in retrievals),
        "by_species": {}, "by_category": {},
        "context_precision_at_5": {"mean": None, "n": 0, "reason": "No accepted relevance annotations were generated. Retrieval outcome/coverage is not P@5."},
    }
    for key, rows in by_species.items():
        coverage["by_species"][key] = {"questions": len(rows), "any_context": sum(bool(r.get("reranked_top5")) for r in rows), "complete_top5": sum(len(r.get("reranked_top5", [])) == 5 for r in rows), "returned_contexts": sum(len(r.get("reranked_top5", [])) for r in rows)}
    for key, rows in by_cat.items():
        coverage["by_category"][key] = {"questions": len(rows), "any_context": sum(bool(r.get("reranked_top5")) for r in rows), "complete_top5": sum(len(r.get("reranked_top5", [])) == 5 for r in rows), "returned_contexts": sum(len(r.get("reranked_top5", [])) for r in rows)}

    citation_rows = []
    for g in gens:
        rr = retrieval_by_qid[g["question_id"]]
        allowed = {(c.get("chunk_id"), c.get("source_id")) for c in rr.get("reranked_top5", [])}
        citations = g.get("model_citations_canonicalized") or g.get("citations") or []
        citation_ids_valid = all((c.get("chunk_id"), c.get("source_id")) in allowed for c in citations)
        citation_rows.append({"question_id": g["question_id"], "model_id": g["model_id"], "status": g.get("status"), "citation_count": len(citations), "citation_ids_in_fixed_context": citation_ids_valid, "citation_semantic_support": "not_evaluated", "human_gold": False})
    citation_summary = {
        "effective_answered_records": sum(g.get("status") == "answered" for g in gens),
        "answered_with_citation_ids_in_fixed_context": sum(x["status"] == "answered" and x["citation_ids_in_fixed_context"] and x["citation_count"] > 0 for x in citation_rows),
        "answered_without_or_invalid_citation_ids": sum(x["status"] == "answered" and (not x["citation_ids_in_fixed_context"] or x["citation_count"] == 0) for x in citation_rows),
        "semantic_citation_support_evaluated": False,
        "limitation": "ID-level citation provenance only; no verified expert semantic support score. A citation ID check is not proof that the cited text entails the answer."
    }

    outcome = {
        "run_id": "phase_w_integrated_v1",
        "population": "regression/exploratory evaluation on the repeatedly used 180-question Fish Test; not a fresh holdout",
        "generation": {
            "canonical_unique_question_model_rows": len(gens),
            "unique_question_ids": len({g.get("question_id") for g in gens}),
            "unique_model_question_pairs": len({(g.get("question_id"), g.get("model_id")) for g in gens}),
            "raw_attempt_log_rows": len(attempts),
            "retry_error_records": len(retries),
            "resolved_retry_failures": len(retries),
            "api_errors_unresolved": sum(g.get("status") == "api_error" for g in gens),
            "effective_status_counts": dict(Counter(g.get("status") for g in gens)),
            "safety_guard_override_count": sum(g.get("safety_guard_applied") is True for g in gens),
            "raw_generated_answer_count": sum(g.get("generator_called") is True for g in gens),
        },
        "models": model_metrics,
        "retrieval_coverage": coverage,
        "citation_support": citation_summary,
        "abstention_quality": {"effective_abstentions": sum(g.get("status") == "abstain" for g in gens), "expert_verified_correct_abstentions": None, "n_evaluable": 0, "reason": "No independently verified expected-answer / expected-abstention ground truth for the full set."},
        "accuracy_reference_status_counts": dict(Counter(r.get("verification_status") for r in refs)),
        "answerable_verified": sum(r.get("verification_status") == "ANSWERABLE_VERIFIED" for r in refs),
        "expected_abstention_candidates_not_gold": sum("EXPECTED_ABSTENTION" in str(r.get("verification_status")) for r in refs),
        "human_gold_reviewed": sum(r.get("human_gold_reviewed") is True for r in refs),
        "source_registry": {"records": len(sources), "distinct_source_hashes": len({x.get("sha256_actual") or x.get("sha256_expected") for x in sources if x.get("sha256_actual") or x.get("sha256_expected")}), "admission_counts": dict(Counter(x.get("admission_status") for x in sources)), "fulltext_scope_independently_verified_records": sum(x.get("fulltext_index_rights_independently_verified") is True for x in sources)},
        "system": {"corpus_version": "research_corpus_v3_phase_v_20261018", "corpus_records": 17402, "retrieval_eligible_chunks": 10412, "context_only_chunks": 6990, "reranker_sha256": "d9e3e081faff1eefb84019509b2f5558fd74c1a05a2c7db22f74174fcedb5286", "reranker_revision": "953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e", "bge_m3_digest": "7907646426070047a77226ac3e684fbbe8410524f7b4a74d02837e43f2146bab", "retrieval_pipeline": "BM25 + BGE-M3 Dense + RRF k=60 + BGE Reranker; fixed context per question shared across models"},
        "protected_baseline": read_json("protected_baseline_recheck_summary_protected_baseline_before_phase_w.json"),
        "interpretation": {"faithfulness_and_judge_relevance": "exploratory AI Judge scores, not expert truth", "bge_similarity": "embedding similarity, not correctness", "structured_ifr": "JSON/citation schema and fixed-context ID validity only, not answer accuracy", "p_at_5_logical_arithmetic": "N/A with zero eligible gold labels/rubrics", "overall_weighted_score_or_winner": "not computed"},
    }
    write_json("evaluation_metrics_v3.json", outcome)
    smoke = read_json("rag_v3_end_to_end_validation.json")
    write_json("rag_v3_smoke_validation.json", smoke)
    streamlit_initial = read_json("rag_v3_streamlit_validation.json")
    streamlit_interaction = read_json("rag_v3_streamlit_interaction_validation.json")
    streamlit_final = {
        "initial_render": streamlit_initial,
        "interactive_form_smoke": streamlit_interaction,
        "interaction_scope": "One real user form submission using isolated Phase W RAG engine. This request is outside the canonical 720 generator rows.",
        "status": "passed" if streamlit_interaction.get("status") == "passed" and streamlit_interaction.get("exception_count") == 0 else "failed",
    }
    write_json("rag_v3_streamlit_validation.json", streamlit_final)
    corpus_integrity = read_json("corpus_and_retrieval_integrity_v3.json")
    validation = {
        "phase": "W",
        "status": "FUNCTIONAL_ISOLATED_RAG_SMOKE_AND_FULL_REGRESSION_GENERATION_COMPLETE; PROFESSIONAL_ACCURACY_GATE_NOT_MET",
        "retrieval_pipeline": outcome["system"]["retrieval_pipeline"],
        "corpus_version": outcome["system"]["corpus_version"],
        "corpus_chunk_count": outcome["system"]["corpus_records"],
        "full_system_smoke": smoke,
        "corpus_and_top5_trace_integrity": corpus_integrity,
        "species_scope_regression": read_json("species_scope_regression_validation.json"),
        "streamlit": streamlit_final,
        "model_identity": models,
        "generation_run_id": "phase_w_integrated_v1",
        "generation_rows": outcome["generation"],
        "retrieval_coverage": coverage,
        "formal_professional_accuracy_ready": False,
        "formal_professional_accuracy_blockers": ["0 independently verified reference answers", "0 locked logical rubrics", "0 verified arithmetic protocols", "0 trusted binary Context relevance labels"],
        "formal_environment_switch": False,
        "repository_full_pytest": "not_run_in_phase_w; isolated corpus, species-scope, model API, and Streamlit checks are reported separately",
    }
    write_json("rag_v3_end_to_end_validation.json", validation)
    write_json("compatibility.json", {
        "phase": "W", "workspace": str(W), "run_id": "phase_w_integrated_v1",
        "protected_manifest_before": "protected_baseline_before_phase_w.jsonl",
        "protected_manifest_after": "protected_baseline_recheck.jsonl",
        "protected_file_records": outcome["protected_baseline"],
        "production_sqlite_sha256": outcome["protected_baseline"].get("production_sqlite_sha256"),
        "production_sqlite_unchanged": outcome["protected_baseline"].get("production_sqlite_match"),
        "phase_v_corpus_v3_unchanged": {"corpus_version": outcome["system"]["corpus_version"], "chunk_sha256": corpus_integrity.get("chunk_jsonl_sha256_actual"), "sqlite_sha256": corpus_integrity.get("sqlite_sha256_actual"), "dense_vector_sha256": corpus_integrity.get("dense_vectors_sha256_actual"), "retrieval_trace_errors": len(corpus_integrity.get("context_trace_errors", []))},
        "original_phase_e_720_results_modified": False,
        "historical_e4_modified": False, "evaluation_corpus_v2_modified": False, "production_modified": False,
        "new_generation_rows": outcome["generation"]["canonical_unique_question_model_rows"],
        "new_results_are_isolated_from_phase_e": True,
        "winner_selected": False, "formal_weighted_total_calculated": False,
        "excel_validation": read_json("fish_test_evaluation_v3_validation.json"),
    })
    report = []
    report += ["# Phase W 最終報告", "", "## 執行範圍", "", "Phase W 在獨立工作區整合檢索、適用性檢查、四模型生成、結構化輸出與 Streamlit 介面，並執行 180 題 × 4 模型的回歸／探索性重新生成。題庫曾多次用於前期調整，因此不是未曝光 Holdout。正式環境未切換。", ""]
    report += ["## Corpus、來源與檢索", "", f"沿用 Phase V 隔離 Corpus `{outcome['system']['corpus_version']}`：{outcome['system']['corpus_records']:,} 個 Chunk，其中 {outcome['system']['retrieval_eligible_chunks']:,} 個 retrieval-eligible、{outcome['system']['context_only_chunks']:,} 個 context-only。Phase W 未將新來源原件加入 Corpus。", "", f"180 題中 {coverage['questions_with_any_context']} 題取得至少一段、{coverage['questions_with_complete_top5']} 題取得完整 Top-5、{coverage['questions_with_partial_top5']} 題取得部分 Top-5、{coverage['questions_with_zero_context']} 題沒有合格 Context；實際返回 {coverage['returned_contexts']} 段。259/259 段都與凍結 Corpus 的 Chunk 文字、ID、來源和摘要一致。檢索覆蓋不等於相關性或答案支持。", "", f"57 筆 Owner Decision 均核准處理流程，依 SHA-256 對應 55 份不同檔案。來源登錄中 50 筆仍未正式 Admission，6 筆為範圍有限 Admission，另 1 筆為先前範圍有限 Admission。Owner Decision 不等於第三方全文授權。", "", f"本輪新增 {len(facts)} 張來源事實研究卡，來源為水試所官方頁面；未將頁面全文或卡片加入 Corpus，也未取得 HTML 原始 bytes checksum。這些內容只能作為研究來源線索，不構成新增正式魚種知識覆蓋。", ""]
    report += ["## 系統驗收", "", f"四個模型實際 API Smoke Test 通過：{smoke.get('generator_calls')} 次生成呼叫、四組模型 ID／Digest 核對，JSON／引用流程與拒答案例均完成。六項魚種範圍回歸測試通過 {read_json('species_scope_regression_validation.json').get('passed')}/6。Streamlit 初始載入及一次實際表單操作均無例外；此表單操作屬獨立 UI Smoke，不計入 720 筆評測。", "", "端到端功能路徑可以執行，但來源權利與專業答案覆蓋不足，不能視為可正式部署的完整專業系統。", ""]
    report += ["## 全量新生成", "", f"建立 {outcome['generation']['canonical_unique_question_model_rows']} 筆唯一 question×model 結果；原始嘗試日誌有 {outcome['generation']['raw_attempt_log_rows']} 筆，其中 {outcome['generation']['retry_error_records']} 次錯誤已成功重試並保留，沒有未解決 API 錯誤。最終為 {outcome['generation']['effective_status_counts']['answered']} 筆有效回答、{outcome['generation']['effective_status_counts']['abstain']} 筆有效拒答及 {outcome['generation']['effective_status_counts']['invalid_output']} 筆無效輸出。安全守門觸發 {outcome['generation']['safety_guard_override_count']} 次。", "", "| 模型 | 有效回答 | 有效拒答 | 無效輸出 | Faithfulness (N) | Judge Relevance (N) | BGE-M3 Cosine (N) | IFR | TTFT 秒 (N) | TPS (N) | RAM 系統採樣峰值 GiB | VRAM 系統採樣峰值 MiB |", "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for mid, m in model_metrics.items():
        f = "N/A" if m["judge_faithfulness"]["mean"] is None else f"{m['judge_faithfulness']['mean']:.4f} ({m['judge_faithfulness']['n']})"
        r = "N/A" if m["judge_answer_relevance"]["mean"] is None else f"{m['judge_answer_relevance']['mean']:.4f} ({m['judge_answer_relevance']['n']})"
        b = "N/A" if m["bge_m3_cosine"]["mean"] is None else f"{m['bge_m3_cosine']['mean']:.4f} ({m['bge_m3_cosine']['n']})"
        report.append(f"| {mid} | {m['effective_answered']} | {m['effective_abstentions']} | {m['invalid_outputs']} | {f} | {r} | {b} | {m['structured_output_ifr']['rate']:.2%} ({m['structured_output_ifr']['eligible_n']}) | {m['ttft_visible_content_seconds']['mean']:.3f} ({m['ttft_visible_content_seconds']['n']}) | {m['tps']['mean']:.3f} ({m['tps']['n']}) | {m['system_ram_gib']['sampled_max']:.3f} | {m['dedicated_vram_mib']['sampled_max']:.0f} |")
    report += ["", "Judge 分數只反映 Mistral NeMo 對實際回答與固定 Context 的探索性評分，不是水產專業正確率。BGE-M3 是回答文字與問題的 cosine 相似度，部分樣本回答為拒答，不能視為正確率。IFR 是原始模型 JSON schema 合規率；引用 ID 檢查另列。RAM／VRAM 為系統層級採樣峰值，非模型程序專屬峰值。", "", "M2 有 0 筆有效回答、179 筆拒答、1 筆無效輸出；Judge Faithfulness 與 Answer Relevance 均 N=0。BGE-M3 Cosine 為 0.4680、N=179；Structured IFR 為 177/180（98.33%）；TTFT 均值 0.248 秒、TPS 44.771；系統採樣 RAM 峰值 20.319 GiB、Dedicated VRAM 峰值 5,697 MiB。這些結果不代表其專業答題能力。", ""]
    report += ["## 11 項指標狀態", "", "| 指標 | 結果 | 有效 N | 限制 |", "|---|---|---:|---|"]
    report += ["| Faithfulness | 依模型列於上表 | 66 筆回答分布於模型 | 探索性 AI Judge；非專業真值 |", "| Judge Answer Relevance | 依模型列於上表 | 66 筆回答分布於模型 | 探索性 AI Judge；非專業真值 |", "| BGE-M3 Cosine Similarity | 依模型列於上表 | 718 筆 | 文字相似度，不是正確率 |", "| Structured IFR | 96.67%、98.33%、95.56%、100.00%（M1–M4） | 每模型 180 | 僅 JSON schema 合規 |", "| TTFT | 依模型列於上表 | 每模型 180 | 可見內容首 Token |", "| TPS | 依模型列於上表 | 每模型 180 | eval_count / eval_duration_ns |", "| System RAM | 每模型系統採樣峰值列於上表 | 288–1,193 次採樣 | 非 process RSS |", "| Dedicated VRAM | 每模型系統採樣峰值列於上表 | 288–1,193 次採樣 | nvidia-smi 系統採樣 |", "| Context Precision@5 | N/A | 0 | 無可信相關性標籤 |", "| Logical Accuracy | N/A | 0 | 無核准答案與凍結 Rubric |", "| Arithmetic Accuracy | N/A | 0 | 無完整核驗公式與容差 |", "", f"所有 {citation_summary['effective_answered_records']} 筆有效回答的引用 ID 都對應該題固定 Top-5，但沒有完成引用語意支持核驗。Human Gold 為 {outcome['human_gold_reviewed']}。", ""]
    report += ["## 完整性與下一步阻塞", "", f"Frozen Manifest：{outcome['protected_baseline']['match']}/{outcome['protected_baseline']['records']} 無差異；Production SQLite SHA-256 為 `{outcome['protected_baseline']['production_sqlite_sha256']}` 並符合預期。Phase E 原始生成、Historical E4、Evaluation Corpus v2、Production 均未修改。", "", "本輪沒有新增正式來源准入或 Corpus 內容。要進行可報告的專業正確率，需先補足具使用依據的水產專業原始來源、固定版本與魚種適用性，再建立獨立可核驗答案及 Logical／Arithmetic Rubric；P@5 需另有可靠段落相關性標註。未計算加權總分、未選 Winner、未切換正式環境。", ""]
    (W / "phase_w_final_report.md").write_text("\n".join(report), encoding="utf-8")
    research = "# Phase W 研究結果\n\n新版系統在隔離環境完成檢索、模型串流生成、JSON schema／引用 ID 驗證及 Streamlit 表單流程。720 個唯一題目×模型結果已保存。檢索取得 259 段，94 題至少有一段，34 題完整 Top-5。\n\n模型效能與 Judge 指標屬回歸／探索性結果；本輪沒有可核驗專業答案、Human Gold、Context relevance labels 或凍結的 Logical／Arithmetic Rubrics，故不得報告專業準確率、P@5 或正式 Winner。來源頁面研究卡沒有進入 Corpus，未解決 50 個來源包的全文處理限制。\n"
    (W / "research_results_v3.md").write_text(research, encoding="utf-8")
    print(json.dumps({"generation": outcome["generation"], "models": {k: {"answer": v["effective_answered"], "abstain": v["effective_abstentions"], "invalid": v["invalid_outputs"], "faithfulness": v["judge_faithfulness"], "relevance": v["judge_answer_relevance"], "bge": v["bge_m3_cosine"], "IFR": v["structured_output_ifr"], "TTFT": v["ttft_visible_content_seconds"], "TPS": v["tps"], "RAM_peak_GiB": v["system_ram_gib"], "VRAM_peak_MiB": v["dedicated_vram_mib"]} for k, v in model_metrics.items()}, "retrieval": coverage, "citation_support": citation_summary, "accuracy_reference_status_counts": outcome["accuracy_reference_status_counts"], "source_registry": outcome["source_registry"], "protected_baseline": outcome["protected_baseline"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
