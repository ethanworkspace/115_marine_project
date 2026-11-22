"""Evaluation-only Reciprocal Rank Fusion helpers for Phase 13."""

from __future__ import annotations

import math
import random
from collections import Counter
from typing import Any

from .grounded_baselines import BOOTSTRAP_ITERATIONS, BOOTSTRAP_METRICS, BOOTSTRAP_SEED, GRANULARITIES, TOP_K
from .retrieval.models import RankedHit


RRF_K = 60
RRF_WEIGHT = 1.0
CANDIDATE_DEPTH = 50
FINAL_DEPTH = 10
RRF_TIE_BREAK = (
    "rrf_score_descending",
    "best_individual_rank_ascending",
    "bm25_rank_ascending_nulls_last",
    "dense_rank_ascending_nulls_last",
    "chunk_id_ascending",
)


def _rank_map(hits: list[RankedHit], label: str) -> dict[str, RankedHit]:
    ranks: dict[str, RankedHit] = {}
    for expected_rank, hit in enumerate(hits, start=1):
        if hit.rank != expected_rank:
            raise ValueError(f"{label} candidate ranks must be contiguous from 1; expected {expected_rank}, got {hit.rank}")
        if hit.chunk_id in ranks:
            raise ValueError(f"Duplicate {label} chunk_id in candidate list: {hit.chunk_id}")
        ranks[hit.chunk_id] = hit
    return ranks


def fuse_ranked_lists(
    bm25_hits: list[RankedHit],
    dense_hits: list[RankedHit],
    corpus_by_id: dict[str, dict[str, Any]],
    *,
    k: int = RRF_K,
    bm25_weight: float = RRF_WEIGHT,
    dense_weight: float = RRF_WEIGHT,
    top_n: int = FINAL_DEPTH,
) -> list[dict[str, Any]]:
    """Fuse ranked candidates using ranks only; raw retriever scores are ignored."""
    if k <= 0 or top_n <= 0:
        raise ValueError("RRF k and top_n must be positive")
    if bm25_weight != 1.0 or dense_weight != 1.0:
        raise ValueError("Phase 13 fixes both RRF weights at 1.0")
    bm25 = _rank_map(bm25_hits, "BM25")
    dense = _rank_map(dense_hits, "Dense")
    candidates = set(bm25) | set(dense)
    fused: list[dict[str, Any]] = []
    for chunk_id in candidates:
        bm_hit, dense_hit = bm25.get(chunk_id), dense.get(chunk_id)
        bm_rank = bm_hit.rank if bm_hit else None
        dense_rank = dense_hit.rank if dense_hit else None
        bm_contribution = bm25_weight / (k + bm_rank) if bm_rank is not None else 0.0
        dense_contribution = dense_weight / (k + dense_rank) if dense_rank is not None else 0.0
        score = bm_contribution + dense_contribution
        best_rank = min(rank for rank in (bm_rank, dense_rank) if rank is not None)
        row = corpus_by_id.get(chunk_id)
        if row is None:
            raise ValueError(f"Candidate chunk is absent from frozen corpus: {chunk_id}")
        pages = row.get("pages") or []
        page_start = row.get("page_start")
        if page_start is None and pages:
            page_start = min(int(page) for page in pages)
        if page_start is None:
            page_start = row.get("page")
        page_end = row.get("page_end")
        if page_end is None and pages:
            page_end = max(int(page) for page in pages)
        if page_end is None:
            page_end = page_start
        hit = RankedHit(
            rank=0,
            chunk_id=chunk_id,
            document_id=str(row.get("document_id") or ""),
            page=int(page_start) if page_start is not None else None,
            page_end=int(page_end) if page_end is not None else None,
            raw_score=score,
            normalized_score=score,
        )
        fused.append({
            "hit": hit,
            "chunk_id": chunk_id,
            "document_id": hit.document_id,
            "page": hit.page,
            "page_end": hit.page_end,
            "bm25_rank": bm_rank,
            "dense_rank": dense_rank,
            "bm25_rrf_contribution": bm_contribution,
            "dense_rrf_contribution": dense_contribution,
            "rrf_score": score,
            "best_individual_rank": best_rank,
        })
    fused.sort(key=lambda item: (
        -item["rrf_score"],
        item["best_individual_rank"],
        item["bm25_rank"] if item["bm25_rank"] is not None else math.inf,
        item["dense_rank"] if item["dense_rank"] is not None else math.inf,
        item["chunk_id"],
    ))
    output = []
    for final_rank, item in enumerate(fused[:top_n], start=1):
        old_hit = item["hit"]
        item["final_rank"] = final_rank
        item["hit"] = RankedHit(
            rank=final_rank,
            chunk_id=old_hit.chunk_id,
            document_id=old_hit.document_id,
            page=old_hit.page,
            page_end=old_hit.page_end,
            raw_score=old_hit.raw_score,
            normalized_score=old_hit.normalized_score,
        )
        output.append(item)
    return output


