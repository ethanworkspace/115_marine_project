from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import time
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
import requests


ROOT = Path(__file__).resolve().parents[4]
RUN = Path(__file__).resolve().parents[1]
DB_PATH = RUN / "corpus" / "phase_s_integrated_kb_v1.sqlite3"
OLLAMA = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
BGE_TAG = "bge-m3:latest"
RERANKER_ID = "BAAI/bge-reranker-v2-m3"
RRF_K = 60
TOP_K = 5

MODEL_TAGS = {
    "M1": "deepseek-r1:7b",
    "M2": "qwen2.5-coder:7b",
    "M3": "hf.co/bartowski/DeepSeek-R1-Distill-Llama-8B-GGUF:Q4_K_M",
    "M4": "gemma2:9b",
}

SPECIES = ("虱目魚", "吳郭魚", "石斑魚", "鱸魚", "烏魚", "鰻魚")


class RerankerUnavailable(RuntimeError):
    pass


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def tokenize_zh(text: str) -> list[str]:
    normalized = re.sub(r"\s+", "", text.lower())
    tokens = re.findall(r"[a-z0-9_]{2,}", text.lower())
    cjk = [(i, ch) for i, ch in enumerate(normalized) if "\u3400" <= ch <= "\u9fff"]
    # Preserve CJK phrase signal without treating an unverified species alias as canonical.
    tokens.extend(ch for _, ch in cjk)
    tokens.extend(normalized[i:i + 2] for i in range(max(0, len(normalized) - 1)) if "\u3400" <= normalized[i] <= "\u9fff" and "\u3400" <= normalized[i + 1] <= "\u9fff")
    tokens.extend(normalized[i:i + 3] for i in range(max(0, len(normalized) - 2)) if all("\u3400" <= normalized[j] <= "\u9fff" for j in range(i, i + 3)))
    return tokens


def embed_texts(texts: list[str], *, timeout: int = 180) -> np.ndarray:
    if not texts:
        return np.empty((0, 1024), dtype=np.float32)
    response = requests.post(f"{OLLAMA}/api/embed", json={"model": BGE_TAG, "input": texts}, timeout=timeout)
    response.raise_for_status()
    vectors = np.asarray(response.json()["embeddings"], dtype=np.float32)
    if vectors.ndim != 2 or vectors.shape != (len(texts), 1024):
        raise ValueError(f"Unexpected BGE-M3 output shape {vectors.shape}; expected ({len(texts)}, 1024)")
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    if np.any(norms == 0) or not np.all(np.isfinite(vectors)):
        raise ValueError("Embedding returned zero or non-finite vectors")
    return vectors / norms


def load_chunks(db_path: Path = DB_PATH) -> list[dict[str, Any]]:
    if not db_path.is_file():
        raise FileNotFoundError(f"Phase S isolated KB is not built: {db_path}")
    with sqlite3.connect(db_path) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute("SELECT chunk_id, source_id, source_title, source_url, source_sha256, source_version, source_kind, species_scope, category_scope, page, locator, content, lexical_tokens, embedding FROM chunks ORDER BY chunk_id").fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["embedding"] = np.frombuffer(item["embedding"], dtype="<f4").astype(np.float32)
        result.append(item)
    return result


def bm25_scores(query: str, chunks: list[dict[str, Any]], *, k1: float = 1.5, b: float = 0.75) -> dict[str, float]:
    query_terms = set(tokenize_zh(query))
    if not query_terms or not chunks:
        return {}
    token_lists = [item["lexical_tokens"].split() for item in chunks]
    doc_freq: dict[str, int] = {}
    term_freqs: list[dict[str, int]] = []
    lengths = []
    for terms in token_lists:
        counts: dict[str, int] = {}
        for term in terms:
            counts[term] = counts.get(term, 0) + 1
        term_freqs.append(counts)
        lengths.append(len(terms))
        for term in counts:
            doc_freq[term] = doc_freq.get(term, 0) + 1
    n = len(chunks)
    avgdl = sum(lengths) / max(n, 1)
    scores: dict[str, float] = {}
    for item, tfmap, dl in zip(chunks, term_freqs, lengths):
        score = 0.0
        for term in query_terms:
            tf = tfmap.get(term, 0)
            if not tf:
                continue
            df = doc_freq.get(term, 0)
            idf = np.log(1.0 + (n - df + 0.5) / (df + 0.5))
            score += float(idf * (tf * (k1 + 1.0)) / (tf + k1 * (1.0 - b + b * dl / max(avgdl, 1e-9))))
        if score > 0:
            scores[item["chunk_id"]] = score
    return scores


