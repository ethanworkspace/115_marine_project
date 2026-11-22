"""Run Phase 13 RRF on frozen, evaluation-only Phase 12 rankings."""

from __future__ import annotations

import json
import math
import sys
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
    EvaluationBM25,
    _error_candidate,
    _evidence_coverage,
    _group_reports,
    _required_evidence,
    _summarize_rows,
    get_git_commit,
    lexical_overlap_bucket,
    load_dense_index,
    read_jsonl,
    sha256_file,
    stable_sha256,
    utc_now,
    validate_frozen_inputs,
    validate_metric_recompute,
    write_json,
    write_jsonl,
)
from src.evaluation.retrieval.metrics import metric_bundle  # noqa: E402
from src.evaluation.retrieval.models import RetrievalResult  # noqa: E402
from src.evaluation.rrf import (  # noqa: E402
    CANDIDATE_DEPTH,
    FINAL_DEPTH,
    RRF_K,
    RRF_TIE_BREAK,
    RRF_WEIGHT,
    candidate_union_oracle,
    fuse_ranked_lists,
    fusion_diagnostics,
    paired_bootstrap_rrf,
    rank_movement,
    rescue_regression,
    summarize_oracle,
)
from src.evaluation.retrievers.bm25 import BM25_CONFIG  # noqa: E402


E1_REL = Path("reports/evaluation/experiments/E1_grounded_bm25_v1")
E2_REL = Path("reports/evaluation/experiments/E2_grounded_dense_v1")
E2_INDEX_REL = Path("data/evaluation/indexes/E2_grounded_bge_m3_v1")
E3_REL = Path("reports/evaluation/experiments/E3_grounded_rrf_v1")
COMPARE_REL = Path("reports/evaluation/experiments/E1_E2_E3_grounded_v1")


def protected_snapshot(root: Path) -> dict[str, dict[str, Any]]:
    """Hash immutable inputs and all prior experiment/index outputs, including stat data."""
    candidates = [
        root / "rag_store.sqlite3",
        root / "data/shadow/chunks_v2.jsonl",
        root / "data/shadow/chunks_v3.jsonl",
        root / "data/evaluation/corpus_v1.jsonl",
        root / "data/evaluation/corpus_v2.jsonl",
        root / "data/evaluation/silver/questions_v1.jsonl",
        root / "data/evaluation/silver/questions_v2.jsonl",
        root / "data/evaluation/silver/questions_v3.jsonl",
        root / "data/evaluation/grounded/questions_v1.jsonl",
        root / "data/evaluation/grounded/evidence_pool_v1.jsonl",
        root / "reports/evaluation/grounded/manifest_v1.json",
    ]
    for directory in (root / E1_REL, root / E2_REL, root / E2_INDEX_REL,
                      root / "reports/evaluation/experiments/E1_vs_E2_grounded_v1"):
        if directory.exists():
            candidates.extend(path for path in directory.rglob("*") if path.is_file())
    result: dict[str, dict[str, Any]] = {}
    for path in sorted(set(candidates)):
        relative = str(path.relative_to(root)).replace("\\", "/")
        if not path.is_file():
            result[relative] = {"status": "missing"}
            continue
        stat = path.stat()
        result[relative] = {"sha256": sha256_file(path), "size": stat.st_size, "mtime_ns": stat.st_mtime_ns}
    return result


def validate_phase12_record(root: Path, frozen: dict[str, Any], e1_manifest: dict[str, Any],
                            e2_manifest: dict[str, Any], e2_index_manifest: dict[str, Any]) -> dict[str, Any]:
    record_path = root / "reports/evaluation/experiments/E1_vs_E2_grounded_v1/phase12_execution.json"
    record = json.loads(record_path.read_text(encoding="utf-8"))
    phase_freeze = record["freeze"]
    expected_inputs = {
        "corpus_v2.jsonl": frozen["hashes"]["evaluation_corpus_v2"],
        "questions_v1.jsonl": frozen["hashes"]["grounded_questions_v1"],
        "evidence_pool_v1.jsonl": frozen["hashes"]["evidence_pool_v1"],
    }
    for key, expected in expected_inputs.items():
        actual = next((value for path, value in phase_freeze.get("protected_files_at_start", {}).items()
                       if path.endswith(key)), None)
        if actual is None or actual.get("sha256") != expected:
            raise RuntimeError(f"Phase 12 frozen input checksum mismatch for {key}: {actual}")
    if phase_freeze.get("corpus_chunk_ids_sha256") != frozen["corpus_chunk_ids_sha256"]:
        raise RuntimeError("Phase 12 retrieval corpus chunk-ID checksum mismatch")
    if phase_freeze.get("question_ids_sha256") != frozen["question_ids_sha256"]:
        raise RuntimeError("Phase 12 question-ID checksum mismatch")
    if phase_freeze.get("required_evidence_resolution_sha256") != frozen["evidence_resolution_sha256"]:
        raise RuntimeError("Phase 12 required-evidence resolution checksum mismatch")
    expected_e1 = record.get("E1", {}).get("manifest")
    expected_e2 = record.get("E2", {}).get("manifest")
    expected_dense_index = record.get("E2", {}).get("index_manifest")
    baseline_identity_fields = (
        "experiment_id", "status", "evaluation_corpus_v2_sha256", "grounded_questions_v1_sha256",
        "evidence_pool_v1_sha256", "required_evidence_resolution_sha256", "question_count",
        "question_ids_sha256", "retrieval_corpus_chunk_ids_sha256", "retrieval_chunk_count",
        "top_k", "top10_rankings_sha256", "retriever_type", "retriever_config",
    )
    for name, current, expected in (("E1", e1_manifest, expected_e1), ("E2", e2_manifest, expected_e2)):
        if expected is None:
            raise RuntimeError(f"Phase 12 execution record is missing its {name} experiment manifest")
        diffs = {key: {"phase12": expected.get(key), "current": current.get(key)}
                 for key in baseline_identity_fields if current.get(key) != expected.get(key)}
        if diffs:
            raise RuntimeError(f"Current {name} baseline identity/config differs from Phase 12: {diffs}")
    if e2_index_manifest != expected_dense_index:
        raise RuntimeError("Current E2 Dense index manifest differs from the saved Phase 12 execution record")
    return {
        "status": "passed",
        "phase12_execution_record": str(record_path.relative_to(root)).replace("\\", "/"),
        "corpus_sha256": frozen["hashes"]["evaluation_corpus_v2"],
        "questions_sha256": frozen["hashes"]["grounded_questions_v1"],
        "evidence_pool_sha256": frozen["hashes"]["evidence_pool_v1"],
        "E1_manifest_matches_phase12_record": True,
        "E2_manifest_matches_phase12_record": True,
        "E2_index_manifest_matches_phase12_record": True,
    }