def candidate_union_oracle(
    question: dict[str, Any],
    bm25_hits: list[RankedHit],
    dense_hits: list[RankedHit],
    rrf_hits: list[dict[str, Any]],
) -> dict[str, Any]:
    """Post-hoc candidate-coverage upper bound, never a ranked retriever result."""
    required = set(map(str, question.get("required_chunks") or []))
    bm_ids = {hit.chunk_id for hit in bm25_hits}
    dense_ids = {hit.chunk_id for hit in dense_hits}
    rrf_ids = {item["chunk_id"] for item in rrf_hits}
    result: dict[str, Any] = {"question_id": str(question["question_id"])}
    for k in (1, 5, 10):
        bm_top = {hit.chunk_id for hit in bm25_hits[:k]}
        dense_top = {hit.chunk_id for hit in dense_hits[:k]}
        rrf_top = {item["chunk_id"] for item in rrf_hits[:k]}
        union = bm_top | dense_top
        union_required = required & union
        rrf_required = required & rrf_top
        result[str(k)] = {
            "candidate_union_oracle_hit": bool(union_required),
            "candidate_union_oracle_all_required": bool(required) and required.issubset(union),
            "candidate_union_required_chunks_hit": sorted(union_required),
            "rrf_required_hit": bool(rrf_required),
            "rrf_all_required": bool(required) and required.issubset(rrf_top),
            "oracle_to_rrf_hit_gap": bool(union_required) and not bool(rrf_required),
            "oracle_to_rrf_all_required_gap": bool(required) and required.issubset(union) and not required.issubset(rrf_top),
            "bm25_hit": bool(required & bm_top),
            "dense_hit": bool(required & dense_top),
        }
    result["required_chunks_in_bm25_top50"] = sorted(required & bm_ids)
    result["required_chunks_in_dense_top50"] = sorted(required & dense_ids)
    result["required_chunks_in_candidate_union"] = sorted(required & (bm_ids | dense_ids))
    result["oracle_definition"] = "Set union of BM25 and Dense Top-K evidence hits; no deployable ranking is implied."
    return result


