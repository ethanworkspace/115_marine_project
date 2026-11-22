from __future__ import annotations

import hashlib

from src.evaluation.grounded_baselines import retrieval_corpus, stable_sha256
from src.evaluation.retrieval.models import RankedHit


def corpus_rows():
    rows = []
    for index in range(4):
        chunk_id = f"c{index}"
        doc_id = f"d{index // 2}"
        text = f"水質管理內容樣本{index} dissolved oxygen mg/L"
        rows.append({
            "chunk_id": chunk_id, "canonical_chunk_id": chunk_id,
            "document_id": doc_id, "canonical_document_id": doc_id,
            "duplicate_status": "canonical", "retrieval_role": "retrieval",
            "page_start": index % 2 + 1, "page_end": index % 2 + 1,
            "pages": [index % 2 + 1], "text": text,
            "content_checksum": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        })
    return rows


def question(question_id="q1", *, chunks=("c0",), pages=(("d0", 1),), docs=("d0",), style="direct", overlap=0.5):
    return {
        "question_id": question_id, "question": "如何管理水質？", "reference_answer": "依文件管理。",
        "query_style": style, "lexical_overlap": overlap, "species": None, "category": "water_quality",
        "difficulty": "easy", "required_chunks": list(chunks),
        "required_pages": [{"document_id": doc, "page": page} for doc, page in pages],
        "required_documents": list(docs), "multi_document": len(set(docs)) > 1,
        "benchmark_type": "silver", "generation_source": "corpus_grounded_ai",
    }


def hit(rank, chunk_id, document_id, page, score=1.0):
    return RankedHit(rank=rank, chunk_id=chunk_id, document_id=document_id, page=page,
                     page_end=page, raw_score=score, normalized_score=score)


def fake_experiment(question_row, order):
    full = [hit(rank, chunk_id, f"d{int(chunk_id[1:]) // 2}", int(chunk_id[1:]) % 2 + 1, 1 / rank)
            for rank, chunk_id in enumerate(order, start=1)]
    evidence_ids = set(question_row["required_chunks"])
    metrics = {granularity: {"recall@1": 1.0 if order[0] in evidence_ids else 0.0,
                             "recall@3": sum(chunk_id in evidence_ids for chunk_id in order[:3]) / len(evidence_ids),
                             "recall@5": 1.0 if evidence_ids.issubset(set(order[:5])) else 0.0,
                             "recall@10": 1.0,
                             "precision@1": 1.0 if order[0] in evidence_ids else 0.0,
                             "precision@3": sum(chunk_id in evidence_ids for chunk_id in order[:3]) / 3,
                             "precision@5": sum(chunk_id in evidence_ids for chunk_id in order[:5]) / 5,
                             "precision@10": len(evidence_ids) / 10,
                             "mrr": 1.0 / (order.index(next(iter(evidence_ids))) + 1),
                             "ndcg@1": 1.0 if order[0] in evidence_ids else 0.0,
                             "ndcg@3": 1.0 if order[0] in evidence_ids else 0.5,
                             "ndcg@5": 1.0 if order[0] in evidence_ids else 0.5,
                             "ndcg@10": 1.0 if order[0] in evidence_ids else 0.5}
               for granularity in ("chunk", "page", "document")}
    row = {"question_id": question_row["question_id"], "question": question_row,
           "metrics": metrics,
           "required_evidence_coverage": {str(k): {"required_chunk_coverage": sum(chunk_id in set(order[:k]) for chunk_id in evidence_ids) / len(evidence_ids),
                                                    "all_required_chunks": evidence_ids.issubset(set(order[:k])),
                                                    "all_required_pages": True, "all_required_documents": True}
                                          for k in (1, 3, 5, 10)},
           "retrieval_top10_chunk_ids": order[:10]}
    return {"rows": [row], "full_rankings": {question_row["question_id"]: full}}
