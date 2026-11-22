from __future__ import annotations

from src.evaluation.corpus import build_corpus


def make_chunk(chunk_id="chunk-a", *, chunk_type="child", strategy="manual", document_id="doc-a", parent=None,
               checksum="abc", status="accepted_with_warning", chunkable=True, verified=False, legal="unknown", text="sample"):
    return {
        "chunk_id": chunk_id, "document_id": document_id, "parent_chunk_id": parent,
        "chunk_type": chunk_type, "chunk_strategy": strategy, "chunk_version": "2.0.0-shadow",
        "text": text, "species": "鰻魚", "topic": "疾病", "disease": None, "chapter": None,
        "section": "section", "article": None, "page_start": 1, "page_end": 1,
        "source_span_ids": ["span-1"], "parser_name": "test", "parser_version": "1",
        "extraction_method": "native", "extraction_confidence": 0.9, "ingestion_status": status,
        "source_verified": verified, "legal_status": legal, "chunkable": chunkable,
        "indexable": False, "content_checksum": checksum,
    }


def make_doc(document_id="doc-a", *, checksum="file-a", duplicate_of=None, tier=None, title="養殖管理"):
    return {"document_id": document_id, "checksum": checksum, "duplicate_of": duplicate_of,
            "source_tier": tier, "title": title, "source_id": "unverified", "source_url": None,
            "legal_status": "unknown", "document_type": "unknown", "topics": []}


def build(chunks, docs):
    return build_corpus(chunks, docs)[0]
