"""Deterministic output, citation, similarity, numeric, and attribution checks."""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from typing import Any


def validate_model_output(parsed: Any, question_id: str) -> tuple[bool, list[str]]:
    errors: list[str] = []
    if not isinstance(parsed, dict):
        return False, ["output_not_object"]
    required = {"question_id", "status", "answer", "citations"}
    if set(parsed) != required:
        errors.append("schema_fields_mismatch")
    if parsed.get("question_id") != question_id:
        errors.append("question_id_mismatch")
    if parsed.get("status") not in {"answered", "insufficient_evidence"}:
        errors.append("invalid_status")
    if not isinstance(parsed.get("answer"), str):
        errors.append("answer_not_string")
    elif parsed.get("status") == "answered" and not parsed["answer"].strip():
        errors.append("answered_with_empty_answer")
    if not isinstance(parsed.get("citations"), list):
        errors.append("citations_not_list")
    else:
        for citation in parsed["citations"]:
            if (not isinstance(citation, dict) or set(citation) != {"context_id", "chunk_id", "document_id", "page"}
                    or not isinstance(citation.get("context_id"), str)
                    or not isinstance(citation.get("chunk_id"), str)
                    or not isinstance(citation.get("document_id"), str)
                    or not isinstance(citation.get("page"), int)):
                errors.append("invalid_citation_shape")
    return not errors, errors


def normalize_citations(parsed: dict[str, Any], contexts: list[dict[str, Any]]) -> dict[str, Any]:
    context_by_id = {str(row["context_id"]): row for row in contexts}
    citations: list[dict[str, Any]] = []
    invalid_context_ids: list[str] = []
    for raw in parsed.get("citations") if isinstance(parsed.get("citations"), list) else []:
        if not isinstance(raw, dict):
            invalid_context_ids.append("<invalid-shape>")
            continue
        context_id = str(raw.get("context_id") or "")
        context = context_by_id.get(context_id)
        if context is None:
            invalid_context_ids.append(context_id or "<empty>")
            citations.append({**raw, "valid": False})
            continue
        matches = (
            str(raw.get("chunk_id")) == str(context["chunk_id"])
            and str(raw.get("document_id")) == str(context["document_id"])
            and raw.get("page") == context["page"]
        )
        if not matches:
            invalid_context_ids.append(context_id)
        citations.append({**raw, "valid": matches})
    valid_count = sum(1 for row in citations if row["valid"])
    return {
        "citations": citations,
        "invalid_context_ids": invalid_context_ids,
        "citation_total": len(citations),
        "citation_valid_count": valid_count,
        "citation_validity_rate": valid_count / len(citations) if citations else None,
        "has_citation": bool(citations),
        "missing_citation": parsed.get("status") == "answered" and not citations,
        "hallucinated_citation_count": len(invalid_context_ids),
        "out_of_context_citation_count": len(invalid_context_ids),
    }


def evidence_citation_recall(parsed: dict[str, Any], contexts: list[dict[str, Any]],
                             required_chunk_ids: list[str]) -> dict[str, Any]:
    present = {str(row["chunk_id"]) for row in contexts}
    available = set(map(str, required_chunk_ids)) & present
    context_by_id = {str(row["context_id"]): row for row in contexts}
    normalized = normalize_citations(parsed, contexts)
    cited_chunks = {
        str(citation["chunk_id"])
        for citation in normalized["citations"]
        if citation.get("valid") and str(citation.get("context_id")) in context_by_id
    }
    cited_required = available & cited_chunks
    return {
        "required_chunks_total": len(required_chunk_ids),
        "required_chunks_in_context": len(available),
        "required_chunks_cited": len(cited_required),
        "required_evidence_citation_recall": len(cited_required) / len(available) if available else None,
        "question_required_evidence_cited": bool(cited_required) if available else None,
        "all_available_required_evidence_cited": available <= cited_chunks if available else None,
        "cited_required_chunk_ids": sorted(cited_required),
        "available_required_chunk_ids": sorted(available),
    }


def _comparison_tokens(text: str) -> list[str]:
    tokens: list[str] = []
    for match in re.finditer(r"[a-z0-9]+(?:[./_%+\-][a-z0-9]+)*|[\u3400-\u9fff]", str(text or "").casefold()):
        tokens.append(match.group(0))
    return tokens


def silver_reference_similarity(answer: str, reference: str) -> dict[str, float | None]:
    predicted = Counter(_comparison_tokens(answer))
    expected = Counter(_comparison_tokens(reference))
    overlap = sum((predicted & expected).values())
    p = overlap / sum(predicted.values()) if predicted else 0.0
    r = overlap / sum(expected.values()) if expected else 0.0
    return {"precision": p, "recall": r, "f1": 2 * p * r / (p + r) if p + r else 0.0}