def rescue_regression(question: dict[str, Any], bm25_hits: list[RankedHit], dense_hits: list[RankedHit],
                      rrf_hits: list[dict[str, Any]]) -> dict[str, Any]:
    required = set(map(str, question.get("required_chunks") or []))
    result: dict[str, Any] = {"question_id": str(question["question_id"]), "by_k": {}}
    tags: Counter[str] = Counter()
    for k in (1, 5, 10):
        bm_ranks = [hit.rank for hit in bm25_hits[:k] if hit.chunk_id in required]
        dense_ranks = [hit.rank for hit in dense_hits[:k] if hit.chunk_id in required]
        rrf_ranks = [item["final_rank"] for item in rrf_hits[:k] if item["chunk_id"] in required]
        bm_rank = min(bm_ranks) if bm_ranks else None
        dense_rank = min(dense_ranks) if dense_ranks else None
        rrf_rank = min(rrf_ranks) if rrf_ranks else None
        bm_hit, dense_hit, rrf_hit = bm_rank is not None, dense_rank is not None, rrf_rank is not None
        baseline_ranks = [rank for rank in (bm_rank, dense_rank) if rank is not None]
        if rrf_rank is None:
            comparison = "rrf_worse_than_both" if baseline_ranks else "rrf_matches_best"
        elif not baseline_ranks:
            comparison = "rrf_improves_over_both"
        else:
            best_baseline = min(baseline_ranks)
            worst_baseline = max(baseline_ranks)
            if rrf_rank < best_baseline:
                comparison = "rrf_improves_over_both"
            elif rrf_rank == best_baseline:
                comparison = "rrf_matches_best"
            elif rrf_rank < worst_baseline:
                comparison = "rrf_between_baselines"
            else:
                comparison = "rrf_worse_than_both"
        flags = {
            "rescued_bm25_miss": not bm_hit and rrf_hit,
            "rescued_dense_miss": not dense_hit and rrf_hit,
            "introduced_regression_from_bm25": bm_hit and not rrf_hit,
            "introduced_regression_from_dense": dense_hit and not rrf_hit,
        }
        for name, value in flags.items():
            tags[name] += bool(value)
        result["by_k"][str(k)] = {
            "bm25_required_hit": bm_hit,
            "dense_required_hit": dense_hit,
            "rrf_required_hit": rrf_hit,
            "bm25_required_rank_within_k": bm_rank,
            "dense_required_rank_within_k": dense_rank,
            "rrf_required_rank_within_k": rrf_rank,
            "comparison": comparison,
            **flags,
        }
    result["comparison_basis"] = "First required-evidence rank within each K; missing ranks remain null, and categories compare only observed ranks/hit states."
    result["tags"] = dict(tags)
    return result


def rank_movement(question: dict[str, Any], bm25_hits: list[RankedHit], dense_hits: list[RankedHit],
                  rrf_hits: list[dict[str, Any]], *, candidate_depth: int = CANDIDATE_DEPTH) -> list[dict[str, Any]]:
    required = sorted(set(map(str, question.get("required_chunks") or [])))
    bm_ranks = {hit.chunk_id: hit.rank for hit in bm25_hits[:candidate_depth]}
    dense_ranks = {hit.chunk_id: hit.rank for hit in dense_hits[:candidate_depth]}
    rrf_ranks = {item["chunk_id"]: item["final_rank"] for item in rrf_hits}
    rows = []
    for chunk_id in required:
        bm_rank, dense_rank, fused_rank = bm_ranks.get(chunk_id), dense_ranks.get(chunk_id), rrf_ranks.get(chunk_id)
        baseline_values = [rank for rank in (bm_rank, dense_rank) if rank is not None]
        best_rank = min(baseline_values) if baseline_values else None
        rows.append({
            "question_id": str(question["question_id"]),
            "required_chunk_id": chunk_id,
            "bm25_rank_top50": bm_rank,
            "dense_rank_top50": dense_rank,
            "rrf_rank": fused_rank,
            "best_baseline_rank_top50": best_rank,
            "rank_delta_vs_best": fused_rank - best_rank if fused_rank is not None and best_rank is not None else None,
            "bm25_status": "retrieved_in_top50" if bm_rank is not None else "not_retrieved_in_top50",
            "dense_status": "retrieved_in_top50" if dense_rank is not None else "not_retrieved_in_top50",
            "rrf_status": "retrieved_in_top10" if fused_rank is not None and fused_rank <= FINAL_DEPTH else "not_retrieved_in_top10",
            "candidate_depth": candidate_depth,
        })
    return rows


