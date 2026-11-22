"""Run frozen G0/G1 with Generation Execution Protocol v2.2 (1024 output tokens)."""

from __future__ import annotations

import json
import math
import statistics
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import requests

from .contexts import build_e4_top5_contexts, build_oracle_contexts
from .frozen import read_jsonl, sha256_file, validate_frozen_inputs
from .ollama import GENERATION_OPTIONS, OLLAMA_BASE_URL
from .protocol_v2 import sha256_text
from .protocol_v22 import (
    CONTEXT_LENGTH, MAX_ATTEMPTS, MAX_OUTPUT_TOKENS, build_ragas_row_v22,
    compare_v21_v22, context_budget_audit, generation_options_v22,
    previous_failure_recovery, readiness_v22, same_generation_config,
)
from .retry_v21 import build_attempt_record, first_pass_metrics, should_retry, validate_attempt_records
from .runner import _capture_protected, _git_commit, _preflight
from .runner_v2 import (
    OUT, _read_jsonl, _run_one_v2, _stats, _summary, _write_json, _write_jsonl,
    format_v2_user_prompt,
)

ROOT = Path(__file__).resolve().parents[3]
EXPERIMENTS = {
    "G0": "G0_grounded_oracle_generation_v2_2",
    "G1": "G1_grounded_e4_top5_generation_v2_2",
}
PREVIOUS = {
    "G0": "G0_grounded_oracle_generation_v2",
    "G1": "G1_grounded_e4_top5_generation_v2",
}
PREVIOUS_RETRY_G1 = "G1_grounded_e4_top5_generation_v2_1"
PHASE_DIR = OUT / "phase15_3"
QUESTION_COUNT = 169
REPEAT_COUNT = 20
OLD_FAILURE_IDS = ("grounded_6363e292be7af639291a", "grounded_960eb614b70d2e08dfd2")


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_jsonl_append(path: Path, row: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(dict(row), ensure_ascii=False, sort_keys=True) + "\n")


def _capture_immutable_v15(root: Path) -> dict[str, dict[str, Any]]:
    paths: set[Path] = set()
    folders = (
        "G0_grounded_oracle_generation_v1", "G1_grounded_e4_top5_generation_v1",
        PREVIOUS["G0"], PREVIOUS["G1"], PREVIOUS_RETRY_G1,
        "phase15_citation_recovery_audit", "phase15_2",
    )
    for folder in folders:
        base = root / OUT / folder
        if base.is_dir():
            paths.update(path for path in base.rglob("*") if path.is_file())
    for relative in (
        OUT / "generation_retrieval_manifest.json", OUT / "phase15_summary.json",
        OUT / "phase15_1_manifest.json", OUT / "phase15_1_summary.json",
        OUT / "phase15_1_compatibility.json", OUT / "phase16_generation_readiness.json",
        Path("prompts/generation_v2.txt"), Path("schemas/generation_output_v2.schema.json"),
    ):
        path = root / relative
        if path.is_file():
            paths.add(path)
    result: dict[str, dict[str, Any]] = {}
    for path in sorted(paths):
        stat = path.stat()
        result[path.relative_to(root).as_posix()] = {
            "sha256": sha256_file(path), "size": stat.st_size, "mtime_ns": stat.st_mtime_ns,
        }
    return result


