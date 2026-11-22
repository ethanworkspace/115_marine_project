"""Protocol and context-window accounting for the Phase 15.3 run."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .ollama import GENERATION_OPTIONS
from .retry_v21 import readiness as base_readiness

MAX_OUTPUT_TOKENS = 1024
CONTEXT_LENGTH = 8192
MAX_ATTEMPTS = 2


def generation_options_v22() -> dict[str, Any]:
    options = dict(GENERATION_OPTIONS)
    if options.get("num_predict") != 768 or options.get("num_ctx") != CONTEXT_LENGTH:
        raise ValueError("The frozen Phase 15 generation options changed unexpectedly")
    options["num_predict"] = MAX_OUTPUT_TOKENS
    return options


def context_budget_audit(*, prompt_tokens: int | None, baseline_prompt_tokens: int | None,
                         context_length: int = CONTEXT_LENGTH,
                         configured_max_output_tokens: int = MAX_OUTPUT_TOKENS) -> dict[str, Any]:
    """Compare runtime prompt token count against the same frozen prompt in v2."""
    observed = int(prompt_tokens) if prompt_tokens is not None else None
    baseline = int(baseline_prompt_tokens) if baseline_prompt_tokens is not None else None
    detectable = observed is not None and baseline is not None
    return {
        "prompt_tokens": observed,
        "prompt_eval_count": observed,
        "baseline_same_input_prompt_tokens": baseline,
        "configured_max_output_tokens": int(configured_max_output_tokens),
        "context_length": int(context_length),
        "remaining_context_margin": context_length - observed - configured_max_output_tokens if observed is not None else None,
        "output_budget_fits_context_after_prompt": (observed + configured_max_output_tokens <= context_length) if observed is not None else None,
        "prompt_count_matches_frozen_same_input_baseline": observed == baseline if detectable else None,
        "input_truncated": observed < baseline if detectable else None,
        "input_truncation_detection": "prompt_eval_count compared with the same question/context/prompt count from the frozen v2 run; Ollama 0.35 has no /api/tokenize endpoint",
    }


def compare_v21_v22(v21: Mapping[str, Any], v22: Mapping[str, Any]) -> dict[str, Any]:
    keys = ("json_parse_rate", "schema_valid_rate", "citation_parse_rate", "strict_citation_validity_rate",
            "generation_error_count", "retry_trigger_count", "completion_truncation_count",
            "completion_truncation_first_pass_count", "completion_truncation_final_count")
    def selected(summary: Mapping[str, Any]) -> dict[str, Any]:
        return {key: summary.get(key) for key in keys if key in summary}
    old_retry = v21.get("retry_protocol") or {}
    new_retry = v22.get("retry_protocol") or {}
    old_trigger = old_retry.get("retry_trigger_count", v21.get("retry_trigger_count"))
    new_trigger = new_retry.get("retry_trigger_count", v22.get("retry_trigger_count"))
    def retry_rate(summary: Mapping[str, Any], trigger: int | None) -> float | None:
        return trigger / int(summary["question_count"]) if trigger is not None and summary.get("question_count") else None
    return {
        "comparison_type": "technical reliability after output-budget capacity change; no prompt semantics changed",
        "v2_1_max_output_tokens": 768,
        "v2_2_max_output_tokens": MAX_OUTPUT_TOKENS,
        "v2_1": selected(v21) | {"retry_trigger_count": old_trigger, "retry_rate": retry_rate(v21, old_trigger)},
        "v2_2": selected(v22) | {"retry_trigger_count": new_trigger, "retry_rate": retry_rate(v22, new_trigger)},
        "difference_claim": "descriptive reliability comparison only",
    }


def same_generation_config(g0_manifest: Mapping[str, Any], g1_manifest: Mapping[str, Any]) -> bool:
    fields = ("generator", "generation_parameters", "prompt_version", "prompt_sha256", "schema_sha256",
              "structured_output_mode", "retry_policy")
    return all(g0_manifest.get(field) == g1_manifest.get(field) for field in fields)


def previous_failure_recovery(*, question_id: str, v21_attempts: Sequence[Mapping[str, Any]],
                              v22_attempts: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    def project(row: Mapping[str, Any]) -> dict[str, Any]:
        result = row.get("result") or {}
        return {
            "attempt_number": row.get("attempt_number"),
            "done_reason": row.get("finish_reason"),
            "completion_tokens": row.get("completion_tokens"),
            "schema_valid": row.get("schema_status"),
            "answer_status": result.get("status"),
            "citation_parse_status": row.get("citation_parse_status"),
            "citation_count": result.get("citation_count"),
            "strict_citation_count": result.get("strict_citation_count"),
            "strict_citation_validity_rate": result.get("strict_citation_validity_rate"),
            "raw_output_sha256": row.get("raw_output_sha256"),
        }
    old = [project(row) for row in v21_attempts if str(row.get("question_id")) == question_id]
    new = [project(row) for row in v22_attempts if str(row.get("question_id")) == question_id]
    recovered = bool(new and any(row.get("schema_valid") for row in new)) and not any(row.get("schema_valid") for row in old)
    return {
        "question_id": question_id,
        "v2_1_attempts": old,
        "v2_2_attempts": new,
        "output_budget_recovery": recovered,
    }


def readiness_v22(*, g0_summary: Mapping[str, Any], g1_summary: Mapping[str, Any],
                  attempts_preserved: bool, budget_audits: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    ready = base_readiness(g0_summary=g0_summary, g1_summary=g1_summary,
                           all_raw_attempts_preserved=attempts_preserved)
    audits_by_condition: dict[str, list[Mapping[str, Any]]] = {"G0": [], "G1": []}
    for row in budget_audits:
        condition = str(row.get("condition") or "")
        if condition in audits_by_condition:
            audits_by_condition[condition].append(row)
    for condition, source_key, readiness_key in (("G0", "G0_v2", "G0_v2_2"), ("G1", "G1_v2_1", "G1_v2_2")):
        rows = audits_by_condition[condition]
        detected = sum(row.get("input_truncated") is True for row in rows)
        unknown = sum(row.get("input_truncated") is None for row in rows)
        complete = bool(rows) and unknown == 0
        check = complete and detected == 0
        condition_row = ready["conditions"].get(readiness_key)
        if condition_row is None:
            condition_row = ready["conditions"].get(source_key)
            if condition_row is not None:
                ready["conditions"][readiness_key] = condition_row
                del ready["conditions"][source_key]
        if condition_row is not None:
            condition_row["checks"]["input_truncation_absent_and_audited"] = check
            condition_row["checks"]["context_budget_margin_nonnegative"] = all(
                row.get("remaining_context_margin") is not None and row["remaining_context_margin"] >= 0 for row in rows
            )
            condition_row["ready"] = all(condition_row["checks"].values())
            condition_row["context_window_audit"] = {
                "questions_audited": len(rows), "input_truncation_detected": detected,
                "input_truncation_unknown": unknown,
                "minimum_remaining_context_margin": min((row["remaining_context_margin"] for row in rows
                    if row.get("remaining_context_margin") is not None), default=None),
            }
    ready["phase16_generation_ready"] = bool(ready["conditions"]) and all(row["ready"] for row in ready["conditions"].values())
    ready["gates"]["input_truncation"] = 0
    ready["gates"]["context_budget_margin_nonnegative"] = True
    return ready


def build_ragas_row_v22(*, question: Mapping[str, Any], answer: str,
                        contexts: Sequence[Mapping[str, Any]], condition: str,
                        model: str, attempts: int, ready: bool) -> dict[str, Any]:
    if not ready:
        raise ValueError("RAGAS export requires all v2.2 generation readiness gates to pass")
    condition_label = {"G0": "oracle", "G1": "e4_top5"}.get(condition)
    if condition_label is None:
        raise ValueError(f"Unknown generation condition: {condition}")
    return {
        "question_id": str(question["question_id"]), "question": str(question["question"]),
        "answer": answer, "contexts": [str(row["text"]) for row in contexts],
        "reference_answer": str(question.get("reference_answer") or ""),
        "condition": condition_label, "benchmark_type": "silver", "silver_reference": True,
        "retrieval_pipeline": "E4", "generation_protocol": "v2.2", "model": model,
        "generation_attempts": int(attempts),
    }
