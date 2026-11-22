"""Evaluation-only cosine retrieval over vectors produced by a local Ollama model."""

from __future__ import annotations

from typing import Any

from ..retrieval.models import RankedHit
from .base import EvaluationRetriever


class EvaluationDense(EvaluationRetriever):
    """Pure dense ranker; query vectors are keyed only by the query text."""

    retriever_type = "dense"

    def __init__(
        self,
        documents: list[dict[str, Any]],
        vectors: list[list[float]],
        query_vectors: dict[str, list[float]],
        *,
        manifest: dict[str, Any],
    ) -> None:
        if len(documents) != len(vectors):
            raise ValueError("Dense vector count must equal document count")
        if not documents:
            raise ValueError("Dense corpus cannot be empty")
        dimensions = {len(vector) for vector in vectors}
        if len(dimensions) != 1 or any(len(vector) not in dimensions for vector in query_vectors.values()):
            raise ValueError("Dense corpus/query vector dimensions do not match")
        self.documents = documents
        self.vectors = vectors
        self.query_vectors = query_vectors
        self._manifest = dict(manifest)

    @property
    def index_manifest(self) -> dict[str, Any]:
        return dict(self._manifest)

    def rank_vector(self, query_vector: list[float]) -> list[RankedHit]:
        if len(query_vector) != len(self.vectors[0]):
            raise ValueError("Query vector dimension does not match dense index")
        scored: list[tuple[float, int]] = []
        for index, vector in enumerate(self.vectors):
            score = sum(left * right for left, right in zip(vector, query_vector))
            scored.append((float(score), index))
        scored.sort(key=lambda item: (-item[0], str(self.documents[item[1]].get("chunk_id") or "")))
        hits: list[RankedHit] = []
        for rank, (score, index) in enumerate(scored, start=1):
            row = self.documents[index]
            pages = row.get("pages") or []
            start = row.get("page_start") or (min(pages) if pages else None)
            end = row.get("page_end") or (max(pages) if pages else start)
            hits.append(RankedHit(
                rank=rank,
                chunk_id=str(row.get("chunk_id") or ""),
                document_id=str(row.get("document_id") or ""),
                page=int(start) if start is not None else None,
                raw_score=score,
                normalized_score=score,
                page_end=int(end) if end is not None else None,
            ))
        return hits

    def rank_all(self, query: str) -> list[RankedHit]:
        try:
            vector = self.query_vectors[query]
        except KeyError as exc:
            raise KeyError("Query was not embedded by the frozen E2 runtime") from exc
        return self.rank_vector(vector)

    def retrieve(self, query: str, *, top_k: int = 10) -> list[RankedHit]:
        if top_k < 1:
            raise ValueError("top_k must be positive")
        return self.rank_all(query)[:top_k]