def _freeze(root: Path) -> tuple[dict[str, Any], dict[str, Any], str, dict[str, dict[str, list[dict[str, Any]]]], dict[str, dict[str, int]]]:
    frozen = validate_frozen_inputs(root)
    if frozen.get("question_count") != QUESTION_COUNT or len(frozen.get("questions", [])) != QUESTION_COUNT:
        raise RuntimeError("Phase 15.3 requires exactly 169 frozen Grounded Silver v1 questions")
    p15 = _read_json(root / OUT / "generation_retrieval_manifest.json")
    if frozen["hashes"] != p15.get("input_hashes"):
        raise RuntimeError("Frozen corpus/question/E4 inputs differ from Phase 15 manifest")
    prompt = (root / "prompts/generation_v2.txt").read_text(encoding="utf-8").strip()
    prompt_sha = sha256_text(prompt)
    schema_sha = sha256_file(root / "schemas/generation_output_v2.schema.json")
    contexts: dict[str, dict[str, list[dict[str, Any]]]] = {"G0": {}, "G1": {}}
    baseline_tokens: dict[str, dict[str, int]] = {"G0": {}, "G1": {}}
    for condition in ("G0", "G1"):
        folder = root / OUT / PREVIOUS[condition]
        manifest = _read_json(folder / "experiment_manifest.json")
        if manifest.get("status") != "completed" or manifest.get("question_count") != QUESTION_COUNT:
            raise RuntimeError(f"Immutable Phase 15.1 {condition} v2 run is incomplete")
        if manifest.get("input_hashes") != frozen["hashes"]:
            raise RuntimeError(f"{condition} Phase 15.1 input hashes differ")
        if manifest.get("prompt_sha256") != prompt_sha or manifest.get("schema_sha256") != schema_sha:
            raise RuntimeError("Generation v2 prompt or schema checksum changed")
        params = manifest.get("generation_parameters") or {}
        if params != GENERATION_OPTIONS:
            raise RuntimeError(f"Frozen {condition} generation parameters differ from Phase 15.1")
        old_rows = {str(row["question_id"]): row for row in read_jsonl(folder / "per_question.jsonl")}
        old_contexts = {str(row["question_id"]): row for row in read_jsonl(folder / "context_manifest.jsonl")}
        if len(old_rows) != QUESTION_COUNT or len(old_contexts) != QUESTION_COUNT:
            raise RuntimeError(f"{condition} frozen per-question/context manifest is incomplete")
        for q in frozen["questions"]:
            qid = str(q["question_id"])
            rows = (build_oracle_contexts(q, frozen["corpus_by_id"]) if condition == "G0" else
                    build_e4_top5_contexts(q, frozen["e4_trace_by_question"][qid], frozen["corpus_by_id"]))
            expected_ids = [str(row["context_id"]) for row in rows]
            expected_chunks = [str(row["chunk_id"]) for row in rows]
            if old_rows[qid].get("context_ids") != expected_ids or old_rows[qid].get("context_chunk_ids") != expected_chunks:
                raise RuntimeError(f"{condition} context IDs/chunks/order differ from v2 for {qid}")
            manifest_rows = old_contexts[qid].get("contexts") or []
            if [str(row["context_id"]) for row in manifest_rows] != expected_ids:
                raise RuntimeError(f"{condition} context manifest IDs differ for {qid}")
            if [str(row["chunk_id"]) for row in manifest_rows] != expected_chunks:
                raise RuntimeError(f"{condition} context manifest chunks differ for {qid}")
            token_count = old_rows[qid].get("prompt_tokens")
            if token_count is None:
                raise RuntimeError(f"Missing same-input prompt_eval_count baseline for {condition} {qid}")
            contexts[condition][qid] = rows
            baseline_tokens[condition][qid] = int(token_count)
        if condition == "G1":
            v1_folder = root / OUT / "G1_grounded_e4_top5_generation_v1"
            v1_rows = {str(row["question_id"]): row for row in read_jsonl(v1_folder / "per_question.jsonl")}
            if len(v1_rows) != QUESTION_COUNT:
                raise RuntimeError("Phase 15 G1 v1 per-question output is incomplete")
            for qid, expected in contexts["G1"].items():
                if v1_rows[qid].get("context_ids") != [row["context_id"] for row in expected]:
                    raise RuntimeError(f"Phase 15 G1 Top-5 context IDs changed for {qid}")
                if v1_rows[qid].get("context_chunk_ids") != [row["chunk_id"] for row in expected]:
                    raise RuntimeError(f"Phase 15 G1 Top-5 chunk order changed for {qid}")
            retry_folder = root / OUT / PREVIOUS_RETRY_G1
            retry_manifest = _read_json(retry_folder / "experiment_manifest.json")
            if retry_manifest.get("input_hashes") != frozen["hashes"]:
                raise RuntimeError("Phase 15.2 G1 v2.1 frozen input hashes differ")
            retry_rows = {str(row["question_id"]): row for row in read_jsonl(retry_folder / "per_question.jsonl")}
            for qid, expected in contexts["G1"].items():
                if retry_rows[qid].get("context_ids") != [row["context_id"] for row in expected]:
                    raise RuntimeError(f"Phase 15.2 E4 Top-5 context IDs changed for {qid}")
                if retry_rows[qid].get("context_chunk_ids") != [row["chunk_id"] for row in expected]:
                    raise RuntimeError(f"Phase 15.2 E4 Top-5 chunk order changed for {qid}")
    retry_manifest = _read_json(root / OUT / PREVIOUS_RETRY_G1 / "experiment_manifest.json")
    model_info = _preflight(root)
    frozen_model = retry_manifest.get("generator") or {}
    for key in ("default_model", "model_digest", "runtime_version"):
        if model_info.get(key) != frozen_model.get(key):
            raise RuntimeError(f"Configured generator {key} differs from frozen Phase 15.2")
    if model_info.get("default_model") != "gemma2:9b" or model_info.get("runtime_version") != "0.35.0":
        raise RuntimeError("Phase 15.3 requires the frozen Gemma 2 9B / Ollama 0.35.0 runtime")
    return frozen, model_info, prompt, contexts, baseline_tokens


