"""Resolve human Gold references against a frozen Evaluation Corpus."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from .models import GoldEvidence, ResolvedGold


class GoldResolutionError(ValueError):
    """Raised when a Gold reference cannot be resolved safely."""


def resolve_gold(question: Mapping[str, Any], corpus: Mapping[str, Mapping[str, Any]] | Iterable[Mapping[str, Any]]) -> ResolvedGold:
    by_id = corpus if isinstance(corpus, Mapping) else {str(row.get("chunk_id")): row for row in corpus if row.get("chunk_id")}
    required_ids = list(dict.fromkeys(str(value) for value in question.get("required_chunks", []) or []))
    acceptable_ids = list(dict.fromkeys(str(value) for value in question.get("acceptable_chunks", []) or []))
    if question.get("answerable") is True and not (required_ids or acceptable_ids):
        raise GoldResolutionError(f"{question.get('question_id')}: answerable question has no required/acceptable Gold evidence")

    def resolve(ids: list[str], relation: str) -> tuple[GoldEvidence, ...]:
        result: list[GoldEvidence] = []
        for chunk_id in ids:
            row = by_id.get(chunk_id)
            if row is None:
                raise GoldResolutionError(f"{question.get('question_id')}: cannot resolve {relation} chunk {chunk_id}")
            if row.get("retrieval_role") == "excluded":
                raise GoldResolutionError(f"{question.get('question_id')}: {relation} chunk {chunk_id} is excluded")
            if row.get("duplicate_status") in {"exact_duplicate", "duplicate_source"}:
                raise GoldResolutionError(f"{question.get('question_id')}: {relation} chunk {chunk_id} is a non-canonical duplicate")
            if relation == "required" and row.get("retrieval_role") != "retrieval":
                raise GoldResolutionError(f"{question.get('question_id')}: required chunk {chunk_id} is not retrieval-role")
            page = row.get("page_start")
            if page is None:
                raise GoldResolutionError(f"{question.get('question_id')}: Gold chunk {chunk_id} has no page provenance")
            result.append(GoldEvidence(chunk_id, str(row.get("document_id") or ""), int(page), relation, int(row.get("page_end") or page)))
        return tuple(result)

    return ResolvedGold(
        question_id=str(question.get("question_id") or ""),
        required=resolve(required_ids, "required"),
        acceptable=resolve(acceptable_ids, "acceptable"),
        answerable=question.get("answerable") if isinstance(question.get("answerable"), bool) else None,
        metadata={key: question.get(key) for key in ("category", "species", "difficulty", "document_scope")},
    )
