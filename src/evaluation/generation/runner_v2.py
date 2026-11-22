"""Phase 15.1: immutable v1 audit plus Generation Protocol v2 experiments."""

from __future__ import annotations

import hashlib
import json
import math
import statistics
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from .contexts import build_e4_top5_contexts, build_oracle_contexts
from .evaluation import calculation_numeric_evaluation, silver_reference_similarity
from .frozen import read_jsonl, sha256_file, validate_frozen_inputs
from .ollama import GENERATION_OPTIONS, OLLAMA_BASE_URL
from .protocol_v2 import (
    jaccard, normalized_answer_similarity, required_citation_recall,
    resolve_citations, sha256_text, validate_v2_output,
)
from .runner import _capture_protected, _preflight

ROOT = Path(__file__).resolve().parents[3]
OUT = Path("reports/evaluation/generation")
AUDIT = OUT / "phase15_citation_recovery_audit"
CONDITIONS = {"G0": "G0_grounded_oracle_generation_v2", "G1": "G1_grounded_e4_top5_generation_v2"}
V1_CONDITIONS = {"G0": "G0_grounded_oracle_generation_v1", "G1": "G1_grounded_e4_top5_generation_v1"}
REPEAT_COUNT = 20
REPEAT_RUNS = 2


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    tmp.replace(path)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return read_jsonl(path) if path.exists() else []


def _stats(values: list[float | int | None]) -> dict[str, Any]:
    data = sorted(float(value) for value in values if value is not None and math.isfinite(float(value)))
    if not data:
        return {"count": 0, "mean": None, "median": None, "p95": None}
    pos = .95 * (len(data) - 1)
    lo, hi = math.floor(pos), math.ceil(pos)
    p95 = data[lo] if lo == hi else data[lo] + (data[hi] - data[lo]) * (pos - lo)
    return {"count": len(data), "mean": statistics.fmean(data), "median": statistics.median(data), "p95": p95}


def _capture_v1_files(root: Path) -> dict[str, dict[str, Any]]:
    paths = [
        OUT / "generation_retrieval_manifest.json", OUT / "phase15_summary.json", OUT / "compatibility.json",
        OUT / "G0_vs_G1_v1/comparison.json", OUT / "G0_vs_G1_v1/comparison_summary.md",
        OUT / "G0_vs_G1_v1/per_question_comparison.jsonl",
        Path("data/evaluation/generation/ragas_input_v1.jsonl"),
        Path("prompts/generation_v1.txt"), Path("schemas/generation_output.schema.json"),
    ]
    for folder in V1_CONDITIONS.values():
        paths.extend((root / OUT / folder).rglob("*"))
    result = {}
    for relative in paths:
        path = root / relative
        if path.is_file():
            stat = path.stat()
            result[path.relative_to(root).as_posix()] = {
                "sha256": sha256_file(path), "size": stat.st_size, "mtime_ns": stat.st_mtime_ns,
            }
    return result


def call_ollama_v2(*, model: str, system_prompt: str, user_prompt: str,
                   base_url: str = OLLAMA_BASE_URL, timeout: int = 900,
                   session: requests.Session | None = None) -> dict[str, Any]:
    """Accumulate a complete response body before attempting JSON parsing."""
    schema = json.loads((ROOT / "schemas/generation_output_v2.schema.json").read_text(encoding="utf-8"))
    body = {
        "model": model, "stream": True, "format": schema, "keep_alive": "30m",
        "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
        "options": dict(GENERATION_OPTIONS),
    }
    client = session or requests.Session()
    start = time.perf_counter()
    first_token: float | None = None
    parts: list[str] = []
    done: dict[str, Any] = {}
    execution_error: str | None = None
    try:
        with client.post(f"{base_url.rstrip('/')}/api/chat", json=body, timeout=timeout, stream=True) as response:
            response.raise_for_status()
            for raw_line in response.iter_lines(decode_unicode=True):
                if not raw_line:
                    continue
                try:
                    event = json.loads(raw_line)
                except json.JSONDecodeError as exc:
                    execution_error = f"stream_event_json_error: {exc}"
                    continue
                delta = (event.get("message") or {}).get("content") or ""
                if delta:
                    first_token = first_token if first_token is not None else time.perf_counter() - start
                    parts.append(str(delta))
                if event.get("done"):
                    done = event
    except Exception as exc:
        execution_error = f"{type(exc).__name__}: {exc}"
    raw_output = "".join(parts)
    parsed: Any = None
    parse_error: str | None = None
    if raw_output:
        try:
            parsed = json.loads(raw_output)
        except json.JSONDecodeError as exc:
            parse_error = f"{type(exc).__name__}: {exc}"
        if parse_error is None and not isinstance(parsed, dict):
            parse_error = "response_json_not_object"
    elif execution_error is None:
        execution_error = "Ollama returned no message content"
    return {
        "raw_output": raw_output,
        "raw_output_sha256": sha256_text(raw_output) if raw_output else None,
        "response_received": bool(raw_output),
        "parsed": parsed if isinstance(parsed, dict) else None,
        "parse_error": parse_error,
        "execution_error": execution_error,
        "latency_seconds": time.perf_counter() - start if raw_output else None,
        "ttft_seconds": first_token,
        "prompt_tokens": done.get("prompt_eval_count"),
        "completion_tokens": done.get("eval_count"),
        "tokens_per_second": done.get("eval_count") / (done.get("eval_duration", 0) / 1e9)
            if done.get("eval_count") is not None and done.get("eval_duration") else None,
        "load_duration_ns": done.get("load_duration"),
        "done_reason": done.get("done_reason"),
    }


def format_v2_user_prompt(question: dict[str, Any], contexts: list[dict[str, Any]]) -> str:
    evidence = "\n\n".join(f"[{row['context_id']}]\nEvidence:\n{row['text']}" for row in contexts)
    return (
        "以下是本題唯一可使用的 Evidence。若 Evidence 無法直接支持答案，請回答 insufficient_evidence。\n\n"
        f"{evidence}\n\n問題：{question['question']}\nquestion_id：{question['question_id']}"
    )


def _context_row(question_id: str, condition: str, contexts: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "question_id": question_id, "condition": condition,
        "contexts": [{
            "context_id": str(row["context_id"]), "chunk_id": str(row["chunk_id"]),
            "document_id": str(row["document_id"]), "page": int(row["page"]),
            "content_checksum": sha256_text(str(row["text"])), "retrieval_rank": row.get("rank"),
        } for row in contexts],
    }


def _write_context_manifests(root: Path, frozen: dict[str, Any]) -> dict[str, dict[str, list[dict[str, Any]]]]:
    contexts_by_condition: dict[str, dict[str, list[dict[str, Any]]]] = {"G0": {}, "G1": {}}
    for condition in ("G0", "G1"):
        v1_rows = {str(row["question_id"]): row for row in _read_jsonl(
            root / OUT / V1_CONDITIONS[condition] / "per_question.jsonl")}
        manifests = []
        for question in frozen["questions"]:
            qid = str(question["question_id"])
            contexts = build_oracle_contexts(question, frozen["corpus_by_id"]) if condition == "G0" else build_e4_top5_contexts(
                question, frozen["e4_trace_by_question"][qid], frozen["corpus_by_id"])
            old = v1_rows.get(qid)
            if not old or old.get("context_ids") != [x["context_id"] for x in contexts]:
                raise ValueError(f"{condition} context IDs differ from Phase 15 v1 for {qid}")
            if old.get("context_chunk_ids") != [x["chunk_id"] for x in contexts]:
                raise ValueError(f"{condition} chunks / E4 ranking differ from Phase 15 v1 for {qid}")
            contexts_by_condition[condition][qid] = contexts
            manifests.append(_context_row(qid, condition, contexts))
        out = root / OUT / CONDITIONS[condition] / "context_manifest.jsonl"
        if out.exists():
            if _read_jsonl(out) != manifests:
                raise ValueError(f"Existing {condition} context manifest does not match the frozen contexts")
        else:
            _write_jsonl(out, manifests)
    return contexts_by_condition