def call_ollama_v22(*, model: str, system_prompt: str, user_prompt: str,
                    base_url: str = OLLAMA_BASE_URL, timeout: int = 900,
                    session: requests.Session | None = None) -> dict[str, Any]:
    """Stream and preserve the complete raw response under the one changed option."""
    schema = json.loads((ROOT / "schemas/generation_output_v2.schema.json").read_text(encoding="utf-8"))
    body = {
        "model": model, "stream": True, "format": schema, "keep_alive": "30m",
        "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
        "options": generation_options_v22(),
    }
    client = session or requests.Session()
    started = time.perf_counter()
    first_token: float | None = None
    parts: list[str] = []
    done: dict[str, Any] = {}
    error: str | None = None
    try:
        with client.post(f"{base_url.rstrip('/')}/api/chat", json=body, timeout=timeout, stream=True) as response:
            response.raise_for_status()
            for raw_line in response.iter_lines(decode_unicode=True):
                if not raw_line:
                    continue
                try:
                    event = json.loads(raw_line)
                except json.JSONDecodeError as exc:
                    error = f"stream_event_json_error: {exc}"
                    continue
                content = (event.get("message") or {}).get("content") or ""
                if content:
                    if first_token is None:
                        first_token = time.perf_counter() - started
                    parts.append(str(content))
                if event.get("done"):
                    done = event
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    raw_output = "".join(parts)
    if not error and not done:
        error = "stream_interrupted: Ollama did not emit a final done event"
    parsed: Any = None
    parse_error: str | None = None
    if raw_output:
        try:
            parsed = json.loads(raw_output)
        except json.JSONDecodeError as exc:
            parse_error = f"{type(exc).__name__}: {exc}"
        if parse_error is None and not isinstance(parsed, dict):
            parse_error = "response_json_not_object"
    elif error is None:
        error = "Ollama returned no message content"
    count = done.get("eval_count")
    duration = done.get("eval_duration")
    return {
        "raw_output": raw_output, "raw_output_sha256": sha256_text(raw_output),
        "response_received": bool(raw_output), "parsed": parsed if isinstance(parsed, dict) else None,
        "parse_error": parse_error, "execution_error": error,
        "latency_seconds": time.perf_counter() - started,
        "ttft_seconds": first_token, "prompt_tokens": done.get("prompt_eval_count"),
        "completion_tokens": count,
        "tokens_per_second": count / (duration / 1e9) if count is not None and duration else None,
        "load_duration_ns": done.get("load_duration"), "done_reason": done.get("done_reason"),
        "prompt_eval_count": done.get("prompt_eval_count"), "completion_eval_count": count,
        "finish_reason": done.get("done_reason"), "final_event": done,
    }


def _run_question(*, question: dict[str, Any], contexts: list[dict[str, Any]], condition: str,
                  model: str, base_url: str, prompt: str, corpus_ids: set[str],
                  baseline_prompt_tokens: int, attempt_number: int,
                  call_fn: Any = call_ollama_v22) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    row, raw = _run_one_v2(question, contexts, condition=condition, model=model, base_url=base_url,
                           prompt=prompt, corpus_ids=corpus_ids, call_fn=call_fn)
    attempt = build_attempt_record(question_id=str(question["question_id"]), attempt_number=attempt_number,
                                   result=row, raw=raw | {
                                       "latency_seconds": row.get("latency_seconds"),
                                       "prompt_tokens": row.get("prompt_tokens"),
                                       "completion_tokens": row.get("completion_tokens"),
                                       "done_reason": row.get("done_reason"),
                                       "response_received": bool(raw.get("raw_output")),
                                   })
    audit = context_budget_audit(prompt_tokens=row.get("prompt_tokens"),
                                 baseline_prompt_tokens=baseline_prompt_tokens)
    attempt["context_window_budget"] = audit
    attempt["condition"] = condition
    attempt["raw_output_capture_status"] = "captured" if attempt["raw_output_preserved"] else "missing"
    raw.update({"condition": condition, "attempt_number": attempt_number,
                "raw_output_preserved": attempt["raw_output_preserved"],
                "raw_output_sha256": attempt["raw_output_sha256"],
                "context_window_budget": audit})
    row.update({"attempt_number": attempt_number, "context_window_budget": audit,
                "response_received": bool(raw.get("raw_output"))})
    return row, raw, attempt


