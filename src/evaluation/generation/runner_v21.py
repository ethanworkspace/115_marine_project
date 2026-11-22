"""Phase 15.2: frozen G1 generation with a single technical retry."""

from __future__ import annotations

import json
import statistics
import subprocess
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from .contexts import build_e4_top5_contexts
from .frozen import read_jsonl, sha256_file, validate_frozen_inputs
from .ollama import GENERATION_OPTIONS
from .protocol_v2 import jaccard, normalized_answer_similarity, sha256_text
from .retry_v21 import (
    MAX_ATTEMPTS,
    build_attempt_record,
    build_ragas_export_row,
    classify_failure,
    first_pass_metrics,
    readiness,
    retry_impact,
    should_retry,
    validate_attempt_records,
)
from .runner import _capture_protected, _git_commit, _preflight
from .runner_v2 import (
    CONDITIONS,
    OUT,
    _read_jsonl,
    _run_one_v2,
    _stats,
    _summary,
    _write_json,
    _write_jsonl,
)

ROOT = Path(__file__).resolve().parents[3]
PHASE = OUT / "phase15_2"
EXPERIMENT_ID = "G1_grounded_e4_top5_generation_v2_1"
EXPERIMENT = OUT / EXPERIMENT_ID
G1_V2 = OUT / CONDITIONS["G1"]
G0_V2 = OUT / CONDITIONS["G0"]
OLD_G1 = OUT / "G1_grounded_e4_top5_generation_v2"
OLD_G0 = OUT / "G0_grounded_oracle_generation_v2"
REPEAT_COUNT = 20


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_attempts(path: Path) -> list[dict[str, Any]]:
    return read_jsonl(path) if path.is_file() else []


def _snapshot_paths(root: Path) -> dict[str, dict[str, Any]]:
    paths: set[Path] = set()
    for directory in (
        root / OUT / "G0_grounded_oracle_generation_v1",
        root / OUT / "G1_grounded_e4_top5_generation_v1",
        root / OLD_G0,
        root / OLD_G1,
        root / OUT / "phase15_citation_recovery_audit",
    ):
        if directory.is_dir():
            paths.update(path for path in directory.rglob("*") if path.is_file())
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


def _health_status(url: str = "http://127.0.0.1:8767/_stcore/health") -> dict[str, Any]:
    try:
        response = requests.get(url, timeout=5)
        return {"url": url, "status_code": response.status_code, "healthy": response.status_code == 200,
                "body": response.text[:200]}
    except Exception as exc:
        return {"url": url, "status_code": None, "healthy": False,
                "error": f"{type(exc).__name__}: {exc}"}