def requirement_profile(question: dict[str, Any]) -> dict[str, Any]:
    text = str(question.get("question_text") or "").strip()
    species = str(question.get("species_chinese") or question.get("species_label_in_test_data") or "").strip()
    category = str(question.get("inferred_category") or question.get("topic") or "UNCLASSIFIED").strip()
    values = re.findall(r"\d+(?:\.\d+)?\s*(?:°\s*C|℃|%|ppm|ppb|公頃|公斤|尾|日|天|倍|mg/?kg|mg/?L)?", text, flags=re.I)
    wants_statistics = any(term in text for term in ("面積", "公頃", "統計", "調查", "養繁殖面積"))
    return {
        "question_id": question.get("question_id"),
        "target_species": species or None,
        "question_category": category,
        "required_answer_elements": "not_independently_verified; derived only from question text and existing category metadata",
        "required_values_or_ranges_in_question": values,
        "requires_numeric_evidence": bool(values) or any(x in text for x in ("範圍", "幾度", "多少", "比例", "濃度", "單位")),
        "requires_statistical_fact": wants_statistics,
        "source_version_requirements": "version must be fixed before use; no candidate answer treated as gold",
    }


def scope_filter(profile: dict[str, Any], chunk: dict[str, Any]) -> tuple[bool, str]:
    scope = chunk["species_scope"]
    kind = chunk["source_kind"]
    category = profile["question_category"]
    if kind == "dgbas_statistic":
        if category not in ("Fact", "事實", "UNCLASSIFIED"):
            return False, "DGBAS source is admitted for Fact only"
        if not profile["requires_statistical_fact"]:
            return False, "DGBAS area statistics do not answer non-statistical question requirements"
        target = profile["target_species"]
        if target and target not in chunk["content"]:
            return False, "native statistical label does not match target label; exact label only"
        return True, "native statistical category; not an exact biological species assertion"
    if kind == "official_statute":
        if category not in ("Medication / Law", "Medication/Law", "法規", "UNCLASSIFIED"):
            return False, "statute source limited to legal questions"
        return True, "general official statute; species-specific drug permissions not inferred"
    return False, f"unsupported source kind {kind}"


def rrf_rank(query: str, profile: dict[str, Any], chunks: list[dict[str, Any]], query_vector: np.ndarray, *, limit: int = 100) -> dict[str, Any]:
    allowed = []
    scope_notes = {}
    for chunk in chunks:
        ok, note = scope_filter(profile, chunk)
        if ok:
            allowed.append(chunk)
        else:
            scope_notes[chunk["chunk_id"]] = note
    if not allowed:
        return {"bm25": [], "dense": [], "rrf": [], "eligible_chunk_count": 0, "scope_excluded_count": len(scope_notes), "scope_excluded_reasons": dict(Counter(scope_notes.values()))}
    lexical = bm25_scores(query, allowed)
    bm25_sorted = sorted(lexical, key=lambda cid: (-lexical[cid], cid))[:100]
    matrix = np.stack([c["embedding"] for c in allowed], axis=0)
    dense_scores = matrix @ query_vector
    dense_order = np.argsort(-dense_scores, kind="stable")[:100]
    dense_sorted = [allowed[int(i)]["chunk_id"] for i in dense_order]
    bm25_rank = {cid: i + 1 for i, cid in enumerate(bm25_sorted)}
    dense_rank = {cid: i + 1 for i, cid in enumerate(dense_sorted)}
    by_id = {c["chunk_id"]: c for c in allowed}
    fused: dict[str, float] = {}
    for rank, cid in enumerate(bm25_sorted, 1):
        fused[cid] = fused.get(cid, 0.0) + 1.0 / (RRF_K + rank)
    for rank, cid in enumerate(dense_sorted, 1):
        fused[cid] = fused.get(cid, 0.0) + 1.0 / (RRF_K + rank)
    rrf_sorted = sorted(fused, key=lambda cid: (-fused[cid], cid))[:limit]
    def describe(ids):
        return [{"chunk_id": cid, "source_id": by_id[cid]["source_id"], "source_title": by_id[cid]["source_title"], "page": by_id[cid]["page"], "locator": by_id[cid]["locator"], "score": float(fused.get(cid, 0) if ids is rrf_sorted else (lexical.get(cid, 0) if ids is bm25_sorted else float(dense_scores[next(i for i,c in enumerate(allowed) if c['chunk_id']==cid)]))), "bm25_rank": bm25_rank.get(cid), "dense_rank": dense_rank.get(cid)} for cid in ids]
    return {"bm25": describe(bm25_sorted), "dense": describe(dense_sorted), "rrf": describe(rrf_sorted), "eligible_chunk_count": len(allowed), "scope_excluded_count": len(scope_notes), "scope_excluded_reasons": dict(Counter(scope_notes.values()))}


def rerank(candidates: list[dict[str, Any]], query: str) -> list[dict[str, Any]]:
    path = os.environ.get("PHASE_S_BGE_RERANKER_PATH")
    if not path or not Path(path).is_dir():
        raise RerankerUnavailable(f"{RERANKER_ID} local model snapshot not found; set PHASE_S_BGE_RERANKER_PATH to the verified local snapshot")
    # Reuse the repository's pinned local cross-encoder implementation without touching Production.
    sys_path = str(ROOT)
    if sys_path not in os.sys.path:
        os.sys.path.insert(0, sys_path)
    from src.evaluation.reranker_runtime import CrossEncoderRuntime
    runtime = CrossEncoderRuntime(path, device="cuda", max_length=512, batch_size=4)
    reranked = runtime.rerank(query, candidates)
    return reranked[:TOP_K]


