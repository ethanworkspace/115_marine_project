"""Run frozen G0/G1 generation conditions and emit audit-ready reports."""

from __future__ import annotations

import hashlib
import ast
import json
import os
import platform
import statistics
import subprocess
import sys
import threading
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from .contexts import build_e4_top5_contexts, build_oracle_contexts, make_user_prompt
from .evaluation import (
    calculation_numeric_evaluation,
    determine_failures,
    evidence_citation_recall,
    failure_distribution,
    grouped_summaries,
    normalize_citations,
    silver_reference_similarity,
    summarize_outputs,
    validate_model_output,
)
from .frozen import read_jsonl, sha256_file, validate_frozen_inputs
from .ollama import GENERATION_OPTIONS, OUTPUT_SCHEMA, LocalGenerationError, call_ollama, load_generation_prompt


ROOT = Path(__file__).resolve().parents[3]
OUTPUT_ROOT = Path("reports/evaluation/generation")
CONDITION_IDS = {
    "G0": "G0_grounded_oracle_generation_v1",
    "G1": "G1_grounded_e4_top5_generation_v1",
}
DETERMINISM_SUBSET_COUNT = 20


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    temporary.replace(path)


def _read_records(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8")
    if text.lstrip().startswith("["):
        rows = json.loads(text)
        if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
            raise ValueError(f"Expected an array of JSON objects in {path}")
        return rows
    return read_jsonl(path)


def _git_commit(root: Path) -> str | None:
    try:
        result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, timeout=10, check=True)
        return result.stdout.strip()
    except Exception:
        return None


def _preflight(root: Path) -> dict[str, Any]:
    """Verify project default model, local availability, runtime, and hardware metadata."""
    core_text = (root / "rag_core.py").read_text(encoding="utf-8")
    chat_text = (root / "chat.py").read_text(encoding="utf-8")
    app_text = (root / "app.py").read_text(encoding="utf-8")
    tree = ast.parse(core_text)
    models: tuple[str, ...] | None = None
    host_default: str | None = None
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "MODELS" for target in node.targets):
            try:
                value = ast.literal_eval(node.value)
                if isinstance(value, (list, tuple)) and all(isinstance(item, str) for item in value):
                    models = tuple(value)
            except (ValueError, TypeError):
                pass
        if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "OLLAMA_HOST" for target in node.targets):
            for call in ast.walk(node.value):
                if (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute) and call.func.attr == "get"
                        and len(call.args) >= 2 and isinstance(call.args[0], ast.Constant) and call.args[0].value == "OLLAMA_HOST"
                        and isinstance(call.args[1], ast.Constant) and isinstance(call.args[1].value, str)):
                    host_default = call.args[1].value
    if models is None or not host_default:
        raise RuntimeError("Cannot statically determine MODELS or OLLAMA_HOST default from rag_core.py")
    if "default=MODELS[0]" not in chat_text or "MODELS, index=0" not in app_text:
        raise RuntimeError("CLI and Streamlit model defaults do not both select MODELS[0]")
    model = models[0] if models else None
    base_url = str(os.environ.get("OLLAMA_HOST") or host_default).rstrip("/")
    if not model:
        raise RuntimeError("No default model is configured in rag_core.MODELS")
    if model != "gemma2:9b":
        raise RuntimeError(f"Unexpected project default model: {model}")
    if not base_url.startswith("http://127.0.0.1") and not base_url.startswith("http://localhost"):
        raise RuntimeError(f"Configured Ollama endpoint is not local: {base_url}")
    try:
        version_response = requests.get(f"{base_url}/api/version", timeout=10)
        version_response.raise_for_status()
        runtime_version = version_response.json().get("version")
        tags_response = requests.get(f"{base_url}/api/tags", timeout=20)
        tags_response.raise_for_status()
        models_found = tags_response.json().get("models") or []
        model_info = next((row for row in models_found if row.get("name") == model or row.get("model") == model), None)
        if model_info is None:
            raise RuntimeError(f"Configured default model is not locally available: {model}")
        show_response = requests.post(f"{base_url}/api/show", json={"model": model}, timeout=30)
        show_response.raise_for_status()
        show = show_response.json()
    except Exception as exc:
        raise RuntimeError(f"Generator preflight failed: {type(exc).__name__}: {exc}") from exc

    gpu_info: dict[str, Any] | None = None
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total,memory.used,driver_version", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=10, check=True,
        )
        first = result.stdout.strip().splitlines()[0].split(",")
        gpu_info = {"name": first[0].strip(), "memory_total": first[1].strip(),
                    "memory_used_before_model": first[2].strip(), "driver_version": first[3].strip()}
    except Exception:
        gpu_info = None
    current_models: list[dict[str, Any]] = []
    try:
        ps_response = requests.get(f"{base_url}/api/ps", timeout=10)
        ps_response.raise_for_status()
        current_models = ps_response.json().get("models") or []
    except Exception:
        pass
    return {
        "configured_models": list(models),
        "default_model": model,
        "default_selected_by": ["rag_core.py MODELS tuple first element", "chat.py --model default=MODELS[0]", "app.py selectbox index=0"],
        "ollama_endpoint": base_url,
        "runtime": "Ollama",
        "runtime_version": runtime_version,
        "model_tag": model_info.get("name"),
        "model_digest": model_info.get("digest"),
        "model_size_bytes": model_info.get("size"),
        "model_details": model_info.get("details") or {},
        "model_show_details": show.get("details") or {},
        "model_context_length": (show.get("model_info") or {}).get("gemma2.context_length") or (model_info.get("details") or {}).get("context_length"),
        "device_information": {"gpu": gpu_info, "ollama_ps_before_generation": current_models,
                               "placement": "Ollama runtime-selected; record loaded-model placement after inference"},
        "python_version": sys.version,
        "os": platform.platform(),
        "host_cpu": platform.processor() or None,
    }


