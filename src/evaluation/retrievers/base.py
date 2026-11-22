"""Minimal interface for isolated evaluation retrievers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from ..retrieval.models import RankedHit


class EvaluationRetriever(ABC):
    retriever_type = "evaluation"

    @abstractmethod
    def retrieve(self, query: str, *, top_k: int = 10) -> list[RankedHit]:
        """Return deterministic ranked hits without access to expected evidence."""

    @abstractmethod
    def rank_all(self, query: str) -> list[RankedHit]:
        """Return the full deterministic ranking for post-hoc error analysis."""

    @property
    @abstractmethod
    def index_manifest(self) -> dict[str, Any]:
        """Describe the experimental index inputs and fixed configuration."""

