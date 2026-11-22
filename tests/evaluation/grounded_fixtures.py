from __future__ import annotations

import hashlib

from src.evaluation.grounded.pipeline import make_question_record


def make_corpus_record(chunk_id="c1", document_id="d1", species="吳郭魚",
                       text=("吳郭魚養殖資料記載，池塘管理需要保持水質穩定，並定期觀察魚群攝食狀況。"
                             "養殖現場應依資料所述記錄魚群活動與攝食變化，並在日常管理中確認池塘環境維持狀況。"
                             "這些內容提供可追溯的魚種管理資訊，說明觀察項目與操作背景，供建立評測 evidence 使用。")):
    checksum = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return {
        "chunk_id": chunk_id,
        "canonical_chunk_id": chunk_id,
        "document_id": document_id,
        "canonical_document_id": document_id,
        "retrieval_role": "retrieval",
        "duplicate_status": "none",
        "risk_level": "normal",
        "species": species,
        "topic": "養殖管理",
        "chunk_strategy": "manual",
        "chunk_type": "child",
        "chunk_version": "2.0.0-shadow",
        "page_start": 3,
        "page_end": 3,
        "source_title": "測試養殖手冊",
        "text": text,
        "content_checksum": checksum,
        "extraction_confidence": 0.95,
        "extraction_method": "native",
        "parser_name": "test",
        "parser_version": "1",
        "source_spans": [{
            "document_id": document_id,
            "page_number": 3,
            "file_checksum": "a" * 64,
            "start_position": 0,
            "end_position": len(text),
            "source_span_id": "s-" + chunk_id,
            "text_checksum": checksum,
            "parser_name": "test",
            "parser_version": "1",
            "extraction_method": "native",
            "extraction_confidence": 0.95,
        }],
        "warnings": [],
        "table_data": None,
    }


def make_evidence(record=None):
    from src.evaluation.grounded.pipeline import build_evidence_pool
    corpus = record or make_corpus_record()
    return build_evidence_pool([corpus])[0]


def make_question(evidences=None, style="direct", category="fact", question_text=None,
                  answer=None, quotes=None, corpus_sha="b" * 64):
    evidences = evidences or [make_evidence()]
    text = evidences[0]["text"]
    return make_question_record(
        question_id="grounded-test-" + style + "-" + evidences[0]["chunk_id"],
        question=question_text or "根據資料，吳郭魚養殖管理應觀察什麼？",
        answer=answer or "資料提到應定期觀察魚群攝食狀況。",
        evidences=evidences,
        style=style,
        category=category,
        corpus_sha256=corpus_sha,
        generation_model="synthetic-test-fixture",
        generation_config={"temperature": 0},
        supporting_quotes=quotes or [{
            "chunk_id": evidences[0]["chunk_id"],
            "quote": text[-14:],
        }],
    )