def _required_available(question: dict[str, Any], contexts: list[dict[str, Any]]) -> tuple[bool, list[str]]:
    required = set(map(str, question.get("required_chunks") or []))
    available = {str(row["chunk_id"]) for row in contexts}
    return bool(required) and required <= available, sorted(required & available)


def _condition_contexts(condition: str, question: dict[str, Any], frozen: dict[str, Any]) -> list[dict[str, Any]]:
    if condition == "G0":
        return build_oracle_contexts(question, frozen["corpus_by_id"])
    return build_e4_top5_contexts(question, frozen["e4_trace_by_question"][str(question["question_id"])], frozen["corpus_by_id"])


def _completed_records(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    return {str(row["question_id"]): row for row in _read_records(path)}


def _run_one(*, question: dict[str, Any], contexts: list[dict[str, Any]], condition: str,
             model: str, base_url: str, prompt: str) -> tuple[dict[str, Any], dict[str, Any]]:
    qid = str(question["question_id"])
    all_required_in_context, present_required = _required_available(question, contexts)
    prompt_text = make_user_prompt(qid, str(question["question"]), contexts)
    raw_model_output = ""
    call_stats: dict[str, Any] = {}
    parsed: dict[str, Any] = {}
    json_parse_valid = False
    error: str | None = None
    try:
        generated = call_ollama(model=model, system_prompt=prompt, user_prompt=prompt_text, base_url=base_url)
        raw_model_output = str(generated["raw_output"])
        parsed = generated["parsed"]
        call_stats = {key: generated.get(key) for key in (
            "latency_seconds", "ttft_seconds", "prompt_tokens", "completion_tokens", "tokens_per_second",
            "load_duration_ns", "done_reason",
        )}
        json_parse_valid = True
    except LocalGenerationError as exc:
        error = str(exc)
    schema_valid, schema_errors = validate_model_output(parsed, qid) if json_parse_valid else (False, ["generation_or_json_parse_error"])
    model_status = parsed.get("status") if isinstance(parsed, dict) else None
    effective_status = str(model_status) if schema_valid else "generation_error"
    answer = str(parsed.get("answer") or "") if isinstance(parsed, dict) else ""
    citation_summary = normalize_citations(parsed, contexts) if isinstance(parsed, dict) else normalize_citations({}, contexts)
    required_citation = evidence_citation_recall(parsed if isinstance(parsed, dict) else {}, contexts,
                                                 list(map(str, question.get("required_chunks") or [])))
    similarity = silver_reference_similarity(answer, str(question.get("reference_answer") or "")) \
        if effective_status == "answered" else None
    numeric = calculation_numeric_evaluation(answer, question.get("calculation_spec")) if question.get("calculation_spec") else None
    failures = determine_failures(
        condition=condition,
        schema_valid=schema_valid,
        status=effective_status,
        required_in_context=all_required_in_context,
        citation_summary=citation_summary,
        numeric=numeric,
    )
    row = {
        "question_id": qid,
        "condition": condition,
        "query_style": question.get("query_style"),
        "species": question.get("species"),
        "category": question.get("category"),
        "difficulty": question.get("difficulty"),
        "risk_level": question.get("risk_level"),
        "multi_document": bool(question.get("multi_document")),
        "status": effective_status,
        "model_status": model_status,
        "answer": answer,
        "json_parse_valid": json_parse_valid,
        "schema_valid": schema_valid,
        "citation_parse_valid": (
            isinstance(parsed.get("citations"), list) and "invalid_citation_shape" not in schema_errors
            if isinstance(parsed, dict) else False
        ),
        "schema_errors": schema_errors,
        "generation_error": error,
        "required_evidence_in_context": all_required_in_context,
        "required_chunks_total": len(question.get("required_chunks") or []),
        "required_chunks_present": len(present_required),
        "required_chunks_present_ids": present_required,
        "required_chunks_in_context_ids": sorted({str(row["chunk_id"]) for row in contexts} & set(map(str, question.get("required_chunks") or []))),
        **citation_summary,
        **required_citation,
        "silver_reference_similarity": similarity,
        "calculation_numeric_evaluation": numeric,
        "failure_attribution": failures,
        "context_count": len(contexts),
        "context_ids": [row["context_id"] for row in contexts],
        "context_chunk_ids": [row["chunk_id"] for row in contexts],
        "model": model,
        "prompt_version": "generation_v1",
        **call_stats,
    }
    raw_row = {
        "question_id": qid,
        "condition": condition,
        "model": model,
        "prompt_version": "generation_v1",
        "raw_output": raw_model_output,
        "raw_output_capture_status": "captured" if raw_model_output else (
            "unavailable_after_json_parse_error" if error and "not valid JSON" in error else "no_response_content_captured"
        ),
        "parsed_model_output": parsed if isinstance(parsed, dict) else None,
        "generation_error": error,
    }
    return row, raw_row


def _determinism_report(main_rows: list[dict[str, Any]], repeat_rows: list[dict[str, Any]]) -> dict[str, Any]:
    main = {row["question_id"]: row for row in main_rows}
    repeat = {row["question_id"]: row for row in repeat_rows}
    ids = sorted(set(main) & set(repeat))
    comparisons = []
    for qid in ids:
        left, right = main[qid], repeat[qid]
        same_raw = left.get("raw_output") == right.get("raw_output")
        same_structured = all(left.get(key) == right.get(key) for key in ("status", "answer", "citations"))
        comparisons.append({"question_id": qid, "raw_output_identical": same_raw,
                            "parsed_output_identical": same_structured})
    return {
        "question_count": len(comparisons),
        "runs_compared": 2,
        "raw_output_identical_count": sum(row["raw_output_identical"] for row in comparisons),
        "parsed_output_identical_count": sum(row["parsed_output_identical"] for row in comparisons),
        "all_raw_outputs_identical": bool(comparisons) and all(row["raw_output_identical"] for row in comparisons),
        "all_parsed_outputs_identical": bool(comparisons) and all(row["parsed_output_identical"] for row in comparisons),
        "comparisons": comparisons,
    }


def _citation_report(rows: list[dict[str, Any]]) -> dict[str, Any]:
    citations = [citation for row in rows for citation in row.get("citations", [])]
    summary = summarize_outputs(rows)
    invalid_reason_counts: Counter[str] = Counter()
    for row in rows:
        context_ids = set(map(str, row.get("context_ids") or []))
        chunk_ids = set(map(str, row.get("context_chunk_ids") or []))
        for citation in row.get("citations", []):
            if citation.get("valid"):
                continue
            context_id = str(citation.get("context_id") or "")
            if context_id not in context_ids and context_id in chunk_ids:
                invalid_reason_counts["model_used_chunk_id_instead_of_context_id"] += 1
            elif context_id not in context_ids:
                invalid_reason_counts["context_id_not_in_prompt"] += 1
            else:
                invalid_reason_counts["citation_provenance_field_mismatch"] += 1
    return {
        "question_count": len(rows),
        "citation_count": len(citations),
        "valid_citation_count": sum(bool(row.get("valid")) for row in citations),
        "citation_validity_rate": summary["citation_validity_rate"],
        "hallucinated_citation_count": summary["hallucinated_citation_count"],
        "out_of_context_citation_count": summary["out_of_context_citation_count"],
        "missing_citation_count": summary["missing_citation_count"],
        "invalid_citation_reason_counts": dict(sorted(invalid_reason_counts.items())),
        "interpretation": "A citation is valid only when context_id, chunk_id, document_id, and page all match this question's supplied context.",
        "required_evidence_citation_recall_chunk_level": summary["required_evidence_citation_recall_chunk_level"],
        "required_evidence_citation_recall_question_level": summary["required_evidence_citation_recall_question_level"],
        "required_evidence_citation_questions_scored": summary["required_evidence_citation_questions_scored"],
    }


def _read_existing_reranker_latency(root: Path) -> dict[str, Any] | None:
    path = root / "reports/evaluation/experiments/E4_grounded_rrf_reranker_v1/latency.json"
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return {
        "source": "frozen E4 Phase 14 aggregate report; not measured in this generation run",
        "query_rerank_latency_seconds": data.get("query_rerank_latency_seconds"),
        "total_scoring_seconds": data.get("total_scoring_seconds"),
        "total_pairs": data.get("total_pairs"),
    }


def _manual_attribution(rows: list[dict[str, Any]]) -> dict[str, Any]:
    counts = failure_distribution(rows)
    return {
        "failure_taxonomy_counts": counts,
        "unsupported_factual_claims_automatically_judged": False,
        "interpretation": "Retrieval/generation labels are deterministic diagnostics from required-evidence availability, output structure, and citation provenance; they do not establish factual correctness.",
    }


class _ResourceSampler:
    def __init__(self) -> None:
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.peak_vram_used_mib: int | None = None
        self.peak_ram_percent: float | None = None
        self.peak_ollama_rss_bytes: int | None = None

    def _sample(self) -> None:
        try:
            import psutil  # noqa: PLC0415
            has_psutil = True
        except Exception:
            psutil = None  # type: ignore[assignment]
            has_psutil = False
        while not self.stop_event.wait(1.0):
            if has_psutil and psutil is not None:
                try:
                    self.peak_ram_percent = max(self.peak_ram_percent or 0.0, float(psutil.virtual_memory().percent))
                    processes = []
                    for process in psutil.process_iter(["name", "memory_info"]):
                        name = str(process.info.get("name") or "").casefold()
                        if "ollama" in name:
                            memory = process.info.get("memory_info")
                            if memory is not None:
                                processes.append(int(memory.rss))
                    if processes:
                        self.peak_ollama_rss_bytes = max(self.peak_ollama_rss_bytes or 0, sum(processes))
                except Exception:
                    pass
            try:
                result = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                                        capture_output=True, text=True, timeout=2)
                value = int(result.stdout.strip().splitlines()[0])
                self.peak_vram_used_mib = max(self.peak_vram_used_mib or 0, value)
            except Exception:
                pass

    def __enter__(self) -> "_ResourceSampler":
        self.thread = threading.Thread(target=self._sample, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *_: Any) -> None:
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=3)