def _attempt_metrics(attempts: list[dict[str, Any]], first_rows: list[dict[str, Any]], final_rows: list[dict[str, Any]]) -> dict[str, Any]:
    first = first_pass_metrics(attempts, question_count=QUESTION_COUNT)
    completion = [row.get("completion_tokens") for row in attempts]
    retry_triggered = sum(int(row.get("attempt_number", 1)) == 2 for row in attempts)
    retry_success = sum(int(row.get("attempt_number", 1)) == 2 and bool(row.get("attempt_valid")) for row in attempts)
    retry_failure = retry_triggered - retry_success
    audits = [row.get("context_window_budget") or {} for row in attempts if int(row.get("attempt_number", 1)) == 1]
    output_stats = _stats(completion)
    output_stats["min"] = min((int(value) for value in completion if value is not None), default=None)
    output_stats["max"] = max((int(value) for value in completion if value is not None), default=None)
    return {
        **first,
        "first_pass_json_parse_rate": first["first_pass_json_valid_rate"],
        "first_pass_citation_parse_rate": first["first_pass_citation_parse_rate"],
        "retry_trigger_count": retry_triggered, "retry_success_count": retry_success,
        "retry_failure_count": retry_failure, "maximum_attempts": MAX_ATTEMPTS,
        "final_json_parse_rate": sum(bool(r.get("json_parse_valid")) for r in final_rows) / len(final_rows),
        "final_schema_valid_rate": sum(bool(r.get("schema_valid")) for r in final_rows) / len(final_rows),
        "final_citation_parse_rate": sum(bool(r.get("citation_parse_valid")) for r in final_rows) / len(final_rows),
        "completion_truncation_count": sum(row.get("finish_reason") == "length" for row in attempts),
        "done_reason_length_count": sum(row.get("finish_reason") == "length" for row in attempts),
        "completion_truncation_first_pass_count": sum(row.get("done_reason") == "length" for row in first_rows),
        "completion_truncation_final_count": sum(row.get("done_reason") == "length" for row in final_rows),
        "completion_tokens_all_attempts": output_stats,
        "completion_tokens_ge_768_count": sum(row is not None and int(row) >= 768 for row in completion),
        "completion_tokens_ge_1024_count": sum(row is not None and int(row) >= 1024 for row in completion),
        "attempt_count": len(attempts), "attempt_records_preserved": len(attempts),
        "context_window_budget": {
            "question_count": len(audits),
            "input_truncation_count": sum(a.get("input_truncated") is True for a in audits),
            "input_truncation_unknown_count": sum(a.get("input_truncated") is None for a in audits),
            "prompt_eval_count_missing": sum(a.get("prompt_eval_count") is None for a in audits),
            "margin_stats": _stats([a.get("remaining_context_margin") for a in audits]),
            "all_fit": all(a.get("output_budget_fits_context_after_prompt") is True for a in audits),
            "detection_method": "actual Ollama prompt_eval_count versus same-input frozen v2 prompt_eval_count; /api/tokenize returned 404 on Ollama 0.35.0",
        },
    }


def _snapshot_succeeded(attempts: list[dict[str, Any]]) -> bool:
    return all(row.get("raw_output_preserved") is True
               and row.get("raw_output_sha256") == sha256_text(str(row.get("raw_output") or ""))
               and row.get("raw_output_hash_matches_client") is True for row in attempts)


