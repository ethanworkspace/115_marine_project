from __future__ import annotations

import hashlib

from src.ingestion.chunking.common import ChunkFactory, TextUnit


CONFIG = {
    "chunk_version": "2.0.0-shadow", "target_size": 60, "max_size": 120,
    "minimum_size": 20, "overlap": 10, "table_row_group_size": 2,
}


def page(text: str, number: int = 1, *, status: str = "accepted_with_warning") -> dict:
    return {
        "document_id": "doc-1", "file_checksum": hashlib.sha256(b"source").hexdigest(),
        "page_number": number, "selected_text": text, "text": text, "native_text": text,
        "extraction_method": "native", "extraction_confidence": 0.99,
        "parser_name": "test-parser", "parser_version": "1.0",
        "ingestion_status": status, "tables": [],
    }


def document(**overrides) -> dict:
    value = {
        "document_id": "doc-1", "title": "一般參考文件", "document_type": "unknown",
        "topics": [], "species": [], "source_verified": False, "legal_status": "unknown",
    }
    value.update(overrides)
    return value


def factory() -> ChunkFactory:
    return ChunkFactory(config=CONFIG, span_registry={})


def run_single(chunker, doc: dict, text: str, number: int = 1):
    pages = [page(text, number)]
    output = factory()
    chunker(doc, TextUnit(pages), output)
    return output