def validate_stored_baseline(root: Path, *, name: str, directory: Path, retriever: Any,
                             frozen: dict[str, Any], expected_experiment_id: str) -> dict[str, Any]:
    manifest_path = directory / "experiment_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected_fields = {
        "experiment_id": expected_experiment_id,
        "status": "completed",
        "evaluation_corpus_v2_sha256": frozen["hashes"]["evaluation_corpus_v2"],
        "grounded_questions_v1_sha256": frozen["hashes"]["grounded_questions_v1"],
        "evidence_pool_v1_sha256": frozen["hashes"]["evidence_pool_v1"],
        "question_count": len(frozen["questions"]),
        "retrieval_chunk_count": len(frozen["corpus"]),
        "required_evidence_resolution_sha256": frozen["evidence_resolution_sha256"],
    }
    mismatches = {key: {"expected": value, "actual": manifest.get(key)}
                  for key, value in expected_fields.items() if manifest.get(key) != value}
    if mismatches:
        raise RuntimeError(f"{name} Phase 12 manifest/input mismatch: {mismatches}")
    traces = read_jsonl(directory / "ranking_traces.jsonl")
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for trace in traces:
        grouped[str(trace["question_id"])].append(trace)
    if len(traces) != len(frozen["questions"]) * 10 or set(grouped) != {str(q["question_id"]) for q in frozen["questions"]}:
        raise RuntimeError(f"{name} does not have exactly Top-10 traces for every frozen question")
    hash_parts: list[dict[str, Any]] = []
    mismatching_questions: list[str] = []
    for question in frozen["questions"]:
        qid = str(question["question_id"])
        saved = sorted(grouped[qid], key=lambda row: int(row["rank"]))
        if [int(row["rank"]) for row in saved] != list(range(1, 11)):
            raise RuntimeError(f"{name} ranking trace ranks are not contiguous for {qid}")
        hash_parts.append({"question_id": qid, "top10": [str(row["chunk_id"]) for row in saved]})
        fresh = retriever.rank_all(str(question["question"]))[:10]
        actual = [(hit.chunk_id, hit.document_id, hit.page, hit.page_end, hit.raw_score) for hit in fresh]
        expected = [(str(row["chunk_id"]), str(row["document_id"]), row.get("page"), row.get("page_end"), row.get("raw_score")) for row in saved]
        if actual != expected:
            mismatching_questions.append(qid)
    actual_rankings_hash = stable_sha256(hash_parts)
    if manifest.get("top10_rankings_sha256") != actual_rankings_hash:
        raise RuntimeError(f"{name} stored trace ranking checksum does not match its Phase 12 manifest")
    if mismatching_questions:
        raise RuntimeError(f"{name} Phase 12 Top-10 reproducibility failure for {mismatching_questions[:10]}")
    if name == "E1 BM25" and manifest.get("retriever_config", {}).get("bm25_configuration") != BM25_CONFIG:
        raise RuntimeError("E1 BM25 configuration differs from the fixed Phase 12 configuration")
    if name == "E2 Dense" and manifest.get("retriever_config", {}).get("embedding_dimension") != 1024:
        raise RuntimeError("E2 Dense model/index metadata does not match the frozen BGE-M3 1024-dimension run")
    return {
        "experiment_id": expected_experiment_id,
        "manifest_sha256": sha256_file(manifest_path),
        "trace_rows": len(traces),
        "top10_rankings_sha256": actual_rankings_hash,
        "reproduced_question_count": len(frozen["questions"]),
        "mismatch_count": 0,
        "status": "passed",
    }


