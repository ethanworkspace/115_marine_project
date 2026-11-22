from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import re
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import requests

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
DB_PATH = HERE / "research_fact_card_corpus_aa_v1.sqlite3"
MODEL_TABLE = {
    "M1": ("deepseek-r1:7b", "755ced02ce7befdb13b7ca74e1e4d08cddba4986afdb63a480f2c93d3140383f"),
    "M2": ("qwen2.5-coder:7b", "dae161e27b0e90dd1856c8bb3209201fd6736d8eb66298e75ed87571486f4364"),
    "M3": ("hf.co/bartowski/DeepSeek-R1-Distill-Llama-8B-GGUF:Q4_K_M", "aab87d0e8a585cc6260d3a448e3f66ff2057d1cd6975c834151deeb1eae94b42"),
    "M4": ("gemma2:9b", "ff02c3702f322b9e075e9568332d96c0a7028002f1a5a056e0a6784320a4db0b"),
}
EMBED_MODEL = "bge-m3:latest"
EMBED_DIGEST = "7907646426070047a77226ac3e684fbbe8410524f7b4a74d02837e43f2146bab"
RERANKER_PATH = ROOT / ".venv-reranker/hf-cache/hub/models--BAAI--bge-reranker-v2-m3/snapshots/953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e"
SCHEMA = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": ["answered", "abstain"]},
        "answer": {"type": "string"},
        "citations": {"type": "array", "items": {"type": "object", "properties": {"chunk_id": {"type": "string"}, "source_id": {"type": "string"}}, "required": ["chunk_id", "source_id"]}},
        "evidence_sufficiency": {"type": "string", "enum": ["sufficient", "partial", "insufficient"]},
        "abstention_reason": {"type": ["string", "null"]},
    },
    "required": ["status", "answer", "citations", "evidence_sufficiency", "abstention_reason"],
}


def _load_engine():
    path = HERE / "grounded_answer_engine_v2.py"
    spec = importlib.util.spec_from_file_location("phase_aa_grounded_engine", path)
    if not spec or not spec.loader:
        raise RuntimeError("grounded answer engine unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


ENGINE = _load_engine()
_reranker = None


def _tokenize(text: str) -> list[str]:
    text = text.lower()
    tokens = re.findall(r"[a-z0-9]+(?:[._/-][a-z0-9]+)*|[\u3400-\u9fff]", text)
    result: list[str] = []
    for token in tokens:
        if re.fullmatch(r"[\u3400-\u9fff]", token):
            result.append(token)
        elif any("\u3400" <= ch <= "\u9fff" for ch in token):
            compact = re.sub(r"\s+", "", token)
            result.extend(compact[i:i + 2] for i in range(max(1, len(compact) - 1)))
        else:
            result.append(token)
    # Also build CJK bigrams across adjacent Chinese characters.
    compact = re.sub(r"\s+", "", text)
    cjk_runs = re.findall(r"[\u3400-\u9fff]+", compact)
    for run in cjk_runs:
        result.extend(run[i:i + 2] for i in range(max(1, len(run) - 1)))
    return result


def _embed(text: str) -> np.ndarray:
    tags = requests.get("http://127.0.0.1:11434/api/tags", timeout=10).json().get("models", [])
    row = next((r for r in tags if r.get("name") == EMBED_MODEL), None)
    if not row or str(row.get("digest", "")).removeprefix("sha256:") != EMBED_DIGEST:
        raise RuntimeError("BGE-M3 model identity check failed")
    response = requests.post("http://127.0.0.1:11434/api/embed", json={"model": EMBED_MODEL, "input": [text], "truncate": True}, timeout=90)
    response.raise_for_status()
    vector = np.asarray(response.json()["embeddings"][0], dtype=np.float32)
    norm = float(np.linalg.norm(vector))
    if not norm or not np.isfinite(norm):
        raise RuntimeError("BGE-M3 produced an invalid vector")
    return vector / norm


def _load_reranker():
    global _reranker
    if _reranker is None:
        for site in (ROOT / ".venv-reranker/Lib/site-packages", ROOT / ".venv/Lib/site-packages"):
            if site.exists():
                sys.path.insert(0, str(site.resolve()))
        from src.evaluation.reranker_runtime import CrossEncoderRuntime
        _reranker = CrossEncoderRuntime(RERANKER_PATH, device="cpu", max_length=512, batch_size=4)
    return _reranker


def _species_labels(row: dict[str, Any]) -> set[str]:
    sid, text, scope = row["source_id"], row["text"], row["species_scope"]
    labels = {x.strip() for x in str(scope).split("|") if x.strip()}
    if sid == "TFRI-M17-GOLD-SEABASS":
        labels = {"金目鱸"}
    elif sid == "TFRI-M17-SEVENSTAR":
        labels = {"七星鱸"}
    elif sid == "TFRI-M17-MULLET":
        labels = {"烏魚"}
    elif sid == "TFRI-EEL-MOLD-2006" or sid.startswith("TFRI-EEL-"):
        labels = {"鰻魚"}
    elif sid == "TFRI-EEL-HEALTH-SPECIAL-8-2006":
        labels = {"鰻魚"}
    elif sid == "TFRI-M17-GROUPER":
        labels = {"鞍帶石斑", "石斑魚"} if "鞍帶石斑" in text else {"石斑魚（手冊界定群組）"}
    return labels


def _scope_ok(row: dict[str, Any], target_species: str) -> tuple[bool, str]:
    labels = _species_labels(row)
    if target_species in labels:
        return True, "EXACT_OR_SOURCE_DEFINED_SCOPE_MATCH"
    if "general_aquaculture" in labels or "general_regulation" in labels:
        return True, "EXPLICIT_GENERAL_SCOPE_CARD"
    return False, "SPECIES_SCOPE_NOT_VERIFIED_FOR_TARGET"


def _bm25(rows: list[dict[str, Any]], query: str, k1: float = 1.5, b: float = 0.75) -> list[dict[str, Any]]:
    docs = [_tokenize(row["text"]) for row in rows]
    qterms = set(_tokenize(query))
    n = len(docs)
    avgdl = sum(map(len, docs)) / max(1, n)
    df: dict[str, int] = {}
    for term in qterms:
        df[term] = sum(1 for doc in docs if term in doc)
    out = []
    for row, doc in zip(rows, docs, strict=True):
        freqs: dict[str, int] = {}
        for term in doc:
            if term in qterms:
                freqs[term] = freqs.get(term, 0) + 1
        score = 0.0
        for term, tf in freqs.items():
            idf = math.log(1 + (n - df.get(term, 0) + 0.5) / (df.get(term, 0) + 0.5))
            score += idf * (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * len(doc) / max(avgdl, 1e-9)))
        if score > 0:
            out.append({**row, "bm25_score": score})
    return sorted(out, key=lambda x: (-x["bm25_score"], x["chunk_id"]))


