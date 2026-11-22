from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import sys
import time
from collections import Counter
from pathlib import Path

# Reuse only the project's existing isolated runtimes: CPU/data packages from
# .venv and the already-verified GPU reranker stack from .venv-reranker.
ROOT = Path.cwd()
sys.path.insert(0, str(ROOT / ".venv/Lib/site-packages"))
sys.path.insert(0, str(ROOT / ".venv-reranker/Lib/site-packages"))
import numpy as np
import requests

OUT = ROOT / "reports/evaluation/fish_test_phase_u_20261018_195823"
CORPUS = OUT / "corpus_v3_final"
CHUNK_FILE = CORPUS / "corpus_chunks_v3_final.jsonl"
MANIFEST_FILE = CORPUS / "corpus_v3_manifest.json"
VECTOR_FILE = CORPUS / "dense_vectors_final.f32"
DB_FILE = CORPUS / "corpus_v3_final.sqlite3"
QUESTION_FILE = ROOT / "reports/evaluation/fish_test_run_20261012_152244/fish_test_questions_normalized.jsonl"
OLLAMA = "http://127.0.0.1:11434"
BGE = "bge-m3:latest"
BGE_DIGEST = "7907646426070047a77226ac3e684fbbe8410524f7b4a74d02837e43f2146bab"
SNAPSHOT = ROOT / ".venv-reranker/hf-cache/hub/models--BAAI--bge-reranker-v2-m3/snapshots/953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e"


def sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def read_jsonl(path: Path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]


def write_json(path: Path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows):
    path.write_text("".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in rows), encoding="utf-8")


TOKEN_RE = re.compile(r"[a-z0-9]+(?:[./_%+\-][a-z0-9]+)*|[\u3400-\u9fff]+", re.I)


def tokenize(text: str) -> list[str]:
    tokens = []
    for match in TOKEN_RE.finditer(text.casefold()):
        token = match.group(0)
        if re.fullmatch(r"[\u3400-\u9fff]+", token):
            tokens.extend([token] if len(token) == 1 else [token[i : i + 2] for i in range(len(token) - 1)])
        else:
            tokens.append(token)
    return tokens


def classify_intent(q: dict) -> dict:
    text = str(q.get("question_text") or "")
    category = str(q.get("inferred_category") or q.get("topic") or "UNCLASSIFIED")
    tax_terms = ("學名", "魚種代碼", "物種代碼", "英文名", "分類代碼", "魚名代碼", "學術名稱")
    stat_terms = ("資料集", "統計資料", "統計數據", "統計數值", "漁業生產量", "養殖產量", "養繁殖面積", "產量是多少", "產值是多少", "調查資料", "依統計")
    production_terms = ("產量", "漁獲量", "產值", "生產量", "產銷", "收穫量")
    stocking_terms = ("放養量統計", "放養調查", "放養魚塭口數", "在池數量")
    if category in ("Medication / Law", "Medication/Law", "法規"):
        intent = "general_legal_requirements"
        allowed = ["MOA-FL014718-ACT"]
    elif any(term in text for term in tax_terms):
        intent = "taxonomy_label_lookup"
        allowed = ["MOA-FISH-SPECIES-CODE-134250"]
    elif any(term in text for term in stocking_terms):
        intent = "stocking_statistics"
        allowed = []  # Dataset lacks a verified reference year; value rows remain context-only.
    elif any(term in text for term in stat_terms) and any(term in text for term in production_terms):
        intent = "fishery_production_statistics"
        allowed = ["MOA-FISHERY-PRODUCTION-44084"]
    elif any(term in text for term in stat_terms) and any(term in text for term in ("面積", "公頃", "主要養殖生物種類")):
        intent = "aquaculture_area_statistics"
        allowed = ["DGBAS-79395-2015", "DGBAS-79395-2020"]
    elif any(term in text for term in stat_terms):
        intent = "official_statistics_unspecified"
        allowed = ["MOA-FISHERY-PRODUCTION-44084", "DGBAS-79395-2015", "DGBAS-79395-2020"]
    else:
        intent = "aquaculture_technical_or_other"
        allowed = []
    if category in ("Water Quality", "Disease", "Climate / Cold", "Calculation"):
        allowed = []
    # Scope is deliberately determined only by the actual question and dataset's approved use.
    return {
        "question_id": q["question_id"],
        "target_species": q.get("species_chinese"),
        "question_category": category,
        "intent": intent,
        "required_answer_elements": "machine-extracted only from question text; not independently validated as gold rubric",
        "required_values_or_ranges": re.findall(r"\d+(?:\.\d+)?\s*(?:°\s*C|℃|%|ppt|ppm|ppb|公頃|公斤|尾|日|天|mg/?kg|mg/?L)?", text, flags=re.I),
        "requires_numeric_evidence": bool(re.search(r"\d|範圍|幾度|多少|比例|濃度|單位", text)),
        "species_scope_constraint": "Exact species-specific unless source supports a broader scope; statistical fish labels are not biological applicability",
        "law_version_constraint": "not applicable" if category != "Medication / Law" else "requires current applicable legal source and version",
        "allowed_source_ids_for_search": allowed,
        "profile_basis": "question text and existing fish-test metadata only; no generated answer, candidate answer, or scoring rubric used",
    }