def _freeze_and_validate(root: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, list[dict[str, Any]]]]:
    frozen = validate_frozen_inputs(root)
    if frozen["question_count"] != 169:
        raise RuntimeError("Phase 15.2 requires the frozen 169-question Grounded Silver v1 set")
    p15_manifest = _read_json(root / OUT / "generation_retrieval_manifest.json")
    if frozen["hashes"] != p15_manifest.get("input_hashes"):
        raise RuntimeError("Frozen evaluation inputs differ from Phase 15")
    old_manifest = _read_json(root / OLD_G1 / "experiment_manifest.json")
    if old_manifest.get("status") != "completed" or old_manifest.get("question_count") != 169:
        raise RuntimeError("Phase 15.1 G1 v2 experiment is not a completed 169-question run")
    old_context_manifest = read_jsonl(root / OLD_G1 / "context_manifest.jsonl")
    old_rows = {str(row["question_id"]): row for row in read_jsonl(root / OLD_G1 / "per_question.jsonl")}
    if len(old_rows) != 169:
        raise RuntimeError("Phase 15.1 G1 v2 per-question output is incomplete")
    old_contexts = {str(row["question_id"]): row for row in old_context_manifest}
    if len(old_contexts) != 169:
        raise RuntimeError("Phase 15.1 G1 v2 context manifest is incomplete")
    contexts: dict[str, list[dict[str, Any]]] = {}
    for question in frozen["questions"]:
        qid = str(question["question_id"])
        context_rows = build_e4_top5_contexts(question, frozen["e4_trace_by_question"][qid], frozen["corpus_by_id"])
        expected_ids = [str(row["context_id"]) for row in context_rows]
        expected_chunks = [str(row["chunk_id"]) for row in context_rows]
        if old_rows[qid].get("context_ids") != expected_ids or old_rows[qid].get("context_chunk_ids") != expected_chunks:
            raise RuntimeError(f"Frozen E4 Top-5 context/order differs from Phase 15.1 for {qid}")
        old_context_record = old_contexts[qid]
        old_manifest_ids = [str(row["context_id"]) for row in old_context_record.get("contexts", [])]
        old_manifest_chunks = [str(row["chunk_id"]) for row in old_context_record.get("contexts", [])]
        if old_manifest_ids != expected_ids or old_manifest_chunks != expected_chunks:
            raise RuntimeError(f"Phase 15.1 context manifest mismatch for {qid}")
        contexts[qid] = context_rows

    prompt = (root / "prompts/generation_v2.txt").read_text(encoding="utf-8").strip()
    prompt_hash = sha256_text(prompt)
    schema_hash = sha256_file(root / "schemas/generation_output_v2.schema.json")
    if prompt_hash != old_manifest.get("prompt_sha256") or schema_hash != old_manifest.get("schema_sha256"):
        raise RuntimeError("Generation v2 prompt/schema changed since Phase 15.1")
    if old_manifest.get("generation_parameters") != GENERATION_OPTIONS:
        raise RuntimeError("Generation parameters changed since Phase 15.1")

    model_info = _preflight(root)
    old_model = old_manifest.get("generator") or {}
    for key, actual in (("default_model", model_info.get("default_model")),
                        ("model_digest", model_info.get("model_digest")),
                        ("runtime_version", model_info.get("runtime_version"))):
        old_key = key
        if old_model.get(old_key) != actual:
            raise RuntimeError(f"Configured generator {key} differs from Phase 15.1")
    return frozen, model_info, contexts


def _failure_forensics(root: Path, old_manifest: dict[str, Any]) -> dict[str, Any]:
    raw_rows = read_jsonl(root / OLD_G1 / "raw_outputs.jsonl")
    question_rows = {str(row["question_id"]): row for row in read_jsonl(root / OLD_G1 / "per_question.jsonl")}
    candidates = []
    for raw in raw_rows:
        parsed = raw.get("parsed_model_output")
        if parsed is not None and not raw.get("execution_error") and not raw.get("parse_error") and not raw.get("validation_error"):
            continue
        row = question_rows[str(raw["question_id"])]
        candidates.append({
            "question_id": str(raw["question_id"]),
            "raw_output_sha256": raw.get("raw_output_sha256") or sha256_text(str(raw.get("raw_output") or "")),
            "raw_length": len(str(raw.get("raw_output") or "")),
            "finish_reason": row.get("done_reason"),
            "parse_error": raw.get("parse_error"),
            "schema_error": raw.get("validation_error"),
            "execution_error": raw.get("execution_error"),
            "runtime_token_counts": {
                "prompt_tokens": row.get("prompt_tokens"),
                "completion_tokens": row.get("completion_tokens"),
            },
            "failure_classification": classify_failure(
                raw_output=str(raw.get("raw_output") or ""), parse_error=raw.get("parse_error"),
                schema_error=raw.get("validation_error"), execution_error=raw.get("execution_error"),
                finish_reason=row.get("done_reason"),
            ),
            "benchmark_type": "AI-generated Grounded Silver; not Human Gold",
        })
    report = {
        "phase": "15.2", "source_experiment": EXPERIMENT_ID.replace("_v2_1", "_v2"),
        "forensic_source_is_immutable_phase15_1_raw_output": True,
        "phase15_1_manifest_sha256": sha256_file(root / OLD_G1 / "experiment_manifest.json"),
        "question_count_with_technical_failure": len(candidates),
        "failures": candidates,
        "classification_counts": dict(sorted(Counter(row["failure_classification"] for row in candidates).items())),
        "interpretation": "No raw output was repaired or rewritten. A finish reason of length plus incomplete JSON is classified as truncated_json.",
    }
    _write_json(root / PHASE / "failure_forensics.json", report)
    return report