def _trace_rows(question: dict[str, Any], fusion_rows: list[dict[str, Any]], evidence: dict[str, Any]) -> list[dict[str, Any]]:
    required_chunks = {item.chunk_id for item in evidence["chunk"].required}
    required_pages = {(item.document_id, page) for item in evidence["page"].required for page in range(item.page, (item.page_end or item.page) + 1)}
    required_documents = {item.document_id for item in evidence["document"].required}
    rows = []
    for item in fusion_rows[:FINAL_DEPTH]:
        hit = item["hit"]
        hit_pages = {(hit.document_id, page) for page in range(hit.page, (hit.page_end or hit.page) + 1)} if hit.page is not None else set()
        rows.append({
            "question_id": str(question["question_id"]),
            "question": question["question"],
            "species": question.get("species") or "unknown",
            "query_style": question.get("query_style"),
            "lexical_overlap": question.get("lexical_overlap"),
            "mapping_status": question.get("mapping_status", "exact_by_construction"),
            "rank": item["final_rank"],
            "chunk_id": item["chunk_id"],
            "document_id": item["document_id"],
            "page": item["page"],
            "page_end": item["page_end"],
            "score": item["rrf_score"],
            "raw_score": item["rrf_score"],
            "rrf_score": item["rrf_score"],
            "bm25_rank": item["bm25_rank"],
            "dense_rank": item["dense_rank"],
            "bm25_rrf_contribution": item["bm25_rrf_contribution"],
            "dense_rrf_contribution": item["dense_rrf_contribution"],
            "is_required_evidence": item["chunk_id"] in required_chunks,
            "chunk_match": item["chunk_id"] in required_chunks,
            "page_match": bool(hit_pages & required_pages),
            "document_match": item["document_id"] in required_documents,
        })
    return rows


def _write_e3_reports(directory: Path, manifest: dict[str, Any], rows: list[dict[str, Any]], traces: list[dict[str, Any]],
                      errors: list[dict[str, Any]], candidate_traces: list[dict[str, Any]]) -> None:
    directory.mkdir(parents=True, exist_ok=False)
    write_json(directory / "experiment_manifest.json", manifest)
    overall = _summarize_rows(rows)
    overall.update({"experiment_id": "E3_grounded_rrf_v1", "benchmark_type": "AI-generated corpus-grounded Silver; not human Gold"})
    write_json(directory / "overall.json", overall)
    write_json(directory / "by_query_style.json", _group_reports(rows, field="query_style"))
    overlap = {bucket: _summarize_rows([row for row in rows if lexical_overlap_bucket(float(row["question"].get("lexical_overlap") or 0.0)) == bucket])
               for bucket in ("low", "medium", "high")}
    write_json(directory / "by_overlap.json", {"boundaries": {"low": "<0.35", "medium": "0.35 through 0.55", "high": ">0.55"}, "groups": overlap})
    write_json(directory / "by_species.json", _group_reports(rows, field="species", expected_order=SPECIES_REPORT_ORDER))
    write_json(directory / "by_category.json", _group_reports(rows, field="category", expected_order=CATEGORY_REPORT_ORDER))
    write_json(directory / "by_difficulty.json", _group_reports(rows, field="difficulty"))
    write_jsonl(directory / "per_question.jsonl", rows)
    write_jsonl(directory / "ranking_traces.jsonl", traces)
    write_jsonl(directory / "fusion_traces.jsonl", traces)
    write_jsonl(directory / "candidate_traces.jsonl", candidate_traces)
    write_jsonl(directory / "errors.jsonl", errors)


def _group_comparison(rows_by_name: dict[str, list[dict[str, Any]]], field: str, *, overlap: bool = False) -> dict[str, Any]:
    if overlap:
        output: dict[str, Any] = {}
        for bucket in ("low", "medium", "high"):
            output[bucket] = {
                name: _summarize_rows([row for row in rows if lexical_overlap_bucket(float(row["question"].get("lexical_overlap") or 0.0)) == bucket])
                for name, rows in rows_by_name.items()
            }
        return {"boundaries": {"low": "<0.35", "medium": "0.35 through 0.55", "high": ">0.55"}, "groups": output}
    groups = {name: _group_reports(rows, field=field, expected_order=SPECIES_REPORT_ORDER if field == "species" else CATEGORY_REPORT_ORDER if field == "category" else None)
              for name, rows in rows_by_name.items()}
    labels = sorted(set().union(*(set(group) for group in groups.values())))
    return {label: {name: groups[name].get(label, {"question_count": 0, "metrics": {}}) for name in groups} for label in labels}