def answer_json_schema() -> dict[str, Any]:
    return {
        "type": "object", "additionalProperties": False,
        "required": ["status", "answer", "citations", "insufficient_evidence_reason"],
        "properties": {
            "status": {"type": "string", "enum": ["answered", "insufficient_evidence"]},
            "answer": {"type": "string"},
            "citations": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                "required": ["chunk_id", "source_id", "page", "quote"],
                "properties": {"chunk_id": {"type": "string"}, "source_id": {"type": "string"}, "page": {"type": ["integer", "null"]}, "quote": {"type": "string"}}}},
            "insufficient_evidence_reason": {"type": ["string", "null"]},
        },
    }


def validate_answer(payload: dict[str, Any], top5: list[dict[str, Any]]) -> list[str]:
    errors = []
    schema = answer_json_schema()
    if set(payload) != set(schema["required"]):
        errors.append("top-level JSON keys do not match schema")
    allowed = {c["chunk_id"]: c for c in top5}
    if payload.get("status") == "insufficient_evidence" and payload.get("citations"):
        errors.append("abstention must not make unsupported citations")
    if payload.get("status") == "answered" and not payload.get("citations"):
        errors.append("answered status requires at least one citation")
    for i, cite in enumerate(payload.get("citations") or []):
        chunk = allowed.get(cite.get("chunk_id"))
        if not chunk:
            errors.append(f"citation {i} references a chunk outside final Top-5")
            continue
        if cite.get("source_id") != chunk.get("source_id") or cite.get("page") != chunk.get("page"):
            errors.append(f"citation {i} source/page mismatch")
        quote = cite.get("quote", "")
        if not quote or quote not in chunk.get("content", ""):
            errors.append(f"citation {i} quote is not an exact substring of cited chunk")
    return errors


def generate(model_tag: str, question: str, top5: list[dict[str, Any]], *, timeout: int = 360) -> dict[str, Any]:
    prompt = (
        "你是水產養殖知識助理。只可使用下列檢索證據回答；不得依常識補造。\n"
        "如沒有足以支持問題核心要求、數值、單位、條件或魚種適用性的證據，必須回覆 insufficient_evidence。\n"
        "引用只可選擇提供的 chunk，quote 必須是該 chunk 的逐字子字串。\n"
        "不得把統計分類解讀為精確生物物種，不得將一種魚的專屬數值外推到其他魚種。\n"
        "只輸出符合 JSON schema 的 JSON。\n\n"
        f"問題：{question}\n\n證據：\n" + "\n\n".join(f"[{c['chunk_id']}] source_id={c['source_id']} page={c['page']} {c['content']}" for c in top5)
    )
    start = time.perf_counter()
    response = requests.post(f"{OLLAMA}/api/chat", json={"model": model_tag, "stream": False, "format": answer_json_schema(),
        "messages": [{"role": "user", "content": prompt}], "options": {"temperature": 0, "top_p": 1, "seed": 15015, "num_predict": 768, "num_ctx": 8192}, "keep_alive": "0s"}, timeout=timeout)
    response.raise_for_status()
    elapsed = time.perf_counter() - start
    body = response.json()
    raw = body.get("message", {}).get("content", "")
    try:
        parsed = json.loads(raw)
        errors = validate_answer(parsed, top5)
    except Exception as e:
        parsed, errors = None, [f"JSON parse error: {e}"]
    return {"model_tag": model_tag, "raw_output": raw, "parsed_output": parsed, "validation_errors": errors, "elapsed_seconds": elapsed,
            "prompt_sha256": sha256_bytes(prompt.encode("utf-8")), "context_sha256": sha256_bytes("\n".join(c["content"] for c in top5).encode("utf-8"))}


class PhaseSRAG:
    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self.chunks = load_chunks(db_path)

    def retrieve(self, question: dict[str, Any], *, limit: int = 100) -> list[dict[str, Any]]:
        profile = requirement_profile(question)
        qtext = f"{profile['target_species'] or ''} {question.get('question_text','')}"
        vector = embed_texts([qtext])[0]
        stages = rrf_rank(qtext, profile, self.chunks, vector, limit=limit)
        candidates = [next(c for c in self.chunks if c["chunk_id"] == row["chunk_id"]) for row in stages["rrf"]]
        return rerank(candidates, qtext)

    def ask(self, question: dict[str, Any], model_tag: str) -> dict[str, Any]:
        try:
            top5 = self.retrieve(question, limit=100)
        except RerankerUnavailable as e:
            return {"status": "blocked", "reason": str(e), "question_id": question.get("question_id"), "generator_called": False}
        return generate(model_tag, str(question.get("question_text") or ""), top5)