def _make_manifest(root: Path, frozen: dict[str, Any], model_info: dict[str, Any],
                   immutable_snapshot: dict[str, Any], protected_snapshot: dict[str, Any]) -> dict[str, Any]:
    out = root / EXPERIMENT
    out.mkdir(parents=True, exist_ok=True)
    path = out / "experiment_manifest.json"
    prompt = (root / "prompts/generation_v2.txt").read_text(encoding="utf-8").strip()
    current = {
        "experiment_id": EXPERIMENT_ID,
        "phase": "15.2",
        "status": "running",
        "benchmark_type": "AI-generated Grounded Silver; not Human Gold",
        "question_count": 169,
        "input_hashes": frozen["hashes"],
        "generator": model_info,
        "generation_parameters": dict(GENERATION_OPTIONS),
        "prompt_version": "generation_v2",
        "prompt_sha256": sha256_text(prompt),
        "schema_sha256": sha256_file(root / "schemas/generation_output_v2.schema.json"),
        "structured_output_mode": "Ollama native JSON Schema constrained output (format=schema), unchanged from v2",
        "execution_protocol": {"version": "2.1", "maximum_attempts": MAX_ATTEMPTS,
                               "retry_condition": "fresh execution after JSON parse, schema validation, or technical execution failure",
                               "retry_changes": [], "same_model_prompt_schema_question_context_and_parameters": True,
                               "no_json_repair": True},
        "condition": "G1 E4 Top-5; identical question IDs, context IDs, chunk IDs, and order to Phase 15.1 G1 v2",
        "context_manifest_sha256": sha256_file(root / OLD_G1 / "context_manifest.jsonl"),
        "phase15_1_g1_v2_manifest_sha256": sha256_file(root / OLD_G1 / "experiment_manifest.json"),
        "phase15_1_immutable_snapshot": immutable_snapshot,
        "protected_artifacts_before": protected_snapshot,
        "git_commit": _git_commit(root),
        "created_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "generation_semantics_unchanged": True,
        "g0_handling": "Reuse immutable G0 Oracle v2; only G1 receives v2.1 technical retries.",
        "reference_answer_or_evidence_label_sent_to_model": False,
    }
    if path.is_file():
        previous = _read_json(path)
        for key in ("input_hashes", "generation_parameters", "prompt_sha256", "schema_sha256",
                    "context_manifest_sha256", "phase15_1_g1_v2_manifest_sha256"):
            if previous.get(key) != current.get(key):
                raise RuntimeError(f"Existing v2.1 output checkpoint has incompatible {key}")
        if previous.get("execution_protocol") != current["execution_protocol"]:
            raise RuntimeError("Existing v2.1 checkpoint uses a different retry protocol")
        current["created_at_utc"] = previous.get("created_at_utc")
    _write_json(path, current)
    return current


def _attempt_row(question: dict[str, Any], attempt_number: int, model_info: dict[str, Any],
                 prompt: str, contexts: list[dict[str, Any]], corpus_ids: set[str]) -> dict[str, Any]:
    result, raw = _run_one_v2(question, contexts, condition="G1_v2_1",
                              model=model_info["default_model"], base_url=model_info["ollama_endpoint"],
                              prompt=prompt, corpus_ids=corpus_ids)
    record = build_attempt_record(question_id=str(question["question_id"]), attempt_number=attempt_number,
                                  result=result, raw=raw)
    record["condition"] = "G1_v2_1"
    record["raw_output_capture_status"] = "captured" if raw.get("raw_output") else "empty_response_preserved"
    return record


def _checkpoint_attempts(path: Path, attempts: list[dict[str, Any]], order: dict[str, int]) -> None:
    attempts.sort(key=lambda row: (order[str(row["question_id"])], int(row["attempt_number"])))
    _write_jsonl(path, attempts)