def _comparison_summary(overall: dict[str, dict[str, Any]]) -> dict[str, Any]:
    comparisons: dict[str, Any] = {}
    for granularity in GRANULARITIES:
        comparisons[granularity] = {}
        metrics = sorted(set().union(*(set(value.get("metrics", {}).get(granularity, {})) for value in overall.values())))
        for metric in metrics:
            vals = {name: value.get("metrics", {}).get(granularity, {}).get(metric) for name, value in overall.items()}
            comparisons[granularity][metric] = {"scores": vals, "E3_minus_E1": (vals.get("E3", 0) or 0) - (vals.get("E1", 0) or 0),
                                                "E3_minus_E2": (vals.get("E3", 0) or 0) - (vals.get("E2", 0) or 0)}
    return comparisons


def _rescue_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    output = {"question_count": len(rows), "by_k": {}}
    for k in (1, 5, 10):
        counts: Counter[str] = Counter()
        for row in rows:
            data = row["by_k"][str(k)]
            counts[data["comparison"]] += 1
            for flag in ("rescued_bm25_miss", "rescued_dense_miss", "introduced_regression_from_bm25", "introduced_regression_from_dense"):
                counts[flag] += bool(data[flag])
        output["by_k"][str(k)] = {key: counts.get(key, 0) for key in (
            "rrf_improves_over_both", "rrf_matches_best", "rrf_between_baselines", "rrf_worse_than_both",
            "rescued_bm25_miss", "rescued_dense_miss", "introduced_regression_from_bm25", "introduced_regression_from_dense")}
    return output