def _experiment_report(root: Path, *, condition: str, model_info: dict[str, Any], prompt_sha: str,
                        frozen: dict[str, Any], rows: list[dict[str, Any]], raw_rows: list[dict[str, Any]],
                        determinism: dict[str, Any] | None, resource_stats: dict[str, Any]) -> None:
    exp_id = CONDITION_IDS[condition]
    out_dir = root / OUTPUT_ROOT / exp_id
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = sorted(rows, key=lambda row: next(i for i, q in enumerate(frozen["questions"]) if q["question_id"] == row["question_id"]))
    summary = summarize_outputs(rows)
    summary["retrieval_availability"] = {
        "required_evidence_in_context_count": sum(bool(row.get("required_evidence_in_context")) for row in rows),
        "required_evidence_missing_count": sum(not bool(row.get("required_evidence_in_context")) for row in rows),
        "label_sent_to_generator": False,
    }
    summary["failure_attribution"] = _manual_attribution(rows)
    manifest = {
        "experiment_id": exp_id,
        "condition": condition,
        "status": "completed" if len(rows) == len(frozen["questions"]) else "incomplete",
        "timestamp_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "question_count": len(rows),
        "generator": model_info,
        "prompt_version": "generation_v1",
        "prompt_sha256": prompt_sha,
        "output_schema_sha256": sha256_file(root / "schemas/generation_output.schema.json"),
        "generation_parameters": dict(GENERATION_OPTIONS),
        "ollama_format": "JSON Schema constrained output",
        "sampling_policy": "temperature=0; fixed seed; same request once per question",
        "input_hashes": frozen["hashes"],
        "git_commit": _git_commit(root),
        "context_policy": "C1..Cn, document_id, page, text only; no expected evidence flags, Silver labels, reference answer, retrieval score, or metadata labels are included",
        "context_source": "required evidence snapshots" if condition == "G0" else "exact frozen E4 Top-5 ranking trace joined to Evaluation Corpus v2",
        "e4_reranker_revision": frozen["e4_manifest"]["reranker"]["revision"],
        "e4_candidate_count": 5 if condition == "G1" else None,
        "model_call_count": len(raw_rows),
        "raw_output_capture": {
            "attempts": len(raw_rows),
            "captured": sum(bool(row.get("raw_output")) for row in raw_rows),
            "missing": sum(not bool(row.get("raw_output")) for row in raw_rows),
            "missing_question_ids": [row.get("question_id") for row in raw_rows if not row.get("raw_output")],
            "note": "Malformed JSON responses were not returned by the initial client parser; their error and question records remain saved, but the malformed body itself is unavailable.",
        },
        "determinism_subset": determinism,
        "resource_sampling": resource_stats,
        "latency_limitations": {
            "retrieval_latency_seconds": None,
            "retrieval_latency_reason": "E4 Phase 14 outputs freeze ranking but contain no per-query retrieval latency; no substitute value was estimated.",
            "reranker_latency_seconds": "See prior E4 aggregate latency report; no per-question E4 timing was saved.",
            "total_end_to_end_latency": None,
        },
    }
    _write_json(out_dir / "experiment_manifest.json", manifest)
    _write_json(out_dir / "overall.json", summary)
    _write_json(out_dir / "citation_validation.json", _citation_report(rows))
    _write_json(out_dir / "failure_analysis.json", _manual_attribution(rows))
    _write_json(out_dir / "latency.json", {
        **summary["latency"],
        "retrieval_latency": None,
        "reranker_latency": _read_existing_reranker_latency(root) if condition == "G1" else None,
        "total_end_to_end_latency": None,
        "generation_machine": resource_stats,
    })
    _write_json(out_dir / "by_query_style.json", grouped_summaries(rows, "query_style"))
    _write_json(out_dir / "by_species.json", grouped_summaries(rows, "species"))
    _write_json(out_dir / "by_category.json", grouped_summaries(rows, "category"))
    _write_jsonl(out_dir / "per_question.jsonl", rows)
    _write_jsonl(out_dir / "raw_outputs.jsonl", raw_rows)
    if determinism is not None:
        _write_json(out_dir / "determinism.json", determinism)