def _rows() -> list[dict[str, Any]]:
    import sqlite3
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        result = []
        for raw in con.execute("SELECT * FROM cards WHERE retrieval_eligible=1 ORDER BY chunk_id"):
            row = dict(raw)
            row["embedding_array"] = np.frombuffer(row.pop("embedding"), dtype=np.float32)
            result.append(row)
        return result
    finally:
        con.close()


def retrieve(question: str, target_species: str, top_k: int = 5) -> dict[str, Any]:
    rows = _rows()
    bm_rows = _bm25(rows, question, k1=1.5, b=0.75)
    bm_top = bm_rows[:min(12, len(bm_rows))]
    query_vector = _embed(question)
    dense_rows = []
    for row in rows:
        dense_rows.append({**row, "dense_score": float(np.dot(query_vector, row["embedding_array"]))})
    dense_rows.sort(key=lambda x: (-x["dense_score"], x["chunk_id"]))
    dense_top = dense_rows[:min(12, len(dense_rows))]
    byid = {r["chunk_id"]: r for r in rows}
    fusion: dict[str, float] = {}
    for rank, row in enumerate(bm_top, 1):
        fusion[row["chunk_id"]] = fusion.get(row["chunk_id"], 0.0) + 1 / (60 + rank)
    for rank, row in enumerate(dense_top, 1):
        fusion[row["chunk_id"]] = fusion.get(row["chunk_id"], 0.0) + 1 / (60 + rank)
    fused = sorted(({**byid[cid], "rrf_score": score} for cid, score in fusion.items()), key=lambda x: (-x["rrf_score"], x["chunk_id"]))
    eligible = []
    scope_excluded = []
    for row in fused:
        ok, reason = _scope_ok(row, target_species)
        if ok:
            row["species_scope_gate"] = {"eligible": True, "reason": reason, "labels": sorted(_species_labels(row))}
            eligible.append(row)
        else:
            scope_excluded.append({"chunk_id": row["chunk_id"], "source_id": row["source_id"], "reason": reason, "labels": sorted(_species_labels(row))})
    rerank_in = [{"chunk_id": row["chunk_id"], "text": row["text"], "rank": i, **{k: v for k, v in row.items() if k != "embedding_array"}} for i, row in enumerate(eligible, 1)]
    if rerank_in:
        reranked = _load_reranker().rerank(question, rerank_in)
    else:
        reranked = []
    top = reranked[:max(0, min(top_k, len(reranked)))]
    top_clean = []
    for rank, row in enumerate(top, 1):
        top_clean.append({
            "chunk_id": row["chunk_id"], "source_id": row["source_id"], "rank": rank,
            "text": row["text"], "content_sha256": row["content_sha256"], "source_sha256": row["source_sha256"],
            "source_version": row["source_version"], "locator": row["locator"], "species_scope": sorted(_species_labels(row)),
            "category_scope": json.loads(row["category_scope"]), "source_cluster_id": row["source_cluster_id"],
            "bm25_score": row.get("bm25_score"), "dense_score": row.get("dense_score"), "rrf_score": row.get("rrf_score"),
            "reranker_score": row.get("reranker_score"), "reranker_rank": row.get("reranker_rank"),
            "context_sha256": hashlib.sha256(row["text"].encode("utf-8")).hexdigest(),
            "retrieval_eligible": True, "formal_corpus_admission": False,
        })
    return {
        "question": question, "target_species": target_species,
        "corpus_id": "research_fact_card_corpus_aa_v1", "database_sha256": hashlib.sha256(DB_PATH.read_bytes()).hexdigest(),
        "retrieval_config": {"bm25": "BM25Okapi-style over character bigrams/Latin tokens; k1=1.5,b=0.75", "dense_model": EMBED_MODEL, "dense_digest": EMBED_DIGEST, "dense_normalized_l2": True, "rrf_k": 60, "reranker": "BAAI/bge-reranker-v2-m3", "top_k_requested": top_k},
        "candidate_counts": {"eligible_source_cards": len(rows), "bm25_raw": len(bm_rows), "bm25_top": len(bm_top), "dense_raw": len(dense_rows), "dense_top": len(dense_top), "rrf_fused": len(fused), "species_scope_pass": len(eligible), "species_scope_excluded": len(scope_excluded), "reranker_candidates": len(reranked), "final_top_k": len(top_clean)},
        "bm25_candidates": [{"chunk_id": r["chunk_id"], "score": r["bm25_score"]} for r in bm_top],
        "dense_candidates": [{"chunk_id": r["chunk_id"], "score": r["dense_score"]} for r in dense_top],
        "rrf_candidates": [{"chunk_id": r["chunk_id"], "rrf_score": r["rrf_score"]} for r in fused],
        "scope_excluded": scope_excluded,
        "reranked_top": top_clean,
    }