def main() -> int:
    frozen = validate_frozen_inputs(ROOT)
    e1_manifest_path = ROOT / E1_REL / "experiment_manifest.json"
    e2_manifest_path = ROOT / E2_REL / "experiment_manifest.json"
    e2_index_manifest_path = ROOT / E2_INDEX_REL / "index_manifest.json"
    # Existing Phase 12 reports and vector files are immutable; snapshot them before loading/ranking.
    protected_before = protected_snapshot(ROOT)
    e1_manifest = json.loads(e1_manifest_path.read_text(encoding="utf-8"))
    e2_manifest = json.loads(e2_manifest_path.read_text(encoding="utf-8"))
    e2_index_manifest = json.loads(e2_index_manifest_path.read_text(encoding="utf-8"))
    phase12_record_validation = validate_phase12_record(ROOT, frozen, e1_manifest, e2_manifest, e2_index_manifest)
    if e1_manifest.get("retriever_config", {}).get("bm25_configuration") != BM25_CONFIG:
        raise RuntimeError("Frozen E1 BM25 config does not match the fixed evaluation adapter")
    bm25 = EvaluationBM25(frozen["corpus"], corpus_sha256=frozen["hashes"]["evaluation_corpus_v2"],
                          git_commit=e1_manifest.get("git_commit"), created_at=e1_manifest.get("timestamp"))
    dense, dense_index_manifest = load_dense_index(ROOT, frozen)
    if dense_index_manifest.get("model", {}).get("model_name") != "bge-m3:latest":
        raise RuntimeError("Phase 13 uses the saved BGE-M3 index only; no alternate Dense model is allowed")
    e1_validation = validate_stored_baseline(ROOT, name="E1 BM25", directory=ROOT / E1_REL, retriever=bm25,
                                             frozen=frozen, expected_experiment_id="E1_grounded_bm25_v1")
    e2_validation = validate_stored_baseline(ROOT, name="E2 Dense", directory=ROOT / E2_REL, retriever=dense,
                                             frozen=frozen, expected_experiment_id="E2_grounded_dense_v1")
    if (ROOT / E3_REL).exists() or (ROOT / COMPARE_REL).exists():
        raise RuntimeError("Phase 13 output directory already exists; refusing to overwrite an earlier run")

    questions = frozen["questions"]
    corpus_by_id = {str(row["chunk_id"]): row for row in frozen["corpus"]}
    e1_per_question = read_jsonl(ROOT / E1_REL / "per_question.jsonl")
    e2_per_question = read_jsonl(ROOT / E2_REL / "per_question.jsonl")
    e1_by_id = {str(row["question_id"]): row for row in e1_per_question}
    e2_by_id = {str(row["question_id"]): row for row in e2_per_question}
    if set(e1_by_id) != set(e2_by_id) or set(e1_by_id) != {str(q["question_id"]) for q in questions}:
        raise RuntimeError("Phase 12 BM25/Dense reports do not cover the same frozen questions")

    rows: list[dict[str, Any]] = []
    traces: list[dict[str, Any]] = []
    candidate_traces: list[dict[str, Any]] = []
    candidate_hash_parts: dict[str, list[dict[str, Any]]] = {"BM25": [], "Dense": []}
    errors: list[dict[str, Any]] = []
    oracle_rows: list[dict[str, Any]] = []
    rescue_rows: list[dict[str, Any]] = []
    movement_rows: list[dict[str, Any]] = []
    diagnostic_rows: list[dict[str, Any]] = []
    deterministic_mismatches: list[str] = []
    for question in questions:
        qid = str(question["question_id"])
        bm25_full = bm25.rank_all(str(question["question"]))
        dense_full = dense.rank_all(str(question["question"]))
        if len(bm25_full) != len(frozen["corpus"]) or len(dense_full) != len(frozen["corpus"]):
            raise RuntimeError(f"Full-corpus ranking is incomplete for {qid}")
        bm_candidates = bm25_full[:CANDIDATE_DEPTH]
        dense_candidates = dense_full[:CANDIDATE_DEPTH]
        for label, candidates in (("BM25", bm_candidates), ("Dense", dense_candidates)):
            candidate_hash_parts[label].append({"question_id": qid, "top50": [hit.chunk_id for hit in candidates]})
            candidate_traces.extend({
                "question_id": qid,
                "question": question["question"],
                "retriever_type": label,
                "rank": hit.rank,
                "chunk_id": hit.chunk_id,
                "document_id": hit.document_id,
                "page": hit.page,
                "raw_score": hit.raw_score,
                "score": hit.raw_score,
            } for hit in candidates)
        fusion_all = fuse_ranked_lists(bm_candidates, dense_candidates, corpus_by_id, k=RRF_K,
                                        bm25_weight=RRF_WEIGHT, dense_weight=RRF_WEIGHT, top_n=len(set(h.chunk_id for h in bm_candidates) | set(h.chunk_id for h in dense_candidates)))
        fusion_repeat = fuse_ranked_lists(bm_candidates, dense_candidates, corpus_by_id, k=RRF_K,
                                          bm25_weight=RRF_WEIGHT, dense_weight=RRF_WEIGHT, top_n=len(fusion_all))
        if [(x["chunk_id"], x["rrf_score"]) for x in fusion_all] != [(x["chunk_id"], x["rrf_score"]) for x in fusion_repeat]:
            deterministic_mismatches.append(qid)
        if len(fusion_all) != len(set(h.chunk_id for h in bm_candidates) | set(h.chunk_id for h in dense_candidates)):
            raise RuntimeError(f"RRF did not preserve the Top-50 candidate union for {qid}")
        fusion_top10 = fusion_all[:FINAL_DEPTH]
        fused_hits = [item["hit"] for item in fusion_all]
        result = RetrievalResult(qid, tuple(fused_hits[:FINAL_DEPTH]))
        evidence = _required_evidence(question, corpus_by_id)
        metrics = {granularity: metric_bundle(result, evidence[granularity], granularity).scores for granularity in GRANULARITIES}
        qrow = {
            "question_id": qid,
            "question": question,
            "metrics": metrics,
            "required_evidence_coverage": _evidence_coverage(fused_hits, question),
            "retrieval_top10_chunk_ids": [item["chunk_id"] for item in fusion_top10],
        }
        rows.append(qrow)
        traces.extend(_trace_rows(question, fusion_top10, evidence))
        error = _error_candidate(question, [item["hit"] for item in fusion_top10], fused_hits)
        if error.get("error_category"):
            errors.append(error)
        oracle_rows.append(candidate_union_oracle(question, bm_candidates, dense_candidates, fusion_all))
        rescue_rows.append(rescue_regression(question, bm_candidates, dense_candidates, fusion_all))
        movement_rows.extend(rank_movement(question, bm_candidates, dense_candidates, fusion_all))
        diagnostic_rows.append(fusion_diagnostics(question, bm_candidates, dense_candidates, fusion_all))
    if deterministic_mismatches:
        raise RuntimeError(f"RRF ranking determinism failure: {deterministic_mismatches[:10]}")

    e1_rows = [e1_by_id[str(question["question_id"])] for question in questions]
    e2_rows = [e2_by_id[str(question["question_id"])] for question in questions]
    e3_ids = [row["question_id"] for row in rows]
    if e3_ids != [str(q["question_id"]) for q in questions]:
        raise RuntimeError("E3 question ordering differs from the frozen E1/E2 question set")
    if any(trace.get("rank") not in range(1, FINAL_DEPTH + 1) for trace in traces) or len(traces) != len(questions) * FINAL_DEPTH:
        raise RuntimeError("RRF ranking trace completeness check failed")

    timestamp = utc_now()
    git_commit = get_git_commit(ROOT)
    corpus_hash = frozen["hashes"]["evaluation_corpus_v2"]
    question_hash = frozen["hashes"]["grounded_questions_v1"]
    e1_manifest_sha = sha256_file(e1_manifest_path)
    e2_manifest_sha = sha256_file(e2_manifest_path)
    dense_index_sha = sha256_file(e2_index_manifest_path)
    rrf_manifest = {
        "experiment_id": "E3_grounded_rrf_v1",
        "status": "completed",
        "timestamp": timestamp,
        "git_commit": git_commit,
        "evaluation_corpus_v2_sha256": corpus_hash,
        "grounded_questions_v1_sha256": question_hash,
        "evidence_pool_v1_sha256": frozen["hashes"]["evidence_pool_v1"],
        "E1_manifest_sha256": e1_manifest_sha,
        "E2_manifest_sha256": e2_manifest_sha,
        "E2_dense_index_manifest_sha256": dense_index_sha,
        "required_evidence_resolution_sha256": frozen["evidence_resolution_sha256"],
        "retrieval_chunk_count": len(frozen["corpus"]),
        "document_count": frozen["corpus_profile"]["document_count"],
        "page_count": frozen["corpus_profile"]["page_count"],
        "question_count": len(questions),
        "question_ids_sha256": frozen["question_ids_sha256"],
        "retrieval_corpus_chunk_ids_sha256": frozen["corpus_chunk_ids_sha256"],
        "candidate_depth": {"BM25": CANDIDATE_DEPTH, "Dense": CANDIDATE_DEPTH},
        "candidate_trace_count": len(candidate_traces),
        "candidate_trace_count_per_retriever": {"BM25": len(questions) * CANDIDATE_DEPTH, "Dense": len(questions) * CANDIDATE_DEPTH},
        "candidate_top50_rankings_sha256": {name: stable_sha256(parts) for name, parts in candidate_hash_parts.items()},
        "final_top_k": FINAL_DEPTH,
        "evaluation_cutoffs": list(TOP_K),
        "fusion": {
            "method": "Reciprocal Rank Fusion",
            "formula": "sum_r weight_r / (rrf_k + rank_r)",
            "bm25_weight": RRF_WEIGHT,
            "dense_weight": RRF_WEIGHT,
            "rrf_k": RRF_K,
            "rank_origin": 1,
            "uses_raw_bm25_score": False,
            "uses_dense_cosine_score": False,
            "tie_break": list(RRF_TIE_BREAK),
        },
        "BM25_config": BM25_CONFIG,
        "Dense_model": dense_index_manifest.get("model"),
        "retriever_inputs": {"BM25": "E1_grounded_bm25_v1 fixed adapter", "Dense": "E2 persisted BGE-M3 float32 vectors and query vectors; no re-embedding"},
        "metric_implementation": "src.evaluation.retrieval.metrics.metric_bundle",
        "metric_semantics": "same as E1/E2 Phase 12; top-K retrieved chunks, unique evidence units for recall, one binary gain per retrieved chunk for precision/nDCG",
        "granularities": list(GRANULARITIES),
        "required_evidence_definition": "Grounded Silver required chunks/pages/documents; AI-generated Silver, not human Gold",
        "gold_evidence_used_for_ranking": False,
        "metadata_filter_used": False,
        "query_rewrite_used": False,
        "deterministic_tie_break_validation": "passed",
        "baseline_top10_reproducibility": {"E1": e1_validation, "E2": e2_validation},
        "phase12_record_validation": phase12_record_validation,
        "ranking_determinism_validation": {"status": "passed", "questions_checked": len(questions), "mismatches": 0},
        "bootstrap": {"method": "paired question-level percentile", "iterations": BOOTSTRAP_ITERATIONS, "seed": BOOTSTRAP_SEED},
        "benchmark_type": "AI-generated corpus-grounded Silver; not human Gold",
    }

    e3_dir = ROOT / E3_REL
    compare_dir = ROOT / COMPARE_REL
    _write_e3_reports(e3_dir, rrf_manifest, rows, traces, errors, candidate_traces)
    rrf_manifest["candidate_traces_sha256"] = sha256_file(e3_dir / "candidate_traces.jsonl")
    rrf_manifest["ranking_traces_sha256"] = sha256_file(e3_dir / "ranking_traces.jsonl")
    rrf_manifest["fusion_traces_sha256"] = sha256_file(e3_dir / "fusion_traces.jsonl")
    write_json(e3_dir / "experiment_manifest.json", rrf_manifest)
    compare_dir.mkdir(parents=True, exist_ok=False)

    e1_overall = _summarize_rows(e1_rows)
    e2_overall = _summarize_rows(e2_rows)
    e3_overall = _summarize_rows(rows)
    rows_by_name = {"E1_BM25": e1_rows, "E2_BGE_M3_Dense": e2_rows, "E3_RRF": rows}
    comparison = {
        "experiment_ids": ["E1_grounded_bm25_v1", "E2_grounded_dense_v1", "E3_grounded_rrf_v1"],
        "benchmark_type": "AI-generated corpus-grounded Silver; not human Gold",
        "question_count": len(questions),
        "same_question_ids": True,
        "same_retrieval_corpus_chunk_ids": True,
        "same_required_evidence": True,
        "same_metric_implementation": True,
        "same_evaluation_cutoffs": True,
        "overall": {"E1_BM25": e1_overall, "E2_BGE_M3_Dense": e2_overall, "E3_RRF": e3_overall},
        "point_estimate_differences": _comparison_summary({"E1": e1_overall, "E2": e2_overall, "E3": e3_overall}),
        "by_query_style": _group_comparison(rows_by_name, "query_style"),
        "by_overlap": _group_comparison(rows_by_name, "lexical_overlap", overlap=True),
        "by_species": _group_comparison(rows_by_name, "species"),
        "by_category": _group_comparison(rows_by_name, "category"),
        "by_difficulty": _group_comparison(rows_by_name, "difficulty"),
        "interpretation": "All scores are descriptive on the same AI-generated Silver sample. Point estimates alone do not establish superiority.",
    }
    write_json(compare_dir / "comparison.json", comparison)
    oracle_summary = summarize_oracle(oracle_rows)
    write_json(compare_dir / "candidate_union_oracle.json", {**oracle_summary, "per_question": oracle_rows})
    write_json(compare_dir / "rescue_regression.json", {**_rescue_summary(rescue_rows), "per_question": rescue_rows})
    write_json(compare_dir / "rank_movement.json", {
        "definition": "Required Silver evidence ranks from E1/E2 Top 50 and E3 fused candidate union (up to rank 100); null indicates not present in that pool.",
        "candidate_depth": CANDIDATE_DEPTH,
        "final_evaluation_top_k": FINAL_DEPTH,
        "records": movement_rows,
    })
    bootstrap = paired_bootstrap_rrf(e1_rows, e2_rows, rows)
    write_json(compare_dir / "bootstrap_ci.json", bootstrap)
    error_counts = Counter(row["error_category"] for row in errors)
    diagnostics_counts: Counter[str] = Counter()
    for row in diagnostic_rows:
        for name in ("good_candidate_bad_fusion", "single_retriever_rescue", "both_retrievers_low_rank", "fusion_rank_dilution"):
            diagnostics_counts[name] += bool(row[name])
    write_json(compare_dir / "error_analysis.json", {
        "taxonomy": list(ERROR_TAXONOMY),
        "E3_error_taxonomy_counts": {name: error_counts.get(name, 0) for name in ERROR_TAXONOMY},
        "fusion_diagnostic_counts": dict(sorted(diagnostics_counts.items())),
        "per_question_errors": errors,
        "per_question_fusion_diagnostics": diagnostic_rows,
        "interpretation": "Automatic labels are trace-derived candidates; unclear cases remain unknown and require review before causal claims.",
    })
    write_jsonl(compare_dir / "paired_rank_analysis.jsonl", movement_rows)
    write_jsonl(compare_dir / "rescue_regression_by_question.jsonl", rescue_rows)
    write_jsonl(compare_dir / "fusion_diagnostics.jsonl", diagnostic_rows)
    # Preserve the already computed Phase 12 leakage audit; never regenerate or filter questions here.
    prior_leakage = ROOT / "reports/evaluation/experiments/E1_vs_E2_grounded_v1/leakage_audit.json"
    leakage_output = {"status": "prior_phase12_audit_unavailable", "note": "No Phase 12 leakage audit file was present."}
    if prior_leakage.exists():
        leakage_output = json.loads(prior_leakage.read_text(encoding="utf-8"))
        leakage_output["reused_from"] = str(prior_leakage.relative_to(ROOT)).replace("\\", "/")
        leakage_output["question_set_sha256"] = question_hash
    write_json(compare_dir / "leakage_audit.json", leakage_output)

    val_checks = {
        "E1_E2_top10_reproduced": e1_validation["mismatch_count"] == e2_validation["mismatch_count"] == 0,
        "all_169_questions_have_top10_trace": len(traces) == len(questions) * FINAL_DEPTH,
        "all_169_questions_have_both_top50_candidate_traces": len(candidate_traces) == len(questions) * CANDIDATE_DEPTH * 2,
        "all_candidate_ids_in_frozen_corpus": all(trace["chunk_id"] in corpus_by_id for trace in traces),
        "all_questions_resolved": len(rows) == len(questions),
        "deterministic_rrf_repeat": not deterministic_mismatches,
        "same_questions": set(e1_by_id) == set(e2_by_id) == set(e3_ids),
        "same_retrieval_corpus": e1_manifest.get("retrieval_corpus_chunk_ids_sha256") == e2_manifest.get("retrieval_corpus_chunk_ids_sha256") == frozen["corpus_chunk_ids_sha256"],
        "same_required_evidence": e1_manifest.get("required_evidence_resolution_sha256") == e2_manifest.get("required_evidence_resolution_sha256") == frozen["evidence_resolution_sha256"],
        "no_evidence_in_ranking_inputs": rrf_manifest["gold_evidence_used_for_ranking"] is False,
    }
    if not all(val_checks.values()):
        raise RuntimeError(f"Phase 13 fairness validation failed: {val_checks}")
    metric_recompute = validate_metric_recompute(e3_dir, questions, frozen["corpus"])
    if metric_recompute.get("status") != "passed":
        raise RuntimeError(f"Phase 13 metric recompute validation failed: {metric_recompute}")
    write_json(e3_dir / "ranking_validation.json", {
        "status": "passed", "checks": val_checks,
        "baseline_top10_reproducibility": {"E1": e1_validation, "E2": e2_validation},
        "trace_rows_expected": len(questions) * FINAL_DEPTH, "trace_rows_actual": len(traces),
        "candidate_trace_rows_expected": len(questions) * CANDIDATE_DEPTH * 2,
        "candidate_trace_rows_actual": len(candidate_traces),
        "candidate_pool_per_question": {"bm25": CANDIDATE_DEPTH, "dense": CANDIDATE_DEPTH, "fusion_union": "up to 100"},
        "metric_implementation": "src.evaluation.retrieval.metrics.metric_bundle",
        "top_k_cutoffs": list(TOP_K),
        "metric_recompute": metric_recompute,
    })

    # Re-check hashes, file sizes, and mtimes for every previously frozen artifact.
    protected_after = protected_snapshot(ROOT)
    changed = {key: {"before": protected_before.get(key), "after": protected_after.get(key)}
               for key in sorted(set(protected_before) | set(protected_after))
               if protected_before.get(key) != protected_after.get(key)}
    compatibility = {
        "status": "passed" if not changed else "failed",
        "protected_artifact_count": len(protected_before),
        "changed_artifacts": changed,
        "protected_sha256_after": {path: data["sha256"] for path, data in protected_after.items() if "sha256" in data},
        "production_retrieval_imported": False,
        "rag_store_modified": False,
    }
    write_json(compare_dir / "protected_artifacts_validation.json", compatibility)
    if changed:
        raise RuntimeError(f"Protected Phase 12/production artifacts changed: {changed}")

    styles = comparison["by_query_style"]
    overlap = comparison["by_overlap"]["groups"]
    summary_lines = [
        "# E1 / E2 / E3 Grounded Silver Comparison",
        "",
        "This is an AI-generated Silver benchmark report, not human Gold accuracy.",
        "All three systems use the same 169 questions, 2,224 retrieval chunks, required evidence, and metric implementation.",
        "",
        "## Overall chunk retrieval",
        "",
        "| Metric | E1 BM25 | E2 BGE-M3 | E3 RRF |",
        "|---|---:|---:|---:|",
    ]
    for metric in ("recall@1", "recall@5", "recall@10", "mrr", "ndcg@10"):
        values = [comparison["overall"][name]["metrics"]["chunk"].get(metric, 0.0) for name in ("E1_BM25", "E2_BGE_M3_Dense", "E3_RRF")]
        summary_lines.append(f"| {metric} | {values[0]:.4f} | {values[1]:.4f} | {values[2]:.4f} |")
    summary_lines += ["", "## Query style (chunk Recall@5)", "", "| Style | E1 BM25 | E2 BGE-M3 | E3 RRF |", "|---|---:|---:|---:|"]
    for style in sorted(styles):
        vals = [styles[style][name]["metrics"].get("chunk", {}).get("recall@5", 0.0) for name in ("E1_BM25", "E2_BGE_M3_Dense", "E3_RRF")]
        summary_lines.append(f"| {style} | {vals[0]:.4f} | {vals[1]:.4f} | {vals[2]:.4f} |")
    summary_lines += ["", "## Lexical overlap (chunk Recall@5)", "", "| Bucket | E1 BM25 | E2 BGE-M3 | E3 RRF |", "|---|---:|---:|---:|"]
    for bucket in ("low", "medium", "high"):
        vals = [overlap[bucket][name]["metrics"].get("chunk", {}).get("recall@5", 0.0) for name in ("E1_BM25", "E2_BGE_M3_Dense", "E3_RRF")]
        summary_lines.append(f"| {bucket} | {vals[0]:.4f} | {vals[1]:.4f} | {vals[2]:.4f} |")
    summary_lines += [
        "",
        "## Interpretation",
        "",
        "Use the paired bootstrap intervals in `bootstrap_ci.json`. An interval containing zero means the difference is not clearly separated on this Silver benchmark sample.",
        f"The candidate-union oracle is an evidence-availability upper bound, not a deployable ranking. Top-10 ranking traces: {len(traces)}.",
    ]
    for granularity in GRANULARITIES:
        for metric in ("recall@5", "recall@10", "mrr", "ndcg@10"):
            for baseline_key, label in (("E3_minus_E1_paired", "E3 - E1"), ("E3_minus_E2_paired", "E3 - E2")):
                interval = bootstrap["metrics"][granularity][metric][baseline_key]
                if interval["lower_95"] <= 0.0 <= interval["upper_95"]:
                    interpretation = "difference not clearly separated on this Silver benchmark sample"
                else:
                    interpretation = "paired interval excludes zero on this Silver benchmark sample"
                summary_lines.append(f"- {granularity} {metric}, {label}: {interpretation} (95% CI {interval['lower_95']:.4f} to {interval['upper_95']:.4f}).")
    (compare_dir / "comparison_summary.md").write_text("\n".join(summary_lines) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({
        "status": "completed",
        "questions": len(questions),
        "retrieval_chunks": len(frozen["corpus"]),
        "E1_manifest_sha256": e1_manifest_sha,
        "E2_manifest_sha256": e2_manifest_sha,
        "E2_index_manifest_sha256": dense_index_sha,
        "baseline_reproducibility": {"E1": e1_validation, "E2": e2_validation},
        "overall_chunk_metrics": comparison["overall"]["E3_RRF"]["metrics"]["chunk"],
        "oracle_hit_at_10": oracle_summary["by_k"]["10"]["candidate_union_oracle_hit"],
        "protected_artifact_count": len(protected_before),
        "protected_status": compatibility["status"],
        "report_dir": str(E3_REL).replace("\\", "/"),
        "comparison_dir": str(COMPARE_REL).replace("\\", "/"),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({"status": "failed", "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False), file=sys.stderr)
        raise