def _number_values(text: str) -> list[float]:
    values: list[float] = []
    for match in re.finditer(r"(?<![\w.])-?\d+(?:\.\d+)?", text.replace(",", "")):
        try:
            values.append(float(match.group(0)))
        except ValueError:
            pass
    return values


def calculation_numeric_evaluation(answer: str, calculation_spec: dict[str, Any] | None,
                                   *, absolute_tolerance: float = 1e-6,
                                   relative_tolerance: float = 1e-6) -> dict[str, Any] | None:
    if not calculation_spec:
        return None
    formula = calculation_spec.get("formula")
    biomass = calculation_spec.get("biomass_kg")
    rate_range = calculation_spec.get("rate_percent")
    expected = calculation_spec.get("result_kg")
    if formula != "biomass_kg * rate_percent / 100" or not isinstance(biomass, (int, float)):
        return {"status": "unsupported_spec", "exact_numeric_match": None}
    if not isinstance(rate_range, list) or len(rate_range) != 2 or not isinstance(expected, list) or len(expected) != 2:
        return {"status": "unsupported_spec", "exact_numeric_match": None}
    recomputed = [float(biomass) * float(rate) / 100.0 for rate in rate_range]
    if any(not math.isclose(left, float(right), rel_tol=1e-12, abs_tol=1e-12) for left, right in zip(recomputed, expected)):
        return {"status": "spec_validation_failed", "exact_numeric_match": None}
    candidates = [number for number in _number_values(answer) if not math.isclose(number, float(biomass), abs_tol=absolute_tolerance)]
    errors = []
    matched: list[float | None] = []
    for target in map(float, expected):
        nearest = min(candidates, key=lambda candidate: abs(candidate - target), default=None)
        matched.append(nearest)
        errors.append(abs(nearest - target) if nearest is not None else None)
    exact = all(
        observed is not None and math.isclose(observed, float(target), rel_tol=relative_tolerance, abs_tol=absolute_tolerance)
        for observed, target in zip(matched, expected)
    )
    relative_errors = [abs_err / abs(float(target)) if abs_err is not None and float(target) else abs_err
                       for abs_err, target in zip(errors, expected)]
    return {
        "status": "evaluated",
        "formula": formula,
        "biomass_kg": float(biomass),
        "expected_result_kg": list(map(float, expected)),
        "observed_numeric_values": candidates,
        "matched_values": matched,
        "absolute_errors": errors,
        "relative_errors": relative_errors,
        "absolute_tolerance": absolute_tolerance,
        "relative_tolerance": relative_tolerance,
        "exact_numeric_match": exact,
    }


def determine_failures(*, condition: str, schema_valid: bool, status: str | None,
                       required_in_context: bool, citation_summary: dict[str, Any],
                       numeric: dict[str, Any] | None) -> list[str]:
    failures: list[str] = []
    if condition == "G1" and not required_in_context:
        failures.append("retrieval_miss")
    if not schema_valid:
        failures.append("invalid_output")
    if condition == "G1" and not required_in_context and status == "answered":
        failures.append("answered_without_required_evidence")
    if required_in_context and status == "insufficient_evidence":
        failures.append("possible_false_abstention")
    if condition == "G1" and required_in_context and (not schema_valid or status == "insufficient_evidence"):
        failures.append("generation_failure_after_retrieval_hit")
    if condition == "G0" and (not schema_valid or status == "insufficient_evidence"):
        failures.append("generation_failure_with_oracle_evidence")
    if citation_summary.get("hallucinated_citation_count", 0):
        failures.append("invalid_citation")
    if citation_summary.get("missing_citation"):
        failures.append("missing_required_citation")
    if numeric and numeric.get("status") == "evaluated" and numeric.get("exact_numeric_match") is False:
        failures.append("numeric_error")
    return failures