def _run_g1(root: Path, frozen: dict[str, Any], model_info: dict[str, Any],
            contexts: dict[str, list[dict[str, Any]]], manifest: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    attempts_path = root / EXPERIMENT / "attempts.jsonl"
    attempts = _read_attempts(attempts_path)
    qids = [str(row["question_id"]) for row in frozen["questions"]]
    order = {qid: index for index, qid in enumerate(qids)}
    if attempts:
        validate_attempt_records(attempts, question_ids=[qid for qid in qids if any(str(a["question_id"]) == qid for a in attempts)])
    by_key = {(str(row["question_id"]), int(row["attempt_number"])): row for row in attempts}
    prompt = (root / "prompts/generation_v2.txt").read_text(encoding="utf-8").strip()
    corpus_ids = set(frozen["corpus_by_id"])
    for index, question in enumerate(frozen["questions"], 1):
        qid = str(question["question_id"])
        first = by_key.get((qid, 1))
        if first is None:
            first = _attempt_row(question, 1, model_info, prompt, contexts[qid], corpus_ids)
            attempts.append(first)
            by_key[(qid, 1)] = first
            _checkpoint_attempts(attempts_path, attempts, order)
        final = first
        if should_retry(first["result"] | {"execution_error": first.get("execution_error")}, attempt_number=1):
            second = by_key.get((qid, 2))
            if second is None:
                second = _attempt_row(question, 2, model_info, prompt, contexts[qid], corpus_ids)
                attempts.append(second)
                by_key[(qid, 2)] = second
                _checkpoint_attempts(attempts_path, attempts, order)
            final = second
        if index == 1 or index % 5 == 0 or index == len(frozen["questions"]):
            print(f"G1 v2.1 {index}/169; attempts={sum(str(x['question_id']) == qid for x in attempts)}; final_valid={final['attempt_valid']}", flush=True)
        manifest["progress"] = {"questions_started": index, "questions_completed": sum((qid2, 1) in by_key and (
            should_retry(by_key[(qid2, 1)]["result"] | {"execution_error": by_key[(qid2, 1)].get("execution_error")}, attempt_number=1)
            and (qid2, 2) in by_key or not should_retry(by_key[(qid2, 1)]["result"] | {"execution_error": by_key[(qid2, 1)].get("execution_error")}, attempt_number=1)
        ) for qid2 in qids), "attempts_written": len(attempts)}
        _write_json(root / EXPERIMENT / "experiment_manifest.json", manifest)

    validate_attempt_records(attempts, question_ids=qids)
    _checkpoint_attempts(attempts_path, attempts, order)
    by_question: dict[str, list[dict[str, Any]]] = {qid: [] for qid in qids}
    for row in attempts:
        by_question[str(row["question_id"])].append(row)
    first_pass, finals, final_raw = [], [], []
    for qid in qids:
        rows = sorted(by_question[qid], key=lambda row: int(row["attempt_number"]))
        first, final = rows[0], rows[-1]
        first_pass.append(first["result"])
        final_row = dict(final["result"])
        final_row["generation_attempts"] = len(rows)
        final_row["final_output_source"] = f"attempt_{final['attempt_number']}"
        finals.append(final_row)
        final_raw.append({
            "question_id": qid, "condition": "G1_v2_1", "model": model_info["default_model"],
            "prompt_version": "generation_v2", "raw_output": final["raw_output"],
            "raw_output_sha256": final["raw_output_sha256"],
            "raw_output_preserved": bool(final.get("raw_output_preserved")),
            "parse_error": final.get("parse_error"), "validation_error": final.get("schema_error"),
            "execution_error": final.get("execution_error"),
            "parsed_model_output": ({
                "question_id": qid, "status": final["result"].get("model_status"),
                "answer": final["result"].get("answer"), "citations": final["result"].get("citations"),
            } if final["result"].get("json_parse_valid") else None),
            "response_received": bool(final["raw_output"]), "final_output_source": final_row["final_output_source"],
        })
    _write_jsonl(root / EXPERIMENT / "per_question_first_pass.jsonl", first_pass)
    _write_jsonl(root / EXPERIMENT / "per_question.jsonl", finals)
    _write_jsonl(root / EXPERIMENT / "raw_outputs.jsonl", final_raw)
    _write_json(root / EXPERIMENT / "experiment_manifest.json", manifest)
    return attempts, first_pass, finals, final_raw


def _repeatability(first_rows: list[dict[str, Any]], final_rows: list[dict[str, Any]],
                   attempts: list[dict[str, Any]], qids: list[str]) -> dict[str, Any]:
    first_map = {str(row["question_id"]): row for row in first_rows}
    final_map = {str(row["question_id"]): row for row in final_rows}
    attempt_1 = {str(row["question_id"]): row for row in attempts if int(row["attempt_number"]) == 1}
    comparisons = []
    for qid in qids[:REPEAT_COUNT]:
        left, right = first_map[qid], final_map[qid]
        left_raw = attempt_1[qid]["raw_output"]
        final_attempt = next(row for row in attempts if str(row["question_id"]) == qid and
                             row["attempt_number"] == final_map[qid]["generation_attempts"])
        left_citations, right_citations = set(map(str, left.get("citations") or [])), set(map(str, right.get("citations") or []))
        comparisons.append({
            "question_id": qid,
            "raw_exact_match": left_raw == final_attempt["raw_output"],
            "parsed_exact_match": all(left.get(key) == right.get(key) for key in ("question_id", "status", "answer", "citations")),
            "status_match": left.get("status") == right.get("status"),
            "normalized_answer_similarity": normalized_answer_similarity(str(left.get("answer") or ""), str(right.get("answer") or "")),
            "citation_set_exact_match": left_citations == right_citations,
            "citation_set_jaccard": jaccard(left_citations, right_citations),
            "retry_used": int(right.get("generation_attempts", 1)) > 1,
        })
    def rate(key: str) -> float | None:
        return sum(bool(row[key]) for row in comparisons) / len(comparisons) if comparisons else None
    return {
        "subset_questions": len(comparisons), "comparison": "first attempt vs final v2.1 protocol result",
        "raw_exact_match_rate": rate("raw_exact_match"), "parsed_exact_match_rate": rate("parsed_exact_match"),
        "status_match_rate": rate("status_match"),
        "normalized_answer_similarity_mean": statistics.fmean(row["normalized_answer_similarity"] for row in comparisons) if comparisons else None,
        "citation_set_exact_match_rate": rate("citation_set_exact_match"),
        "citation_set_jaccard_mean": statistics.fmean(row["citation_set_jaccard"] for row in comparisons) if comparisons else None,
        "comparisons": comparisons,
    }


def _summary_add_protocol(summary: dict[str, Any], attempts: list[dict[str, Any]],
                          first_metrics: dict[str, Any], finals: list[dict[str, Any]],
                          attempts_intact: bool) -> dict[str, Any]:
    retry_rows = [row for row in finals if int(row.get("generation_attempts", 1)) > 1]
    retry_success = sum(bool(row.get("schema_valid")) for row in retry_rows)
    retry_failure = len(retry_rows) - retry_success
    retry_latency = [float(row.get("generation_latency_seconds") or 0) for row in attempts
                     if int(row["attempt_number"]) == 2]
    first_attempt_latency = [float(row.get("generation_latency_seconds") or 0) for row in attempts
                             if int(row["attempt_number"]) == 1]
    summary.update(first_metrics)
    summary["retry_protocol"] = {
        "maximum_attempts": MAX_ATTEMPTS,
        "retry_trigger_count": len(retry_rows),
        "retry_success_count": retry_success,
        "retry_failure_count": retry_failure,
        "attempt_1_valid_count": first_metrics["first_pass_valid_count"],
        "attempt_1_failure_count": len(finals) - first_metrics["first_pass_valid_count"],
        "attempt_count_total": len(attempts),
        "raw_output_attempt_records_intact": attempts_intact,
        "raw_output_attempt_record_integrity_rate": sum(bool(row.get("raw_output_preserved") and
            row.get("raw_output_sha256") == sha256_text(str(row.get("raw_output") or ""))) for row in attempts) / len(attempts) if attempts else None,
        "nonempty_raw_output_attempt_count": sum(bool(row.get("raw_output")) for row in attempts),
        "retry_latency_overhead_seconds": sum(retry_latency),
        "retry_latency_overhead": _stats(retry_latency),
        "first_attempt_latency_seconds": sum(first_attempt_latency),
        "complete_protocol_latency_seconds": sum(float(row.get("generation_latency_seconds") or 0) for row in attempts),
        "protocol_latency_overhead_percent": (sum(retry_latency) / sum(first_attempt_latency) * 100) if sum(first_attempt_latency) else None,
    }
    summary["raw_output_preservation_rate"] = 1.0 if attempts_intact else 0.0
    summary["final_nonempty_raw_output_rate"] = (
        float(summary.get("raw_response_received_count") or 0) / len(finals) if finals else None
    )
    return summary


def run_phase15_2(root: Path = ROOT) -> dict[str, Any]:
    root = root.resolve()
    phase_dir = root / PHASE
    phase_dir.mkdir(parents=True, exist_ok=True)
    frozen, model_info, contexts = _freeze_and_validate(root)
    old_manifest = _read_json(root / OLD_G1 / "experiment_manifest.json")
    immutable_before = _snapshot_paths(root)
    protected_before = _capture_protected(root)
    _failure_forensics(root, old_manifest)
    manifest = _make_manifest(root, frozen, model_info, immutable_before, protected_before)
    _write_json(phase_dir / "generation_execution_protocol_v2_1.json", {
        "version": "2.1",
        "maximum_attempts": MAX_ATTEMPTS,
        "attempt_1": "Use the frozen Phase 15.1 question, contexts, prompt, schema, model, and generation parameters.",
        "retry_condition": ["JSON parse failure", "schema validation failure", "technical generation failure"],
        "retry": "One fresh execution with the same inputs and settings; do not mention or repair the previous answer.",
        "acceptance": "Accept the first attempt that parses and validates against the unchanged schema.",
        "exhaustion": "If attempt 2 also fails, final status is generation_error and execution stops for that question.",
        "raw_output": "Preserve every complete attempt body and SHA-256 before evaluation; do not repair JSON.",
        "generation_semantics_changed": False,
        "citation_resolver_changed": False,
        "benchmark_type": "AI-generated Grounded Silver; not Human Gold",
    })
    attempts, first_rows, final_rows, final_raw = _run_g1(root, frozen, model_info, contexts, manifest)
    validate_attempt_records(attempts, question_ids=[str(row["question_id"]) for row in frozen["questions"]])
    first_metrics = first_pass_metrics(attempts, question_count=169)
    impacts = []
    attempt_map = {(str(row["question_id"]), int(row["attempt_number"])): row for row in attempts}
    for row in final_rows:
        qid = str(row["question_id"])
        impacts.append(retry_impact(attempt_map[(qid, 1)], attempt_map[(qid, int(row["generation_attempts"]))]))
    _write_jsonl(root / EXPERIMENT / "retry_impact.jsonl", impacts)
    retried_impacts = [row for row in impacts if row["attempt_2_used"]]
    _write_json(root / EXPERIMENT / "retry_impact_summary.json", {
        "retry_trigger_count": len(retried_impacts),
        "technical_retry_recovery_count": sum(bool(row["technical_retry_recovery"]) for row in retried_impacts),
        "retry_failure_count": sum(bool(row["final_attempt_failed"]) for row in retried_impacts),
        "status_changed_count": sum(bool(row["status_changed"]) for row in retried_impacts),
        "citation_set_changed_count": sum(bool(row["citation_set_changed"]) for row in retried_impacts),
        "completion_token_change": [row["completion_token_change"] for row in retried_impacts],
        "retry_latency_overhead_seconds": sum(float(row["latency_overhead_seconds"] or 0) for row in retried_impacts),
        "retried_question_ids": [row["question_id"] for row in retried_impacts],
    })
    attempts_intact = all(
        row.get("raw_output_preserved") is True
        and row.get("raw_output_sha256") == sha256_text(str(row.get("raw_output") or ""))
        and row.get("raw_output_hash_matches_client") is True
        for row in attempts
    )
    summary = _summary(final_rows, final_raw)
    summary = _summary_add_protocol(summary, attempts, first_metrics, final_rows, attempts_intact)
    _write_json(root / EXPERIMENT / "overall.json", summary)
    _write_json(root / EXPERIMENT / "citation_validation.json", {
        key: summary[key] for key in (
            "citation_count", "strict_valid_citation_count", "recoverable_valid_citation_count",
            "strict_citation_validity_rate", "recoverable_citation_validity_rate", "citation_parse_rate",
            "citation_error_taxonomy", "missing_citation_question_count", "required_evidence_citation_recall",
            "required_evidence_question_recall",
        )
    } | {"citation_resolver": "Phase 15.1 unchanged"})
    _write_json(root / EXPERIMENT / "repeatability.json", _repeatability(
        first_rows, final_rows, attempts, [str(row["question_id"]) for row in frozen["questions"]]))
    _write_json(root / EXPERIMENT / "latency.json", summary["latency"] | {
        "retry_latency_overhead_seconds": summary["retry_protocol"]["retry_latency_overhead_seconds"],
        "retry_latency_overhead": summary["retry_protocol"]["retry_latency_overhead"],
        "complete_protocol_latency_seconds": summary["retry_protocol"]["complete_protocol_latency_seconds"],
    })
    _write_json(root / EXPERIMENT / "failure_analysis.json", {
        "status_counts": summary["status_counts"],
        "retry_trigger_count": summary["retry_protocol"]["retry_trigger_count"],
        "retry_success_count": summary["retry_protocol"]["retry_success_count"],
        "retry_failure_count": summary["retry_protocol"]["retry_failure_count"],
        "diagnostic_failures": {row["question_id"]: row["failure_attribution"] for row in final_rows if row["failure_attribution"]},
        "unsupported_factual_claims_automatically_judged": False,
    })
    v2_g1 = _read_json(root / OLD_G1 / "overall.json")
    comparison = {
        "comparison_type": "technical retry reliability; answer semantics and citation contract unchanged",
        "same_questions_and_contexts": True,
        "G1_v2_first_pass": first_metrics | {"final_metrics_reference": "Phase 15.1 immutable G1 v2 overall"},
        "G1_v2_immutable_baseline": {key: v2_g1.get(key) for key in (
            "schema_valid_rate", "citation_parse_rate", "strict_citation_validity_rate",
            "answered_count", "insufficient_evidence_count", "generation_error_count",
            "silver_reference_similarity", "calculation_numeric_evaluation")},
        "G1_v2_1_final": {key: summary.get(key) for key in (
            "schema_valid_rate", "citation_parse_rate", "strict_citation_validity_rate",
            "answered_count", "insufficient_evidence_count", "generation_error_count",
            "silver_reference_similarity", "calculation_numeric_evaluation")},
        "causal_claim": False,
    }
    _write_json(phase_dir / "v2_vs_v2_1_comparison.json", comparison)
    g0_summary = _read_json(root / G0_V2 / "overall.json")
    ready = readiness(g0_summary=g0_summary, g1_summary=summary, all_raw_attempts_preserved=attempts_intact)
    _write_json(phase_dir / "phase16_generation_readiness_v2_1.json", ready)
    if ready["phase16_generation_ready"]:
        export = [build_ragas_export_row(
            question=question, answer=final_rows[index]["answer"], contexts=contexts[str(question["question_id"])],
            attempts=int(final_rows[index]["generation_attempts"]),
            final_output_source=str(final_rows[index]["final_output_source"]), ready=True,
        ) for index, question in enumerate(frozen["questions"])]
        _write_jsonl(root / "data/evaluation/generation/ragas_input_v2_1.jsonl", export)

    immutable_after = _snapshot_paths(root)
    immutable_failures = [key for key in sorted(set(immutable_before) | set(immutable_after))
                          if immutable_before.get(key) != immutable_after.get(key)]
    protected_after = _capture_protected(root)
    protected_failures = [key for key in sorted(set(protected_before) | set(protected_after))
                          if protected_before.get(key) != protected_after.get(key)]
    health = _health_status()
    compatibility = {
        "status": "passed" if health["healthy"] and not immutable_failures and not protected_failures else "failed",
        "production_streamlit_http": health,
        "rag_store_sqlite3_before": protected_before.get("rag_store.sqlite3"),
        "rag_store_sqlite3_after": protected_after.get("rag_store.sqlite3"),
        "rag_store_sqlite3_unchanged": protected_before.get("rag_store.sqlite3") == protected_after.get("rag_store.sqlite3"),
        "phase15_and_phase15_1_immutable": not immutable_failures,
        "phase15_1_immutable_failures": immutable_failures,
        "protected_artifacts_unchanged": not protected_failures,
        "protected_failures": protected_failures,
    }
    _write_json(phase_dir / "compatibility.json", compatibility)
    manifest["status"] = "completed" if len(final_rows) == 169 and not summary["generation_error_count"] else "completed_with_generation_errors"
    manifest["attempt_counts"] = dict(sorted(Counter(str(row["attempt_number"]) for row in attempts).items()))
    manifest["readiness"] = ready["phase16_generation_ready"]
    manifest["compatibility_status"] = compatibility["status"]
    manifest["completed_at_utc"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    _write_json(root / EXPERIMENT / "experiment_manifest.json", manifest)
    result = {"overall": summary, "failure_forensics": _read_json(phase_dir / "failure_forensics.json"),
              "readiness": ready, "comparison": comparison, "compatibility": compatibility}
    _write_json(phase_dir / "summary.json", result)
    if compatibility["status"] != "passed":
        raise RuntimeError("Phase 15.2 production compatibility or immutable artifact check failed")
    return result
