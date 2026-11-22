"""Pure retrieval metrics at chunk, page, and document granularity."""

from __future__ import annotations

import math
from collections.abc import Iterable
from typing import Literal

from .models import GoldEvidence, QuestionMetrics, ResolvedGold, RetrievalResult

Granularity = Literal["chunk", "page", "document"]
SUPPORTED_GRANULARITIES = ("chunk", "page", "document")


def _hit_key_groups(result: RetrievalResult, granularity: Granularity) -> list[tuple[int, set[str | tuple[str, int]]]]:
    groups: list[tuple[int, set[str | tuple[str, int]]]] = []
    for hit in sorted(result.hits, key=lambda item: item.rank):
        if granularity == "chunk":
            keys = {hit.chunk_id}
        elif granularity == "document":
            keys = {hit.document_id}
        elif granularity == "page":
            if hit.page is None:
                continue
            end = hit.page_end or hit.page
            keys = {(hit.document_id, page) for page in range(hit.page, end + 1)}
        else:
            raise ValueError(f"unknown granularity: {granularity}")
        groups.append((hit.rank, keys))
    return groups


def _evidence_keys(evidence: Iterable[GoldEvidence], granularity: Granularity) -> set[str | tuple[str, int]]:
    keys: set[str | tuple[str, int]] = set()
    for item in evidence:
        if granularity == "chunk":
            keys.add(item.chunk_id)
        elif granularity == "document":
            keys.add(item.document_id)
        elif granularity == "page":
            if item.page is None:
                raise ValueError(f"Gold evidence has no page: {item.chunk_id}")
            end = item.page_end or item.page
            keys.update((item.document_id, page) for page in range(item.page, end + 1))
        else:
            raise ValueError(f"unknown granularity: {granularity}")
    return keys


def recall_at(result: RetrievalResult, gold: ResolvedGold, k: int, granularity: Granularity) -> float:
    relevant = _evidence_keys((*gold.required, *gold.acceptable), granularity)
    if not relevant:
        return 0.0
    ranked_groups = _hit_key_groups(result, granularity)[:k]
    ranked = set().union(*(keys for _, keys in ranked_groups)) if ranked_groups else set()
    return len(ranked & relevant) / len(relevant)


def precision_at(result: RetrievalResult, gold: ResolvedGold, k: int, granularity: Granularity) -> float:
    relevant = _evidence_keys((*gold.required, *gold.acceptable), granularity)
    ranked_groups = _hit_key_groups(result, granularity)[:k]
    if k <= 0:
        raise ValueError("k must be positive")
    covered: set[str | tuple[str, int]] = set()
    relevant_results = 0
    for _, keys in ranked_groups:
        new_matches = (keys & relevant) - covered
        if new_matches:
            # One retrieved chunk is one ranked result even when it spans several
            # relevant pages/documents. This keeps Precision@K bounded by 1.
            relevant_results += 1
        covered.update(keys)
    return relevant_results / k


def reciprocal_rank(result: RetrievalResult, gold: ResolvedGold, granularity: Granularity) -> float:
    relevant = _evidence_keys((*gold.required, *gold.acceptable), granularity)
    for rank, keys in _hit_key_groups(result, granularity):
        if keys & relevant:
            return 1.0 / rank
    return 0.0


def ndcg_at(result: RetrievalResult, gold: ResolvedGold, k: int, granularity: Granularity) -> float:
    if k <= 0:
        raise ValueError("k must be positive")
    relevant = _evidence_keys((*gold.required, *gold.acceptable), granularity)
    ranked_groups = _hit_key_groups(result, granularity)[:k]
    covered: set[str | tuple[str, int]] = set()
    relevant_ranks: list[int] = []
    for rank, keys in ranked_groups:
        new_matches = (keys & relevant) - covered
        if new_matches:
            # A chunk gets at most one binary gain at its rank, even if its page
            # span overlaps several required pages.
            relevant_ranks.append(rank)
        covered.update(keys)
    dcg = sum(1.0 / math.log2(rank + 1) for rank in relevant_ranks)
    ideal_hits = min(len(relevant), k)
    idcg = sum(1.0 / math.log2(rank + 1) for rank in range(1, ideal_hits + 1))
    return dcg / idcg if idcg else 0.0


def required_evidence_coverage(result: RetrievalResult, gold: ResolvedGold) -> dict[str, object]:
    retrieved = {hit.chunk_id for hit in result.hits}
    required_ids = {item.chunk_id for item in gold.required}
    acceptable_ids = {item.chunk_id for item in gold.acceptable}
    required_hit_ids = required_ids & retrieved
    acceptable_hit_ids = acceptable_ids & retrieved
    required_documents = {item.document_id for item in gold.required}
    retrieved_documents = {hit.document_id for hit in result.hits}
    missing = sorted(required_ids - retrieved)
    return {
        "required_hit": bool(required_hit_ids),
        "acceptable_hit": bool(acceptable_hit_ids),
        "all_required_recalled": bool(required_ids) and required_ids.issubset(retrieved),
        "required_recall": len(required_hit_ids) / len(required_ids) if required_ids else None,
        "missing_required_chunks": missing,
        "required_documents": sorted(required_documents),
        "retrieved_required_documents": sorted(required_documents & retrieved_documents),
        "all_required_documents_retrieved": bool(required_documents) and required_documents.issubset(retrieved_documents),
        "multi_document_partial": len(required_documents) > 1 and bool(required_documents & retrieved_documents) and not required_documents.issubset(retrieved_documents),
    }


def metric_bundle(result: RetrievalResult, gold: ResolvedGold, granularity: Granularity) -> QuestionMetrics:
    scores = {f"recall@{k}": recall_at(result, gold, k, granularity) for k in (1, 3, 5, 10)}
    scores.update({f"precision@{k}": precision_at(result, gold, k, granularity) for k in (1, 3, 5, 10)})
    scores["mrr"] = reciprocal_rank(result, gold, granularity)
    scores.update({f"ndcg@{k}": ndcg_at(result, gold, k, granularity) for k in (1, 3, 5, 10)})
    coverage = required_evidence_coverage(result, gold)
    return QuestionMetrics(gold.question_id, granularity, scores, bool(coverage["required_hit"]), bool(coverage["acceptable_hit"]), bool(coverage["all_required_recalled"]), list(coverage["missing_required_chunks"]))