def spans_from_retrieval(result: dict[str, Any]):
    from grounded_answer_engine_v2 import EvidenceSpan
    spans = []
    for row in result["reranked_top"]:
        quote = ""
        source_page_text = ""
        start = end = 0
        import sqlite3
        con = sqlite3.connect(DB_PATH)
        try:
            data = con.execute("SELECT source_quote, source_path, source_page, quote_start, quote_end, scientific_scope, taxonomy_level, processing_scope FROM cards WHERE chunk_id=?", (row["chunk_id"],)).fetchone()
        finally:
            con.close()
        if not data:
            continue
        quote, source_path, page_no, source_start, source_end, scientific_scope, taxonomy, processing = data
        # Only the short locator quote is passed to the answer engine; the full
        # source page remains outside the index and prompt.
        source_page_text = quote
        scope = tuple(row["species_scope"])
        exact = result["target_species"] in scope
        app_status = "VERIFIED_EXACT" if exact else "VERIFIED_GENERAL" if any(x in scope for x in ("general_aquaculture", "general_regulation")) else "UNKNOWN"
        cross_basis = "Source card explicitly declares this general scope." if app_status == "VERIFIED_GENERAL" else None
        span = EvidenceSpan(
            span_id="span-" + row["chunk_id"], chunk_id=row["chunk_id"], source_id=row["source_id"],
            source_version=row["source_version"], source_sha256=row["source_sha256"], expected_source_sha256=row["source_sha256"],
            locator=row["locator"], quote=quote, source_page_text=source_page_text, start_char=0, end_char=len(quote),
            fact_card_text=row["text"], species_scope=scope, applicability_status=app_status, cross_species_basis=cross_basis,
            processing_scope="RESEARCH_FACT_CARD_NONPUBLIC" if "RESEARCH_FACT_CARD" in processing else processing,
            retrieval_eligible=True, formally_admitted_to_evaluation_corpus=False,
        )
        spans.append(span)
    return spans


def check_model_identity(model_id: str) -> dict[str, str]:
    expected_tag, expected_digest = MODEL_TABLE[model_id]
    rows = requests.get("http://127.0.0.1:11434/api/tags", timeout=10).json().get("models", [])
    row = next((r for r in rows if r.get("name") == expected_tag), None)
    if not row:
        raise RuntimeError(f"model missing: {model_id}/{expected_tag}")
    digest = str(row.get("digest", "")).removeprefix("sha256:")
    if digest != expected_digest:
        raise RuntimeError(f"digest mismatch for {model_id}: {digest}")
    return {"model_id": model_id, "model_tag": expected_tag, "digest": digest}