def _run_condition(root: Path, *, condition: str, frozen: dict[str, Any], model_info: dict[str, Any], prompt: str,
                   contexts: dict[str, list[dict[str, Any]]], baseline_tokens: dict[str, int], repeat_subset: bool = True) -> dict[str, Any]:
    experiment_id = EXPERIMENTS[condition]
    folder = root / OUT / experiment_id
    if folder.exists() and any(folder.iterdir()):
        raise RuntimeError(f"Refusing to overwrite an existing v2.2 experiment folder: {folder}")
    folder.mkdir(parents=True, exist_ok=True)
    questions = frozen["questions"]
    qids = [str(row["question_id"]) for row in questions]
    by_id = {str(row["question_id"]): row for row in questions}
    context_manifest = []
    for qid in qids:
        context_manifest.append({"question_id": qid, "condition": condition,
            "contexts": [{"context_id": row["context_id"], "chunk_id": row["chunk_id"],
                          "document_id": row["document_id"], "page": row["page"],
                          "content_checksum": sha256_text(str(row["text"])), "rank": row.get("rank")}
                         for row in contexts[qid]]})
    _write_jsonl(folder / "context_manifest.jsonl", context_manifest)
    context_manifest_sha = sha256_file(folder / "context_manifest.jsonl")
    manifest = {
        "experiment_id": experiment_id, "phase": "15.3", "protocol_version": "2.2",
        "condition": "Oracle evidence" if condition == "G0" else "Frozen E4 Top-5",
        "created_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "question_count": len(questions), "question_ids_sha256": sha256_text("\n".join(qids)),
        "input_hashes": frozen["hashes"], "evaluation_corpus_v2_sha256": frozen["hashes"].get("evaluation_corpus_v2_sha256"),
        "grounded_silver_v1_sha256": frozen["hashes"].get("grounded_silver_v1_sha256"),
        "e4_manifest_sha256": frozen["hashes"].get("e4_manifest_sha256"),
        "e4_ranking_trace_sha256": frozen["hashes"].get("e4_ranking_trace_sha256"),
        "context_manifest_sha256": context_manifest_sha,
        "generator": model_info, "generation_parameters": generation_options_v22(),
        "generation_parameters_difference_from_v2": {"num_predict": {"v2": 768, "v2_2": MAX_OUTPUT_TOKENS}},
        "prompt_version": "generation_v2", "prompt_sha256": sha256_text(prompt),
        "schema_version": "generation_output_v2", "schema_sha256": sha256_file(root / "schemas/generation_output_v2.schema.json"),
        "structured_output_mode": "Ollama /api/chat JSON schema format; generation output schema v2",
        "context_length": CONTEXT_LENGTH, "context_window_audit_method": "same-input prompt_eval_count compared with immutable v2; Ollama 0.35 /api/tokenize unavailable",
        "retry_policy": {"maximum_attempts": MAX_ATTEMPTS, "trigger": ["JSON parse failure", "schema failure", "technical execution failure"],
                         "retry": "one fresh execution with identical inputs and configuration", "no_silent_json_repair": True},
        "context_ordering": "G0 evidence snapshot order; G1 E4 rank order; rank 1 = C1",
        "generation_semantics_changed": False, "citation_contract_changed": False,
        "benchmark_type": "AI-generated Grounded Silver; not Human Gold",
        "status": "running", "git_commit": _git_commit(root),
    }
    _write_json(folder / "experiment_manifest.json", manifest)

    attempts: list[dict[str, Any]] = []
    first_rows: list[dict[str, Any]] = []
    final_rows: list[dict[str, Any]] = []
    final_raw: list[dict[str, Any]] = []
    attempts_path = folder / "attempts.jsonl"
    raw_path = folder / "raw_outputs.jsonl"
    first_path = folder / "per_question_first_pass.jsonl"
    final_path = folder / "per_question.jsonl"
    audits: list[dict[str, Any]] = []
    corpus_ids = set(frozen["corpus_by_id"])
    for index, qid in enumerate(qids, 1):
        q = by_id[qid]
        row, raw, attempt = _run_question(question=q, contexts=contexts[qid], condition=condition,
            model=str(model_info["default_model"]), base_url=str(model_info["ollama_endpoint"]), prompt=prompt,
            corpus_ids=corpus_ids, baseline_prompt_tokens=baseline_tokens[qid], attempt_number=1)
        attempts.append(attempt); first_rows.append(row); audits.append({"question_id": qid, "condition": condition, **attempt["context_window_budget"]})
        _write_jsonl_append(attempts_path, attempt); _write_jsonl_append(raw_path, raw); _write_jsonl_append(first_path, row)
        latest_row, latest_raw, latest_attempt = row, raw, attempt
        if should_retry(row, attempt_number=1):
            latest_row, latest_raw, latest_attempt = _run_question(question=q, contexts=contexts[qid], condition=condition,
                model=str(model_info["default_model"]), base_url=str(model_info["ollama_endpoint"]), prompt=prompt,
                corpus_ids=corpus_ids, baseline_prompt_tokens=baseline_tokens[qid], attempt_number=2)
            attempts.append(latest_attempt)
            _write_jsonl_append(attempts_path, latest_attempt); _write_jsonl_append(raw_path, latest_raw)
        final_rows.append(latest_row); final_raw.append(latest_raw)
        _write_jsonl_append(final_path, latest_row)
        print(f"[{condition}] {index}/{len(qids)} {qid}: {latest_row['status']} (attempt {latest_attempt['attempt_number']}, done={latest_row.get('done_reason')})", flush=True)
    validate_attempt_records(attempts, question_ids=qids)
    if len(first_rows) != QUESTION_COUNT or len(final_rows) != QUESTION_COUNT:
        raise RuntimeError(f"{condition} run did not produce 169 question outputs")
    summary = _summary(final_rows, final_raw)
    protocol_metrics = _attempt_metrics(attempts, first_rows, final_rows)
    summary.update(protocol_metrics)
    summary["strict_citation_validity_rate"] = summary.get("strict_citation_validity_rate")
    _write_json(folder / "overall.json", summary)
    _write_json(folder / "citation_validation.json", {
        key: summary.get(key) for key in ("citation_count", "strict_valid_citation_count", "recoverable_valid_citation_count",
            "strict_citation_validity_rate", "recoverable_citation_validity_rate", "citation_parse_rate",
            "citation_error_taxonomy", "missing_citation_question_count", "required_evidence_citation_recall",
            "required_evidence_question_recall")})
    _write_json(folder / "context_window_budget.json", {
        "condition": condition, "question_count": QUESTION_COUNT, "context_length": CONTEXT_LENGTH,
        "configured_max_output_tokens": MAX_OUTPUT_TOKENS, "questions": len(audits),
        "input_truncation_count": sum(row.get("input_truncated") is True for row in audits),
        "unknown_count": sum(row.get("input_truncated") is None for row in audits),
        "prompt_tokens": _stats([row.get("prompt_tokens") for row in audits]),
        "remaining_context_margin": _stats([row.get("remaining_context_margin") for row in audits]),
        "all_output_budgets_fit": all(row.get("output_budget_fits_context_after_prompt") is True for row in audits),
        "detection_method": "Compare prompt_eval_count with the same frozen question/context/prompt's v2 count; Ollama 0.35.0 /api/tokenize unavailable.",
    })
    _write_jsonl(folder / "context_window_budget.jsonl", audits)
    _write_json(folder / "failure_analysis.json", {
        "status_counts": summary["status_counts"], "retry_trigger_count": protocol_metrics["retry_trigger_count"],
        "retry_success_count": protocol_metrics["retry_success_count"], "retry_failure_count": protocol_metrics["retry_failure_count"],
        "done_reason_length_attempts": protocol_metrics["done_reason_length_count"],
        "failures": [{"question_id": row["question_id"], "attempt_number": row["attempt_number"],
                      "parse_error": row.get("parse_error"), "schema_error": row.get("schema_error"),
                      "execution_error": row.get("execution_error"), "finish_reason": row.get("finish_reason")}
                     for row in attempts if not row.get("attempt_valid")],
        "unsupported_factual_claims_automatically_judged": False,
    })
    attempts_intact = _snapshot_succeeded(attempts)
    repeatability = _repeatability(root, condition=condition, questions=questions[:REPEAT_COUNT], contexts=contexts,
        model_info=model_info, prompt=prompt, corpus_ids=corpus_ids, baseline_tokens=baseline_tokens,
        reference_rows=final_rows[:REPEAT_COUNT], reference_raw=final_raw[:REPEAT_COUNT], output_folder=folder)
    _write_json(folder / "repeatability.json", repeatability)
    manifest.update({"status": "completed" if summary["generation_error_count"] == 0 else "completed_with_generation_errors",
        "completed_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "attempt_counts": dict(sorted(Counter(str(row["attempt_number"]) for row in attempts).items())),
        "raw_attempts_preserved_and_hash_valid": attempts_intact,
        "summary_sha256": sha256_file(folder / "overall.json")})
    _write_json(folder / "experiment_manifest.json", manifest)
    return {"folder": folder, "manifest": manifest, "summary": summary, "attempts": attempts,
            "first_rows": first_rows, "final_rows": final_rows, "final_raw": final_raw,
            "audits": audits, "attempts_intact": attempts_intact}


