"""Offline scoring of explicitly supplied results; no retriever is imported or called."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .metrics import SUPPORTED_GRANULARITIES, metric_bundle, required_evidence_coverage
from .models import ResolvedGold, RetrievalQuery, RetrievalResult, as_jsonable


def evaluate_results(
    queries: Sequence[RetrievalQuery],
    results: Mapping[str, RetrievalResult],
    gold: Mapping[str, ResolvedGold],
) -> list[dict[str, Any]]:
    """Score caller-supplied synthetic/offline results only.

    This is intentionally a pure harness boundary, not a production retrieval adapter.
    """
    output: list[dict[str, Any]] = []
    for query in queries:
        if query.question_id not in gold:
            raise KeyError(f"missing resolved Gold for question: {query.question_id}")
        if query.question_id not in results:
            raise KeyError(f"missing RetrievalResult for question: {query.question_id}")
        result = results[query.question_id]
        if result.question_id != query.question_id:
            raise ValueError(f"result question_id mismatch for {query.question_id}")
        output.append({
            "question": as_jsonable(query),
            "metrics": {level: as_jsonable(metric_bundle(result, gold[query.question_id], level)) for level in SUPPORTED_GRANULARITIES},
            "required_evidence_coverage": required_evidence_coverage(result, gold[query.question_id]),
        })
    return output
