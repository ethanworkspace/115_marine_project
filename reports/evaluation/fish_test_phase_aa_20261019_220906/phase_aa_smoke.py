from __future__ import annotations

import hashlib
import json
import sys
import traceback
from collections import Counter
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE))
import phase_aa_runtime as runtime


def jload(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def jlines(path: Path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]


def dump(path: Path, obj: Any):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def append_jsonl(path: Path, row: dict[str, Any]):
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def main():
    test_set = jlines(HERE / "independent_test_set.jsonl")
    answerable = [row for row in test_set if row.get("source_card_chunk_id")]
    retrieval_path = HERE / "retrieval_independent_cases.jsonl"
    if retrieval_path.exists():
        retrieval_path.unlink()
    retrievals: dict[str, dict[str, Any]] = {}
    identity_results = {}
    identity_errors = {}
    for model_id in runtime.MODEL_TABLE:
        try:
            identity_results[model_id] = runtime.check_model_identity(model_id)
        except Exception as exc:
            identity_errors[model_id] = f"{type(exc).__name__}: {exc}"
    for case in answerable:
        record = {"test_id": case["test_id"], "question_id": case["question_id"], "status": "ERROR"}
        try:
            result = runtime.retrieve(case["question_text"], case["target_species"], top_k=5)
            retrievals[case["test_id"]] = result
            present = any(r["chunk_id"] == case["source_card_chunk_id"] for r in result["reranked_top"])
            record.update({"status": "PASS" if present else "TARGET_EVIDENCE_NOT_IN_TOP5", "target_card_id": case["source_card_chunk_id"],
                           "target_card_in_reranked_top5": present, "candidate_counts": result["candidate_counts"],
                           "reranked_top": result["reranked_top"], "retrieval_configuration": result["retrieval_config"],
                           "corpus_id": result["corpus_id"], "database_sha256": result["database_sha256"]})
        except Exception as exc:
            record.update({"status": "ERROR", "error": f"{type(exc).__name__}: {exc}", "traceback": traceback.format_exc()})
        append_jsonl(retrieval_path, record)

    generator_path = HERE / "real_generator_smoke_results.jsonl"
    if generator_path.exists():
        generator_path.unlink()
    # All four generators see the same retrieved context for the same item.
    positive_case = next((x for x in answerable if x["test_id"] == "AA-NEW-EEL-TEMP-01"), None)
    generation_rows = []
    if positive_case and positive_case["test_id"] in retrievals:
        trace = retrievals[positive_case["test_id"]]
        spans = runtime.spans_from_retrieval(trace)
        profile = runtime.profile_for_case(positive_case, spans)
        expected_linked = "span-" + positive_case["source_card_chunk_id"]
        for model_id in runtime.MODEL_TABLE:
            try:
                row = runtime.run_generator(profile, spans, model_id, positive_case["test_id"], trace)
                row["expected_card_retrieved"] = any(s.span_id == expected_linked for s in spans)
            except Exception as exc:
                row = {"test_id": positive_case["test_id"], "model_id": model_id, "generator_called": False,
                       "status": "GENERATOR_CALL_ERROR", "error": f"{type(exc).__name__}: {exc}", "traceback": traceback.format_exc(),
                       "corpus_id": "research_fact_card_corpus_aa_v1", "formal_corpus": False}
            generation_rows.append(row)
            append_jsonl(generator_path, row)

    # Extra M2 direct-answer opportunities on other verified low-risk cards.
    m2_cases = [x for x in answerable if x["test_id"] in {"AA-NEW-GROUPER-DEPTH-01", "AA-NEW-MULLET-TEMP-01"}]
    for case in m2_cases:
        trace = retrievals.get(case["test_id"])
        if not trace:
            continue
        spans = runtime.spans_from_retrieval(trace)
        profile = runtime.profile_for_case(case, spans)
        try:
            row = runtime.run_generator(profile, spans, "M2", case["test_id"], trace)
        except Exception as exc:
            row = {"test_id": case["test_id"], "model_id": "M2", "generator_called": False, "status": "GENERATOR_CALL_ERROR", "error": f"{type(exc).__name__}: {exc}"}
        generation_rows.append(row)
        append_jsonl(generator_path, row)

    # Safety-path tests are deterministic system gate tests; no generator is called.
    safety_rows = []
    eel_trace = retrievals.get("AA-NEW-EEL-TEMP-01")
    if eel_trace:
        eel_spans = runtime.spans_from_retrieval(eel_trace)
        eel_temp_id = "span-aa-eel-eel-2006-temp"
        eel_temp_span = [span for span in eel_spans if span.span_id == eel_temp_id]
        wrong_species_profile = {"question_id": "AA-NEG-SPECIES-CONFLICT-01", "question_text": "請將白鰻20–30°C數值套用到吳郭魚。", "target_species": "吳郭魚", "category": "Water Quality", "risk_class": "LOW_RISK_FACT", "species_applicability": {"status": "VERIFIED_EXACT", "basis": "negative regression"}, "required_answer_elements": [{"element_id": "wrong_species_value", "required": True, "required_literals": ["20", "30"], "evidence_span_ids": [eel_temp_id]}]}
        wrong = runtime.ENGINE.assess_evidence(wrong_species_profile, eel_temp_span)
        safety_rows.append({"test_id": "AA-NEG-SPECIES-CONFLICT-01", "expected": "SOURCE_INAPPLICABLE", "actual": wrong.get("state"), "pass": wrong.get("state") == "SOURCE_INAPPLICABLE", "generator_called": False})
    no_evidence_profile = {"question_id": "AA-NEG-NO-CONTEXT-01", "question_text": "提供未核實的藥物劑量及停藥期。", "target_species": "未指定", "category": "Medication/Law", "risk_class": "MEDICATION", "high_risk_authority_verified": False, "species_applicability": {"status": "UNKNOWN"}, "required_answer_elements": []}
    no_context = runtime.ENGINE.assess_evidence(no_evidence_profile, [])
    safety_rows.append({"test_id": "AA-NEG-NO-CONTEXT-01", "expected": "HIGH_RISK_SOURCE_UNVERIFIED", "actual": no_context.get("state"), "pass": no_context.get("state") == "HIGH_RISK_SOURCE_UNVERIFIED", "generator_called": False})
    no_top = runtime.ENGINE.assess_evidence({**no_evidence_profile, "risk_class": "LOW_RISK_FACT"}, [])
    safety_rows.append({"test_id": "AA-NEG-NO-EVIDENCE-LOW-RISK", "expected": "EVIDENCE_INSUFFICIENT", "actual": no_top.get("state"), "pass": no_top.get("state") == "EVIDENCE_INSUFFICIENT", "generator_called": False})

    app_test = {"status": "PENDING", "detail": "AppTest run separately after generator smoke."}
    valid_outputs = 0
    direct_model_answer = 0
    fallback_answers = 0
    model_calls_ok = 0
    for row in generation_rows:
        if row.get("generator_called"):
            model_calls_ok += 1
            final = row.get("final_response") or {}
            if final.get("status") == "answered" and final.get("citations"):
                valid_outputs += 1
            if row.get("answer_origin") == "MODEL_GENERATED":
                direct_model_answer += 1
            if row.get("answer_origin") == "DETERMINISTIC_EVIDENCE_EXTRACTION":
                fallback_answers += 1
    summary = {
        "phase": "AA",
        "created_at_utc": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
        "corpus": "research_fact_card_corpus_aa_v1; research-only; not formal Corpus v3",
        "model_identity": identity_results,
        "model_identity_errors": identity_errors,
        "retrieval_test_records": len(answerable),
        "retrieval_target_evidence_hit_top5": sum(1 for x in jlines(retrieval_path) if x.get("target_card_in_reranked_top5")),
        "retrieval_status_counts": dict(Counter(x["status"] for x in jlines(retrieval_path))),
        "generator_calls_completed": model_calls_ok,
        "generator_output_answer_with_citation": valid_outputs,
        "direct_model_generated_answers": direct_model_answer,
        "deterministic_system_extractions": fallback_answers,
        "generator_rows": len(generation_rows),
        "safety_gate_tests": safety_rows,
        "safety_gate_all_pass": all(x["pass"] for x in safety_rows),
        "streamlit_apptest": app_test,
        "human_gold": 0,
        "formal_corpus": False,
    }
    dump(HERE / "rag_integrated_e2e_validation.json", summary)
    dump(HERE / "safety_gate_validation.json", {"cases": safety_rows, "passed": sum(x["pass"] for x in safety_rows), "total": len(safety_rows)})
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