def fusion_diagnostics(question: dict[str, Any], bm25_hits: list[RankedHit], dense_hits: list[RankedHit],
                       rrf_hits: list[dict[str, Any]], *, candidate_depth: int = CANDIDATE_DEPTH) -> dict[str, Any]:
    required = set(map(str, question.get("required_chunks") or []))
    bm_rank = {hit.chunk_id: hit.rank for hit in bm25_hits[:candidate_depth]}
    dense_rank = {hit.chunk_id: hit.rank for hit in dense_hits[:candidate_depth]}
    rrf_rank = {item["chunk_id"]: item["final_rank"] for item in rrf_hits}
    in_union = {chunk for chunk in required if chunk in bm_rank or chunk in dense_rank}
    in_both = {chunk for chunk in required if chunk in bm_rank and chunk in dense_rank}
    rrf_top = {chunk for chunk, rank in rrf_rank.items() if rank <= FINAL_DEPTH}
    required_top_hit = required & rrf_top
    single_retriever_rescue = {
        chunk for chunk in required
        if (chunk in bm_rank) != (chunk in dense_rank) and chunk in rrf_top
    }
    both_low = {chunk for chunk in required if chunk not in bm_rank and chunk not in dense_rank}
    dilution = {
        chunk for chunk in in_both
        if chunk not in rrf_rank or rrf_rank[chunk] > min(bm_rank[chunk], dense_rank[chunk])
    }
    return {
        "question_id": str(question["question_id"]),
        "good_candidate_bad_fusion": bool((required & in_union) - required_top_hit),
        "good_candidate_bad_fusion_chunks": sorted((required & in_union) - required_top_hit),
        "single_retriever_rescue": bool(single_retriever_rescue),
        "single_retriever_rescue_chunks": sorted(single_retriever_rescue),
        "both_retrievers_low_rank": bool(both_low),
        "both_retrievers_low_rank_chunks": sorted(both_low),
        "fusion_rank_dilution": bool(dilution),
        "fusion_rank_dilution_chunks": sorted(dilution),
        "required_chunks_in_any_candidate_pool": sorted(in_union),
        "required_chunks_in_both_candidate_pools": sorted(in_both),
        "required_chunks_in_rrf_top10": sorted(required_top_hit),
    }


def paired_bootstrap_rrf(e1_rows: list[dict[str, Any]], e2_rows: list[dict[str, Any]],
                         e3_rows: list[dict[str, Any]], *, seed: int = BOOTSTRAP_SEED,
                         iterations: int = BOOTSTRAP_ITERATIONS) -> dict[str, Any]:
    id_lists = [[str(row["question_id"]) for row in rows] for rows in (e1_rows, e2_rows, e3_rows)]
    if not id_lists[0] or id_lists[0] != id_lists[1] or id_lists[0] != id_lists[2]:
        raise ValueError("Paired bootstrap requires identical nonempty ordered question IDs")
    n = len(e1_rows)
    metrics: dict[str, Any] = {}
    for granularity in GRANULARITIES:
        metrics[granularity] = {}
        for metric in BOOTSTRAP_METRICS:
            vectors = {
                "E1": [float(row["metrics"][granularity][metric]) for row in e1_rows],
                "E2": [float(row["metrics"][granularity][metric]) for row in e2_rows],
                "E3": [float(row["metrics"][granularity][metric]) for row in e3_rows],
            }
            rng = random.Random(seed)
            samples: dict[str, list[float]] = {name: [] for name in ("E1", "E2", "E3", "E3_minus_E1", "E3_minus_E2")}
            for _ in range(iterations):
                indices = [rng.randrange(n) for _ in range(n)]
                means = {name: sum(values[index] for index in indices) / n for name, values in vectors.items()}
                samples["E1"].append(means["E1"])
                samples["E2"].append(means["E2"])
                samples["E3"].append(means["E3"])
                samples["E3_minus_E1"].append(means["E3"] - means["E1"])
                samples["E3_minus_E2"].append(means["E3"] - means["E2"])
            def interval(series: list[float]) -> dict[str, float]:
                ordered = sorted(series)
                return {
                    "lower_95": ordered[int(0.025 * (iterations - 1))],
                    "upper_95": ordered[int(0.975 * (iterations - 1))],
                }
            metrics[granularity][metric] = {
                "E1": interval(samples["E1"]),
                "E2": interval(samples["E2"]),
                "E3": interval(samples["E3"]),
                "E3_minus_E1_paired": interval(samples["E3_minus_E1"]),
                "E3_minus_E2_paired": interval(samples["E3_minus_E2"]),
                "E3_minus_E1_point_estimate": sum(vectors["E3"]) / n - sum(vectors["E1"]) / n,
                "E3_minus_E2_point_estimate": sum(vectors["E3"]) / n - sum(vectors["E2"]) / n,
            }
    return {
        "method": "question-level paired percentile bootstrap with shared resampled question positions across E1/E2/E3",
        "confidence_level": 0.95,
        "random_seed": seed,
        "iterations": iterations,
        "sample_unit": "question_id",
        "interpretation_limit": "Intervals describe uncertainty on this AI-generated Silver benchmark sample only; they do not establish performance over all aquaculture questions.",
        "metrics": metrics,
    }


