"""Run the frozen Phase 14 reranker smoke gate, then E4 when the gate passes."""

from __future__ import annotations

import ctypes
import datetime as dt
import hashlib
import importlib.metadata
import json
import math
import os
import random
import shutil
import statistics
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.evaluation.grounded_baselines import (  # noqa: E402
    BOOTSTRAP_ITERATIONS,
    BOOTSTRAP_SEED,
    CATEGORY_REPORT_ORDER,
    ERROR_TAXONOMY,
    GRANULARITIES,
    SPECIES_REPORT_ORDER,
    TOP_K,
    _error_candidate,
    _evidence_coverage,
    _group_reports,
    _required_evidence,
    _summarize_rows,
    get_git_commit,
    lexical_overlap_bucket,
    read_jsonl,
    sha256_file,
    stable_sha256,
    utc_now,
    validate_frozen_inputs,
    write_json,
    write_jsonl,
)
from src.evaluation.retrieval.metrics import metric_bundle  # noqa: E402
from src.evaluation.retrieval.models import RankedHit, RetrievalResult  # noqa: E402
from src.evaluation.reranker_runtime import CrossEncoderRuntime, MODEL_ID  # noqa: E402


E4_REL = Path("reports/evaluation/experiments/E4_grounded_rrf_reranker_v1")
COMPARE_REL = Path("reports/evaluation/experiments/E1_E2_E3_E4_grounded_v1")
RUNTIME_REL = Path("reports/evaluation/reranker_runtime")
CANDIDATE_REL = RUNTIME_REL / "e3_rrf_top50_candidates.jsonl"
CANDIDATE_MANIFEST_REL = RUNTIME_REL / "e3_rrf_top50_candidate_manifest.json"
MODEL_REL = Path(".venv-reranker/hf-cache/hub/models--BAAI--bge-reranker-v2-m3/snapshots/953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e")
MODEL_REVISION = MODEL_REL.name
MAX_LENGTH = 512
BATCH_SIZE = 4
RERANKER_ERROR_TYPES = ("candidate_generation_failure", "reranker_misranking", "reranker_rank_dilution", "reranker_rescue")


def _hash(path: Path) -> str:
    return sha256_file(path)


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(float(value) for value in values)
    return ordered[max(0, math.ceil(fraction * len(ordered)) - 1)]


def _distribution(values: list[float]) -> dict[str, float | int | None]:
    if not values:
        return {"count": 0, "mean": None, "min": None, "median": None, "p95": None, "max": None}
    return {
        "count": len(values),
        "mean": statistics.mean(values),
        "min": min(values),
        "median": statistics.median(values),
        "p95": _percentile(values, 0.95),
        "max": max(values),
    }


def _verify_freeze() -> dict[str, Any]:
    phase13_path = ROOT / "reports/evaluation/experiments/E1_E2_E3_grounded_v1/protected_artifacts_validation.json"
    phase13 = _read_json(phase13_path)
    protected_expected = phase13.get("protected_sha256_after", {})
    protected_mismatches = []
    for relative, expected in protected_expected.items():
        path = ROOT / relative
        actual = _hash(path) if path.is_file() else None
        if actual != expected:
            protected_mismatches.append({"path": relative, "expected": expected, "actual": actual})
    if phase13.get("status") != "passed" or protected_mismatches:
        raise RuntimeError(f"Phase 13 protected input checksum failure: {protected_mismatches[:5]}")

    initial_e4 = _read_json(ROOT / E4_REL / "experiment_manifest.json")
    frozen = validate_frozen_inputs(ROOT)
    e1_path = ROOT / "reports/evaluation/experiments/E1_grounded_bm25_v1/experiment_manifest.json"
    e2_path = ROOT / "reports/evaluation/experiments/E2_grounded_dense_v1/experiment_manifest.json"
    e2_index_path = ROOT / "data/evaluation/indexes/E2_grounded_bge_m3_v1/index_manifest.json"
    e3_path = ROOT / "reports/evaluation/experiments/E3_grounded_rrf_v1/experiment_manifest.json"
    e3_dir = e3_path.parent
    hashes = {
        "evaluation_corpus_v2": _hash(ROOT / "data/evaluation/corpus_v2.jsonl"),
        "grounded_questions_v1": _hash(ROOT / "data/evaluation/grounded/questions_v1.jsonl"),
        "evidence_pool_v1": _hash(ROOT / "data/evaluation/grounded/evidence_pool_v1.jsonl"),
        "E1_manifest": _hash(e1_path),
        "E2_manifest": _hash(e2_path),
        "E2_dense_index_manifest": _hash(e2_index_path),
        "E3_manifest": _hash(e3_path),
        "E3_ranking_trace": _hash(e3_dir / "ranking_traces.jsonl"),
        "E3_fusion_trace": _hash(e3_dir / "fusion_traces.jsonl"),
        "E3_candidate_trace": _hash(e3_dir / "candidate_traces.jsonl"),
    }
    frozen_hash_keys = (
        "evaluation_corpus_v2", "grounded_questions_v1", "evidence_pool_v1", "E1_manifest",
        "E2_manifest", "E2_dense_index_manifest", "E3_manifest", "E3_ranking_trace", "E3_fusion_trace",
    )
    previous_hashes = initial_e4.get("input_sha256", {})
    mismatches = {key: {"phase14": previous_hashes.get(key), "current": hashes[key]}
                  for key in frozen_hash_keys if previous_hashes.get(key) != hashes[key]}
    if mismatches:
        raise RuntimeError(f"Phase 14 frozen inputs changed: {mismatches}")
    e3 = _read_json(e3_path)
    if e3.get("status") != "completed" or e3.get("question_count") != 169 or e3.get("retrieval_chunk_count") != 2224:
        raise RuntimeError("Phase 13 E3 manifest does not match the frozen 169-question, 2,224-chunk experiment")
    for key, field in (
        ("evaluation_corpus_v2", "evaluation_corpus_v2_sha256"),
        ("grounded_questions_v1", "grounded_questions_v1_sha256"),
        ("evidence_pool_v1", "evidence_pool_v1_sha256"),
        ("E1_manifest", "E1_manifest_sha256"),
        ("E2_manifest", "E2_manifest_sha256"),
        ("E2_dense_index_manifest", "E2_dense_index_manifest_sha256"),
        ("E3_ranking_trace", "ranking_traces_sha256"),
        ("E3_fusion_trace", "fusion_traces_sha256"),
        ("E3_candidate_trace", "candidate_traces_sha256"),
    ):
        if hashes[key] != e3.get(field):
            raise RuntimeError(f"E3 manifest checksum mismatch for {key}")
    if len(frozen["questions"]) != 169 or len(frozen["corpus"]) != 2224:
        raise RuntimeError("Frozen benchmark cardinality mismatch")
    candidate_manifest = _read_json(ROOT / CANDIDATE_MANIFEST_REL)
    if candidate_manifest.get("status") != "passed" or candidate_manifest.get("candidate_rows") != 8450:
        raise RuntimeError("RRF Top-50 candidate pool was not validated")
    if candidate_manifest.get("E3_top10_reproducibility", {}).get("mismatches") != 0:
        raise RuntimeError("E3 Top-10 was not reproducible")
    return {
        "frozen": frozen,
        "hashes": hashes,
        "phase13_protected": protected_expected,
        "phase13_protected_count": len(protected_expected),
        "e3_manifest": e3,
        "initial_e4_manifest": initial_e4,
        "candidate_manifest": candidate_manifest,
        "git_commit": get_git_commit(ROOT),
    }


