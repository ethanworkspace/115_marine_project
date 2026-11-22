"""Small, deterministic helpers for the Phase 15.2 technical retry protocol."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .protocol_v2 import sha256_text

MAX_ATTEMPTS = 2


def attempt_is_valid(result: Mapping[str, Any]) -> bool:
    """A model attempt is accepted only when parsing and v2 schema validation pass."""
    return bool(
        result.get("json_parse_valid")
        and result.get("schema_valid")
        and result.get("status_valid")
        and not result.get("execution_error")
    )


def should_retry(result: Mapping[str, Any], *, attempt_number: int) -> bool:
    """Permit one fresh call after technical failure; never loop until success."""
    return attempt_number < MAX_ATTEMPTS and not attempt_is_valid(result)


def build_attempt_record(
    *, question_id: str, attempt_number: int, result: Mapping[str, Any], raw: Mapping[str, Any]
) -> dict[str, Any]:
    raw_output = str(raw.get("raw_output") or "")
    raw_hash = sha256_text(raw_output)
    raw_row_hash = raw.get("raw_output_sha256")
    validity_input = dict(result)
    validity_input["execution_error"] = raw.get("execution_error")
    valid = attempt_is_valid(validity_input)
    return {
        "question_id": str(question_id),
        "attempt_number": int(attempt_number),
        "attempt_valid": valid,
        "raw_output": raw_output,
        "raw_output_sha256": raw_hash,
        "raw_output_hash_matches_client": raw_row_hash in (None, raw_hash),
        "raw_output_preserved": True,
        "json_parse_status": bool(result.get("json_parse_valid")),
        "schema_status": bool(result.get("schema_valid")),
        "citation_parse_status": bool(result.get("citation_parse_valid")),
        "parse_error": raw.get("parse_error"),
        "schema_error": raw.get("validation_error"),
        "execution_error": raw.get("execution_error"),
        "error_message": raw.get("execution_error") or raw.get("parse_error")
        or raw.get("validation_error"),
        "generation_latency_seconds": result.get("latency_seconds"),
        "prompt_tokens": result.get("prompt_tokens"),
        "completion_tokens": result.get("completion_tokens"),
        "finish_reason": result.get("done_reason"),
        "result": dict(result),
    }


def first_pass_metrics(attempts: Sequence[Mapping[str, Any]], *, question_count: int) -> dict[str, Any]:
    first = [row for row in attempts if int(row.get("attempt_number", 0)) == 1]
    denominator = question_count
    if len(first) != denominator:
        raise ValueError(f"Expected one first attempt per question; found {len(first)} for {denominator} questions")
    return {
        "question_count": denominator,
        "first_pass_json_valid_count": sum(bool(row.get("json_parse_status")) for row in first),
        "first_pass_json_valid_rate": sum(bool(row.get("json_parse_status")) for row in first) / denominator if denominator else None,
        "first_pass_schema_valid_count": sum(bool(row.get("schema_status")) for row in first),
        "first_pass_schema_valid_rate": sum(bool(row.get("schema_status")) for row in first) / denominator if denominator else None,
        "first_pass_citation_parse_count": sum(bool(row.get("citation_parse_status")) for row in first),
        "first_pass_citation_parse_rate": sum(bool(row.get("citation_parse_status")) for row in first) / denominator if denominator else None,
        "first_pass_valid_count": sum(bool(row.get("attempt_valid")) for row in first),
    }


def classify_failure(
    *, raw_output: str, parse_error: str | None, schema_error: Any,
    execution_error: str | None, finish_reason: str | None,
) -> str:
    """Classify a technical failure without repairing or changing the model output."""
    if execution_error:
        lowered = execution_error.casefold()
        if raw_output and not finish_reason or any(token in lowered for token in ("stream", "connection", "timeout", "incomplete")):
            return "stream_interrupted"
        return "runtime_error"
    if parse_error:
        if finish_reason == "length":
            return "truncated_json"
        if "Extra data" in parse_error or "trailing" in parse_error.casefold():
            return "extra_text"
        return "malformed_json"
    if schema_error:
        return "schema_violation"
    return "unknown"


def retry_impact(first: Mapping[str, Any], final: Mapping[str, Any]) -> dict[str, Any]:
    first_result = first.get("result") or {}
    final_result = final.get("result") or {}
    first_parsed = bool(first_result.get("json_parse_valid"))
    final_parsed = bool(final_result.get("json_parse_valid"))
    first_citations = set(map(str, first_result.get("citations") or []))
    final_citations = set(map(str, final_result.get("citations") or []))
    from .protocol_v2 import jaccard, normalized_answer_similarity

    first_answer = str(first_result.get("answer") or "")
    final_answer = str(final_result.get("answer") or "")
    retry_used = int(final.get("attempt_number", 1)) > 1
    first_valid = bool(first.get("attempt_valid", attempt_is_valid(first_result)))
    final_valid = bool(final.get("attempt_valid", attempt_is_valid(final_result)))
    return {
        "question_id": str(first.get("question_id")),
        "attempt_1_valid": first_valid,
        "attempt_2_used": retry_used,
        "attempt_2_valid": final_valid if retry_used else None,
        "technical_retry_recovery": retry_used and not first_valid and final_valid,
        "final_attempt_failed": retry_used and not final_valid,
        "attempt_1_status": first_result.get("status"),
        "final_status": final_result.get("status"),
        "status_changed": first_result.get("status") != final_result.get("status"),
        "answer_similarity": normalized_answer_similarity(first_answer, final_answer) if first_parsed and final_parsed else None,
        "citation_set_changed": first_citations != final_citations if first_parsed and final_parsed else None,
        "citation_set_jaccard": jaccard(first_citations, final_citations) if first_parsed and final_parsed else None,
        "attempt_1_completion_tokens": first.get("completion_tokens"),
        "final_completion_tokens": final.get("completion_tokens"),
        "completion_token_change": (
            int(final["completion_tokens"]) - int(first["completion_tokens"])
            if final.get("completion_tokens") is not None and first.get("completion_tokens") is not None else None
        ),
        "attempt_1_latency_seconds": first.get("generation_latency_seconds"),
        "retry_latency_seconds": final.get("generation_latency_seconds") if retry_used else 0.0,
        "latency_overhead_seconds": final.get("generation_latency_seconds") if retry_used else 0.0,
    }


def validate_attempt_records(attempts: Sequence[Mapping[str, Any]], *, question_ids: Sequence[str]) -> None:
    keys = [(str(row.get("question_id")), int(row.get("attempt_number", 0))) for row in attempts]
    if len(keys) != len(set(keys)):
        raise ValueError("Attempt records contain duplicate question/attempt keys")
    allowed = set(map(str, question_ids))
    if any(qid not in allowed for qid, _ in keys):
        raise ValueError("Attempt records contain an unknown question_id")
    by_question: dict[str, list[int]] = {}
    for qid, number in keys:
        by_question.setdefault(qid, []).append(number)
        if number not in (1, 2):
            raise ValueError(f"Attempt limit exceeded for {qid}: {number}")
    missing = allowed - set(by_question)
    if missing:
        raise ValueError(f"Missing generation attempts for {len(missing)} questions")
    for qid, numbers in by_question.items():
        ordered = sorted(numbers)
        if ordered[0] != 1 or ordered not in ([1], [1, 2]):
            raise ValueError(f"Invalid retry sequence for {qid}: {ordered}")
        first = next(row for row in attempts if str(row.get("question_id")) == qid and int(row.get("attempt_number")) == 1)
        if len(ordered) == 2 and bool(first.get("attempt_valid", attempt_is_valid(first.get("result") or {}))):
            raise ValueError(f"Successful first attempt must not be retried: {qid}")


def readiness(*, g0_summary: Mapping[str, Any], g1_summary: Mapping[str, Any],
              all_raw_attempts_preserved: bool) -> dict[str, Any]:
    conditions: dict[str, dict[str, Any]] = {}
    for label, summary in (("G0_v2", g0_summary), ("G1_v2_1", g1_summary)):
        taxonomy = summary.get("citation_error_taxonomy") or {}
        checks = {
            "raw_output_preservation_100_percent": all_raw_attempts_preserved
            if label == "G1_v2_1" else summary.get("raw_output_preservation_rate") == 1.0,
            "schema_valid_at_least_99_percent": float(summary.get("schema_valid_rate") or 0) >= 0.99,
            "citation_parse_at_least_99_percent": float(summary.get("citation_parse_rate") or 0) >= 0.99,
            "strict_citation_validity_at_least_95_percent": float(summary.get("strict_citation_validity_rate") or 0) >= 0.95,
            "no_systematic_chunk_id_context_id_confusion": int(taxonomy.get("chunk_id_in_context", 0)) == 0,
        }
        conditions[label] = {"checks": checks, "ready": all(checks.values()), "metrics": {
            "raw_output_preservation_rate": (1.0 if all_raw_attempts_preserved else 0.0)
            if label == "G1_v2_1" else summary.get("raw_output_preservation_rate"),
            "schema_valid_rate": summary.get("schema_valid_rate"),
            "citation_parse_rate": summary.get("citation_parse_rate"),
            "strict_citation_validity_rate": summary.get("strict_citation_validity_rate"),
            "chunk_id_in_context_count": taxonomy.get("chunk_id_in_context", 0),
        }}
    return {
        "phase16_generation_ready": bool(conditions) and all(row["ready"] for row in conditions.values()),
        "conditions": conditions,
        "gates": {"raw_output_preservation": 1.0, "schema_valid_rate_min": 0.99,
                  "citation_parse_rate_min": 0.99, "strict_citation_validity_min": 0.95,
                  "no_systematic_citation_field_confusion": True},
        "ragas_executed": False,
        "interpretation": "Technical readiness only; not expert answer correctness.",
    }


def build_ragas_export_row(*, question: Mapping[str, Any], answer: str, contexts: Sequence[Mapping[str, Any]],
                           attempts: int, final_output_source: str, ready: bool) -> dict[str, Any]:
    if not ready:
        raise ValueError("RAGAS export is disabled until Phase 16 generation readiness passes")
    return {
        "question_id": str(question["question_id"]),
        "question": str(question["question"]),
        "answer": answer,
        "contexts": [str(row["text"]) for row in contexts],
        "reference_answer": str(question.get("reference_answer") or ""),
        "benchmark_type": "silver",
        "silver_reference": True,
        "retrieval_pipeline": "E4",
        "generation_protocol": "v2.1",
        "generation_attempts": attempts,
        "final_output_source": final_output_source,
    }
