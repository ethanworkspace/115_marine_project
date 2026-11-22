"""Fixed-configuration BM25 index over a filtered, frozen evaluation corpus."""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any

from ..retrieval.models import RankedHit
from ..silver import _eligible_corpus
from .base import EvaluationRetriever

TOKENIZER = "traditional_chinese_bigrams_latin_terms_v1"
BM25_CONFIG = {"k1": 1.5, "b": 0.75, "query_term_frequency": "unique_terms", "tie_break": "chunk_id_ascending"}


def tokenize(text: str) -> list[str]:
    terms: list[str] = []
    for match in re.finditer(r"[a-z0-9]+(?:[./_%+\-][a-z0-9]+)*|[\u3400-\u9fff]+", str(text or "").casefold()):
        token = match.group(0)
        if re.fullmatch(r"[\u3400-\u9fff]+", token):
            if len(token) == 1:
                terms.append(token)
            else:
                terms.extend(token[index:index + 2] for index in range(len(token) - 1))
        else:
            terms.append(token)
    return terms


class EvaluationBM25(EvaluationRetriever):
    """In-memory experimental BM25; never imports or calls production retrieval."""

    retriever_type = "bm25"

    def __init__(
        self,
        corpus_rows: list[dict[str, Any]],
        *,
        corpus_sha256: str,
        git_commit: str | None = None,
        created_at: str | None = None,
    ) -> None:
        self.documents = _eligible_corpus(corpus_rows)
        self.corpus_sha256 = corpus_sha256
        self.git_commit = git_commit
        self.created_at = created_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        self._tokens: list[list[str]] = []
        self._term_freqs: list[Counter[str]] = []
        self._lengths: list[int] = []
        document_frequency: Counter[str] = Counter()
        for row in self.documents:
            tokens = tokenize(str(row.get("text") or ""))
            term_freq = Counter(tokens)
            self._tokens.append(tokens)
            self._term_freqs.append(term_freq)
            self._lengths.append(len(tokens))
            document_frequency.update(term_freq.keys())
        self._df = document_frequency
        self._average_length = sum(self._lengths) / len(self._lengths) if self._lengths else 0.0
        self._manifest = {
            "index_id": "bm25_silver_v1",
            "benchmark_type": "silver",
            "generation_source": "ai_question_bank",
            "question_origin": "ai_generated",
            "evidence_mapping_type": "auto_mapped",
            "corpus_sha256": corpus_sha256,
            "retrieval_chunk_count": len(self.documents),
            "tokenizer": TOKENIZER,
            "bm25_configuration": dict(BM25_CONFIG),
            "created_at": self.created_at,
            "git_commit": git_commit or "unknown",
            "index_storage": "in_memory_experimental_only",
            "eligibility_filter": {
                "retrieval_role": "retrieval",
                "duplicate_status_excluded": ["exact_duplicate", "duplicate_source"],
                "canonical_chunk_only": True,
                "context_only_excluded": True,
                "human_gold_benchmark_eligible_filter": False,
            },
        }

    @property
    def index_manifest(self) -> dict[str, Any]:
        return dict(self._manifest)

    def rank_all(self, query: str) -> list[RankedHit]:
        query_terms = sorted(set(tokenize(query)))
        scores: list[tuple[float, int]] = []
        n_docs = len(self.documents)
        k1, b = float(BM25_CONFIG["k1"]), float(BM25_CONFIG["b"])
        for index, term_freq in enumerate(self._term_freqs):
            score = 0.0
            doc_length = self._lengths[index]
            length_norm = k1 * (1.0 - b + b * doc_length / self._average_length) if self._average_length else k1
            for term in query_terms:
                tf = term_freq.get(term, 0)
                if not tf:
                    continue
                df = self._df.get(term, 0)
                idf = math.log(1.0 + (n_docs - df + 0.5) / (df + 0.5))
                score += idf * (tf * (k1 + 1.0)) / (tf + length_norm)
            scores.append((score, index))
        scores.sort(key=lambda item: (-item[0], str(self.documents[item[1]].get("chunk_id") or "")))
        max_score = scores[0][0] if scores else 0.0
        hits = []
        for rank, (score, index) in enumerate(scores, start=1):
            row = self.documents[index]
            page = row.get("page_start")
            page_end = row.get("page_end") or page
            hits.append(RankedHit(
                rank=rank,
                chunk_id=str(row.get("chunk_id") or ""),
                document_id=str(row.get("document_id") or ""),
                page=int(page) if page is not None else None,
                raw_score=float(score),
                normalized_score=float(score / max_score) if max_score else 0.0,
                page_end=int(page_end) if page_end is not None else None,
            ))
        return hits

    def retrieve(self, query: str, *, top_k: int = 10) -> list[RankedHit]:
        if top_k < 1:
            raise ValueError("top_k must be positive")
        return self.rank_all(query)[:top_k]
