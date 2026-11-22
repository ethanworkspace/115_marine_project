"""Construct leakage-free Oracle and frozen E4 Top-5 contexts."""

from __future__ import annotations

from typing import Any

from .frozen import sha256_text


def _corpus_pages(row: dict[str, Any]) -> set[int]:
    pages: set[int] = set()
    for value in row.get("pages") or []:
        try:
            pages.add(int(value))
        except (TypeError, ValueError):
            continue
    for span in row.get("source_spans") or []:
        value = span.get("page_number")
        if value is not None:
            pages.add(int(value))
    start = row.get("page_start")
    end = row.get("page_end") or start
    if start is not None:
        pages.update(range(int(start), int(end) + 1))
    return pages


def build_oracle_contexts(question: dict[str, Any], corpus_by_id: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    snapshots = question.get("evidence_snapshot") or []
    required_chunks = list(question.get("required_chunks") or [])
    if not required_chunks or {str(s.get("chunk_id")) for s in snapshots} != set(map(str, required_chunks)):
        raise ValueError(f"Oracle evidence snapshots do not exactly cover required chunks for {question.get('question_id')}")
    contexts: list[dict[str, Any]] = []
    for snapshot in snapshots:
        chunk_id = str(snapshot.get("chunk_id") or "")
        row = corpus_by_id.get(chunk_id)
        if row is None:
            raise ValueError(f"Oracle chunk does not resolve in Evaluation Corpus v2: {chunk_id}")
        text = str(snapshot.get("text_snapshot") or "")
        if not text or sha256_text(text) != snapshot.get("content_checksum"):
            raise ValueError(f"Oracle snapshot checksum is invalid: {chunk_id}")
        if str(snapshot.get("content_checksum")) != str(row.get("content_checksum")):
            raise ValueError(f"Oracle snapshot and corpus checksums differ: {chunk_id}")
        if text != str(row.get("text") or ""):
            raise ValueError(f"Oracle snapshot text differs from the frozen corpus: {chunk_id}")
        document_id = str(snapshot.get("document_id") or "")
        page = int(snapshot["page"])
        if document_id != str(row.get("document_id") or "") or page not in _corpus_pages(row):
            raise ValueError(f"Oracle snapshot provenance is inconsistent: {chunk_id}")
        contexts.append({
            "context_id": f"C{len(contexts) + 1}",
            "chunk_id": chunk_id,
            "document_id": document_id,
            "page": page,
            "text": text,
        })
    return contexts


def build_e4_top5_contexts(question: dict[str, Any], trace_rows: list[dict[str, Any]],
                           corpus_by_id: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    top5 = sorted((row for row in trace_rows if int(row.get("rank", 0)) <= 5), key=lambda row: int(row["rank"]))
    if len(top5) != 5 or [int(row["rank"]) for row in top5] != [1, 2, 3, 4, 5]:
        raise ValueError(f"E4 Top-5 is incomplete for {question.get('question_id')}")
    contexts: list[dict[str, Any]] = []
    seen: set[str] = set()
    for hit in top5:
        chunk_id = str(hit.get("chunk_id") or "")
        if chunk_id in seen:
            raise ValueError(f"E4 Top-5 has duplicate chunk ID: {chunk_id}")
        seen.add(chunk_id)
        row = corpus_by_id.get(chunk_id)
        if row is None:
            raise ValueError(f"E4 Top-5 chunk does not resolve in frozen corpus: {chunk_id}")
        duplicate_status = row.get("duplicate_status")
        if row.get("retrieval_role") != "retrieval" or duplicate_status not in {"none", "canonical"}:
            raise ValueError(f"E4 Top-5 contains a non-retrieval or non-canonical chunk: {chunk_id}")
        canonical_id = row.get("canonical_chunk_id")
        if (duplicate_status == "canonical" and str(canonical_id) != chunk_id) or (
            duplicate_status == "none" and canonical_id not in (None, chunk_id)
        ):
            raise ValueError(f"E4 Top-5 contains a non-canonical duplicate: {chunk_id}")
        document_id = str(hit.get("document_id") or "")
        page = int(hit["page"])
        if document_id != str(row.get("document_id") or "") or page not in _corpus_pages(row):
            raise ValueError(f"E4 Top-5 provenance differs from frozen corpus: {chunk_id}")
        text = str(row.get("text") or "")
        if not text:
            raise ValueError(f"E4 Top-5 chunk has no text: {chunk_id}")
        contexts.append({
            "context_id": f"C{len(contexts) + 1}",
            "chunk_id": chunk_id,
            "document_id": document_id,
            "page": page,
            "text": text,
            "rank": int(hit["rank"]),
        })
    return contexts


def format_user_prompt(question: str, contexts: list[dict[str, Any]]) -> str:
    formatted = []
    for context in contexts:
        formatted.append(
            f"[{context['context_id']}]\nchunk_id: {context['chunk_id']}\ndocument_id: {context['document_id']}\npage: {context['page']}\n"
            f"Evidence:\n{context['text']}"
        )
    return (
        "以下是本題唯一可使用的 Evidence。若不能直接支持答案，請依規則回答 insufficient_evidence。\n\n"
        + "\n\n".join(formatted)
        + f"\n\n問題：{question}"
    )


def make_user_prompt(question_id: str, question: str, contexts: list[dict[str, Any]]) -> str:
    return format_user_prompt(question, contexts) + f"\n\nquestion_id：{question_id}"