def _parse_v1(raw: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    parsed = raw.get("parsed_model_output")
    if isinstance(parsed, dict):
        return parsed, None
    text = raw.get("raw_output") or ""
    if not text:
        return None, raw.get("generation_error") or "v1 raw output unavailable"
    try:
        value = json.loads(text)
        return (value if isinstance(value, dict) else None), None
    except json.JSONDecodeError as exc:
        return None, f"{type(exc).__name__}: {exc}"


def _v1_forensic(root: Path, frozen: dict[str, Any], contexts: dict[str, dict[str, list[dict[str, Any]]]],
                 v1_hashes: dict[str, dict[str, Any]]) -> dict[str, Any]:
    citation_rows: list[dict[str, Any]] = []
    question_rows: dict[str, list[dict[str, Any]]] = {"G0": [], "G1": []}
    summaries = {}
    for condition in ("G0", "G1"):
        folder = root / OUT / V1_CONDITIONS[condition]
        raws = {str(row["question_id"]): row for row in _read_jsonl(folder / "raw_outputs.jsonl")}
        perq = {str(row["question_id"]): row for row in _read_jsonl(folder / "per_question.jsonl")}
        category_counts: Counter[str] = Counter()
        strict_total = recoverable_total = citation_total = 0
        req_counts = Counter()
        req_q = Counter()
        for question in frozen["questions"]:
            qid = str(question["question_id"])
            raw = raws[qid]
            parsed, parse_error = _parse_v1(raw)
            status = str(perq[qid].get("status") or "generation_error")
            citations = parsed.get("citations") if parsed else []
            if not isinstance(citations, list):
                citations = []
            resolved = resolve_citations(citations, contexts[condition][qid],
                                         corpus_chunk_ids=set(frozen["corpus_by_id"]), status=status)
            recall = required_citation_recall(required_chunk_ids=list(map(str, question.get("required_chunks") or [])),
                                              contexts=contexts[condition][qid], citations=resolved["citations"], status=status)
            available_required = set(map(str, question.get("required_chunks") or [])) & {
                str(context["chunk_id"]) for context in contexts[condition][qid]
            }
            citation_total += resolved["citation_count"]
            strict_total += resolved["strict_valid_count"]
            recoverable_total += resolved["recoverable_valid_count"]
            category_counts.update(resolved["error_taxonomy_counts"])
            req_counts["all_den"] += recall["required_chunk_count_all_questions"]
            req_counts["all_strict_num"] += recall["strict_cited_required_chunk_count"]
            req_counts["all_rec_num"] += recall["recoverable_cited_required_chunk_count"]
            req_counts["present_den"] += recall["required_chunk_count_present"]
            if recall["all_required_evidence_present"]:
                req_q["present"] += 1
                if status == "answered":
                    req_q["present_answered"] += 1
                    req_counts["present_answered_den"] += recall["required_chunk_count_present"]
            strict_present = {
                item.get("chunk_id") for item in resolved["citations"]
                if item.get("strict_valid") and item.get("chunk_id") in available_required
            }
            recoverable_present = {
                item.get("chunk_id") for item in resolved["citations"]
                if item.get("recoverable_valid") and item.get("chunk_id") in available_required
            }
            req_counts["present_strict_num"] += len(strict_present)
            req_counts["present_rec_num"] += len(recoverable_present)
            if status == "answered" and recall["all_required_evidence_present"]:
                req_counts["present_answered_strict_num"] += len(strict_present)
                req_counts["present_answered_rec_num"] += len(recoverable_present)
            for item in resolved["citations"]:
                citation_rows.append({"question_id": qid, "condition": condition, **item})
            question_rows[condition].append({
                "question_id": qid, "condition": condition, "status": status,
                "raw_output_available": bool(raw.get("raw_output")), "parse_error": parse_error,
                "citation_count": resolved["citation_count"],
                "strict_valid_count": resolved["strict_valid_count"],
                "recoverable_valid_count": resolved["recoverable_valid_count"],
                "citations": resolved["citations"], **recall,
            })
        summaries[condition] = {
            "question_count": len(question_rows[condition]),
            "citation_count": citation_total,
            "strict_valid_citation_count": strict_total,
            "recoverable_valid_citation_count": recoverable_total,
            "strict_citation_validity_rate": strict_total / citation_total if citation_total else None,
            "recoverable_citation_validity_rate": recoverable_total / citation_total if citation_total else None,
            "true_out_of_context_citation_count": category_counts["out_of_context_chunk_id"],
            "format_only_citation_error_count": category_counts["chunk_id_in_context"],
            "unresolvable_citation_count": sum(category_counts[key] for key in ("unknown_context_id", "out_of_context_chunk_id", "malformed_citation")),
            "missing_citation_count": category_counts["missing_citation"],
            "citation_error_taxonomy": dict(sorted(category_counts.items())),
            "required_evidence_citation_recall": {
                "denominator_all_questions": req_counts["all_den"],
                "strict_all_questions": req_counts["all_strict_num"] / req_counts["all_den"] if req_counts["all_den"] else None,
                "recoverable_all_questions": req_counts["all_rec_num"] / req_counts["all_den"] if req_counts["all_den"] else None,
                "denominator_evidence_present": req_counts["present_den"],
                "strict_evidence_present": req_counts["present_strict_num"] / req_counts["present_den"] if req_counts["present_den"] else None,
                "recoverable_evidence_present": req_counts["present_rec_num"] / req_counts["present_den"] if req_counts["present_den"] else None,
                "denominator_evidence_present_and_answered": req_counts["present_answered_den"],
                "strict_evidence_present_and_answered": req_counts["present_answered_strict_num"] / req_counts["present_answered_den"] if req_counts["present_answered_den"] else None,
                "recoverable_evidence_present_and_answered": req_counts["present_answered_rec_num"] / req_counts["present_answered_den"] if req_counts["present_answered_den"] else None,
            },
            "required_evidence_present_question_count": req_q["present"],
            "evidence_present_answered_question_count": req_q["present_answered"],
        }
    audit = {
        "audit_version": "phase15_citation_recovery_audit_v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "benchmark_type": "AI-generated Grounded Silver; not Human Gold",
        "phase15_v1_immutable": True,
        "phase15_v1_file_hashes_before": v1_hashes,
        "frozen_inputs": frozen["hashes"],
        "conditions": summaries,
        "citation_error_taxonomy": ["valid_context_id", "chunk_id_in_context", "unknown_context_id",
                                    "out_of_context_chunk_id", "malformed_citation", "missing_citation", "duplicate_citation"],
        "interpretation": "chunk_id_in_context is a recoverable format-only error, not a hallucinated citation. A corpus-known chunk absent from the question context is true out-of-context; unknown IDs are reported separately.",
    }
    _write_json(root / AUDIT / "v1_citation_reanalysis.json", audit)
    for condition in ("G0", "G1"):
        _write_jsonl(root / AUDIT / f"{condition.lower()}_per_question.jsonl", question_rows[condition])
    _write_jsonl(root / AUDIT / "per_citation.jsonl", citation_rows)
    return audit


def _run_one_v2(question: dict[str, Any], contexts: list[dict[str, Any]], *, condition: str,
                model: str, base_url: str, prompt: str, corpus_ids: set[str],
                call_fn: Any = None) -> tuple[dict[str, Any], dict[str, Any]]:
    qid = str(question["question_id"])
    generation_call = call_fn or call_ollama_v2
    call = generation_call(model=model, system_prompt=prompt,
                           user_prompt=format_v2_user_prompt(question, contexts), base_url=base_url)
    parsed = call["parsed"]
    validation_errors = validate_v2_output(parsed, qid) if parsed is not None and call["parse_error"] is None else []
    if call["parse_error"]:
        validation_errors.append("json_parse_failure")
    if call["execution_error"]:
        validation_errors.append("execution_failure")
    status_valid = bool(parsed and parsed.get("status") in {"answered", "insufficient_evidence"})
    effective_status = str(parsed.get("status")) if parsed is not None and not validation_errors else "generation_error"
    answer = str(parsed.get("answer") or "") if parsed else ""
    raw_citations = parsed.get("citations") if parsed else []
    resolved = resolve_citations(raw_citations, contexts, corpus_chunk_ids=corpus_ids,
                                 status=(str(parsed.get("status")) if parsed else effective_status))
    required_ids = list(map(str, question.get("required_chunks") or []))
    evidence_metrics = required_citation_recall(
        required_chunk_ids=required_ids, contexts=contexts, citations=resolved["citations"], status=effective_status,
    )
    present_required = set(required_ids) & {str(row["chunk_id"]) for row in contexts}
    strict_cited_present = {
        str(item["chunk_id"]) for item in resolved["citations"]
        if item.get("strict_valid") and item.get("chunk_id") in present_required
    }
    recoverable_cited_present = {
        str(item["chunk_id"]) for item in resolved["citations"]
        if item.get("recoverable_valid") and item.get("chunk_id") in present_required
    }
    evidence_metrics["strict_cited_required_chunk_count_present"] = len(strict_cited_present)
    evidence_metrics["recoverable_cited_required_chunk_count_present"] = len(recoverable_cited_present)
    evidence_metrics["strict_cited_required_chunk_count_present_and_answered"] = (
        len(strict_cited_present) if effective_status == "answered" and evidence_metrics["all_required_evidence_present"] else 0
    )
    evidence_metrics["recoverable_cited_required_chunk_count_present_and_answered"] = (
        len(recoverable_cited_present) if effective_status == "answered" and evidence_metrics["all_required_evidence_present"] else 0
    )
    evidence_metrics["strict_recall_present"] = len(strict_cited_present) / len(present_required) if present_required else None
    evidence_metrics["recoverable_recall_present"] = len(recoverable_cited_present) / len(present_required) if present_required else None
    den_answered = len(present_required) if effective_status == "answered" and evidence_metrics["all_required_evidence_present"] else 0
    evidence_metrics["strict_recall_present_and_answered"] = len(strict_cited_present) / den_answered if den_answered else None
    evidence_metrics["recoverable_recall_present_and_answered"] = len(recoverable_cited_present) / den_answered if den_answered else None
    required_present = bool(required_ids) and set(required_ids) <= {str(row["chunk_id"]) for row in contexts}
    similarity = silver_reference_similarity(answer, str(question.get("reference_answer") or "")) if effective_status == "answered" else None
    numeric = calculation_numeric_evaluation(answer, question.get("calculation_spec")) if question.get("calculation_spec") else None
    failures = []
    if not required_present:
        failures.append("retrieval_miss")
        if effective_status == "answered":
            failures.append("answered_without_required_evidence")
    if required_present and effective_status == "insufficient_evidence":
        failures.append("false_abstention_candidate")
    if required_present and effective_status == "generation_error":
        failures.append("generation_failure_after_retrieval_hit")
    if validation_errors:
        failures.append("invalid_output")
    if resolved["missing_citation"]:
        failures.append("missing_citation")
    if numeric and numeric.get("exact_numeric_match") is False:
        failures.append("numeric_error")
    row = {
        "question_id": qid, "question": str(question["question"]), "condition": condition,
        "query_style": question.get("query_style"), "species": question.get("species"),
        "category": question.get("category"), "difficulty": question.get("difficulty"),
        "risk_level": question.get("risk_level"), "multi_document": bool(question.get("multi_document")),
        "status": effective_status, "model_status": parsed.get("status") if parsed else None,
        "answer": answer, "citations": raw_citations if isinstance(raw_citations, list) else [],
        "resolved_citations": resolved["citations"],
        "json_parse_valid": parsed is not None and call["parse_error"] is None,
        "schema_valid": not validation_errors, "schema_errors": validation_errors,
        "status_valid": status_valid,
        "citation_parse_valid": bool(parsed and isinstance(parsed.get("citations"), list)
                                     and all(isinstance(value, str) for value in parsed["citations"])),
        "required_evidence_in_context": required_present,
        "required_chunk_ids": required_ids,
        "context_ids": [str(item["context_id"]) for item in contexts],
        "context_chunk_ids": [str(item["chunk_id"]) for item in contexts],
        "citation_count": resolved["citation_count"],
        "strict_citation_count": resolved["strict_valid_count"],
        "recoverable_citation_count": resolved["recoverable_valid_count"],
        "strict_citation_validity_rate": resolved["strict_validity_rate"],
        "recoverable_citation_validity_rate": resolved["recoverable_validity_rate"],
        "citation_error_taxonomy": resolved["error_taxonomy_counts"],
        "missing_citation": resolved["missing_citation"],
        "required_evidence_citation": evidence_metrics,
        "silver_reference_similarity": similarity,
        "calculation_numeric_evaluation": numeric,
        "failure_attribution": failures,
        "model": model, "prompt_version": "generation_v2",
        "latency_seconds": call["latency_seconds"], "ttft_seconds": call["ttft_seconds"],
        "prompt_tokens": call["prompt_tokens"], "completion_tokens": call["completion_tokens"],
        "tokens_per_second": call["tokens_per_second"], "load_duration_ns": call["load_duration_ns"],
        "done_reason": call["done_reason"],
    }
    raw = {
        "question_id": qid, "condition": condition, "model": model, "prompt_version": "generation_v2",
        "raw_output": call["raw_output"], "raw_output_sha256": call["raw_output_sha256"],
        "raw_output_preserved": bool(call["raw_output"]), "parse_error": call["parse_error"],
        "validation_error": validation_errors or None, "execution_error": call["execution_error"],
        "parsed_model_output": parsed,
    }
    return row, raw


def _summary(rows: list[dict[str, Any]], raw_rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(rows)
    status_counts = Counter(str(row.get("status")) for row in rows)
    parsed_count = sum(bool(row.get("json_parse_valid")) for row in rows)
    schema_count = sum(bool(row.get("schema_valid")) for row in rows)
    status_valid_count = sum(bool(row.get("status_valid")) for row in rows)
    citation_parse_count = sum(bool(row.get("citation_parse_valid")) for row in rows)
    citation_count = sum(int(row.get("citation_count") or 0) for row in rows)
    strict_count = sum(int(row.get("strict_citation_count") or 0) for row in rows)
    recoverable_count = sum(int(row.get("recoverable_citation_count") or 0) for row in rows)
    raw_count = sum(bool(row.get("raw_output")) for row in raw_rows)
    taxonomy: Counter[str] = Counter()
    for row in rows:
        taxonomy.update(row.get("citation_error_taxonomy") or {})

    buckets = {
        "all_questions": ("required_chunk_count_all_questions", "strict_cited_required_chunk_count", "recoverable_cited_required_chunk_count"),
        "evidence_present": ("required_chunk_count_present", "strict_cited_required_chunk_count_present", "recoverable_cited_required_chunk_count_present"),
        "evidence_present_and_answered": ("required_chunk_count_present_and_answered", "strict_cited_required_chunk_count_present_and_answered", "recoverable_cited_required_chunk_count_present_and_answered"),
    }
    recall_summary: dict[str, Any] = {}
    for label, (den_key, strict_key, recoverable_key) in buckets.items():
        denominator = sum(int(row["required_evidence_citation"].get(den_key) or 0) for row in rows)
        strict_num = sum(int(row["required_evidence_citation"].get(strict_key) or 0) for row in rows)
        recoverable_num = sum(int(row["required_evidence_citation"].get(recoverable_key) or 0) for row in rows)
        recall_summary[label] = {
            "denominator": denominator,
            "strict_numerator": strict_num,
            "recoverable_numerator": recoverable_num,
            "strict_recall": strict_num / denominator if denominator else None,
            "recoverable_recall": recoverable_num / denominator if denominator else None,
        }
    full_evidence = sum(bool(row.get("required_evidence_in_context")) for row in rows)
    full_and_answered = sum(bool(row.get("required_evidence_in_context")) and row.get("status") == "answered" for row in rows)
    strict_all_q = sum(bool(row["required_evidence_citation"].get("question_strict_all_available_required_cited")) for row in rows)
    rec_all_q = sum(bool(row["required_evidence_citation"].get("question_recoverable_all_available_required_cited")) for row in rows)
    strict_all_q_hit_answer = sum(
        bool(row.get("required_evidence_in_context")) and row.get("status") == "answered"
        and bool(row["required_evidence_citation"].get("question_strict_all_available_required_cited")) for row in rows
    )
    rec_all_q_hit_answer = sum(
        bool(row.get("required_evidence_in_context")) and row.get("status") == "answered"
        and bool(row["required_evidence_citation"].get("question_recoverable_all_available_required_cited")) for row in rows
    )
    answered_rows = [row for row in rows if row.get("status") == "answered"]
    ref_f1 = [row["silver_reference_similarity"]["f1"] for row in answered_rows if row.get("silver_reference_similarity")]
    calculations = [row["calculation_numeric_evaluation"] for row in rows if row.get("calculation_numeric_evaluation")]
    calculation_matches = sum(row.get("exact_numeric_match") is True for row in calculations)
    latency_fields = ("latency_seconds", "ttft_seconds", "tokens_per_second", "prompt_tokens", "completion_tokens")
    latency = {field: _stats([row.get(field) for row in rows]) for field in latency_fields}
    latency["total_generation_seconds"] = sum(float(row["latency_seconds"]) for row in rows if row.get("latency_seconds") is not None)
    return {
        "question_count": total, "status_counts": dict(sorted(status_counts.items())),
        "answered_count": status_counts["answered"], "answered_rate": status_counts["answered"] / total if total else None,
        "insufficient_evidence_count": status_counts["insufficient_evidence"],
        "insufficient_evidence_rate": status_counts["insufficient_evidence"] / total if total else None,
        "generation_error_count": status_counts["generation_error"],
        "raw_response_received_count": raw_count,
        "raw_output_preservation_rate": raw_count / total if total else None,
        "raw_output_preservation_response_only_rate": raw_count / sum(bool(r.get("response_received", bool(r.get("raw_output")))) for r in raw_rows)
            if any(bool(r.get("response_received", bool(r.get("raw_output")))) for r in raw_rows) else None,
        "json_parse_count": parsed_count, "json_parse_rate": parsed_count / total if total else None,
        "schema_valid_count": schema_count, "schema_valid_rate": schema_count / total if total else None,
        "status_valid_count": status_valid_count, "status_valid_rate": status_valid_count / total if total else None,
        "citation_parse_count": citation_parse_count, "citation_parse_rate": citation_parse_count / total if total else None,
        "citation_count": citation_count, "strict_valid_citation_count": strict_count,
        "recoverable_valid_citation_count": recoverable_count,
        "strict_citation_validity_rate": strict_count / citation_count if citation_count else None,
        "recoverable_citation_validity_rate": recoverable_count / citation_count if citation_count else None,
        "citation_error_taxonomy": dict(sorted(taxonomy.items())),
        "missing_citation_question_count": sum(bool(row.get("missing_citation")) for row in rows),
        "required_evidence_citation_recall": recall_summary,
        "required_evidence_question_recall": {
            "required_evidence_present_question_count": full_evidence,
            "evidence_present_and_answered_question_count": full_and_answered,
            "strict_all_required_cited_all_questions": strict_all_q / total if total else None,
            "recoverable_all_required_cited_all_questions": rec_all_q / total if total else None,
            "strict_all_required_cited_when_present_and_answered": strict_all_q_hit_answer / full_and_answered if full_and_answered else None,
            "recoverable_all_required_cited_when_present_and_answered": rec_all_q_hit_answer / full_and_answered if full_and_answered else None,
        },
        "retrieval_availability": {
            "required_evidence_present_count": full_evidence, "required_evidence_missing_count": total - full_evidence,
            "label_sent_to_generator": False,
        },
        "abstention_diagnostics": {
            "false_abstention_candidate": sum(row.get("status") == "insufficient_evidence" and row.get("required_evidence_in_context") for row in rows),
            "answered_without_required_evidence": sum(row.get("status") == "answered" and not row.get("required_evidence_in_context") for row in rows),
            "unsupported_claim_judged_automatically": False,
        },
        "silver_reference_similarity": {
            "metric": "normalized token overlap F1; AI-generated Silver reference, not expert correctness",
            "scored_answers": len(ref_f1), "f1_mean": statistics.fmean(ref_f1) if ref_f1 else None,
        },
        "calculation_numeric_evaluation": {
            "scored_questions": len(calculations), "exact_numeric_matches": calculation_matches,
            "descriptive_accuracy": calculation_matches / len(calculations) if calculations else None,
            "interpretation": "descriptive only; small Silver calculation sample",
        },
        "latency": latency,
    }


def _group_summaries(rows: list[dict[str, Any]], raw_by_id: dict[str, dict[str, Any]], key: str) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[str(row.get(key) or "unknown")].append(row)
    return {label: _summary(values, [raw_by_id[row["question_id"]] for row in values])
            for label, values in sorted(groups.items())}


def _run_condition(root: Path, condition: str, frozen: dict[str, Any],
                   contexts_by_condition: dict[str, dict[str, list[dict[str, Any]]]],
                   model_info: dict[str, Any], prompt: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    out_dir = root / OUT / CONDITIONS[condition]
    out_dir.mkdir(parents=True, exist_ok=True)
    per_path, raw_path = out_dir / "per_question.jsonl", out_dir / "raw_outputs.jsonl"
    rows_by_id = {str(row["question_id"]): row for row in _read_jsonl(per_path)}
    raw_by_id = {str(row["question_id"]): row for row in _read_jsonl(raw_path)}
    order = {str(q["question_id"]): i for i, q in enumerate(frozen["questions"])}
    print(f"{condition} v2: resuming {len(set(rows_by_id) & set(raw_by_id))}/169", flush=True)
    for index, question in enumerate(frozen["questions"], 1):
        qid = str(question["question_id"])
        if qid in rows_by_id and qid in raw_by_id:
            continue
        row, raw = _run_one_v2(question, contexts_by_condition[condition][qid], condition=condition,
                               model=model_info["default_model"], base_url=model_info["ollama_endpoint"],
                               prompt=prompt, corpus_ids=set(frozen["corpus_by_id"]))
        rows_by_id[qid], raw_by_id[qid] = row, raw
        _write_jsonl(per_path, sorted(rows_by_id.values(), key=lambda item: order[item["question_id"]]))
        _write_jsonl(raw_path, sorted(raw_by_id.values(), key=lambda item: order[item["question_id"]]))
        if index == 1 or index % 5 == 0 or index == len(frozen["questions"]):
            print(f"{condition} v2 {index}/169: {row['status']}; {row.get('latency_seconds')}s", flush=True)
    qids = [str(q["question_id"]) for q in frozen["questions"]]
    if set(rows_by_id) != set(qids) or set(raw_by_id) != set(qids):
        raise RuntimeError(f"{condition} generation checkpoint is incomplete")
    return [rows_by_id[qid] for qid in qids], [raw_by_id[qid] for qid in qids]


def _parsed_key(row: dict[str, Any]) -> str:
    value = {key: row.get(key) for key in ("question_id", "status", "answer", "citations")}
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _repeatability(root: Path, condition: str, frozen: dict[str, Any], contexts: dict[str, list[dict[str, Any]]],
                   model_info: dict[str, Any], prompt: str, primary_rows: list[dict[str, Any]],
                   primary_raw: list[dict[str, Any]]) -> dict[str, Any]:
    out_dir = root / OUT / CONDITIONS[condition]
    path = out_dir / "repeatability_reruns.jsonl"
    existing_rows = _read_jsonl(path)
    existing = {(int(row["repeat_run"]), str(row["question_id"])): row for row in existing_rows}
    subset = frozen["questions"][:REPEAT_COUNT]
    corpus_ids = set(frozen["corpus_by_id"])
    for repeat_run in range(1, REPEAT_RUNS + 1):
        for question in subset:
            qid = str(question["question_id"])
            key = (repeat_run, qid)
            if key in existing:
                continue
            row, raw = _run_one_v2(question, contexts[qid], condition=condition,
                                   model=model_info["default_model"], base_url=model_info["ollama_endpoint"],
                                   prompt=prompt, corpus_ids=corpus_ids)
            existing[key] = {"repeat_run": repeat_run, **row, "raw_output": raw["raw_output"],
                             "raw_output_sha256": raw["raw_output_sha256"], "parse_error": raw["parse_error"],
                             "validation_error": raw["validation_error"], "execution_error": raw["execution_error"]}
            serialized = [existing[(run_no, str(q["question_id"]))] for run_no in range(1, REPEAT_RUNS + 1)
                          for q in subset if (run_no, str(q["question_id"])) in existing]
            _write_jsonl(path, serialized)

    base_rows = {str(row["question_id"]): row for row in primary_rows}
    base_raw = {str(row["question_id"]): row for row in primary_raw}
    comparisons = []
    for question in subset:
        qid = str(question["question_id"])
        base = base_rows[qid]
        for repeat_run in range(1, REPEAT_RUNS + 1):
            repeated = existing[(repeat_run, qid)]
            left_cites, right_cites = set(map(str, base.get("citations") or [])), set(map(str, repeated.get("citations") or []))
            comparisons.append({
                "question_id": qid, "repeat_run": repeat_run,
                "raw_exact_match": (base_raw[qid].get("raw_output") or "") == (repeated.get("raw_output") or ""),
                "parsed_exact_match": _parsed_key(base) == _parsed_key(repeated),
                "status_match": base.get("status") == repeated.get("status"),
                "normalized_answer_similarity": normalized_answer_similarity(str(base.get("answer") or ""), str(repeated.get("answer") or "")),
                "citation_set_exact_match": left_cites == right_cites,
                "citation_set_jaccard": jaccard(left_cites, right_cites),
            })
    rate = lambda key: sum(bool(row[key]) for row in comparisons) / len(comparisons) if comparisons else None
    report = {
        "subset_questions": len(subset), "repeat_runs_per_question": REPEAT_RUNS,
        "baseline_to_repeat_comparisons": len(comparisons),
        "raw_exact_match_rate": rate("raw_exact_match"), "parsed_exact_match_rate": rate("parsed_exact_match"),
        "status_match_rate": rate("status_match"),
        "normalized_answer_similarity_mean": statistics.fmean(row["normalized_answer_similarity"] for row in comparisons) if comparisons else None,
        "citation_set_exact_match_rate": rate("citation_set_exact_match"),
        "citation_set_jaccard_mean": statistics.fmean(row["citation_set_jaccard"] for row in comparisons) if comparisons else None,
        "comparisons": comparisons,
    }
    _write_json(out_dir / "repeatability.json", report)
    return report


def _manifest(root: Path, condition: str, frozen: dict[str, Any], model_info: dict[str, Any],
              prompt: str, preflight: dict[str, Any]) -> dict[str, Any]:
    out_dir = root / OUT / CONDITIONS[condition]
    manifest_path = out_dir / "experiment_manifest.json"
    current = {
        "experiment_id": CONDITIONS[condition], "condition": condition,
        "benchmark_type": "AI-generated Grounded Silver; not Human Gold", "status": "running",
        "input_hashes": frozen["hashes"], "question_count": frozen["question_count"],
        "generator": model_info, "generation_parameters": dict(GENERATION_OPTIONS),
        "prompt_version": "generation_v2", "prompt_sha256": sha256_text(prompt),
        "schema_sha256": sha256_file(root / "schemas/generation_output_v2.schema.json"),
        "structured_output_mode": "Ollama JSON Schema constrained output (format=schema)",
        "structured_output_preflight_passed": preflight["passed"],
        "context_ordering": "Oracle frozen evidence_snapshot order; E4 exact rank order with rank 1 as C1",
        "context_protocol": "The model sees each C ID and evidence text; document/page/chunk provenance is resolved outside the model.",
        "context_manifest_sha256": sha256_file(out_dir / "context_manifest.jsonl"),
        "e4_top5_identity_and_order_verified_against_v1": True,
        "reference_answer_or_required_evidence_flag_sent_to_model": False,
        "repeatability_subset": {"question_count": REPEAT_COUNT, "reruns_per_question": REPEAT_RUNS},
        "created_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    if manifest_path.exists():
        old = json.loads(manifest_path.read_text(encoding="utf-8"))
        for key in ("input_hashes", "generator", "generation_parameters", "prompt_sha256", "schema_sha256", "context_manifest_sha256"):
            if old.get(key) != current.get(key):
                raise RuntimeError(f"Existing v2 checkpoint has incompatible {key}; will not combine generations")
        current["created_at_utc"] = old.get("created_at_utc")
    _write_json(manifest_path, current)
    return current


def _finish_condition(root: Path, condition: str, frozen: dict[str, Any], rows: list[dict[str, Any]],
                      raw_rows: list[dict[str, Any]], repeat: dict[str, Any]) -> dict[str, Any]:
    out = root / OUT / CONDITIONS[condition]
    summary = _summary(rows, raw_rows)
    _write_json(out / "overall.json", summary)
    _write_json(out / "failure_analysis.json", {
        "counts": {
            "retrieval_miss": sum("retrieval_miss" in row["failure_attribution"] for row in rows),
            "answered_without_required_evidence": summary["abstention_diagnostics"]["answered_without_required_evidence"],
            "false_abstention_candidate": summary["abstention_diagnostics"]["false_abstention_candidate"],
            "generation_error": summary["generation_error_count"],
            "numeric_error": sum("numeric_error" in row["failure_attribution"] for row in rows),
        },
        "unsupported_factual_claims_automatically_judged": False,
        "interpretation": "Diagnostic labels only; no automatic factual correctness or absolute causal claim.",
    })
    _write_json(out / "citation_validation.json", {
        key: summary[key] for key in (
            "citation_count", "strict_valid_citation_count", "recoverable_valid_citation_count",
            "strict_citation_validity_rate", "recoverable_citation_validity_rate", "citation_parse_rate",
            "citation_error_taxonomy", "missing_citation_question_count", "required_evidence_citation_recall",
            "required_evidence_question_recall",
        )
    } | {"interpretation": "Strict validity resolves supplied C IDs; chunk ID aliases are separately recoverable and are not labelled hallucinated."})
    _write_json(out / "repeatability.json", repeat)
    _write_json(out / "latency.json", summary["latency"])
    raw_by_id = {row["question_id"]: row for row in raw_rows}
    for key in ("query_style", "species", "category"):
        _write_json(out / f"by_{key}.json", _group_summaries(rows, raw_by_id, key))
    manifest = json.loads((out / "experiment_manifest.json").read_text(encoding="utf-8"))
    manifest["status"] = "completed" if len(rows) == len(frozen["questions"]) else "incomplete"
    manifest["raw_output_preservation"] = {
        "attempt_count": len(rows), "captured_nonempty_response_count": summary["raw_response_received_count"],
        "missing_raw_question_ids": [row["question_id"] for row in raw_rows if not row.get("raw_output")],
        "parse_failures_with_raw_preserved": sum(bool(row.get("raw_output")) and bool(row.get("parse_error")) for row in raw_rows),
        "schema_failures_with_raw_preserved": sum(bool(row.get("raw_output")) and bool(row.get("validation_error")) for row in raw_rows),
    }
    _write_json(out / "experiment_manifest.json", manifest)
    return summary


def _v1_v2_comparison(root: Path, audit: dict[str, Any], summaries: dict[str, dict[str, Any]]) -> dict[str, Any]:
    result = {}
    for condition in ("G0", "G1"):
        folder = root / OUT / V1_CONDITIONS[condition]
        v1_summary = json.loads((folder / "overall.json").read_text(encoding="utf-8"))
        v1_manifest = json.loads((folder / "experiment_manifest.json").read_text(encoding="utf-8"))
        v1_capture = v1_manifest.get("raw_output_capture", {})
        v1_attempts = int(v1_capture.get("attempts") or 0)
        v1 = audit["conditions"][condition]
        v2 = summaries[condition]
        result[condition] = {
            "v1": {
                "schema_valid_rate": v1_summary.get("schema_valid_rate"),
                "strict_citation_validity_rate": v1["strict_citation_validity_rate"],
                "recoverable_citation_validity_rate": v1["recoverable_citation_validity_rate"],
                "required_evidence_citation_recall": v1["required_evidence_citation_recall"],
                "raw_output_preservation_rate": v1_capture.get("captured", 0) / v1_attempts if v1_attempts else None,
                "answered_count": v1_summary.get("answered_count"),
                "silver_reference_f1": (v1_summary.get("silver_reference_similarity") or {}).get("f1_mean"),
                "calculation_numeric": v1_summary.get("calculation_numeric_evaluation"),
            },
            "v2": {
                "schema_valid_rate": v2["schema_valid_rate"],
                "strict_citation_validity_rate": v2["strict_citation_validity_rate"],
                "recoverable_citation_validity_rate": v2["recoverable_citation_validity_rate"],
                "required_evidence_citation_recall": v2["required_evidence_citation_recall"],
                "raw_output_preservation_rate": v2["raw_output_preservation_rate"],
                "answered_count": v2["answered_count"],
                "silver_reference_f1": (v2.get("silver_reference_similarity") or {}).get("f1_mean"),
                "calculation_numeric": v2.get("calculation_numeric_evaluation"),
            },
        }
    return {"comparison_type": "output protocol stabilization, not answer-quality prompt optimization",
            "benchmark_type": "AI-generated Grounded Silver; not Human Gold", "conditions": result,
            "same_question_and_context_inputs": True, "causal_claim": False}


def _readiness(summaries: dict[str, dict[str, Any]]) -> dict[str, Any]:
    conditions = {}
    for condition, summary in summaries.items():
        taxonomy = summary["citation_error_taxonomy"]
        checks = {
            "raw_output_preservation_100_percent": summary["raw_output_preservation_rate"] == 1.0,
            "schema_valid_at_least_99_percent": (summary["schema_valid_rate"] or 0) >= .99,
            "citation_parse_at_least_99_percent": (summary["citation_parse_rate"] or 0) >= .99,
            "strict_citation_validity_at_least_95_percent": (summary["strict_citation_validity_rate"] or 0) >= .95,
            "no_systematic_chunk_id_context_id_confusion": taxonomy.get("chunk_id_in_context", 0) == 0,
        }
        conditions[condition] = {"checks": checks, "ready": all(checks.values()), "metrics": {
            "raw_output_preservation_rate": summary["raw_output_preservation_rate"],
            "schema_valid_rate": summary["schema_valid_rate"],
            "citation_parse_rate": summary["citation_parse_rate"],
            "strict_citation_validity_rate": summary["strict_citation_validity_rate"],
            "chunk_id_in_context_count": taxonomy.get("chunk_id_in_context", 0),
        }}
    return {
        "phase16_generation_ready": bool(conditions) and all(row["ready"] for row in conditions.values()),
        "conditions": conditions,
        "gates": {"raw_output_preservation": 1.0, "schema_valid_rate_min": .99,
                  "citation_parse_rate_min": .99, "strict_citation_validity_min": .95,
                  "no_systematic_citation_field_confusion": True},
        "ragas_executed": False,
        "interpretation": "Technical readiness only; not expert answer correctness.",
    }


def run_phase15_1(root: Path = ROOT) -> dict[str, Any]:
    frozen = validate_frozen_inputs(root)
    if frozen["question_count"] != 169:
        raise RuntimeError("Expected the frozen 169-question Grounded Silver v1 dataset")
    old_manifest = json.loads((root / OUT / "generation_retrieval_manifest.json").read_text(encoding="utf-8"))
    if frozen["hashes"] != old_manifest.get("input_hashes"):
        raise RuntimeError("Phase 15 frozen input checksums differ")
    old_model = old_manifest["generator_preflight"]
    model_info = _preflight(root)
    if model_info["default_model"] != old_model["default_model"] or model_info["model_digest"] != old_model["model_digest"]:
        raise RuntimeError("Phase 15 default generator/model digest is unavailable or changed")
    if model_info["runtime_version"] != old_model["runtime_version"]:
        raise RuntimeError("Ollama runtime version differs from Phase 15")
    old_g1_manifest = json.loads((root / OUT / V1_CONDITIONS["G1"] / "experiment_manifest.json").read_text(encoding="utf-8"))
    if old_g1_manifest.get("ollama_format") != "JSON Schema constrained output":
        raise RuntimeError("Phase 15 runtime did not confirm native structured output support")
    compat_v1 = json.loads((root / OUT / "compatibility.json").read_text(encoding="utf-8"))
    if not compat_v1.get("protected_artifacts_unchanged"):
        raise RuntimeError("Phase 15 protected artifact compatibility check did not pass")

    v1_hashes = _capture_v1_files(root)
    protected_before = _capture_protected(root)
    for relative, expected in (old_manifest.get("protected_artifacts_before") or {}).items():
        actual = protected_before.get(relative)
        if not actual or actual["sha256"] != expected["sha256"] or actual["size"] != expected["size"] or actual["mtime_ns"] != expected["mtime_ns"]:
            raise RuntimeError(f"Protected Phase 12-14 artifact changed: {relative}")
    contexts = _write_context_manifests(root, frozen)

    out_preflight = call_ollama_v2(
        model=model_info["default_model"],
        system_prompt="只輸出符合指定 JSON Schema 的 JSON。question_id 使用 protocol_preflight，status 使用 insufficient_evidence，answer 使用簡短繁體中文，citations 使用空陣列。",
        user_prompt="JSON Schema constrained output runtime preflight。question_id：protocol_preflight。",
        base_url=model_info["ollama_endpoint"],
    )
    preflight_errors = validate_v2_output(out_preflight["parsed"], "protocol_preflight") if out_preflight["parsed"] else ["json_parse_failure"]
    schema_preflight = {
        "runtime": model_info["runtime"], "runtime_version": model_info["runtime_version"],
        "structured_output_mode": "Ollama native JSON Schema constrained output (format=schema)",
        "schema_sha256": sha256_file(root / "schemas/generation_output_v2.schema.json"),
        "raw_output": out_preflight["raw_output"], "raw_output_sha256": out_preflight["raw_output_sha256"],
        "parse_error": out_preflight["parse_error"], "execution_error": out_preflight["execution_error"],
        "validation_errors": preflight_errors,
        "passed": bool(out_preflight["raw_output"] and not out_preflight["parse_error"] and not preflight_errors),
        "benchmark_question_count_excludes_preflight": True,
    }
    _write_json(root / AUDIT / "structured_output_preflight.json", schema_preflight)
    if not schema_preflight["passed"]:
        raise RuntimeError("V2 schema-constrained output preflight failed; no benchmark calls were started")

    v1_audit = _v1_forensic(root, frozen, contexts, v1_hashes)
    _write_json(root / AUDIT / "phase15_1_manifest.json", {
        "phase": "15.1", "created_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "frozen_input_hashes": frozen["hashes"], "model": old_model,
        "generation_parameters": dict(GENERATION_OPTIONS), "phase15_v1_file_hashes_before": v1_hashes,
        "protected_artifacts_before": protected_before, "structured_output_preflight": schema_preflight,
        "v1_citation_audit": "v1_citation_reanalysis.json",
    })

    summaries: dict[str, dict[str, Any]] = {}
    for condition in ("G0", "G1"):
        exp = root / OUT / CONDITIONS[condition]
        exp.mkdir(parents=True, exist_ok=True)
        context_rows = [_context_row(str(q["question_id"]), condition, contexts[condition][str(q["question_id"])])
                        for q in frozen["questions"]]
        manifest_path = exp / "experiment_manifest.json"
        manifest = {
            "experiment_id": CONDITIONS[condition], "condition": condition, "status": "running",
            "benchmark_type": "AI-generated Grounded Silver; not Human Gold",
            "input_hashes": frozen["hashes"], "question_count": 169, "generator": old_model,
            "generation_parameters": dict(GENERATION_OPTIONS), "prompt_version": "generation_v2",
            "prompt_sha256": sha256_text((root / "prompts/generation_v2.txt").read_text(encoding="utf-8").strip()),
            "schema_sha256": sha256_file(root / "schemas/generation_output_v2.schema.json"),
            "structured_output_mode": schema_preflight["structured_output_mode"],
            "structured_output_preflight_passed": True,
            "context_ordering": "G0 required evidence snapshot order; G1 frozen E4 ranking order; rank 1 = C1",
            "context_protocol": "The model sees C ID and evidence text; provenance is resolved outside the model.",
            "context_manifest_sha256": sha256_file(exp / "context_manifest.jsonl"),
            "e4_top5_identity_and_order_verified_against_v1": True,
            "reference_answer_or_required_evidence_flag_sent_to_model": False,
            "repeatability_subset": {"question_count": REPEAT_COUNT, "reruns_per_question": REPEAT_RUNS},
            "created_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }
        if manifest_path.exists():
            previous = json.loads(manifest_path.read_text(encoding="utf-8"))
            for key in ("input_hashes", "generator", "generation_parameters", "prompt_sha256", "schema_sha256", "context_manifest_sha256"):
                if previous.get(key) != manifest.get(key):
                    raise RuntimeError(f"Existing {condition} v2 output checkpoint uses different {key}")
            manifest["created_at_utc"] = previous.get("created_at_utc")
        _write_json(manifest_path, manifest)
        prompt = (root / "prompts/generation_v2.txt").read_text(encoding="utf-8").strip()
        rows, raw_rows = _run_condition(root, condition, frozen, contexts, old_model, prompt)
        repeat = _repeatability(root, condition, frozen, contexts[condition], old_model, prompt, rows, raw_rows)
        summary = _finish_condition(root, condition, frozen, rows, raw_rows, repeat)
        summaries[condition] = summary
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["status"] = "completed"
        manifest["raw_output_preservation"] = {
            "attempt_count": len(raw_rows),
            "captured_nonempty_response_count": summary["raw_response_received_count"],
            "missing_raw_question_ids": [row["question_id"] for row in raw_rows if not row.get("raw_output")],
            "parse_failures_with_raw_preserved": sum(bool(row.get("raw_output")) and bool(row.get("parse_error")) for row in raw_rows),
            "schema_failures_with_raw_preserved": sum(bool(row.get("raw_output")) and bool(row.get("validation_error")) for row in raw_rows),
        }
        _write_json(manifest_path, manifest)

    comp = _v1_v2_comparison(root, v1_audit, summaries)
    comp_dir = root / OUT / "G0_G1_protocol_v1_vs_v2"
    comp_dir.mkdir(parents=True, exist_ok=True)
    _write_json(comp_dir / "comparison.json", comp)
    readiness = _readiness(summaries)
    _write_json(root / OUT / "phase16_generation_readiness.json", readiness)
    if readiness["phase16_generation_ready"]:
        q_by_id = {str(q["question_id"]): q for q in frozen["questions"]}
        g1_rows = {row["question_id"]: row for row in _read_jsonl(root / OUT / CONDITIONS["G1"] / "per_question.jsonl")}
        export = [{
            "question_id": qid, "question": q_by_id[qid]["question"], "answer": row["answer"],
            "contexts": [context["text"] for context in contexts["G1"][qid]],
            "reference_answer": q_by_id[qid]["reference_answer"], "benchmark_type": "silver",
            "silver_reference": True, "generation_protocol": "v2",
        } for qid, row in g1_rows.items()]
        _write_jsonl(root / "data/evaluation/generation/ragas_input_v2.jsonl", export)

    summary_lines = [
        "# Phase 15.1 — Generation Protocol v1 vs v2", "",
        "Comparison is for structured-output and citation-protocol stabilization, not semantic prompt optimization.",
        "The benchmark uses AI-generated Grounded Silver, not Human Gold.", "",
    ]
    for condition in ("G0", "G1"):
        v1 = comp["conditions"][condition]["v1"]
        v2 = comp["conditions"][condition]["v2"]
        summary_lines += [
            f"## {condition}",
            f"- v1 strict citation validity: {v1['strict_citation_validity_rate']}",
            f"- v1 recoverable citation validity: {v1['recoverable_citation_validity_rate']}",
            f"- v2 schema validity: {v2['schema_valid_rate']}",
            f"- v2 strict citation validity: {v2['strict_citation_validity_rate']}",
            f"- v2 recoverable citation validity: {v2['recoverable_citation_validity_rate']}",
            f"- v2 raw output preservation: {v2['raw_output_preservation_rate']}", "",
        ]
    summary_lines += [f"Phase 16 generation readiness: {readiness['phase16_generation_ready']}.", "RAGAS was not run."]
    (comp_dir / "comparison_summary.md").write_text("\n".join(summary_lines) + "\n", encoding="utf-8")

    protected_after = _capture_protected(root)
    protected_checks = {
        relative: bool(protected_after.get(relative))
        and expected["sha256"] == protected_after[relative]["sha256"]
        and expected["size"] == protected_after[relative]["size"]
        and expected["mtime_ns"] == protected_after[relative]["mtime_ns"]
        for relative, expected in protected_before.items()
    }
    v1_after = _capture_v1_files(root)
    v1_checks = {
        relative: bool(v1_after.get(relative))
        and expected["sha256"] == v1_after[relative]["sha256"]
        and expected["size"] == v1_after[relative]["size"]
        and expected["mtime_ns"] == v1_after[relative]["mtime_ns"]
        for relative, expected in v1_hashes.items()
    }
    smoke = requests.get("http://127.0.0.1:8767/_stcore/health", timeout=10)
    compatibility = {
        "status": "passed" if all(protected_checks.values()) and all(v1_checks.values()) and smoke.status_code == 200 else "failed",
        "production_streamlit_http_status": smoke.status_code,
        "rag_store_sqlite3_unchanged": protected_checks.get("rag_store.sqlite3", False),
        "protected_artifact_count": len(protected_checks), "protected_artifacts_all_unchanged": all(protected_checks.values()),
        "phase15_v1_file_count": len(v1_checks), "phase15_v1_all_immutable": all(v1_checks.values()),
        "protected_failures": [key for key, value in protected_checks.items() if not value],
        "v1_immutability_failures": [key for key, value in v1_checks.items() if not value],
        "production_files_modified": False, "phase15_v1_modified": False, "frozen_inputs": frozen["hashes"],
    }
    _write_json(root / OUT / "phase15_1_compatibility.json", compatibility)
    v1_audit["phase15_v1_file_hashes_after"] = v1_after
    v1_audit["phase15_v1_immutable_check_passed"] = all(v1_checks.values())
    _write_json(root / AUDIT / "v1_citation_reanalysis.json", v1_audit)
    summary = {
        "benchmark_type": "AI-generated Grounded Silver; not Human Gold",
        "frozen_inputs": frozen["hashes"], "structured_output_preflight": schema_preflight,
        "phase15_v1_citation_audit": v1_audit["conditions"],
        "G0_v2": summaries["G0"], "G1_v2": summaries["G1"],
        "phase16_readiness": readiness, "protocol_comparison": comp, "compatibility": compatibility,
    }
    _write_json(root / OUT / "phase15_1_summary.json", summary)
    if compatibility["status"] != "passed":
        raise RuntimeError("Production or immutable artifact compatibility check failed")
    return summary


def finalize_phase15_1_reports(root: Path = ROOT) -> dict[str, Any]:
    """Rebuild metrics from saved v2 outputs without making any model calls."""
    frozen = validate_frozen_inputs(root)
    audit_dir = root / AUDIT
    phase_manifest = json.loads((audit_dir / "phase15_1_manifest.json").read_text(encoding="utf-8"))
    schema_preflight = json.loads((audit_dir / "structured_output_preflight.json").read_text(encoding="utf-8"))
    if not schema_preflight.get("passed"):
        raise RuntimeError("Cannot finalize: stored structured-output preflight did not pass")
    if phase_manifest.get("frozen_input_hashes") != frozen["hashes"]:
        raise RuntimeError("Cannot finalize: frozen corpus, questions, or E4 inputs changed")
    protected_before = phase_manifest.get("protected_artifacts_before") or {}
    v1_before = phase_manifest.get("phase15_v1_file_hashes_before") or {}
    contexts = _write_context_manifests(root, frozen)
    v1_audit = _v1_forensic(root, frozen, contexts, v1_before)
    summaries = {}
    for condition in ("G0", "G1"):
        out = root / OUT / CONDITIONS[condition]
        rows = _read_jsonl(out / "per_question.jsonl")
        raw_rows = _read_jsonl(out / "raw_outputs.jsonl")
        repeat = json.loads((out / "repeatability.json").read_text(encoding="utf-8"))
        if len(rows) != 169 or len(raw_rows) != 169:
            raise RuntimeError(f"Cannot finalize: {condition} v2 artifacts are incomplete")
        summaries[condition] = _finish_condition(root, condition, frozen, rows, raw_rows, repeat)
    comparison = _v1_v2_comparison(root, v1_audit, summaries)
    comparison_dir = root / OUT / "G0_G1_protocol_v1_vs_v2"
    _write_json(comparison_dir / "comparison.json", comparison)
    readiness = _readiness(summaries)
    _write_json(root / OUT / "phase16_generation_readiness.json", readiness)
    lines = [
        "# Phase 15.1 — Generation Protocol v1 vs v2", "",
        "This comparison covers output-protocol stabilization, not semantic prompt tuning.",
        "All results use AI-generated Grounded Silver, not Human Gold.", "",
    ]
    for condition in ("G0", "G1"):
        v1 = comparison["conditions"][condition]["v1"]
        v2 = comparison["conditions"][condition]["v2"]
        lines += [
            f"## {condition}",
            f"- v1 strict citation validity: {v1['strict_citation_validity_rate']}",
            f"- v1 recoverable citation validity: {v1['recoverable_citation_validity_rate']}",
            f"- v2 schema validity: {v2['schema_valid_rate']}",
            f"- v2 strict citation validity: {v2['strict_citation_validity_rate']}",
            f"- v2 recoverable citation validity: {v2['recoverable_citation_validity_rate']}",
            f"- v2 raw output preservation: {v2['raw_output_preservation_rate']}", "",
        ]
    lines += [f"Phase 16 generation readiness: {readiness['phase16_generation_ready']}.", "RAGAS was not run."]
    (comparison_dir / "comparison_summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    protected_after = _capture_protected(root)
    protected_checks = {
        path: bool(protected_after.get(path))
        and value.get("sha256") == protected_after[path]["sha256"]
        and value.get("size") == protected_after[path]["size"]
        and value.get("mtime_ns") == protected_after[path]["mtime_ns"]
        for path, value in protected_before.items()
    }
    v1_after = _capture_v1_files(root)
    v1_checks = {
        path: bool(v1_after.get(path))
        and value.get("sha256") == v1_after[path]["sha256"]
        and value.get("size") == v1_after[path]["size"]
        and value.get("mtime_ns") == v1_after[path]["mtime_ns"]
        for path, value in v1_before.items()
    }
    smoke = requests.get("http://127.0.0.1:8767/_stcore/health", timeout=10)
    compatibility = {
        "status": "passed" if all(protected_checks.values()) and all(v1_checks.values()) and smoke.status_code == 200 else "failed",
        "production_streamlit_http_status": smoke.status_code,
        "rag_store_sqlite3_unchanged": protected_checks.get("rag_store.sqlite3", False),
        "protected_artifact_count": len(protected_checks),
        "protected_artifacts_all_unchanged": all(protected_checks.values()),
        "phase15_v1_file_count": len(v1_checks),
        "phase15_v1_all_immutable": all(v1_checks.values()),
        "protected_failures": [key for key, value in protected_checks.items() if not value],
        "v1_immutability_failures": [key for key, value in v1_checks.items() if not value],
        "production_files_modified": False,
        "phase15_v1_modified": False,
        "frozen_inputs": frozen["hashes"],
    }
    _write_json(root / OUT / "phase15_1_compatibility.json", compatibility)
    v1_audit["phase15_v1_file_hashes_after"] = v1_after
    v1_audit["phase15_v1_immutable_check_passed"] = all(v1_checks.values())
    _write_json(audit_dir / "v1_citation_reanalysis.json", v1_audit)
    result = {
        "benchmark_type": "AI-generated Grounded Silver; not Human Gold",
        "frozen_inputs": frozen["hashes"],
        "structured_output_preflight": schema_preflight,
        "phase15_v1_citation_audit": v1_audit["conditions"],
        "G0_v2": summaries["G0"],
        "G1_v2": summaries["G1"],
        "phase16_readiness": readiness,
        "protocol_comparison": comparison,
        "compatibility": compatibility,
    }
    _write_json(root / OUT / "phase15_1_summary.json", result)
    if compatibility["status"] != "passed":
        raise RuntimeError("Production or immutable artifact compatibility check failed")
    return result