def query_vectors(queries: list[str]) -> np.ndarray:
    batches = []
    for start in range(0, len(queries), 24):
        batch = queries[start : start + 24]
        r = requests.post(f"{OLLAMA}/api/embed", json={"model": BGE, "input": batch, "truncate": False, "keep_alive": "30m"}, timeout=180)
        r.raise_for_status()
        a = np.asarray(r.json()["embeddings"], dtype=np.float32)
        if a.shape != (len(batch), 1024) or not np.isfinite(a).all():
            raise RuntimeError(f"BGE query vectors invalid: {a.shape}")
        norms = np.linalg.norm(a, axis=1, keepdims=True)
        if np.any(norms <= 0):
            raise RuntimeError("zero norm BGE query vector")
        batches.append(a / norms)
    return np.vstack(batches)


def bm25_search(con: sqlite3.Connection, allowed_ids: list[str], query: str, top_k: int = 100) -> list[dict]:
    terms = tokenize(query)
    if not allowed_ids or not terms:
        return []
    match = " OR ".join('"' + term.replace('"', '""') + '"' for term in dict.fromkeys(terms))
    marks = ",".join("?" for _ in allowed_ids)
    sql = f"""SELECT c.chunk_id, bm25(chunks_fts) AS bm25_score
        FROM chunks_fts JOIN chunks c ON c.chunk_id=chunks_fts.chunk_id
        WHERE chunks_fts MATCH ? AND c.retrieval_eligible=1 AND c.source_id IN ({marks})
        ORDER BY bm25_score ASC, c.chunk_id ASC LIMIT ?"""
    try:
        rows = con.execute(sql, [match, *allowed_ids, top_k]).fetchall()
    except sqlite3.OperationalError:
        return []
    return [{"chunk_id": r[0], "score": float(r[1])} for r in rows]


