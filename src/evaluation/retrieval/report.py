"""Report serialization and aggregate grouping helpers for future experiments."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from .models import ResolvedGold, RetrievalQuery, RetrievalResult

GROUP_FIELDS = {
    "by_category": "category",
    "by_species": "species",
    "by_difficulty": "difficulty",
}


def aggregate_by(rows: list[dict[str, Any]], field: str) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        query = row.get("question") or {}
        groups[str(query.get(field) or "unknown")].append(row)
    return {key: aggregate_metrics(values) for key, values in sorted(groups.items())}


def aggregate_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    metric_values: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    coverage_counts: dict[str, int] = defaultdict(int)
    for row in rows:
        for granularity, metrics in (row.get("metrics") or {}).items():
            for name, value in (metrics.get("scores") or {}).items():
                metric_values[granularity][name].append(float(value))
            for name in ("required_hit", "acceptable_hit", "all_required_recalled"):
                coverage_counts[f"{granularity}.{name}"] += bool(metrics.get(name))
    means = {
        granularity: {name: sum(values) / len(values) for name, values in sorted(metrics.items()) if values}
        for granularity, metrics in sorted(metric_values.items())
    }
    return {"question_count": len(rows), "mean_metrics": means, "coverage_counts": dict(sorted(coverage_counts.items()))}


def aggregate_report(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "overall": aggregate_metrics(rows),
        "by_category": aggregate_by(rows, "category"),
        "by_species": aggregate_by(rows, "species"),
        "by_difficulty": aggregate_by(rows, "difficulty"),
        "by_document_scope": aggregate_by(rows, "document_scope"),
    }


def ranking_trace(query: RetrievalQuery, result: RetrievalResult, gold: ResolvedGold) -> list[dict[str, Any]]:
    required = {item.chunk_id for item in gold.required}
    acceptable = {item.chunk_id for item in gold.acceptable}
    gold_pages = {(item.document_id, page) for item in (*gold.required, *gold.acceptable) if item.page is not None for page in range(item.page, (item.page_end or item.page) + 1)}
    gold_documents = {item.document_id for item in (*gold.required, *gold.acceptable)}
    traces = []
    for hit in sorted(result.hits, key=lambda item: item.rank):
        pages = set(range(hit.page, (hit.page_end or hit.page) + 1)) if hit.page is not None else set()
        traces.append({
            "question_id": query.question_id,
            "query": query.query,
            "rank": hit.rank,
            "chunk_id": hit.chunk_id,
            "document_id": hit.document_id,
            "page": hit.page,
            "raw_score": hit.raw_score,
            "normalized_score": hit.normalized_score,
            "is_required_gold": hit.chunk_id in required,
            "is_acceptable_gold": hit.chunk_id in acceptable,
            "chunk_match": hit.chunk_id in required | acceptable,
            "page_match": any((hit.document_id, page) in gold_pages for page in pages),
            "document_match": hit.document_id in gold_documents,
        })
    return traces


def write_json(path: str | Path, value: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def not_run_placeholders(directory: str | Path) -> None:
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    placeholder = {"status": "not_run", "results": None, "note": "No retrieval benchmark has been executed."}
    for name in ("overall.json", "by_category.json", "by_species.json", "by_difficulty.json"):
        write_json(directory / name, placeholder)
    (directory / "per_question.jsonl").write_text("", encoding="utf-8")
    (directory / "ranking_traces.jsonl").write_text("", encoding="utf-8")