def _repeatability(root: Path, *, condition: str, questions: list[dict[str, Any]], contexts: dict[str, list[dict[str, Any]]],
                   model_info: dict[str, Any], prompt: str, corpus_ids: set[str], baseline_tokens: dict[str, int],
                   reference_rows: list[dict[str, Any]], reference_raw: list[dict[str, Any]], output_folder: Path) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    first_by_id = {str(row["question_id"]): row for row in reference_rows}
    first_raw_by_id = {str(row["question_id"]): row for row in reference_raw}
    repeat_attempts: list[dict[str, Any]] = []
    repeat_raw: list[dict[str, Any]] = []
    for i, q in enumerate(questions, 1):
        qid = str(q["question_id"])
        row, raw, attempt = _run_question(question=q, contexts=contexts[qid], condition=condition,
            model=str(model_info["default_model"]), base_url=str(model_info["ollama_endpoint"]), prompt=prompt,
            corpus_ids=corpus_ids, baseline_prompt_tokens=baseline_tokens[qid], attempt_number=1)
        repeat_attempts.append(attempt); repeat_raw.append(raw)
        final_row = row
        if should_retry(row, attempt_number=1):
            final_row, raw2, attempt2 = _run_question(question=q, contexts=contexts[qid], condition=condition,
                model=str(model_info["default_model"]), base_url=str(model_info["ollama_endpoint"]), prompt=prompt,
                corpus_ids=corpus_ids, baseline_prompt_tokens=baseline_tokens[qid], attempt_number=2)
            repeat_attempts.append(attempt2); repeat_raw.append(raw2)
        ref = first_by_id[qid]
        ref_raw = first_raw_by_id[qid]
        final_repeat_raw = repeat_raw[-1]
        try:
            ref_parsed = json.loads(ref_raw.get("raw_output") or "") if ref.get("json_parse_valid") else None
        except json.JSONDecodeError:
            ref_parsed = None
        try:
            new_parsed = json.loads(final_repeat_raw.get("raw_output") or "") if final_row.get("json_parse_valid") else None
        except json.JSONDecodeError:
            new_parsed = None
        from .protocol_v2 import jaccard, normalized_answer_similarity
        ref_citations = set(map(str, ref.get("citations") or []))
        new_citations = set(map(str, final_row.get("citations") or []))
        records.append({
            "question_id": qid,
            "raw_exact_match": bool(ref_raw.get("raw_output") == final_repeat_raw.get("raw_output")),
            "parsed_exact_match": bool(ref_parsed == new_parsed) if ref_parsed is not None and new_parsed is not None else False,
            "status_match": ref.get("status") == final_row.get("status"),
            "normalized_answer_similarity": normalized_answer_similarity(str(ref.get("answer") or ""), str(final_row.get("answer") or "")),
            "citation_set_exact_match": ref_citations == new_citations,
            "citation_set_jaccard": jaccard(ref_citations, new_citations),
            "reference_status": ref.get("status"), "repeat_status": final_row.get("status"),
        })
        print(f"[{condition} repeat] {i}/{len(questions)} {qid}: {final_row['status']}", flush=True)
    _write_jsonl(output_folder / "repeatability_attempts.jsonl", repeat_attempts)
    _write_jsonl(output_folder / "repeatability_raw_outputs.jsonl", repeat_raw)
    _write_jsonl(output_folder / "repeatability_per_question.jsonl", records)
    return {
        "subset_question_count": len(questions), "second_execution_attempt_count": len(repeat_attempts),
        "raw_exact_match_rate": sum(row["raw_exact_match"] for row in records) / len(records) if records else None,
        "parsed_exact_match_rate": sum(row["parsed_exact_match"] for row in records) / len(records) if records else None,
        "status_match_rate": sum(row["status_match"] for row in records) / len(records) if records else None,
        "normalized_answer_similarity_mean": statistics.fmean(row["normalized_answer_similarity"] for row in records if row["normalized_answer_similarity"] is not None) if records else None,
        "citation_set_exact_match_rate": sum(row["citation_set_exact_match"] for row in records) / len(records) if records else None,
        "citation_set_jaccard_mean": statistics.fmean(row["citation_set_jaccard"] for row in records) if records else None,
        "records": records,
        "interpretation": "Primary run versus a separate second execution of the same fixed first 20 question subset; retries remain limited to one per execution.",
    }


