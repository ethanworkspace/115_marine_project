"""Typed data models for offline retrieval evaluation."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class RetrievalQuery:
    question_id: str
    query: str
    category: str | None = None
    species: str | None = None
    difficulty: str | None = None


@dataclass(frozen=True)
class RankedHit:
    rank: int
    chunk_id: str
    document_id: str
    page: int | None
    raw_score: float | None = None
    normalized_score: float | None = None
    page_end: int | None = None


@dataclass(frozen=True)
class RetrievalResult:
    question_id: str
    hits: tuple[RankedHit, ...] = ()


@dataclass(frozen=True)
class GoldEvidence:
    chunk_id: str
    document_id: str
    page: int | None
    relation: str
    page_end: int | None = None


@dataclass(frozen=True)
class ResolvedGold:
    question_id: str
    required: tuple[GoldEvidence, ...] = ()
    acceptable: tuple[GoldEvidence, ...] = ()
    answerable: bool | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class QuestionMetrics:
    question_id: str
    granularity: str
    scores: dict[str, float] = field(default_factory=dict)
    required_hit: bool = False
    acceptable_hit: bool = False
    all_required_recalled: bool = False
    missing_required_chunks: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class RankingTrace:
    question_id: str
    query: str
    rank: int
    chunk_id: str
    document_id: str
    page: int | None
    raw_score: float | None
    normalized_score: float | None
    is_required_gold: bool
    is_acceptable_gold: bool
    chunk_match: bool
    page_match: bool
    document_match: bool


def as_jsonable(value: Any) -> Any:
    if hasattr(value, "__dataclass_fields__"):
        return asdict(value)
    if isinstance(value, (tuple, set)):
        return [as_jsonable(item) for item in value]
    if isinstance(value, list):
        return [as_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): as_jsonable(item) for key, item in value.items()}
    return value