def summarize_oracle(rows: list[dict[str, Any]]) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "type": "candidate_union_oracle",
        "interpretation": "Set-union availability of evidence in BM25/Dense Top-K; this is not a deployable ranking. Because RRF can promote candidates from deeper within either Top-50 pool, the Top-K union is not a strict upper bound on RRF Top-K hits.",
        "question_count": len(rows),
        "by_k": {},
    }
    for k in (1, 5, 10):
        result = {}
        for field in ("candidate_union_oracle_hit", "candidate_union_oracle_all_required", "rrf_required_hit", "rrf_all_required", "oracle_to_rrf_hit_gap", "oracle_to_rrf_all_required_gap"):
            count = sum(bool(row[str(k)][field]) for row in rows)
            result[field] = {"count": count, "rate": count / len(rows) if rows else None}
        oracle_hits = sum(bool(row[str(k)]["candidate_union_oracle_hit"]) for row in rows)
        rrf_hits = sum(bool(row[str(k)]["rrf_required_hit"]) for row in rows)
        oracle_all = sum(bool(row[str(k)]["candidate_union_oracle_all_required"]) for row in rows)
        rrf_all = sum(bool(row[str(k)]["rrf_all_required"]) for row in rows)
        result["hit_comparison"] = {
            "oracle_hit_count": oracle_hits,
            "rrf_hit_count": rrf_hits,
            "oracle_minus_rrf_net_gap_count": oracle_hits - rrf_hits,
            "oracle_but_not_rrf_count": sum(bool(row[str(k)]["candidate_union_oracle_hit"]) and not bool(row[str(k)]["rrf_required_hit"]) for row in rows),
            "rrf_hit_outside_either_retriever_top_k_count": sum(not bool(row[str(k)]["candidate_union_oracle_hit"]) and bool(row[str(k)]["rrf_required_hit"]) for row in rows),
            "all_required_oracle_count": oracle_all,
            "all_required_rrf_count": rrf_all,
            "all_required_oracle_minus_rrf_net_gap_count": oracle_all - rrf_all,
            "all_required_oracle_but_not_rrf_count": sum(bool(row[str(k)]["candidate_union_oracle_all_required"]) and not bool(row[str(k)]["rrf_all_required"]) for row in rows),
            "all_required_rrf_outside_either_retriever_top_k_count": sum(not bool(row[str(k)]["candidate_union_oracle_all_required"]) and bool(row[str(k)]["rrf_all_required"]) for row in rows),
        }
        summary["by_k"][str(k)] = result
    return summary