def _candidate_map(rows: list[dict[str, Any]], questions: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row["question_id"])].append(row)
    expected_ids = [str(row["question_id"]) for row in questions]
    if set(grouped) != set(expected_ids):
        raise RuntimeError("RRF candidate pool question IDs differ from the frozen benchmark")
    for qid in expected_ids:
        grouped[qid].sort(key=lambda row: int(row["rank"]))
        if len(grouped[qid]) != 50 or [int(row["rank"]) for row in grouped[qid]] != list(range(1, 51)):
            raise RuntimeError(f"RRF candidate pool must contain exactly Top 50 for {qid}")
    return dict(grouped)


def _rerank_candidates(runtime: CrossEncoderRuntime, question: str, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ids = [str(row["chunk_id"]) for row in candidates]
    if len(ids) != len(set(ids)):
        raise RuntimeError("Duplicate candidate chunk IDs in RRF Top 50")
    scores = runtime.score_pairs(question, [str(row["text"]) for row in candidates])
    if len(scores) != len(candidates) or not all(math.isfinite(value) for value in scores):
        raise RuntimeError("Candidate scoring returned missing or non-finite scores")
    ranked = []
    for row, score in zip(candidates, scores, strict=True):
        candidate = dict(row)
        candidate["reranker_score"] = float(score)
        ranked.append(candidate)
    ranked.sort(key=lambda row: (-row["reranker_score"], int(row["rank"]), str(row["chunk_id"])))
    for rank, row in enumerate(ranked, start=1):
        row["reranker_rank"] = rank
    if [str(row["chunk_id"]) for row in ranked] and set(str(row["chunk_id"]) for row in ranked) != set(ids):
        raise RuntimeError("Reranker added or removed candidates")
    return ranked


def _run_mini_gate(runtime: CrossEncoderRuntime, questions: list[dict[str, Any]], grouped: dict[str, list[dict[str, Any]]]) -> tuple[dict[str, Any], dict[str, Any]]:
    mini_questions = questions[:10]
    if len(mini_questions) != 10:
        raise RuntimeError("The frozen question set does not contain 10 smoke-test questions")
    pass_scores: list[dict[str, list[float]]] = []
    pass_rankings: list[dict[str, list[str]]] = []
    pass_latencies: list[list[float]] = []
    token_lengths: list[int] = []
    truncated_pairs = 0
    same_candidates = True
    for pass_index in range(2):
        scores_by_qid: dict[str, list[float]] = {}
        rankings_by_qid: dict[str, list[str]] = {}
        query_latencies: list[float] = []
        for question in mini_questions:
            qid = str(question["question_id"])
            candidates = grouped[qid]
            if pass_index == 0:
                raw_lengths = runtime.untruncated_token_lengths(
                    str(question["question"]), [str(row["text"]) for row in candidates]
                )
                token_lengths.extend(raw_lengths)
                truncated_pairs += sum(length > runtime.max_length for length in raw_lengths)
            started = time.perf_counter()
            ranked = _rerank_candidates(runtime, str(question["question"]), candidates)
            query_latencies.append(time.perf_counter() - started)
            scores_by_qid[qid] = [float(row["reranker_score"]) for row in sorted(ranked, key=lambda item: int(item["rank"]))]
            rankings_by_qid[qid] = [str(row["chunk_id"]) for row in ranked]
            if {row["chunk_id"] for row in ranked} != {row["chunk_id"] for row in candidates} or len(ranked) != 50:
                same_candidates = False
        pass_scores.append(scores_by_qid)
        pass_rankings.append(rankings_by_qid)
        pass_latencies.append(query_latencies)

    score_differences = [
        abs(left[qid][i] - right[qid][i])
        for qid in pass_scores[0]
        for i in range(50)
        for left, right in [(pass_scores[0], pass_scores[1])]
    ]
    ranking_differences = [
        qid for qid in pass_rankings[0]
        if pass_rankings[0][qid] != pass_rankings[1][qid]
    ]
    all_finite = all(math.isfinite(value) for record in pass_scores for values in record.values() for value in values)
    mini = {
        "status": "passed" if all_finite and same_candidates and not ranking_differences else "failed",
        "question_count": len(mini_questions),
        "question_ids": [str(question["question_id"]) for question in mini_questions],
        "pairs_expected_per_pass": 500,
        "pairs_scored_per_pass": sum(len(value) for value in pass_scores[0].values()),
        "passes": 2,
        "all_scores_finite": all_finite,
        "candidate_count_preserved": same_candidates,
        "ranking_difference_questions": ranking_differences,
        "raw_score_difference": {
            "max_absolute": max(score_differences, default=0.0),
            "mean_absolute": statistics.mean(score_differences) if score_differences else 0.0,
            "exactly_equal_pairs": sum(value == 0.0 for value in score_differences),
            "compared_pairs": len(score_differences),
        },
        "query_latency_seconds_pass1": _distribution(pass_latencies[0]),
        "query_latency_seconds_pass2": _distribution(pass_latencies[1]),
        "runtime_config": {
            "device": runtime.load_info.device,
            "dtype": runtime.load_info.dtype,
            "batch_size": runtime.load_info.batch_size,
            "max_length": runtime.load_info.max_sequence_length,
        },
    }
    truncation = {
        "sample": "first 10 questions in frozen Grounded Silver v1 order; RRF Top 50 per question",
        "total_pairs": len(token_lengths),
        "truncated_pairs": truncated_pairs,
        "truncation_rate": truncated_pairs / len(token_lengths) if token_lengths else None,
        "input_tokens_before_truncation": _distribution(token_lengths),
        "max_length": runtime.max_length,
        "truncation_strategy": "longest_first, right side, configured cap 512 including special tokens",
        "padding_policy": "longest sequence in each batch",
        "abnormality_threshold": None,
        "note": "No truncation threshold was specified; the observed rate is reported without changing max_length.",
    }
    return mini, truncation


def _peak_working_set_bytes() -> int | None:
    if os.name != "nt":
        return None
    from ctypes import wintypes

    size_t = ctypes.c_size_t

    class ProcessMemoryCounters(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
            ("PeakWorkingSetSize", size_t), ("WorkingSetSize", size_t),
            ("QuotaPeakPagedPoolUsage", size_t), ("QuotaPagedPoolUsage", size_t),
            ("QuotaPeakNonPagedPoolUsage", size_t), ("QuotaNonPagedPoolUsage", size_t),
            ("PagefileUsage", size_t), ("PeakPagefileUsage", size_t),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessMemoryCounters), wintypes.DWORD]
    psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
    counters = ProcessMemoryCounters()
    counters.cb = ctypes.sizeof(ProcessMemoryCounters)
    if not psapi.GetProcessMemoryInfo(kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
        return None
    return int(counters.PeakWorkingSetSize)


def _runtime_package_versions() -> dict[str, str | None]:
    names = ("torch", "transformers", "huggingface-hub", "tokenizers", "safetensors", "sentencepiece", "hf-xet")
    result = {}
    for name in names:
        try:
            result[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            result[name] = None
    return result


def _model_file_checksums(snapshot: Path) -> dict[str, dict[str, Any]]:
    result = {}
    for name in ("config.json", "tokenizer_config.json", "tokenizer.json", "special_tokens_map.json", "sentencepiece.bpe.model", "model.safetensors"):
        path = snapshot / name
        if path.is_file():
            result[name] = {"size_bytes": path.stat().st_size, "sha256": _hash(path)}
    return result


def _metric_rows(
    questions: list[dict[str, Any]],
    corpus: list[dict[str, Any]],
    reranked_by_qid: dict[str, list[dict[str, Any]]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    corpus_by_id = {str(row["chunk_id"]): row for row in corpus}
    rows: list[dict[str, Any]] = []
    traces: list[dict[str, Any]] = []
    full_by_qid: dict[str, list[RankedHit]] = {}
    for question in questions:
        qid = str(question["question_id"])
        full_rows = reranked_by_qid[qid]
        hits = [
            RankedHit(
                rank=index,
                chunk_id=str(row["chunk_id"]),
                document_id=str(row["document_id"]),
                page=int(row["page"]) if row.get("page") is not None else None,
                raw_score=float(row["reranker_score"]),
                normalized_score=float(row["reranker_score"]),
                page_end=int(row["page_end"]) if row.get("page_end") is not None else None,
            )
            for index, row in enumerate(full_rows, start=1)
        ]
        full_by_qid[qid] = hits
        top10 = tuple(hits[:10])
        result = RetrievalResult(qid, top10)
        evidence = _required_evidence(question, corpus_by_id)
        metrics = {granularity: metric_bundle(result, evidence[granularity], granularity).scores for granularity in GRANULARITIES}
        qrow = {
            "question_id": qid,
            "question": question,
            "metrics": metrics,
            "required_evidence_coverage": _evidence_coverage(hits, question),
            "retrieval_top10_chunk_ids": [hit.chunk_id for hit in top10],
            "reranker_candidate_count": len(full_rows),
        }
        rows.append(qrow)

        required_chunks = {str(item) for item in question.get("required_chunks") or []}
        required_docs = {str(item) for item in question.get("required_documents") or []}
        required_pages = {
            (str(item.get("document_id")), int(item["page"]))
            for item in question.get("required_pages") or [] if item.get("page") is not None
        }
        for row in full_rows[:10]:
            pages = {(str(row["document_id"]), page)
                     for page in range(int(row["page"]), int(row.get("page_end") or row["page"]) + 1)} if row.get("page") is not None else set()
            traces.append({
                "question_id": qid,
                "question": question["question"],
                "query_style": question.get("query_style"),
                "lexical_overlap": question.get("lexical_overlap"),
                "species": question.get("species") or "unknown",
                "category": question.get("category"),
                "rank": row["reranker_rank"],
                "final_rank": row["reranker_rank"],
                "chunk_id": row["chunk_id"],
                "document_id": row["document_id"],
                "page": row.get("page"),
                "page_end": row.get("page_end"),
                "bm25_rank": row.get("bm25_rank"),
                "dense_rank": row.get("dense_rank"),
                "rrf_rank": row.get("rank"),
                "rrf_score": row.get("rrf_score"),
                "reranker_score": row["reranker_score"],
                "reranker_rank": row["reranker_rank"],
                "required_evidence": row["chunk_id"] in required_chunks,
                "is_required_evidence": row["chunk_id"] in required_chunks,
                "chunk_match": row["chunk_id"] in required_chunks,
                "page_match": bool(pages & required_pages),
                "document_match": str(row["document_id"]) in required_docs,
            })
    return rows, traces, full_by_qid


def _error_rows(
    questions: list[dict[str, Any]],
    full_hits: dict[str, list[RankedHit]],
    pools: dict[str, list[dict[str, Any]]],
    e3_top10: dict[str, set[str]],
) -> list[dict[str, Any]]:
    errors = []
    for question in questions:
        qid = str(question["question_id"])
        qhits = full_hits[qid]
        required = {str(value) for value in question.get("required_chunks") or []}
        pool_ids = {str(value["chunk_id"]) for value in pools[qid]}
        top10_ids = {hit.chunk_id for hit in qhits[:10]}
        missing_required = sorted(required - top10_ids)
        if not missing_required:
            continue
        missing_from_pool = sorted(required - pool_ids)
        base = _error_candidate(question, qhits[:10], qhits)
        if missing_from_pool:
            category = "candidate_generation_failure"
        elif required & e3_top10.get(qid, set()):
            category = "reranker_rank_dilution"
        else:
            category = "reranker_misranking"
        errors.append({
            **base,
            "error_category": category,
            "required_chunks_missing_from_e3_top50": missing_from_pool,
            "required_chunks_available_but_not_in_e4_top10": sorted((required & pool_ids) - top10_ids),
            "e3_top10_required_hit": bool(required & e3_top10.get(qid, set())),
            "candidate_generation_failure": bool(missing_from_pool),
            "reranker_rescue": False,
            "taxonomy": [*ERROR_TAXONOMY, *RERANKER_ERROR_TYPES],
        })
    return errors


def _group_comparison(
    systems: dict[str, list[dict[str, Any]]],
    *,
    field: str,
    overlap: bool = False,
    expected_order: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    keys = ("low", "medium", "high") if overlap else None
    grouped: dict[str, dict[str, list[dict[str, Any]]]] = {}
    all_labels: set[str] = set(keys or ())
    for system, rows in systems.items():
        local: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            question = row["question"]
            if overlap:
                key = lexical_overlap_bucket(float(question.get("lexical_overlap") or 0.0))
            else:
                raw = question.get(field)
                key = str(raw) if raw not in (None, "") else "unknown"
            local[key].append(row)
        if expected_order:
            for key in expected_order:
                local.setdefault(key, [])
        grouped[system] = local
        all_labels.update(local)
    out = {}
    for label in sorted(all_labels):
        out[label] = {system: _summarize_rows(grouped[system].get(label, [])) for system in systems}
    if overlap:
        return {"boundaries": {"low": "<0.35", "medium": "0.35–0.55", "high": ">0.55"}, "groups": out}
    return out


def _paired_bootstrap(e3_rows: list[dict[str, Any]], e4_rows: list[dict[str, Any]]) -> dict[str, Any]:
    if [str(row["question_id"]) for row in e3_rows] != [str(row["question_id"]) for row in e4_rows]:
        raise ValueError("Paired bootstrap requires the same ordered question IDs")
    metric_names = ("recall@1", "recall@5", "recall@10", "mrr", "ndcg@10")
    rng = random.Random(BOOTSTRAP_SEED)
    n = len(e3_rows)
    result: dict[str, Any] = {
        "method": "paired question-level percentile bootstrap with replacement",
        "iterations": BOOTSTRAP_ITERATIONS,
        "seed": BOOTSTRAP_SEED,
        "sample_unit": "question_id",
        "confidence_level": 0.95,
        "interpretation_limit": "Intervals describe uncertainty on this AI-generated Silver benchmark sample, not the full aquaculture question population.",
        "metrics": {},
    }
    for granularity in GRANULARITIES:
        result["metrics"][granularity] = {}
        for metric in metric_names:
            left = [float(row["metrics"][granularity][metric]) for row in e3_rows]
            right = [float(row["metrics"][granularity][metric]) for row in e4_rows]
            left_samples: list[float] = []
            right_samples: list[float] = []
            delta_samples: list[float] = []
            for _ in range(BOOTSTRAP_ITERATIONS):
                indices = [rng.randrange(n) for _ in range(n)]
                mean_left = sum(left[index] for index in indices) / n
                mean_right = sum(right[index] for index in indices) / n
                left_samples.append(mean_left)
                right_samples.append(mean_right)
                delta_samples.append(mean_right - mean_left)

            def interval(samples: list[float]) -> dict[str, float]:
                samples.sort()
                return {
                    "lower_95": samples[int(0.025 * (BOOTSTRAP_ITERATIONS - 1))],
                    "upper_95": samples[int(0.975 * (BOOTSTRAP_ITERATIONS - 1))],
                }

            result["metrics"][granularity][metric] = {
                "E3": interval(left_samples),
                "E4": interval(right_samples),
                "E4_minus_E3_paired": interval(delta_samples),
                "delta_point_estimate": sum(right) / n - sum(left) / n,
            }
    return result


def _rescue_regression(
    questions: list[dict[str, Any]],
    e3_top10: dict[str, set[str]],
    e4_full: dict[str, list[RankedHit]],
    phase13_rank_movement: dict[tuple[str, str], dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    aggregate = {str(k): Counter() for k in (1, 5, 10)}
    rows = []
    for question in questions:
        qid = str(question["question_id"])
        required = {str(value) for value in question.get("required_chunks") or []}
        e3ranks = {chunk: rank for chunk, rank in ((chunk, phase13_rank_movement.get((qid, chunk), {}).get("rrf_rank")) for chunk in required) if rank is not None}
        e4ranks = {hit.chunk_id: hit.rank for hit in e4_full[qid]}
        first_e3 = min(e3ranks.values(), default=None)
        first_e4 = min((e4ranks[chunk] for chunk in required if chunk in e4ranks), default=None)
        by_k = {}
        for k in (1, 5, 10):
            e3_hit = bool(required & e3_top10.get(qid, set()) and any(rank <= k for chunk, rank in e3ranks.items()))
            e4_hit = any(e4ranks.get(chunk, 10**9) <= k for chunk in required)
            label = "both_hit" if e3_hit and e4_hit else "reranker_rescue" if (not e3_hit and e4_hit) else "reranker_regression" if (e3_hit and not e4_hit) else "both_miss"
            aggregate[str(k)][label] += 1
            by_k[str(k)] = {"e3_required_hit": e3_hit, "e4_required_hit": e4_hit, "comparison": label}
        if first_e3 is None or first_e4 is None:
            movement = "not_retrieved"
        elif first_e4 < first_e3:
            movement = "e4_improves_rank"
        elif first_e4 == first_e3:
            movement = "e4_same_rank"
        else:
            movement = "e4_worsens_rank"
        rows.append({
            "question_id": qid,
            "required_chunk_ids": sorted(required),
            "e3_first_required_rank_full_union": first_e3,
            "e4_first_required_rank_top50": first_e4,
            "rank_delta_e4_minus_e3": first_e4 - first_e3 if first_e3 is not None and first_e4 is not None else None,
            "rank_movement": movement,
            "by_k": by_k,
        })
    movement_counts = Counter(row["rank_movement"] for row in rows)
    return {
        "question_count": len(questions),
        "by_k": {k: {name: aggregate[k][name] for name in ("reranker_rescue", "reranker_regression", "both_hit", "both_miss")} for k in aggregate},
        "rank_movement_counts": {name: movement_counts.get(name, 0) for name in ("e4_improves_rank", "e4_same_rank", "e4_worsens_rank", "not_retrieved")},
        "per_question": rows,
    }, rows


def _rank_dilution_recovery(
    questions: list[dict[str, Any]],
    e4_full: dict[str, list[RankedHit]],
    pools: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    phase13_dir = ROOT / "reports/evaluation/experiments/E1_E2_E3_grounded_v1"
    diagnostic_path = phase13_dir / "error_analysis.json"
    diagnostic = _read_json(diagnostic_path)
    prior = diagnostic.get("per_question_fusion_diagnostics", [])
    movement_path = phase13_dir / "rank_movement.json"
    movement = _read_json(movement_path).get("records", [])
    move_by = {(str(row["question_id"]), str(row["required_chunk_id"])): row for row in movement}
    question_by_id = {str(row["question_id"]): row for row in questions}
    output_rows = []
    counts = Counter()
    for item in prior:
        qid = str(item["question_id"])
        for diagnostic_type, key in (
            ("fusion_rank_dilution", "fusion_rank_dilution_chunks"),
            ("good_candidate_bad_fusion", "good_candidate_bad_fusion_chunks"),
        ):
            for chunk_id in item.get(key, []):
                e3row = move_by.get((qid, str(chunk_id)), {})
                e3rank = e3row.get("rrf_rank")
                pool = pools.get(qid, [])
                e4_by_id = {hit.chunk_id: hit.rank for hit in e4_full.get(qid, [])}
                e4rank = e4_by_id.get(str(chunk_id))
                if str(chunk_id) not in {str(row["chunk_id"]) for row in pool}:
                    status = "candidate_generation_failure"
                elif e3rank is not None and int(e3rank) > 10 and e4rank is not None and e4rank <= 10:
                    status = "reranker_recovered"
                elif e3rank is not None and e4rank == int(e3rank):
                    status = "unchanged"
                elif e3rank is not None and e4rank is not None and e4rank > int(e3rank):
                    status = "further_degraded"
                elif e3rank is not None and e4rank is not None and e4rank < int(e3rank):
                    status = "improved_rank_not_top10"
                else:
                    status = "unknown_baseline_rank"
                counts[f"{diagnostic_type}:{status}"] += 1
                output_rows.append({
                    "question_id": qid,
                    "question": question_by_id.get(qid, {}).get("question"),
                    "diagnostic": diagnostic_type,
                    "required_chunk_id": str(chunk_id),
                    "e3_rrf_rank": e3rank,
                    "e4_reranker_rank": e4rank,
                    "rank_delta_e4_minus_e3": e4rank - int(e3rank) if e3rank is not None and e4rank is not None else None,
                    "status": status,
                })
    summary = {
        "source_phase13_diagnostics": str(diagnostic_path.relative_to(ROOT)).replace("\\", "/"),
        "fusion_rank_dilution_source_question_count": sum(bool(row.get("fusion_rank_dilution")) for row in prior),
        "good_candidate_bad_fusion_source_question_count": sum(bool(row.get("good_candidate_bad_fusion")) for row in prior),
        "tracked_required_evidence_count": len(output_rows),
        "counts": dict(sorted(counts.items())),
        "records": output_rows,
    }
    return summary


def _trace_rows_for_all_pairs(
    questions: list[dict[str, Any]],
    reranked_by_qid: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    question_by_id = {str(row["question_id"]): row for row in questions}
    all_rows = []
    for question in questions:
        qid = str(question["question_id"])
        required = {str(value) for value in question.get("required_chunks") or []}
        for row in reranked_by_qid[qid]:
            all_rows.append({
                "question_id": qid,
                "chunk_id": row["chunk_id"],
                "document_id": row["document_id"],
                "page": row.get("page"),
                "rrf_rank": row["rank"],
                "rrf_score": row["rrf_score"],
                "bm25_rank": row.get("bm25_rank"),
                "dense_rank": row.get("dense_rank"),
                "reranker_score": row["reranker_score"],
                "reranker_rank": row["reranker_rank"],
                "final_rank": row["reranker_rank"],
                "required_evidence": str(row["chunk_id"]) in required,
                "question": question_by_id[qid]["question"],
            })
    return all_rows


def _persist_blocked_history() -> None:
    archive = ROOT / RUNTIME_REL / "phase14_blocked_snapshot"
    archive.mkdir(parents=True, exist_ok=True)
    for name in ("experiment_manifest.json", "runtime_preflight.json", "overall.json", "latency.json", "errors.jsonl", "compatibility.json", "protected_artifacts_validation.json"):
        source = ROOT / E4_REL / name
        target = archive / name
        if source.is_file() and not target.exists():
            shutil.copy2(source, target)


def _write_comparison_reports(
    e4_rows: list[dict[str, Any]],
    e4_full: dict[str, list[RankedHit]],
    reranked_by_qid: dict[str, list[dict[str, Any]]],
    questions: list[dict[str, Any]],
    pools: dict[str, list[dict[str, Any]]],
    traces: list[dict[str, Any]],
    errors: list[dict[str, Any]],
    hashes: dict[str, str],
    model_info: dict[str, Any],
    mini_report: dict[str, Any],
    latency: dict[str, Any],
) -> dict[str, Any]:
    e1dir = ROOT / "reports/evaluation/experiments/E1_grounded_bm25_v1"
    e2dir = ROOT / "reports/evaluation/experiments/E2_grounded_dense_v1"
    e3dir = ROOT / "reports/evaluation/experiments/E3_grounded_rrf_v1"
    e1_rows = read_jsonl(e1dir / "per_question.jsonl")
    e2_rows = read_jsonl(e2dir / "per_question.jsonl")
    e3_rows = read_jsonl(e3dir / "per_question.jsonl")
    frozen_ids = [str(q["question_id"]) for q in questions]
    for name, values in (("E1", e1_rows), ("E2", e2_rows), ("E3", e3_rows), ("E4", e4_rows)):
        if [str(row["question_id"]) for row in values] != frozen_ids:
            raise RuntimeError(f"{name} ordered question IDs differ from frozen benchmark")
    systems = {"E1_BM25": e1_rows, "E2_BGE_M3_Dense": e2_rows, "E3_RRF": e3_rows, "E4_RRF_Reranker": e4_rows}
    overall = {name: _summarize_rows(rows) for name, rows in systems.items()}

    e4_overall = dict(overall["E4_RRF_Reranker"])
    e4_overall.update({"experiment_id": "E4_grounded_rrf_reranker_v1", "benchmark_type": "AI-generated corpus-grounded Silver; not human Gold"})
    e4_overall.update({
        "required_evidence_coverage": e4_overall.get("required_evidence"),
        "candidate_generation_failure_questions": sum(bool(row.get("error_category") == "candidate_generation_failure") for row in errors),
    })
    e4_dir = ROOT / E4_REL
    e4_dir.mkdir(parents=True, exist_ok=True)
    write_json(e4_dir / "overall.json", e4_overall)
    write_json(e4_dir / "by_query_style.json", _group_reports(e4_rows, field="query_style"))
    overlap_e4 = {bucket: _summarize_rows([row for row in e4_rows if lexical_overlap_bucket(float(row["question"].get("lexical_overlap") or 0.0)) == bucket]) for bucket in ("low", "medium", "high")}
    write_json(e4_dir / "by_overlap.json", {"boundaries": {"low": "<0.35", "medium": "0.35–0.55", "high": ">0.55"}, "groups": overlap_e4})
    write_json(e4_dir / "by_species.json", _group_reports(e4_rows, field="species", expected_order=SPECIES_REPORT_ORDER))
    write_json(e4_dir / "by_category.json", _group_reports(e4_rows, field="category", expected_order=CATEGORY_REPORT_ORDER))
    write_json(e4_dir / "by_difficulty.json", _group_reports(e4_rows, field="difficulty"))
    write_jsonl(e4_dir / "per_question.jsonl", e4_rows)
    write_jsonl(e4_dir / "ranking_traces.jsonl", traces)
    # Trace objects include candidate provenance and all three prior ranks.
    all_pairs = []
    for question in questions:
        qid = str(question["question_id"])
        required = {str(value) for value in question.get("required_chunks") or []}
        for row in pools[qid]:
            reranker_row = next(item for item in reranked_by_qid[qid] if str(item["chunk_id"]) == str(row["chunk_id"]))
            all_pairs.append({
                "question_id": qid, "question": question["question"],
                "query_style": question.get("query_style"), "lexical_overlap": question.get("lexical_overlap"),
                "chunk_id": row["chunk_id"], "document_id": row["document_id"], "page": row.get("page"),
                "rank": row["rank"], "rrf_rank": row["rank"], "rrf_score": row["rrf_score"],
                "bm25_rank": row.get("bm25_rank"), "dense_rank": row.get("dense_rank"),
                "reranker_score": reranker_row["reranker_score"], "reranker_rank": reranker_row["reranker_rank"],
                "final_rank": reranker_row["reranker_rank"], "required_evidence": str(row["chunk_id"]) in required,
                "is_required_evidence": str(row["chunk_id"]) in required,
            })
    write_jsonl(e4_dir / "reranker_traces.jsonl", all_pairs)
    write_jsonl(e4_dir / "errors.jsonl", errors)
    write_json(e4_dir / "latency.json", latency)

    comparison_dir = ROOT / COMPARE_REL
    comparison_dir.mkdir(parents=True, exist_ok=True)
    comparison = {
        "status": "completed",
        "benchmark_type": "AI-generated corpus-grounded Silver; not human Gold",
        "question_count": len(questions),
        "retrieval_chunk_count": 2224,
        "same_questions": True,
        "same_retrieval_corpus": True,
        "same_required_evidence": True,
        "same_metric_implementation": "src.evaluation.retrieval.metrics.metric_bundle",
        "same_top_k": [1, 3, 5, 10],
        "E4_model_revision": model_info["revision"],
        "overall": overall,
        "E4_minus_E3_point_estimates": {
            granularity: {
                metric: overall["E4_RRF_Reranker"]["metrics"][granularity][metric]
                - overall["E3_RRF"]["metrics"][granularity][metric]
                for metric in ("recall@1", "recall@5", "recall@10", "mrr", "ndcg@10")
            }
            for granularity in GRANULARITIES
        },
        "interpretation": "Silver benchmark results are descriptive; point estimates alone do not establish superiority.",
    }
    write_json(comparison_dir / "comparison.json", comparison)
    group_specs = (
        ("by_query_style.json", "query_style", False, None),
        ("by_overlap.json", "lexical_overlap", True, None),
        ("by_species.json", "species", False, SPECIES_REPORT_ORDER),
        ("by_category.json", "category", False, CATEGORY_REPORT_ORDER),
        ("by_difficulty.json", "difficulty", False, None),
    )
    for filename, field, overlap, order in group_specs:
        write_json(comparison_dir / filename, _group_comparison(systems, field=field, overlap=overlap, expected_order=order))

    e3_top10: dict[str, set[str]] = defaultdict(set)
    for row in read_jsonl(e3dir / "ranking_traces.jsonl"):
        if int(row["rank"]) <= 10 and row.get("chunk_match"):
            e3_top10[str(row["question_id"])].add(str(row["chunk_id"]))
    phase13_movement = _read_json(ROOT / "reports/evaluation/experiments/E1_E2_E3_grounded_v1/rank_movement.json").get("records", [])
    phase13_rank_movement = {(str(row["question_id"]), str(row["required_chunk_id"])): row for row in phase13_movement}
    rescue_summary, rescue_rows = _rescue_regression(questions, e3_top10, e4_full, phase13_rank_movement)
    write_json(comparison_dir / "rescue_regression.json", rescue_summary)
    movement_rows = []
    for question in questions:
        qid = str(question["question_id"])
        e4ranks = {hit.chunk_id: hit.rank for hit in e4_full[qid]}
        for chunk_id in sorted({str(x) for x in question.get("required_chunks") or []}):
            old = phase13_rank_movement.get((qid, chunk_id), {})
            pool_has = chunk_id in {str(row["chunk_id"]) for row in pools[qid]}
            e4rank = e4ranks.get(chunk_id)
            movement_rows.append({
                "question_id": qid,
                "required_chunk_id": chunk_id,
                "best_baseline_rank_top50": old.get("best_baseline_rank_top50"),
                "e3_rrf_rank_full_union": old.get("rrf_rank"),
                "e3_rrf_rank_top50": old.get("rrf_rank") if pool_has else None,
                "e4_reranker_rank_top50": e4rank,
                "candidate_generation_failure": not pool_has,
                "rank_delta_vs_e3": e4rank - old["rrf_rank"] if e4rank is not None and old.get("rrf_rank") is not None and pool_has else None,
            })
    write_json(comparison_dir / "rank_movement.json", {
        "definition": "Reranker rank is measured only within the frozen RRF Top 50; null means the required chunk was absent from that candidate set.",
        "candidate_depth": 50,
        "candidate_generation_failure_count": sum(row["candidate_generation_failure"] for row in movement_rows),
        "records": movement_rows,
    })
    dilution = _rank_dilution_recovery(questions, e4_full, pools)
    write_json(comparison_dir / "rank_dilution_recovery.json", dilution)
    bootstrap = _paired_bootstrap(e3_rows, e4_rows)
    write_json(comparison_dir / "bootstrap_ci.json", bootstrap)
    error_counts = Counter(row["error_category"] for row in errors)
    taxonomy_counts = {name: error_counts.get(name, 0) for name in (*ERROR_TAXONOMY, *RERANKER_ERROR_TYPES)}
    write_json(comparison_dir / "error_analysis.json", {
        "taxonomy_counts": taxonomy_counts,
        "per_question_errors": errors,
        "interpretation": "Trace-based error labels are diagnostic candidates and require review before causal claims.",
    })
    prior_leakage_path = ROOT / "reports/evaluation/experiments/E1_E2_E3_grounded_v1/leakage_audit.json"
    if prior_leakage_path.exists():
        leakage = _read_json(prior_leakage_path)
        leakage["reused_from"] = str(prior_leakage_path.relative_to(ROOT)).replace("\\", "/")
        leakage["question_set_sha256"] = hashes["grounded_questions_v1"]
        write_json(comparison_dir / "leakage_audit.json", leakage)

    summary_lines = [
        "# E1 / E2 / E3 / E4 Grounded Silver Comparison", "",
        "This is an AI-generated corpus-grounded Silver benchmark, not human Gold accuracy.",
        "All four systems use the same 169 questions, 2,224 retrieval chunks, required evidence, and metric implementation.",
        "", "## Overall chunk retrieval", "",
        "| Metric | E1 BM25 | E2 BGE-M3 | E3 RRF | E4 RRF + reranker |",
        "|---|---:|---:|---:|---:|",
    ]
    for metric in ("recall@1", "recall@5", "recall@10", "mrr", "ndcg@10"):
        vals = [overall[key]["metrics"]["chunk"][metric] for key in ("E1_BM25", "E2_BGE_M3_Dense", "E3_RRF", "E4_RRF_Reranker")]
        summary_lines.append(f"| {metric} | " + " | ".join(f"{value:.4f}" for value in vals) + " |")
    summary_lines.extend(["", "## E4 − E3 paired 95% CI (chunk)", "", "| Metric | Difference | 95% CI | Interpretation |", "|---|---:|---:|---|"])
    for metric in ("recall@1", "recall@5", "recall@10", "mrr", "ndcg@10"):
        item = bootstrap["metrics"]["chunk"][metric]
        ci = item["E4_minus_E3_paired"]
        interpretation = "difference not clearly separated on this Silver benchmark sample" if ci["lower_95"] <= 0 <= ci["upper_95"] else "paired interval excludes zero on this Silver benchmark sample"
        summary_lines.append(f"| {metric} | {item['delta_point_estimate']:.4f} | {ci['lower_95']:.4f} to {ci['upper_95']:.4f} | {interpretation} |")
    summary_lines.extend(["", "E4 latency and truncation details are in the E4 report directory. Statistical intervals describe this Silver sample only."])
    (comparison_dir / "comparison_summary.md").write_text("\n".join(summary_lines) + "\n", encoding="utf-8", newline="\n")
    return {
        "overall": overall,
        "comparison": comparison,
        "bootstrap": bootstrap,
        "rescue_regression": rescue_summary,
        "rank_dilution_recovery": dilution,
        "error_taxonomy_counts": taxonomy_counts,
        "e4_overall": e4_overall,
    }


def main() -> int:
    freeze = _verify_freeze()
    frozen = freeze["frozen"]
    questions = frozen["questions"]
    pools_rows = read_jsonl(ROOT / CANDIDATE_REL)
    pools = _candidate_map(pools_rows, questions)
    if _hash(ROOT / CANDIDATE_REL) != freeze["candidate_manifest"].get("candidate_pool_sha256"):
        raise RuntimeError("The deterministic E3 RRF Top-50 candidate pool checksum changed")

    import torch

    if not MODEL_REVISION or not (ROOT / MODEL_REL / "model.safetensors").is_file():
        raise RuntimeError("The specified model snapshot or immutable revision is missing")
    device = "cuda:0" if torch.cuda.is_available() else "cpu"
    if device.startswith("cuda"):
        torch.cuda.reset_peak_memory_stats()
    runtime = CrossEncoderRuntime(ROOT / MODEL_REL, device=device, max_length=MAX_LENGTH, batch_size=BATCH_SIZE)
    one_pair_path = ROOT / RUNTIME_REL / "one_pair_smoke.json"
    one_pair = _read_json(one_pair_path)
    if one_pair.get("status") != "passed" or one_pair.get("pairs") != 2 or not one_pair.get("finite"):
        raise RuntimeError("Required 1-query / 2-candidate smoke test did not pass")

    mini, truncation = _run_mini_gate(runtime, questions, pools)
    write_json(ROOT / RUNTIME_REL / "mini_batch_smoke.json", mini)
    write_json(ROOT / RUNTIME_REL / "truncation_audit.json", truncation)
    if mini["status"] != "passed" or mini["pairs_scored_per_pass"] != 500 or truncation["total_pairs"] != 500:
        readiness = {"reranker_runtime_ready": False, "status": "blocked_runtime", "blocking_reason": "Mini-batch gate failed", "mini_batch": mini, "truncation": truncation}
        write_json(ROOT / RUNTIME_REL / "runtime_readiness.json", readiness)
        print(json.dumps(readiness, ensure_ascii=False, indent=2))
        return 2

    model_file_checksums = _model_file_checksums(ROOT / MODEL_REL)
    runtime_packages = _runtime_package_versions()
    model_config = _read_json(ROOT / MODEL_REL / "config.json")
    tokenizer_config = _read_json(ROOT / MODEL_REL / "tokenizer_config.json")
    if not all(runtime_packages.get(key) for key in ("torch", "transformers", "huggingface-hub", "tokenizers", "safetensors")):
        readiness = {"reranker_runtime_ready": False, "status": "blocked_runtime", "blocking_reason": "Runtime package metadata is incomplete"}
        write_json(ROOT / RUNTIME_REL / "runtime_readiness.json", readiness)
        print(json.dumps(readiness, ensure_ascii=False, indent=2))
        return 2
    readiness = {
        "reranker_runtime_ready": True,
        "status": "ready",
        "model_loaded": True,
        "model_id": MODEL_ID,
        "resolved_revision": MODEL_REVISION,
        "model_file_checksums": model_file_checksums,
        "runtime_packages": runtime_packages,
        "device": runtime.load_info.device,
        "dtype": runtime.load_info.dtype,
        "max_sequence_length": MAX_LENGTH,
        "truncation_policy": truncation["truncation_strategy"],
        "padding_policy": truncation["padding_policy"],
        "batch_size": BATCH_SIZE,
        "score_extraction": "raw XLMRobertaForSequenceClassification logits.float(); higher score ranks first",
        "tokenizer_class": runtime.load_info.tokenizer_class,
        "tokenizer_is_fast": runtime.load_info.tokenizer_is_fast,
        "one_pair_smoke_passed": True,
        "mini_batch_questions": 10,
        "mini_batch_pairs_per_pass": mini["pairs_scored_per_pass"],
        "mini_batch_passes": mini["passes"],
        "mini_batch_finite": mini["all_scores_finite"],
        "mini_batch_candidate_ids_preserved": mini["candidate_count_preserved"],
        "determinism": mini["raw_score_difference"],
        "ranking_difference_questions": mini["ranking_difference_questions"],
    }
    write_json(ROOT / RUNTIME_REL / "runtime_readiness.json", readiness)
    write_json(ROOT / RUNTIME_REL / "model_metadata.json", {
        "model_id": MODEL_ID,
        "revision": MODEL_REVISION,
        "snapshot_location": str((ROOT / MODEL_REL).resolve()),
        "snapshot_repository": "BAAI/bge-reranker-v2-m3",
        "config": model_config,
        "tokenizer_config": tokenizer_config,
        "files": model_file_checksums,
        "acquired_at": "2026-10-04T14:26:31.784992Z",
        "model_class": runtime.load_info.model_class,
        "parameter_count": runtime.load_info.parameter_count,
        "tokenizer_class": runtime.load_info.tokenizer_class,
        "tokenizer_fast": runtime.load_info.tokenizer_is_fast,
    })

    # The full E4 run is gated exclusively on the preflight and fixed 500-pair mini batch.
    e4_questions = questions
    reranked_by_qid: dict[str, list[dict[str, Any]]] = {}
    query_latencies: list[float] = []
    total_scoring_seconds = 0.0
    for question in e4_questions:
        qid = str(question["question_id"])
        started = time.perf_counter()
        reranked_by_qid[qid] = _rerank_candidates(runtime, str(question["question"]), pools[qid])
        elapsed = time.perf_counter() - started
        query_latencies.append(elapsed)
        total_scoring_seconds += elapsed
        if len(reranked_by_qid[qid]) != 50:
            raise RuntimeError(f"Candidate loss for {qid}")
    if len(reranked_by_qid) != 169 or sum(map(len, reranked_by_qid.values())) != 8450:
        raise RuntimeError("Full E4 scoring did not cover exactly 169 × 50 candidate pairs")

    e4_rows, traces, e4_full = _metric_rows(e4_questions, frozen["corpus"], reranked_by_qid)
    e3_trace_rows = read_jsonl(ROOT / "reports/evaluation/experiments/E3_grounded_rrf_v1/ranking_traces.jsonl")
    e3_top10: dict[str, set[str]] = defaultdict(set)
    for row in e3_trace_rows:
        if row.get("chunk_match"):
            e3_top10[str(row["question_id"])].add(str(row["chunk_id"]))
    errors = _error_rows(e4_questions, e4_full, pools, e3_top10)

    peak_vram_allocated = int(torch.cuda.max_memory_allocated()) if torch.cuda.is_available() else None
    peak_vram_reserved = int(torch.cuda.max_memory_reserved()) if torch.cuda.is_available() else None
    latency = {
        "status": "measured",
        "model_load_seconds": runtime.load_info.model_load_seconds,
        "total_pairs": 8450,
        "total_scoring_seconds": total_scoring_seconds,
        "pair_throughput_per_second": 8450 / total_scoring_seconds if total_scoring_seconds else None,
        "query_rerank_latency_seconds": _distribution(query_latencies),
        "query_rerank_latency_ms": _distribution([value * 1000 for value in query_latencies]),
        "batch_size": BATCH_SIZE,
        "device": device,
        "dtype": "float32",
        "peak_ram_working_set_bytes": _peak_working_set_bytes(),
        "peak_vram_allocated_bytes": peak_vram_allocated,
        "peak_vram_reserved_bytes": peak_vram_reserved,
    }

    _persist_blocked_history()
    e1_sha = freeze["hashes"]["E1_manifest"]
    e2_sha = freeze["hashes"]["E2_manifest"]
    e2_index_sha = freeze["hashes"]["E2_dense_index_manifest"]
    e3_manifest = freeze["e3_manifest"]
    manifest = {
        "experiment_id": "E4_grounded_rrf_reranker_v1",
        "status": "completed",
        "timestamp": utc_now(),
        "git_commit": freeze["git_commit"],
        "benchmark_type": "AI-generated corpus-grounded Silver; not human Gold",
        "evaluation_corpus_v2_sha256": freeze["hashes"]["evaluation_corpus_v2"],
        "grounded_questions_v1_sha256": freeze["hashes"]["grounded_questions_v1"],
        "evidence_pool_v1_sha256": freeze["hashes"]["evidence_pool_v1"],
        "E1_manifest_sha256": e1_sha,
        "E2_manifest_sha256": e2_sha,
        "E2_dense_index_manifest_sha256": e2_index_sha,
        "E3_manifest_sha256": freeze["hashes"]["E3_manifest"],
        "E3_ranking_trace_sha256": freeze["hashes"]["E3_ranking_trace"],
        "E3_fusion_trace_sha256": freeze["hashes"]["E3_fusion_trace"],
        "E3_candidate_trace_sha256": freeze["hashes"]["E3_candidate_trace"],
        "E3_candidate_pool_sha256": freeze["candidate_manifest"]["candidate_pool_sha256"],
        "required_evidence_resolution_sha256": e3_manifest["required_evidence_resolution_sha256"],
        "question_count": 169,
        "retrieval_chunk_count": 2224,
        "candidate_depth": {"BM25": 50, "Dense": 50, "RRF": 50},
        "reranker_pairs": 8450,
        "final_top_k": 10,
        "RRF_config": e3_manifest["fusion"],
        "reranker": {
            "model_id": MODEL_ID,
            "revision": MODEL_REVISION,
            "files": model_file_checksums,
            "runtime": runtime_packages,
            "device": device,
            "dtype": "float32",
            "max_sequence_length": MAX_LENGTH,
            "tokenizer_truncation_policy": "longest_first; right truncation; cap includes special tokens",
            "padding_policy": "longest sequence in each batch",
            "batch_size": BATCH_SIZE,
            "score_extraction": "raw classification logits converted to float32; higher is more relevant",
        },
        "runtime_readiness": "passed",
        "mini_batch": mini,
        "truncation_audit": truncation,
        "metric_implementation": "src.evaluation.retrieval.metrics.metric_bundle",
        "granularities": list(GRANULARITIES),
        "gold_evidence_used_for_ranking": False,
        "reranker_input": "query plus retrieval child-chunk text only",
        "metadata_added_to_pair": False,
        "parent_context_added": False,
        "query_rewrite_used": False,
        "candidate_ids_changed": False,
        "candidate_generation_reproducibility": "E3 RRF Top 50 reproduced from frozen BM25/Dense inputs; E3 Top 10 matched exactly.",
        "bootstrap": {"method": "paired question-level percentile", "iterations": BOOTSTRAP_ITERATIONS, "seed": BOOTSTRAP_SEED},
        "prior_blocked_manifest": "reports/evaluation/reranker_runtime/phase14_blocked_snapshot/experiment_manifest.json",
    }
    results = _write_comparison_reports(
        e4_rows, e4_full, reranked_by_qid, questions, pools, traces, errors, freeze["hashes"],
        {"revision": MODEL_REVISION}, mini, latency,
    )
    write_json(ROOT / E4_REL / "experiment_manifest.json", manifest)

    # Revalidate every Phase 13 protected artifact and every Phase 14 frozen input.
    final_mismatches = []
    for relative, expected in freeze["phase13_protected"].items():
        path = ROOT / relative
        actual = _hash(path) if path.is_file() else None
        if actual != expected:
            final_mismatches.append({"path": relative, "expected": expected, "actual": actual})
    for key, relative in (
        ("evaluation_corpus_v2", "data/evaluation/corpus_v2.jsonl"),
        ("grounded_questions_v1", "data/evaluation/grounded/questions_v1.jsonl"),
        ("E1_manifest", "reports/evaluation/experiments/E1_grounded_bm25_v1/experiment_manifest.json"),
        ("E2_manifest", "reports/evaluation/experiments/E2_grounded_dense_v1/experiment_manifest.json"),
        ("E2_dense_index_manifest", "data/evaluation/indexes/E2_grounded_bge_m3_v1/index_manifest.json"),
        ("E3_manifest", "reports/evaluation/experiments/E3_grounded_rrf_v1/experiment_manifest.json"),
        ("E3_ranking_trace", "reports/evaluation/experiments/E3_grounded_rrf_v1/ranking_traces.jsonl"),
        ("E3_fusion_trace", "reports/evaluation/experiments/E3_grounded_rrf_v1/fusion_traces.jsonl"),
    ):
        actual = _hash(ROOT / relative)
        if actual != freeze["hashes"][key]:
            final_mismatches.append({"path": relative, "expected": freeze["hashes"][key], "actual": actual})
    if final_mismatches:
        raise RuntimeError(f"Frozen/protected artifacts changed during E4: {final_mismatches[:5]}")
    write_json(ROOT / E4_REL / "protected_artifacts_validation.json", {
        "status": "passed",
        "phase13_protected_artifact_count": len(freeze["phase13_protected"]),
        "mismatches": [],
        "phase13_protected_sha256": freeze["phase13_protected"],
        "phase14_frozen_input_sha256": freeze["hashes"],
    })
    write_json(ROOT / E4_REL / "compatibility.json", {
        "status": "passed",
        "production_retrieval_imported": False,
        "production_app_modified": False,
        "rag_store_modified": False,
        "phase13_protected_artifacts_unchanged": True,
        "existing_venv_modified": False,
        "isolated_venv": ".venv-reranker",
    })
    write_json(ROOT / RUNTIME_REL / "reranker_runtime_ready.json", readiness)
    print(json.dumps({
        "status": "completed",
        "experiment_id": "E4_grounded_rrf_reranker_v1",
        "question_count": 169,
        "pairs_scored": 8450,
        "runtime_ready": True,
        "model_id": MODEL_ID,
        "revision": MODEL_REVISION,
        "device": device,
        "mini_batch": mini["status"],
        "truncation_rate": truncation["truncation_rate"],
        "latency": latency,
        "chunk_metrics": results["e4_overall"]["metrics"]["chunk"],
        "protected_artifacts": len(freeze["phase13_protected"]),
        "report_dir": str(E4_REL).replace("\\", "/"),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        failure = {
            "status": "blocked_runtime",
            "reranker_runtime_ready": False,
            "blocking_reason": f"{type(exc).__name__}: {exc}",
            "requested_model": MODEL_ID,
            "revision": MODEL_REVISION,
            "timestamp": utc_now(),
        }
        try:
            write_json(ROOT / RUNTIME_REL / "runtime_failure.json", failure)
        except Exception:
            pass
        print(json.dumps(failure, ensure_ascii=False), file=sys.stderr)
        raise