def run_phase15_3(root: Path = ROOT) -> dict[str, Any]:
    root = root.resolve()
    frozen, model_info, prompt, all_contexts, baseline_tokens = _freeze(root)
    protected_before = _capture_protected(root)
    immutable_before = _capture_immutable_v15(root)
    # A pre-existing v2.2 result is immutable: use a new run only after a clean preflight.
    for folder in EXPERIMENTS.values():
        target = root / OUT / folder
        if target.exists() and any(target.iterdir()):
            raise RuntimeError(f"Existing Phase 15.3 output prevents overwrite: {target}")
    e4_v2_trace_sha = frozen["hashes"].get("e4_ranking_trace_sha256")
    input_freeze = {"evaluation_corpus_v2_sha256": frozen["hashes"].get("evaluation_corpus_v2_sha256"),
        "grounded_silver_v1_sha256": frozen["hashes"].get("grounded_silver_v1_sha256"),
        "e4_manifest_sha256": frozen["hashes"].get("e4_manifest_sha256"),
        "e4_ranking_trace_sha256": e4_v2_trace_sha, "question_count": len(frozen["questions"]),
        "question_ids_sha256": sha256_text("\n".join(str(q["question_id"]) for q in frozen["questions"]))}
    phase_root = root / PHASE_DIR
    phase_root.mkdir(parents=True, exist_ok=True)
    if any(phase_root.iterdir()):
        raise RuntimeError(f"Refusing to overwrite existing Phase 15.3 report folder: {phase_root}")
    _write_json(phase_root / "input_freeze.json", input_freeze)
    _write_json(phase_root / "protected_hashes_before.json", {"phase15_immutable": immutable_before, "protected": protected_before})

    results: dict[str, dict[str, Any]] = {}
    for condition in ("G0", "G1"):
        results[condition] = _run_condition(root, condition=condition, frozen=frozen, model_info=model_info,
            prompt=prompt, contexts=all_contexts[condition], baseline_tokens=baseline_tokens[condition])

    # Configuration parity across both independent manifests is a hard requirement.
    if not same_generation_config(results["G0"]["manifest"], results["G1"]["manifest"]):
        raise RuntimeError("G0 and G1 do not share the exact v2.2 generation configuration")
    summary_v21 = _read_json(root / OUT / PREVIOUS_RETRY_G1 / "overall.json")
    v21_attempts = read_jsonl(root / OUT / PREVIOUS_RETRY_G1 / "attempts.jsonl")
    v21_final_attempts = {str(row["question_id"]): row for row in
                          sorted(v21_attempts, key=lambda row: int(row["attempt_number"]))}
    summary_v21 = summary_v21 | {
        "completion_truncation_count": sum(row.get("finish_reason") == "length" for row in v21_attempts),
        "completion_truncation_first_pass_count": sum(row.get("finish_reason") == "length" and row.get("attempt_number") == 1 for row in v21_attempts),
        "completion_truncation_final_count": sum(row.get("finish_reason") == "length" for row in v21_final_attempts.values()),
    }
    comparison = compare_v21_v22(summary_v21, results["G1"]["summary"])
    comparison["same_question_ids"] = True
    comparison["same_e4_top5_contexts_and_order"] = True
    comparison["answer_metric_interpretation"] = "Descriptive only; this is output-budget reliability correction, not prompt quality improvement."
    _write_json(phase_root / "v2_1_vs_v2_2_comparison.json", comparison)

    v22_attempts = results["G1"]["attempts"]
    recovery = [previous_failure_recovery(question_id=qid, v21_attempts=v21_attempts, v22_attempts=v22_attempts)
                for qid in OLD_FAILURE_IDS]
    _write_json(phase_root / "previously_truncated_questions.json", recovery)
    budget_audits = [{"condition": condition, **audit} for condition in ("G0", "G1") for audit in results[condition]["audits"]]
    ready = readiness_v22(g0_summary=results["G0"]["summary"], g1_summary=results["G1"]["summary"],
        attempts_preserved=all(result["attempts_intact"] for result in results.values()), budget_audits=budget_audits)
    _write_json(phase_root / "phase16_generation_readiness_v2_2.json", ready)
    if ready["phase16_generation_ready"]:
        ragas_path = root / "data/evaluation/generation/ragas_input_v2_2.jsonl"
        if ragas_path.exists():
            raise RuntimeError(f"Refusing to overwrite existing RAGAS input export: {ragas_path}")
        exports = []
        for condition in ("G0", "G1"):
            for question, result in zip(frozen["questions"], results[condition]["final_rows"]):
                exports.append(build_ragas_row_v22(question=question, answer=result["answer"],
                    contexts=all_contexts[condition][str(question["question_id"])], condition=condition,
                    model="Gemma 2 9B", attempts=int(result["attempt_number"]), ready=True))
        _write_jsonl(ragas_path, exports)

    protected_after = _capture_protected(root)
    immutable_after = _capture_immutable_v15(root)
    immutable_diff = sorted(key for key in set(immutable_before) | set(immutable_after)
                            if immutable_before.get(key) != immutable_after.get(key))
    protected_diff = sorted(key for key in set(protected_before) | set(protected_after)
                            if protected_before.get(key) != protected_after.get(key))
    try:
        health_response = requests.get("http://127.0.0.1:8767/_stcore/health", timeout=5)
        health = {"url": "http://127.0.0.1:8767/_stcore/health", "status_code": health_response.status_code,
                  "healthy": health_response.status_code == 200, "body": health_response.text[:200]}
    except Exception as exc:
        health = {"url": "http://127.0.0.1:8767/_stcore/health", "status_code": None,
                  "healthy": False, "error": f"{type(exc).__name__}: {exc}"}
    compatibility = {"status": "passed" if health["healthy"] and not immutable_diff and not protected_diff else "failed",
        "production_streamlit_http": health,
        "rag_store_sqlite3_before": protected_before.get("rag_store.sqlite3"),
        "rag_store_sqlite3_after": protected_after.get("rag_store.sqlite3"),
        "rag_store_sqlite3_unchanged": protected_before.get("rag_store.sqlite3") == protected_after.get("rag_store.sqlite3"),
        "phase15_phase15_1_phase15_2_immutable": not immutable_diff, "immutable_differences": immutable_diff,
        "protected_artifacts_unchanged": not protected_diff, "protected_differences": protected_diff,
        "production_prompt_unchanged": True}
    _write_json(phase_root / "compatibility.json", compatibility)
    report = {"protocol_version": "2.2", "input_freeze": input_freeze,
        "G0": {"experiment_id": EXPERIMENTS["G0"], "overall": results["G0"]["summary"]},
        "G1": {"experiment_id": EXPERIMENTS["G1"], "overall": results["G1"]["summary"]},
        "v2_1_vs_v2_2": comparison, "previous_failure_recovery": recovery,
        "phase16_readiness": ready, "ragas_export_created": ready["phase16_generation_ready"],
        "compatibility": compatibility}
    _write_json(phase_root / "summary.json", report)
    if compatibility["status"] != "passed":
        raise RuntimeError("Phase 15.3 protected artifact or production compatibility check failed")
    return report
