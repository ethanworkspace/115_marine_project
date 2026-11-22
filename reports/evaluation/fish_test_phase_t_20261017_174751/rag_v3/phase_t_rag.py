from __future__ import annotations
import hashlib
import os
import sys
from pathlib import Path
from typing import Any
import numpy as np

ROOT = Path(__file__).resolve().parents[4]
PHASE_S = ROOT / "reports/evaluation/fish_test_phase_s_integrated_20261017_173906"
SNAPSHOT = ROOT / ".venv-reranker/hf-cache/hub/models--BAAI--bge-reranker-v2-m3/snapshots/953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e"
RAG_DIR = PHASE_S / "rag_v2"
sys.path.append(str(ROOT / '.venv/Lib/site-packages'))
if str(RAG_DIR) not in sys.path:
    sys.path.insert(0, str(RAG_DIR))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
import phase_s_rag as base
from src.evaluation.reranker_runtime import CrossEncoderRuntime


class PhaseTRAG:
    """Isolated Phase T adapter; does not modify Production or frozen E4."""

    def __init__(self, db_path: Path | None = None, model_path: Path = SNAPSHOT):
        self.db_path = db_path or PHASE_S / "corpus/phase_s_integrated_kb_v1.sqlite3"
        if not self.db_path.is_file():
            raise FileNotFoundError(self.db_path)
        if not model_path.is_dir():
            raise FileNotFoundError(model_path)
        self.chunks = base.load_chunks(self.db_path)
        self.by_id = {str(c["chunk_id"]): c for c in self.chunks}
        self.reranker = CrossEncoderRuntime(model_path, device="cuda", max_length=512, batch_size=4)

    def retrieve(self, question: dict[str, Any]) -> dict[str, Any]:
        profile = base.requirement_profile(question)
        query = f"{profile['target_species'] or ''} {question.get('question_text', '')}".strip()
        qvec = base.embed_texts([query])[0]
        stages = base.rrf_rank(query, profile, self.chunks, qvec, limit=100)
        candidates = []
        for rank, row in enumerate(stages["rrf"], start=1):
            item = dict(self.by_id[row["chunk_id"]])
            item.update({"text": item["content"], "rank": rank, "rrf_score": row["score"],
                         "bm25_rank": row.get("bm25_rank"), "dense_rank": row.get("dense_rank")})
            candidates.append(item)
        reranked = self.reranker.rerank(query, candidates)[:5] if candidates else []
        result = []
        for rank, item in enumerate(reranked, start=1):
            body = str(item["content"])
            result.append({
                "chunk_id": item["chunk_id"], "rank": rank,
                "source_id": item["source_id"], "source_title": item["source_title"],
                "source_url": item["source_url"], "source_sha256": item["source_sha256"],
                "source_version": item.get("source_version"), "page": item.get("page"),
                "locator": item.get("locator"), "content": body,
                "content_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
                "reranker_score": item["reranker_score"], "rrf_rank": item["rank"],
                "retrieval_eligible": True,
            })
        return {
            "question_id": question.get("question_id"), "query": query,
            "query_excludes_answer_and_rubric": True,
            "corpus_version": "phase_s_integrated_kb_v1_candidate_only",
            "bm25_top100": stages["bm25"], "dense_top100": stages["dense"],
            "rrf_candidates_top100": stages["rrf"], "reranked_top5": result,
            "retrieval_status": "complete" if len(result) == 5 else "insufficient_retrieval_evidence",
            "support_sufficiency": "not_evaluated",
            "final_top5_count": len(result),
        }

    def answer(self, question: dict[str, Any], model_tag: str, *, answer_gate: dict[str, Any] | None = None) -> dict[str, Any]:
        """Fail closed unless independent source/rubric qualification is explicitly supplied."""
        answer_gate = answer_gate or {}
        if answer_gate.get("answer_verified") is not True or answer_gate.get("support_sufficient") is not True:
            return {"status": "insufficient_evidence", "reason": "Gate 2/4 source-answer qualification has not passed", "generator_called": False}
        retrieved = self.retrieve(question)
        if retrieved["final_top5_count"] != 5:
            return {"status": "insufficient_evidence", "reason": "fewer than five retrieval-eligible chunks", "generator_called": False}
        return base.generate(model_tag, str(question.get("question_text") or ""), retrieved["reranked_top5"])