def _run_condition(root: Path, condition: str, frozen: dict[str, Any], model_info: dict[str, Any],
                   prompt: str, prompt_sha: str, base_url: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    out_dir = root / OUTPUT_ROOT / CONDITION_IDS[condition]
    out_dir.mkdir(parents=True, exist_ok=True)
    per_question_path = out_dir / "per_question.jsonl"
    raw_path = out_dir / "raw_outputs.jsonl"
    completed = _completed_records(per_question_path)
    raw_by_id = {str(row["question_id"]): row for row in read_jsonl(raw_path)} if raw_path.exists() else {}
    records = [completed[qid] for qid in completed]
    raw_records = list(raw_by_id.values())
    sampler = _ResourceSampler()
    print(f"{condition}: {len(completed)}/{len(frozen['questions'])} questions already complete", flush=True)
    with sampler:
        for index, question in enumerate(frozen["questions"], start=1):
            qid = str(question["question_id"])
            if qid in completed:
                continue
            contexts = _condition_contexts(condition, question, frozen)
            row, raw_row = _run_one(question=question, contexts=contexts, condition=condition,
                                    model=model_info["default_model"], base_url=base_url, prompt=prompt)
            completed[qid] = row
            raw_by_id[qid] = raw_row
            records.append(row)
            raw_records.append(raw_row)
            # Checkpoint after each question so an interrupted run can resume without repeating calls.
            _write_jsonl(per_question_path, [completed[str(q["question_id"])] for q in frozen["questions"] if str(q["question_id"]) in completed])
            _write_jsonl(raw_path, [raw_by_id[str(q["question_id"])] for q in frozen["questions"] if str(q["question_id"]) in raw_by_id])
            if index == 1 or index % 5 == 0 or index == len(frozen["questions"]):
                print(f"{condition}: {index}/{len(frozen['questions'])}; status={row['status']}; {row.get('latency_seconds')}s", flush=True)
    ps_models: list[dict[str, Any]] = []
    try:
        ps = requests.get(f"{base_url}/api/ps", timeout=10)
        ps.raise_for_status()
        ps_models = ps.json().get("models") or []
    except Exception:
        pass
    resources = {
        "peak_gpu_memory_used_mib_sampled": sampler.peak_vram_used_mib,
        "peak_system_ram_percent_sampled": sampler.peak_ram_percent,
        "peak_ollama_process_rss_bytes_sampled": sampler.peak_ollama_rss_bytes,
        "ollama_loaded_models_after_condition": ps_models,
        "note": "RAM/VRAM values are sampled machine-level telemetry; unavailable values remain null.",
    }
    ordered_records = [completed[str(q["question_id"])] for q in frozen["questions"] if str(q["question_id"]) in completed]
    ordered_raw = [raw_by_id[str(q["question_id"])] for q in frozen["questions"] if str(q["question_id"]) in raw_by_id]
    return ordered_records, ordered_raw, resources


def _run_determinism(root: Path, condition: str, frozen: dict[str, Any], model_info: dict[str, Any],
                     prompt: str, base_url: str, primary_rows: list[dict[str, Any]],
                     primary_raw: list[dict[str, Any]]) -> dict[str, Any]:
    out_dir = root / OUTPUT_ROOT / CONDITION_IDS[condition]
    primary_by_id = {row["question_id"]: row for row in primary_rows}
    raw_by_id = {row["question_id"]: row for row in primary_raw}
    subset = frozen["questions"][:DETERMINISM_SUBSET_COUNT]
    reruns: list[dict[str, Any]] = []
    repeat_raw: list[dict[str, Any]] = []
    for index, question in enumerate(subset, start=1):
        contexts = _condition_contexts(condition, question, frozen)
        row, raw = _run_one(question=question, contexts=contexts, condition=condition,
                            model=model_info["default_model"], base_url=base_url, prompt=prompt)
        row["raw_output"] = raw["raw_output"]
        reruns.append(row)
        repeat_raw.append(raw)
        print(f"{condition} determinism rerun: {index}/{len(subset)}", flush=True)
    report = _determinism_report([primary_by_id[row["question_id"]] | {"raw_output": raw_by_id[row["question_id"]].get("raw_output")} for row in reruns], reruns)
    _write_jsonl(out_dir / "determinism_rerun_outputs.jsonl", repeat_raw)
    _write_json(out_dir / "determinism.json", report)
    return report


def _compare_conditions(root: Path, frozen: dict[str, Any], g0: list[dict[str, Any]], g1: list[dict[str, Any]]) -> None:
    out_dir = root / OUTPUT_ROOT / "G0_vs_G1_v1"
    g0_by_id = {row["question_id"]: row for row in g0}
    g1_by_id = {row["question_id"]: row for row in g1}
    questions_by_id = {str(row["question_id"]): row for row in frozen["questions"]}
    rows = []
    for question in frozen["questions"]:
        qid = str(question["question_id"])
        left, right = g0_by_id[qid], g1_by_id[qid]
        rows.append({
            "question_id": qid,
            "query_style": question.get("query_style"),
            "species": question.get("species"),
            "category": question.get("category"),
            "calculation": bool(question.get("calculation_spec")),
            "g0_status": left.get("status"),
            "g1_status": right.get("status"),
            "g0_answered": left.get("status") == "answered",
            "g1_answered": right.get("status") == "answered",
            "g0_required_evidence_citation_recall": left.get("required_evidence_citation_recall"),
            "g1_required_evidence_citation_recall": right.get("required_evidence_citation_recall"),
            "g0_reference_similarity_f1": (left.get("silver_reference_similarity") or {}).get("f1"),
            "g1_reference_similarity_f1": (right.get("silver_reference_similarity") or {}).get("f1"),
            "required_evidence_in_g1_context": right.get("required_evidence_in_context"),
            "interpretation": "heuristic_diagnostic_not_causal" if right.get("required_evidence_in_context") else "G1 retrieval miss; compare with G0 only as a likely retrieval contribution",
        })
    g0_summary, g1_summary = summarize_outputs(g0), summarize_outputs(g1)
    comparison = {
        "benchmark_type": "AI-generated Grounded Silver; not Human Gold",
        "question_count": len(rows),
        "same_question_ids": set(g0_by_id) == set(g1_by_id) == set(questions_by_id),
        "conditions": {
            "G0_oracle": {key: g0_summary[key] for key in (
                "answered_count", "answered_rate", "insufficient_evidence_count", "insufficient_evidence_rate",
                "schema_valid_rate", "required_evidence_citation_recall_chunk_level",
                "required_evidence_citation_recall_question_level", "silver_reference_similarity",
                "calculation_numeric_evaluation",
            )},
            "G1_E4_Top5": {key: g1_summary[key] for key in (
                "answered_count", "answered_rate", "insufficient_evidence_count", "insufficient_evidence_rate",
                "schema_valid_rate", "required_evidence_citation_recall_chunk_level",
                "required_evidence_citation_recall_question_level", "silver_reference_similarity",
                "calculation_numeric_evaluation",
            )},
        },
        "paired_answered_rate_difference_G1_minus_G0": g1_summary.get("answered_rate", 0) - g0_summary.get("answered_rate", 0),
        "retrieval_miss_count_G1": sum(not bool(row.get("required_evidence_in_context")) for row in g1),
        "g1_required_evidence_present_but_not_answered": sum(
            bool(row.get("required_evidence_in_context")) and row.get("status") != "answered" for row in g1
        ),
        "silver_reference_similarity_warning": "Secondary comparison against AI-generated evidence-grounded references; not expert correctness.",
        "causal_claim": False,
    }
    _write_json(out_dir / "comparison.json", comparison)
    _write_json(out_dir / "retrieval_vs_generation_attribution.json", {
        "g1_retrieval_miss_questions": [row for row in rows if not row["required_evidence_in_g1_context"]],
        "g1_retrieval_hit_but_generation_failure_questions": [row for row in rows if row["required_evidence_in_g1_context"] and not row["g1_answered"]],
        "interpretation": "Likely component attribution only. The Silver reference and automated checks do not establish expert answer correctness or absolute causality.",
    })
    _write_json(out_dir / "calculation_analysis.json", {
        "question_count": sum(bool(row["calculation"]) for row in rows),
        "questions": [row for row in rows if row["calculation"]],
        "interpretation": "Only three Silver calculation questions; descriptive results only. Numeric assessment uses the deterministic calculation_spec and explicit tolerances.",
    })
    _write_jsonl(out_dir / "per_question_comparison.jsonl", rows)
    summary_text = [
        "# G0 Oracle vs G1 E4 Top-5 Generation",
        "",
        "This is an AI-generated Silver benchmark, not a Human Gold evaluation or expert correctness estimate.",
        "",
        f"- Questions: {len(rows)}",
        f"- G0 answered: {g0_summary['answered_count']} ({g0_summary['answered_rate']:.3f})" if g0_summary['answered_rate'] is not None else "- G0 answered: unavailable",
        f"- G1 answered: {g1_summary['answered_count']} ({g1_summary['answered_rate']:.3f})" if g1_summary['answered_rate'] is not None else "- G1 answered: unavailable",
        f"- G1 required-evidence retrieval misses: {comparison['retrieval_miss_count_G1']}",
        f"- G1 required evidence present, but not answered: {comparison['g1_required_evidence_present_but_not_answered']}",
        "- Silver reference similarity is secondary and is not human expert correctness.",
        "- End-to-end latency is not reported because the frozen E4 artifacts lack retrieval timings.",
    ]
    (out_dir / "comparison_summary.md").write_text("\n".join(summary_text) + "\n", encoding="utf-8")


def _write_ragas_export(root: Path, frozen: dict[str, Any], g1: list[dict[str, Any]]) -> None:
    rows_by_id = {row["question_id"]: row for row in g1}
    output = []
    for question in frozen["questions"]:
        row = rows_by_id.get(str(question["question_id"]), {})
        output.append({
            "question_id": question["question_id"],
            "question": question["question"],
            "answer": row.get("answer", ""),
            "contexts": [
                f"document_id: {context['document_id']}\npage: {context['page']}\n{context['text']}"
                for context in build_e4_top5_contexts(question, frozen["e4_trace_by_question"][str(question["question_id"])], frozen["corpus_by_id"])
            ],
            "reference_answer": question.get("reference_answer"),
            "silver_reference": True,
            "benchmark_type": "AI-generated Silver; not Human Gold",
            "generation_status": row.get("status"),
        })
    _write_jsonl(root / "data/evaluation/generation/ragas_input_v1.jsonl", output)


def _capture_protected(root: Path) -> dict[str, dict[str, Any]]:
    fixed_files = [
        "rag_store.sqlite3", "data/shadow/chunks_v2.jsonl", "data/shadow/chunks_v3.jsonl",
        "data/evaluation/corpus_v1.jsonl", "data/evaluation/corpus_v2.jsonl",
        "data/evaluation/silver/questions_v1.jsonl", "data/evaluation/silver/questions_v2.jsonl",
        "data/evaluation/silver/questions_v3.jsonl", "data/evaluation/grounded/questions_v1.jsonl",
        "data/evaluation/grounded/evidence_pool_v1.jsonl",
    ]
    protected: dict[str, dict[str, Any]] = {}
    for relative in fixed_files:
        path = root / relative
        if path.is_file():
            stat = path.stat()
            protected[relative] = {"sha256": sha256_file(path), "size": stat.st_size, "mtime_ns": stat.st_mtime_ns}
    for relative in ("app.py", "rag_core.py", "chat.py"):
        path = root / relative
        if path.is_file():
            stat = path.stat()
            protected[relative] = {"sha256": sha256_file(path), "size": stat.st_size, "mtime_ns": stat.st_mtime_ns}
    for directory in (root / "reports/evaluation/experiments/E1_grounded_bm25_v1",
                      root / "reports/evaluation/experiments/E2_grounded_dense_v1",
                      root / "reports/evaluation/experiments/E3_grounded_rrf_v1",
                      root / "reports/evaluation/experiments/E4_grounded_rrf_reranker_v1",
                      root / "data/evaluation/indexes/E2_grounded_bge_m3_v1"):
        if directory.is_dir():
            for path in sorted(item for item in directory.rglob("*") if item.is_file()):
                rel = path.relative_to(root).as_posix()
                stat = path.stat()
                protected[rel] = {"sha256": sha256_file(path), "size": stat.st_size, "mtime_ns": stat.st_mtime_ns}
    return protected


def _write_comparison_group_reports(root: Path, frozen: dict[str, Any], g0: list[dict[str, Any]], g1: list[dict[str, Any]]) -> None:
    out_dir = root / OUTPUT_ROOT / "G0_vs_G1_v1"
    question_by_id = {str(row["question_id"]): row for row in frozen["questions"]}
    for name, key in (("by_query_style.json", "query_style"), ("by_species.json", "species"), ("by_category.json", "category")):
        condition_groups = {}
        for condition, rows in (("G0", g0), ("G1", g1)):
            buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for row in rows:
                buckets[str(question_by_id[row["question_id"]].get(key) or "unknown")].append(row)
            condition_groups[condition] = {label: summarize_outputs(values) for label, values in sorted(buckets.items())}
        _write_json(out_dir / name, condition_groups)


def run_phase15(root: Path = ROOT) -> dict[str, Any]:
    frozen = validate_frozen_inputs(root)
    if frozen["question_count"] != 169:
        raise ValueError("Phase 15 requires exactly 169 frozen questions")
    for question in frozen["questions"]:
        build_oracle_contexts(question, frozen["corpus_by_id"])
        build_e4_top5_contexts(question, frozen["e4_trace_by_question"][str(question["question_id"])], frozen["corpus_by_id"])
    preflight = _preflight(root)
    prompt = load_generation_prompt(root)
    prompt_sha = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    protected_before = _capture_protected(root)
    baseline_protected_path = root / "reports/evaluation/experiments/E4_grounded_rrf_reranker_v1/protected_artifacts_validation.json"
    prior_protected: dict[str, Any] = {}
    if baseline_protected_path.is_file():
        baseline_record = json.loads(baseline_protected_path.read_text(encoding="utf-8"))
        prior_protected = baseline_record.get("phase13_protected_sha256") or {}
        mismatches = []
        for relative, expected_sha in prior_protected.items():
            path = root / Path(relative)
            if not path.is_file() or sha256_file(path) != expected_sha:
                mismatches.append(relative)
        phase14_map = baseline_record.get("phase14_frozen_input_sha256") or {}
        phase14_paths = {
            "E1_manifest": "reports/evaluation/experiments/E1_grounded_bm25_v1/experiment_manifest.json",
            "E2_dense_index_manifest": "data/evaluation/indexes/E2_grounded_bge_m3_v1/index_manifest.json",
            "E2_manifest": "reports/evaluation/experiments/E2_grounded_dense_v1/experiment_manifest.json",
            "E3_candidate_trace": "reports/evaluation/experiments/E3_grounded_rrf_v1/candidate_traces.jsonl",
            "E3_fusion_trace": "reports/evaluation/experiments/E3_grounded_rrf_v1/fusion_traces.jsonl",
            "E3_manifest": "reports/evaluation/experiments/E3_grounded_rrf_v1/experiment_manifest.json",
            "evaluation_corpus_v2": "data/evaluation/corpus_v2.jsonl",
            "evidence_pool_v1": "data/evaluation/grounded/evidence_pool_v1.jsonl",
            "grounded_questions_v1": "data/evaluation/grounded/questions_v1.jsonl",
        }
        for key, relative in phase14_paths.items():
            expected_sha = phase14_map.get(key)
            path = root / relative
            if expected_sha and (not path.is_file() or sha256_file(path) != expected_sha):
                mismatches.append(relative)
        if mismatches:
            raise RuntimeError(f"Protected Phase 12-14 artifacts differ before Phase 15: {sorted(set(mismatches))[:10]}")

    freeze_path = root / OUTPUT_ROOT / "generation_retrieval_manifest.json"
    model_metadata = {
        **preflight,
        "model_name": preflight["default_model"],
        "model_tag": preflight["model_tag"],
        "model_digest": preflight["model_digest"],
        "runtime": preflight["runtime"],
        "runtime_version": preflight["runtime_version"],
        "quantization": preflight["model_details"].get("quantization_level"),
        "context_length": preflight["model_context_length"],
    }
    if model_metadata["model_digest"] != "ff02c3702f322b9e075e9568332d96c0a7028002f1a5a056e0a6784320a4db0b":
        raise RuntimeError("Configured default model digest changed after preflight; stop rather than substitute")
    freeze_record = {
        "manifest_version": "generation_retrieval_v1",
        "timestamp_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "git_commit": _git_commit(root),
        "input_hashes": frozen["hashes"],
        "question_count": frozen["question_count"],
        "e4_top5_match": True,
        "e4_reranker_model": frozen["e4_manifest"]["reranker"]["model_id"],
        "e4_reranker_revision": frozen["e4_manifest"]["reranker"]["revision"],
        "generator_preflight": model_metadata,
        "generation_parameters": GENERATION_OPTIONS,
        "prompt_sha256": prompt_sha,
        "protected_artifacts_before": protected_before,
        "prior_phase12_protected_artifacts": prior_protected,
    }
    _write_json(freeze_path, freeze_record)
    _write_json(root / "reports/evaluation/generation/environment_audit.json", preflight)
    _write_json(root / "reports/evaluation/generation/generator_preflight.json", {
        "status": "passed",
        "default_model_confirmed": True,
        "local_model_available": True,
        "model": model_metadata,
        "fixed_generation_parameters": GENERATION_OPTIONS,
        "output_schema": "schemas/generation_output.schema.json",
    })

    resource_by_condition = {}
    outputs_by_condition: dict[str, list[dict[str, Any]]] = {}
    raws_by_condition: dict[str, list[dict[str, Any]]] = {}
    determinism_by_condition: dict[str, dict[str, Any]] = {}
    base_url = preflight["ollama_endpoint"]
    for condition in ("G0", "G1"):
        rows, raw_rows, resources = _run_condition(root, condition, frozen, model_metadata, prompt, prompt_sha, base_url)
        resource_by_condition[condition] = resources
        if len(rows) != 169:
            raise RuntimeError(f"{condition} incomplete: only {len(rows)}/169 questions have outputs")
        outputs_by_condition[condition] = rows
        raws_by_condition[condition] = raw_rows
        determinism = _run_determinism(root, condition, frozen, model_metadata, prompt, base_url, rows, raw_rows)
        determinism_by_condition[condition] = determinism
        _experiment_report(root, condition=condition, model_info=model_metadata, prompt_sha=prompt_sha,
                           frozen=frozen, rows=rows, raw_rows=raw_rows, determinism=determinism,
                           resource_stats=resources)

    _compare_conditions(root, frozen, outputs_by_condition["G0"], outputs_by_condition["G1"])
    _write_comparison_group_reports(root, frozen, outputs_by_condition["G0"], outputs_by_condition["G1"])
    _write_ragas_export(root, frozen, outputs_by_condition["G1"])

    protected_after = _capture_protected(root)
    protected_checks = {}
    for name, before in protected_before.items():
        after = protected_after.get(name)
        protected_checks[name] = {
            "unchanged": bool(after) and before["sha256"] == after["sha256"] and before["size"] == after["size"] and before["mtime_ns"] == after["mtime_ns"],
            "before": before,
            "after": after,
        }
    protected_unchanged = all(item["unchanged"] for item in protected_checks.values())
    compat = {
        "status": "passed" if protected_unchanged else "failed",
        "protected_artifacts_unchanged": protected_unchanged,
        "artifact_checks": protected_checks,
        "rag_store_sqlite3": protected_checks.get("rag_store.sqlite3"),
        "production_app_modified": False,
        "production_prompt_modified": False,
        "production_retrieval_modified": False,
    }
    _write_json(root / OUTPUT_ROOT / "compatibility.json", compat)
    freeze_record["protected_artifacts_after"] = protected_after
    freeze_record["protected_compatibility"] = compat
    _write_json(freeze_path, freeze_record)
    result = {
        "G0": summarize_outputs(outputs_by_condition["G0"]),
        "G1": summarize_outputs(outputs_by_condition["G1"]),
        "protected_unchanged": protected_unchanged,
        "model": model_metadata,
        "determinism": determinism_by_condition,
    }
    _write_json(root / OUTPUT_ROOT / "phase15_summary.json", result)
    if not protected_unchanged:
        raise RuntimeError("One or more protected artifacts changed during Phase 15")
    return result


def finalize_phase15_reports(root: Path = ROOT) -> dict[str, Any]:
    """Recompute Phase 15 reports from saved outputs without making any model calls."""
    frozen = validate_frozen_inputs(root)
    model_file = root / OUTPUT_ROOT / "generator_preflight.json"
    freeze_file = root / OUTPUT_ROOT / "generation_retrieval_manifest.json"
    if not model_file.is_file() or not freeze_file.is_file():
        raise RuntimeError("Saved Phase 15 preflight/freeze manifests are required")
    model_info = json.loads(model_file.read_text(encoding="utf-8"))["model"]
    freeze_record = json.loads(freeze_file.read_text(encoding="utf-8"))
    prompt = load_generation_prompt(root)
    prompt_sha = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    result_rows: dict[str, list[dict[str, Any]]] = {}
    raw_by_condition: dict[str, list[dict[str, Any]]] = {}
    for condition in ("G0", "G1"):
        out_dir = root / OUTPUT_ROOT / CONDITION_IDS[condition]
        rows = _read_records(out_dir / "per_question.jsonl")
        raw_rows = _read_records(out_dir / "raw_outputs.jsonl")
        if len(rows) != len(frozen["questions"]) or len(raw_rows) != len(frozen["questions"]):
            raise RuntimeError(f"Saved {condition} outputs are incomplete")
        for raw in raw_rows:
            if "raw_output_capture_status" not in raw:
                raw["raw_output_capture_status"] = "captured" if raw.get("raw_output") else (
                    "unavailable_after_json_parse_error" if "not valid JSON" in str(raw.get("generation_error") or "") else "no_response_content_captured"
                )
        for row in rows:
            citation_summary = {
                "hallucinated_citation_count": row.get("hallucinated_citation_count", 0),
                "missing_citation": row.get("missing_citation", False),
            }
            numeric = row.get("calculation_numeric_evaluation")
            row["failure_attribution"] = determine_failures(
                condition=condition,
                schema_valid=bool(row.get("schema_valid")),
                status=row.get("status"),
                required_in_context=bool(row.get("required_evidence_in_context")),
                citation_summary=citation_summary,
                numeric=numeric,
            )
        manifest_path = out_dir / "experiment_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        determinism_path = out_dir / "determinism.json"
        determinism = json.loads(determinism_path.read_text(encoding="utf-8")) if determinism_path.is_file() else None
        resources = manifest.get("resource_sampling") or {}
        _experiment_report(root, condition=condition, model_info=model_info, prompt_sha=prompt_sha,
                           frozen=frozen, rows=rows, raw_rows=raw_rows,
                           determinism=determinism, resource_stats=resources)
        result_rows[condition] = rows
        raw_by_condition[condition] = raw_rows

    _compare_conditions(root, frozen, result_rows["G0"], result_rows["G1"])
    _write_comparison_group_reports(root, frozen, result_rows["G0"], result_rows["G1"])
    _write_ragas_export(root, frozen, result_rows["G1"])
    protected_before = freeze_record.get("protected_artifacts_before") or {}
    protected_after = _capture_protected(root)
    checks = {}
    for name, before in protected_before.items():
        after = protected_after.get(name)
        checks[name] = {
            "unchanged": bool(after) and before.get("sha256") == after.get("sha256")
                         and before.get("size") == after.get("size")
                         and before.get("mtime_ns") == after.get("mtime_ns"),
            "before": before,
            "after": after,
        }
    compatibility = {
        "status": "passed" if all(row["unchanged"] for row in checks.values()) else "failed",
        "protected_artifacts_unchanged": all(row["unchanged"] for row in checks.values()),
        "artifact_checks": checks,
        "rag_store_sqlite3": checks.get("rag_store.sqlite3"),
        "production_app_modified": False,
        "production_prompt_modified": False,
        "production_retrieval_modified": False,
    }
    _write_json(root / OUTPUT_ROOT / "compatibility.json", compatibility)
    freeze_record["protected_artifacts_after"] = protected_after
    freeze_record["protected_compatibility"] = compatibility
    _write_json(freeze_file, freeze_record)
    summary = {
        "G0": summarize_outputs(result_rows["G0"]),
        "G1": summarize_outputs(result_rows["G1"]),
        "protected_unchanged": compatibility["protected_artifacts_unchanged"],
        "model": model_info,
        "determinism": {
            condition: json.loads((root / OUTPUT_ROOT / CONDITION_IDS[condition] / "determinism.json").read_text(encoding="utf-8"))
            for condition in ("G0", "G1")
        },
    }
    _write_json(root / OUTPUT_ROOT / "phase15_summary.json", summary)
    if not compatibility["protected_artifacts_unchanged"]:
        raise RuntimeError("Protected artifact compatibility check failed during report finalization")
    return summary