def summarize_outputs(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(rows)
    valid_json = sum(bool(row.get("json_parse_valid")) for row in rows)
    valid_schema = sum(bool(row.get("schema_valid")) for row in rows)
    citation_parse = sum(bool(row.get("citation_parse_valid")) for row in rows)
    answered = sum(row.get("status") == "answered" for row in rows)
    abstained = sum(row.get("status") == "insufficient_evidence" for row in rows)
    errors = sum(row.get("status") == "generation_error" for row in rows)
    cited_answers = sum(row.get("status") == "answered" and not row.get("missing_citation") for row in rows)
    citations = [citation for row in rows for citation in row.get("citations", [])]
    valid_citations = sum(bool(citation.get("valid")) for citation in citations)
    required_cite_values = [row.get("required_evidence_citation_recall") for row in rows
                            if row.get("required_evidence_citation_recall") is not None]
    required_question_values = [row.get("question_required_evidence_cited") for row in rows
                                if row.get("question_required_evidence_cited") is not None]
    answer_similarity = [row["silver_reference_similarity"]["f1"] for row in rows
                         if row.get("silver_reference_similarity") is not None]
    latency = [float(row["latency_seconds"]) for row in rows if row.get("latency_seconds") is not None]
    ttft = [float(row["ttft_seconds"]) for row in rows if row.get("ttft_seconds") is not None]
    tps = [float(row["tokens_per_second"]) for row in rows if row.get("tokens_per_second") is not None]
    prompt_tokens = [int(row["prompt_tokens"]) for row in rows if row.get("prompt_tokens") is not None]
    completion_tokens = [int(row["completion_tokens"]) for row in rows if row.get("completion_tokens") is not None]
    numeric_rows = [row["calculation_numeric_evaluation"] for row in rows
                    if row.get("calculation_numeric_evaluation") and row["calculation_numeric_evaluation"].get("status") == "evaluated"]
    required_chunks = sum(int(row.get("required_chunks_total", 0)) for row in rows)
    required_cited = sum(int(row.get("required_chunks_cited", 0)) for row in rows)
    return {
        "question_count": total,
        "json_valid_rate": valid_json / total if total else None,
        "schema_valid_rate": valid_schema / total if total else None,
        "answered_count": answered,
        "answered_rate": answered / total if total else None,
        "insufficient_evidence_count": abstained,
        "insufficient_evidence_rate": abstained / total if total else None,
        "generation_error_count": errors,
        "generation_error_rate": errors / total if total else None,
        "citation_parse_rate": citation_parse / total if total else None,
        "answered_with_citation_count": cited_answers,
        "answered_without_citation_count": sum(row.get("missing_citation", False) for row in rows),
        "citation_count": len(citations),
        "citation_validity_rate": valid_citations / len(citations) if citations else None,
        "hallucinated_citation_count": sum(int(row.get("hallucinated_citation_count", 0)) for row in rows),
        "out_of_context_citation_count": sum(int(row.get("out_of_context_citation_count", 0)) for row in rows),
        "missing_citation_count": sum(bool(row.get("missing_citation")) for row in rows),
        "required_evidence_citation_recall_chunk_level": required_cited / required_chunks if required_chunks else None,
        "required_evidence_citation_recall_question_level": (
            sum(bool(value) for value in required_question_values) / len(required_question_values)
            if required_question_values else None
        ),
        "required_evidence_citation_questions_scored": len(required_question_values),
        "silver_reference_similarity": {
            "metric": "normalized token overlap precision/recall/F1; CJK character unigrams and Latin/numeric terms",
            "f1_mean": sum(answer_similarity) / len(answer_similarity) if answer_similarity else None,
            "scored_answers": len(answer_similarity),
            "label": "Silver reference similarity; not human expert correctness",
        },
        "calculation_numeric_evaluation": {
            "scored_questions": len(numeric_rows),
            "exact_numeric_matches": sum(bool(row.get("exact_numeric_match")) for row in numeric_rows),
            "descriptive_accuracy": sum(bool(row.get("exact_numeric_match")) for row in numeric_rows) / len(numeric_rows) if numeric_rows else None,
            "label": "descriptive only; three Silver calculation questions",
        },
        "latency": {
            "total_generation_seconds": sum(latency) if latency else None,
            "generation_timing_sample_count": len(latency),
            "generation_timing_missing_count": total - len(latency),
            "generation_timing_coverage": len(latency) / total if total else None,
            "generation_seconds": _stats(latency),
            "ttft_seconds": _stats(ttft),
            "tokens_per_second": _stats(tps),
            "prompt_tokens": _stats(prompt_tokens),
            "completion_tokens": _stats(completion_tokens),
        },
    }


def _stats(values: list[float | int]) -> dict[str, float | int | None]:
    if not values:
        return {"count": 0, "mean": None, "median": None, "p95": None, "min": None, "max": None}
    ordered = sorted(values)
    index = max(0, math.ceil(0.95 * len(ordered)) - 1)
    return {
        "count": len(ordered),
        "mean": sum(ordered) / len(ordered),
        "median": (ordered[(len(ordered) - 1) // 2] + ordered[len(ordered) // 2]) / 2,
        "p95": ordered[index],
        "min": ordered[0],
        "max": ordered[-1],
    }


def grouped_summaries(rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        value = row.get(key)
        buckets[str(value) if value is not None else "unknown"].append(row)
    return {label: summarize_outputs(values) for label, values in sorted(buckets.items())}


def failure_distribution(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: Counter[str] = Counter(failure for row in rows for failure in (row.get("failure_attribution") or []))
    return dict(sorted(counts.items()))