def main():
    manifest = read_json(MANIFEST_FILE)
    if manifest.get("embedding_index", {}).get("status") != "BUILT":
        raise RuntimeError("Corpus manifest does not record built dense vectors")
    embedding_meta = manifest["embedding_index"]
    if embedding_meta.get("model_digest") != BGE_DIGEST:
        raise RuntimeError("dense embedding model digest mismatch")
    chunks = read_jsonl(CHUNK_FILE)
    eligible = [c for c in chunks if c["retrieval_eligible"]]
    dim = manifest["embedding_index"]["dimensions"]
    vectors = np.memmap(VECTOR_FILE, dtype=np.float32, mode="r", shape=(len(eligible), dim))
    if len(eligible) != manifest["retrieval_eligible_chunk_count"] or vectors.shape != (len(eligible), dim):
        raise RuntimeError("dense matrix alignment/count mismatch")
    ids = [c["chunk_id"] for c in eligible]
    if len(ids) != len(set(ids)):
        raise RuntimeError("duplicate chunk IDs")
    order_digest = sha_bytes("\n".join(ids).encode("utf-8"))
    if order_digest != embedding_meta.get("matrix_order_ids_sha256"):
        raise RuntimeError("dense vector row order does not match the corpus manifest")
    if sha_file(VECTOR_FILE) != embedding_meta.get("vector_file_sha256"):
        raise RuntimeError("dense vector checksum does not match the corpus manifest")
    if sha_file(CHUNK_FILE) != manifest.get("chunk_jsonl_sha256"):
        raise RuntimeError("chunk JSONL checksum does not match the corpus manifest")
    by_id = {c["chunk_id"]: c for c in eligible}
    qrows = read_jsonl(QUESTION_FILE)
    if len(qrows) != 180 or len({q["question_id"] for q in qrows}) != 180:
        raise RuntimeError("Expected 180 unique questions")
    profiles = [classify_intent(q) for q in qrows]
    # The complete index is retained, but only source classes allowed for the query are eligible for its final answer context.
    source_ids_by_profile = [set(p["allowed_source_ids_for_search"]) for p in profiles]
    query_texts = [f"{p['target_species'] or ''} {q['question_text']}".strip() for q, p in zip(qrows, profiles, strict=True)]
    qvecs = query_vectors(query_texts)
    if qvecs.shape != (180, 1024):
        raise RuntimeError("query embedding alignment mismatch")
    import requests as _requests
    tags = _requests.get(f"{OLLAMA}/api/tags", timeout=8).json().get("models", [])
    bge_matches = [m for m in tags if m.get("name") == BGE]
    if not bge_matches or bge_matches[0].get("digest", "").removeprefix("sha256:") != BGE_DIGEST:
        raise RuntimeError("BGE-M3 runtime identity changed during retrieval")

    sys.path.insert(0, str(ROOT / ".venv/Lib/site-packages"))
    sys.path.insert(0, str(ROOT))
    from src.evaluation.reranker_runtime import CrossEncoderRuntime

    reranker = CrossEncoderRuntime(SNAPSHOT, device="cuda", max_length=512, batch_size=4)
    con = sqlite3.connect(DB_FILE)
    con.row_factory = None
    results = []
    out_retrieval = OUT / "retrieval_results_v3_final.jsonl"
    for i, (q, profile, query, qvec, allowed_ids) in enumerate(zip(qrows, profiles, query_texts, qvecs, source_ids_by_profile, strict=True), 1):
        allowed = [c for c in eligible if c["source_id"] in allowed_ids]
        bm = bm25_search(con, list(allowed_ids), query)
        bm_rank = {row["chunk_id"]: rank for rank, row in enumerate(bm, 1)}
        if allowed:
            local_indices = np.fromiter((j for j, c in enumerate(eligible) if c["source_id"] in allowed_ids), dtype=np.int32)
            dense_scores = vectors[local_indices] @ qvec
            order = np.argsort(-dense_scores, kind="stable")[: min(100, len(local_indices))]
            dense = [{"chunk_id": eligible[int(local_indices[int(j)])]["chunk_id"], "score": float(dense_scores[int(j)])} for j in order]
        else:
            dense = []
        dense_rank = {row["chunk_id"]: rank for rank, row in enumerate(dense, 1)}
        fused = {}
        for rank, row in enumerate(bm, 1): fused[row["chunk_id"]] = fused.get(row["chunk_id"], 0.0) + 1.0 / (60 + rank)
        for rank, row in enumerate(dense, 1): fused[row["chunk_id"]] = fused.get(row["chunk_id"], 0.0) + 1.0 / (60 + rank)
        rrf_ids = sorted(fused, key=lambda cid: (-fused[cid], cid))[:100]
        candidates = []
        for rr, cid in enumerate(rrf_ids, 1):
            c = by_id[cid]
            candidates.append({"chunk_id": cid, "text": c["text"], "rank": rr, "source_id": c["source_id"], "rrf_score": fused[cid], "bm25_rank": bm_rank.get(cid), "dense_rank": dense_rank.get(cid)})
        reranked = reranker.rerank(query, candidates) if candidates else []
        top5 = []
        for rank, c in enumerate(reranked[:5], 1):
            raw = by_id[c["chunk_id"]]
            text = raw["text"]
            top5.append({
                "chunk_id": c["chunk_id"], "rank": rank, "source_id": raw["source_id"],
                "source_title": raw["source_title"], "source_url": raw["source_url"],
                "source_sha256": raw["source_sha256"], "source_version": raw["source_version"],
                "page": raw.get("page"), "locator": raw.get("locator"), "record_locator": raw["record_locator"],
                "content": text, "content_sha256": sha_bytes(text.encode("utf-8")),
                "retrieval_eligible": True, "source_category_scope": raw["category_scope"],
                "source_species_scope": raw["species_scope"], "rrf_rank": c["rank"],
                "rrf_score": c["rrf_score"], "reranker_rank": c["reranker_rank"], "reranker_score": c["reranker_score"],
                "bm25_rank": bm_rank.get(c["chunk_id"]), "dense_rank": dense_rank.get(c["chunk_id"]),
            })
        status = "reranked_top5_complete" if len(top5) == 5 else ("no_applicable_retrieval_eligible_source" if not allowed else "fewer_than_five_candidates")
        row = {
            "question_id": q["question_id"], "species": q.get("species_chinese"), "category": profile["question_category"],
            "question_text": q["question_text"], "question_requirement_profile": profile,
            "query": query, "query_excludes_candidate_answer_and_rubric": True,
            "run_id": OUT.name, "corpus_version": manifest["corpus_version"], "corpus_manifest_sha256": sha_file(MANIFEST_FILE),
            "corpus_chunks_sha256": manifest["chunk_jsonl_sha256"], "dense_vector_sha256": manifest["embedding_index"]["vector_file_sha256"],
            "retrieval_config": {"bm25": "SQLite FTS5, bigram tokenizer", "dense_model": BGE, "dense_digest": BGE_DIGEST, "dense_dim": 1024, "rrf_k": 60, "reranker": "BAAI/bge-reranker-v2-m3", "reranker_revision": SNAPSHOT.name, "top_k": 5},
            "scope_allowed_source_ids": sorted(allowed_ids), "applicability_filter_applied_before_retrieval": True,
            "scope_eligible_chunk_count": len(allowed), "bm25_top100": bm, "dense_top100": dense,
            "rrf_candidates_top100": [{"chunk_id": cid, "rrf_rank": r, "rrf_score": fused[cid], "bm25_rank": bm_rank.get(cid), "dense_rank": dense_rank.get(cid)} for r, cid in enumerate(rrf_ids, 1)],
            "reranked_top5": top5, "final_top5_count": len(top5), "retrieval_status": status,
            "answer_support_sufficiency": "not_evaluated; source retrieval is not answer verification",
            "benchmark_eligible_v3": False,
            "eligibility_note": "Retrieval outcome is separate from eligibility; corpus coverage may not satisfy exact answer requirements and answers/rubrics have not been independently verified.",
        }
        results.append(row)
        if i % 20 == 0:
            write_jsonl(out_retrieval, results)
            print(json.dumps({"completed": i, "total": 180, "top5": sum(x["final_top5_count"] == 5 for x in results)}, ensure_ascii=True), flush=True)
    con.close()
    write_jsonl(out_retrieval, results)

    eligibility = []
    for q, p, r in zip(qrows, profiles, results, strict=True):
        original = {"candidate_reference_answer_present": bool(q.get("candidate_reference_answer")), "candidate_source_urls": q.get("candidate_source_urls") or [], "source_ids_from_question_registry": q.get("source_ids") or []}
        matching = []
        for chunk in r["reranked_top5"]:
            sid = chunk["source_id"]
            if sid in p["allowed_source_ids_for_search"]:
                matching.append(chunk["chunk_id"])
        fail = []
        if not p["allowed_source_ids_for_search"]:
            fail.append("no_source_in_isolated_v3_corpus_with_approved_scope_for_question_intent")
        if not original["candidate_reference_answer_present"]:
            fail.append("candidate_reference_answer_missing")
        # Even if a retrieval candidate exists, these source classes are not presumed to prove a reference answer.
        fail.append("reference_answer_and_required_elements_not_independently_verified")
        # Human Gold is tracked independently; it is not a Gate v2 eligibility requirement.
        eligibility.append({
            "question_id": q["question_id"], "question_text": q["question_text"], "species": q.get("species_chinese"),
            "category": p["question_category"], "question_text_valid": bool(q.get("question_text")),
            "requirement_profile": p, "answer_verified": False, "species_applicability_verified": False,
            "category_applicability_verified": False, "authoritative_evidence_verified": False,
            "source_version_verified": False, "source_rights_suitable_for_intended_evaluation": False,
            "evidence_in_designated_corpus_v3": False,
            "candidate_source_chunk_found_in_designated_corpus_v3": bool(matching),
            "evidence_retrieval_eligible": bool(matching),
            "candidate_matching_chunk_ids": matching, "sufficient_corpus_support_span": False,
            "benchmark_eligible_v3": False, "gate_status": "blocked",
            "failed_gate_reasons": fail, "retrieval_outcome": r["retrieval_status"],
            "retrieval_top5_is_not_eligibility_gate": True, "human_gold_reviewed": False,
            "human_gold_is_separate_from_gate": True,
            "historical_gate_status": "unchanged; no inheritance from Corpus v2 or older reports",
            "source_registry_provenance": original,
        })
    write_jsonl(OUT / "question_eligibility_v3.jsonl", eligibility)
    summary = {
        "question_count": len(qrows), "unique_question_ids": len({q["question_id"] for q in qrows}),
        "intent_counts": dict(Counter(p["intent"] for p in profiles)),
        "category_counts": dict(Counter(p["question_category"] for p in profiles)),
        "retrieval_status_counts": dict(Counter(r["retrieval_status"] for r in results)),
        "reranked_top5_total": sum(r["final_top5_count"] for r in results),
        "benchmark_eligible_v3_count": sum(r["benchmark_eligible_v3"] for r in results),
        "note": "No reference answer, rubric, Generator answer, or Phase E metric was used in query construction or retrieval labeling.",
        "reranker_runtime": reranker.load_info.__dict__,
        "reranker_smoke_retrievals": 180,
        "new_generator_calls": 0,
    }
    write_json(OUT / "retrieval_run_summary.json", summary)
    print(json.dumps(summary, ensure_ascii=True, default=str))


if __name__ == "__main__":
    main()