def species_filter_spans(profile: dict[str, Any], spans):
    target = str(profile.get("target_species") or "")
    eligible = []
    excluded = []
    for span in spans:
        scope = set(span.species_scope)
        exact = target in scope
        declared_general = span.applicability_status in {"VERIFIED_GROUP", "VERIFIED_GENERAL"} and bool(span.cross_species_basis)
        if exact or declared_general:
            eligible.append(span)
        else:
            excluded.append({"span_id": span.span_id, "source_id": span.source_id, "species_scope": sorted(scope), "reason": "TARGET_SPECIES_NOT_SUPPORTED_BY_REQUIRED_SOURCE_SCOPE"})
    return eligible, excluded


def run_generator(profile: dict[str, Any], spans, model_id: str, case_id: str, retrieval_trace: dict[str, Any]) -> dict[str, Any]:
    identity = check_model_identity(model_id)
    spans, excluded_spans = species_filter_spans(profile, spans)
    decision = ENGINE.assess_evidence(profile, spans)
    base = {"test_id": case_id, "question_id": profile.get("question_id", case_id), "model_id": model_id, **identity,
            "question": profile.get("question_text"), "target_species": profile.get("target_species"),
            "corpus_id": "research_fact_card_corpus_aa_v1", "formal_corpus": False, "evidence_decision": decision,
            "generator_called": False, "raw_model_response": None, "final_response": None, "answer_origin": None,
            "retrieval_trace": retrieval_trace, "species_scope_excluded_before_prompt": excluded_spans,
            "human_gold": False, "evaluation_status": "ISOLATED_E2E_SMOKE_NOT_FULL_EVALUATION"}
    if decision.get("state") != "EVIDENCE_SUFFICIENT":
        final = {"status": "abstain", "answer": "目前沒有足以支持此回答的合格研究證據。", "citations": [], "evidence_sufficiency": decision.get("state"), "abstention_reason": decision.get("reason")}
        return {**base, "answer_origin": "ABSTAINED", "final_response": final, "abstention_reason": decision.get("reason"), "system_action": "GENERATOR_NOT_CALLED_EVIDENCE_GATE"}
    messages = ENGINE.make_model_prompt(profile, spans, decision)
    started = time.perf_counter()
    response = requests.post("http://127.0.0.1:11434/api/chat", json={
        "model": identity["model_tag"], "messages": messages, "format": SCHEMA, "think": False, "stream": False,
        "options": {"temperature": 0, "seed": 42, "num_predict": 384}, "keep_alive": "0",
    }, timeout=600)
    response.raise_for_status()
    payload = response.json()
    raw = (payload.get("message") or {}).get("content") or ""
    allowed = {(s.chunk_id, s.source_id) for s in spans}
    finished = ENGINE.finish_model_answer(profile, spans, raw, decision, allowed)
    elapsed = time.perf_counter() - started
    return {**base, "generator_called": True, "prompt": messages,
            "prompt_sha256": hashlib.sha256(json.dumps(messages, ensure_ascii=False, sort_keys=True).encode()).hexdigest(),
            "raw_model_response": raw, "answer_origin": finished.get("answer_origin"), "final_response": finished.get("final_response"),
            "support_validation": finished.get("support_validation"), "abstention_reason": finished.get("abstention_reason"),
            "generator_timing": {"wall_seconds": elapsed, "eval_count": payload.get("eval_count"), "eval_duration_ns": payload.get("eval_duration"),
                                 "tps": payload.get("eval_count") / (payload.get("eval_duration") / 1e9) if payload.get("eval_count") and payload.get("eval_duration") else None,
                                 "total_duration_ns": payload.get("total_duration"), "prompt_eval_count": payload.get("prompt_eval_count")},
            "system_action": "MODEL_OUTPUT_VALIDATED_WITH_EVIDENCE_GATE"}


def profile_for_case(case: dict[str, Any], spans) -> dict[str, Any]:
    card_id = case.get("source_card_chunk_id")
    linked_span = "span-" + card_id if card_id else None
    elements = []
    for e in case.get("required_answer_elements", []):
        elements.append({**e, "evidence_span_ids": [linked_span] if linked_span else []})
    return {
        "question_id": case.get("question_id"), "question_text": case.get("question_text"), "target_species": case.get("target_species"),
        "category": case.get("category"), "risk_class": case.get("risk_class", "LOW_RISK_FACT"),
        "species_applicability": case.get("species_applicability") or {"status": "UNKNOWN"},
        "required_answer_elements": elements,
        "high_risk_authority_verified": False,
    }


def render_answer(result: dict[str, Any]) -> str:
    if result.get("answer_origin") == "MODEL_GENERATED":
        final = result.get("final_response") or {}
        return str(final.get("answer") or "")
    return ""
