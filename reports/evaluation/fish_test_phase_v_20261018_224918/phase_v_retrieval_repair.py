from __future__ import annotations

import importlib.util
import json
import pathlib
import sqlite3
import sys
from collections import Counter

import numpy as np
import requests

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[2]
BUILDER_PATH = HERE / "phase_v_build_and_retrieval.py"
spec = importlib.util.spec_from_file_location("phase_v_builder", BUILDER_PATH)
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


def read_jsonl(p):
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]


def write_jsonl(p, rows):
    p.write_text("".join(json.dumps(r, ensure_ascii=False, separators=(",", ":")) + "\n" for r in rows), encoding="utf-8")


def load_scope(q, m):
    target = q.get("species_chinese", "")
    text = q.get("question_text", "")
    meta = json.loads(m.get("metadata_json") or "{}")
    sid = m["source_id"]
    scope = str(meta.get("species_scope", ""))
    taxonomy = str(meta.get("species_taxonomy", ""))
    # Scope rules are fail-closed for species-specific numeric husbandry facts.
    if sid == "MOA-FL014718-ACT":
        return (q.get("inferred_category") in {"Medication / Law", "Medication/Law", "Law"}, "GENERAL_REGULATION" if q.get("inferred_category") in {"Medication / Law", "Medication/Law", "Law"} else "CATEGORY_MISMATCH")
    if sid.startswith("DGBAS-") or sid.startswith("MOA-FISH-") or sid.startswith("WRA-") or sid.startswith("FA-STOCKING"):
        if any(k in text for k in ["統計", "資料集", "產量", "產值", "放養調查", "原始分類"]):
            return True, "STATISTICAL_LABEL_ONLY"
        return False, "STATISTICAL_DATA_NOT_SPECIES_TECHNICAL_EVIDENCE"
    if "general_aquaculture" in scope:
        if target in scope:
            return True, "EXPLICIT_MULTI_SPECIES_SCOPE"
        return False, "GENERAL_SCOPE_NOT_AUTO_EXTENDED"
    if target == "鱸魚":
        if "金目鱸" in text:
            ok = "Lates calcarifer" in taxonomy
            return ok, "EXACT_GOLD_SEABASS" if ok else "SPECIES_SCOPE_UNKNOWN_OR_MISMATCH"
        if "七星鱸" in text:
            ok = "Lateolabrax japonicus" in taxonomy
            return ok, "EXACT_SEVENSTAR_SEABASS" if ok else "SPECIES_SCOPE_UNKNOWN_OR_MISMATCH"
        return False, "GENERIC_SEABASS_UNRESOLVED"
    if sid == "TFRI-EEL-MOLD-2006":
        if target != "鰻魚" or not any(k in text for k in ["2006", "歷史", "特刊", "水黴", "黴菌", "病原", "診斷"]):
            return False, "HISTORICAL_EEL_SOURCE_ONLY"
        return True, "HISTORICAL_EEL_SOURCE_EXPLICITLY_REQUESTED"
    if "SPECIFIC: Epinephelus lanceolatus" in taxonomy:
        ok = target == "石斑魚" and any(k in text for k in ["鞍帶石斑", "龍膽", "Epinephelus lanceolatus"])
        return ok, "EXACT_GIANT_GROUPER_SCOPE" if ok else "SPECIES_SPECIFIC_SCOPE_NOT_MATCHED"
    if "GROUP" in taxonomy:
        ok = target == "石斑魚" and not any(k in text for k in ["鞍帶石斑", "龍膽", "Epinephelus lanceolatus"])
        return ok, "MANUAL_DEFINED_GROUP_SCOPE" if ok else "GROUP_SCOPE_NOT_MATCHED"
    if target in scope:
        return True, "EXACT_SPECIES_SCOPE"
    return False, "SPECIES_SCOPE_UNKNOWN_OR_MISMATCH"


def main():
    sys.path.insert(0, str(ROOT / ".venv-reranker/Lib/site-packages"))
    sys.path.insert(0, str(ROOT / ".venv/Lib/site-packages"))
    sys.path.insert(0, str(ROOT))
    import torch
    from src.evaluation.reranker_runtime import CrossEncoderRuntime

    run = builder.RUN
    corpus = builder.NEW_CORPUS
    manifest = json.loads((corpus / "corpus_v3_final_manifest.json").read_text(encoding="utf-8"))
    questions = read_jsonl(builder.QUESTION_FILE)
    chunks = read_jsonl(corpus / "corpus_chunks_v3_final.jsonl")
    eligible = [c for c in chunks if c.get("retrieval_eligible")]
    byid = {c["chunk_id"]: c for c in eligible}
    ids = [c["chunk_id"] for c in eligible]
    fts_row_to_chunk = {i + 1: c["chunk_id"] for i, c in enumerate(eligible)}
    vec = np.memmap(corpus / "dense_vectors_v3_final.f32", dtype=np.float32, mode="r", shape=(len(eligible), 1024))
    if builder.sha_bytes("\n".join(ids).encode()) != manifest["embedding_index"]["matrix_order_ids_sha256"]:
        raise RuntimeError("Dense vector matrix ordering failed integrity check")
    db = sqlite3.connect(corpus / "corpus_v3_final.sqlite3")
    db.row_factory = sqlite3.Row
    source_rows = {x["source_id"]: dict(x) for x in db.execute("select * from sources")}
    tags = requests.get(f"{builder.OLLAMA}/api/tags", timeout=8).json().get("models", [])
    bge = next((x for x in tags if x.get("name") == builder.BGE), None)
    if not bge or bge.get("digest", "").removeprefix("sha256:") != builder.BGE_DIGEST:
        raise RuntimeError("Embedding model identity changed")
    profiles = [builder.classify_scope(q) for q in questions]
    queries = [f"{p['species']} {q['question_text']}".strip() for q, p in zip(questions, profiles)]
    qemb = []
    for start in range(0, len(queries), 24):
        response = requests.post(f"{builder.OLLAMA}/api/embed", json={"model": builder.BGE, "input": queries[start:start+24], "truncate": False, "keep_alive": "30m"}, timeout=180)
        response.raise_for_status()
        batch = np.asarray(response.json()["embeddings"], dtype=np.float32)
        batch /= np.linalg.norm(batch, axis=1, keepdims=True)
        qemb.append(batch)
    qemb = np.vstack(qemb)
    reranker = CrossEncoderRuntime(builder.RERANKER_SNAPSHOT, device="cuda", max_length=512, batch_size=4)
    final = []
    failures = []
    for pos, (q, profile, query, qv) in enumerate(zip(questions, profiles, queries, qemb), 1):
        allowed = set(profile["allowed_source_ids"])
        present = {sid for sid in allowed if sid in source_rows}
        corpus_candidates = [c for c in eligible if c["source_id"] in present]
        # Capture corpus-wide raw candidates, then keep the allowed-source ranked pool for fusion.
        terms = list(dict.fromkeys(builder.tokenize(query)))
        bm_global = []
        bm_raw = []
        if terms:
            expr = " OR ".join('"' + x.replace('"', '""') + '"' for x in terms)
            try:
                rows = db.execute("SELECT rowid,bm25(chunks_fts) AS score FROM chunks_fts WHERE chunks_fts MATCH ? ORDER BY bm25(chunks_fts),rowid", [expr]).fetchall()
                for x in rows:
                    cid = fts_row_to_chunk.get(x["rowid"])
                    if cid is None: continue
                    item = {"chunk_id": cid, "score": float(x["score"]), "global_rank": len(bm_global) + 1}
                    if len(bm_global) < 100: bm_global.append(item)
                    c = byid[cid]
                    if c["source_id"] in present and len(bm_raw) < 100:
                        bm_raw.append({**item, "source_scope_rank": len(bm_raw) + 1})
            except sqlite3.OperationalError:
                bm_global = []; bm_raw = []
        local = [i for i, c in enumerate(eligible) if c["source_id"] in present]
        dense_global = []
        dense_raw = []
        if eligible:
            sims = vec @ qv
            global_order = np.argsort(-sims, kind="stable")[:min(100, len(eligible))]
            dense_global = [{"chunk_id": eligible[int(i)]["chunk_id"], "score": float(sims[int(i)]), "global_rank": rank} for rank, i in enumerate(global_order, 1)]
            scoped_order = sorted(local, key=lambda i: (-float(sims[i]), eligible[i]["chunk_id"]))[:min(100, len(local))]
            dense_raw = [{"chunk_id": eligible[i]["chunk_id"], "score": float(sims[i]), "source_scope_rank": rank} for rank, i in enumerate(scoped_order, 1)]
        fused = {}
        bmrank = {r["chunk_id"]: i for i, r in enumerate(bm_raw, 1)}
        denserank = {r["chunk_id"]: i for i, r in enumerate(dense_raw, 1)}
        for ranks in (bmrank, denserank):
            for cid, rank in ranks.items(): fused[cid] = fused.get(cid, 0.0) + 1 / (60 + rank)
        rrf_order = sorted(fused, key=lambda cid: (-fused[cid], cid))
        rrf_raw = [{"chunk_id": cid, "rank": rank, "rrf_score": fused[cid], "bm25_rank": bmrank.get(cid), "dense_rank": denserank.get(cid)} for rank, cid in enumerate(rrf_order[:100], 1)]
        source_pass = []
        source_reject = Counter()
        for item in rrf_raw:
            c = byid[item["chunk_id"]]
            s = source_rows.get(c["source_id"])
            if not s or not s.get("retrieval_default"):
                source_reject["SOURCE_NOT_RETRIEVAL_ADMITTED"] += 1
                continue
            if c["source_id"] not in present:
                source_reject["SOURCE_OUTSIDE_QUERY_ALLOWLIST"] += 1
                continue
            source_pass.append(item)
        species_pass = []
        scope_reject = Counter()
        scope_details = {}
        for item in source_pass:
            c = byid[item["chunk_id"]]
            ok, reason = load_scope(q, c)
            scope_details[c["chunk_id"]] = reason
            if ok: species_pass.append(item)
            else: scope_reject[reason] += 1
        rerank_in = [{"chunk_id": x["chunk_id"], "text": byid[x["chunk_id"]]["text"], "rank": x["rank"], "source_id": byid[x["chunk_id"]]["source_id"], "rrf_score": x["rrf_score"]} for x in species_pass]
        reranked = reranker.rerank(query, rerank_in) if rerank_in else []
        top = []
        for rank, item in enumerate(reranked[:5], 1):
            c = byid[item["chunk_id"]]
            meta = json.loads(c.get("metadata_json") or "{}")
            top.append({"chunk_id": c["chunk_id"], "rank": rank, "source_id": c["source_id"], "source_sha256": c["source_sha256"], "source_version": c["source_version"], "source_title": meta.get("source_title"), "source_url": meta.get("source_url"), "publisher": meta.get("publisher"), "page_or_locator": c["record_locator"], "content": c["text"], "content_sha256": c["content_sha256"], "retrieval_eligible": bool(c["retrieval_eligible"]), "species_scope": meta.get("species_scope"), "species_taxonomy": meta.get("species_taxonomy"), "category_scope": meta.get("category_scope"), "chunk_role": c.get("chunk_role"), "evidence_span": meta.get("evidence_span"), "evidence_span_start_char": meta.get("evidence_span_start_char"), "evidence_span_end_char": meta.get("evidence_span_end_char"), "source_scope_rule": scope_details.get(c["chunk_id"]), "bm25_rank": bmrank.get(c["chunk_id"]), "dense_rank": denserank.get(c["chunk_id"]), "rrf_rank": next((x["rank"] for x in rrf_raw if x["chunk_id"] == c["chunk_id"]), None), "rrf_score": next((x["rrf_score"] for x in rrf_raw if x["chunk_id"] == c["chunk_id"]), None), "reranker_rank": rank, "reranker_score": item.get("reranker_score")})
        if not present:
            status = "no_applicable_retrieval_eligible_source"
            failure = "SOURCE_MISSING"
        elif not corpus_candidates:
            status = "no_applicable_retrieval_eligible_source"
            failure = "INGESTION_FAILURE"
        elif not rrf_raw:
            status = "no_applicable_retrieval_eligible_source"
            failure = "RETRIEVAL_RECALL_FAILURE"
        elif not source_pass:
            status = "no_applicable_retrieval_eligible_source"
            failure = "METADATA_FILTER_TOO_STRICT_OR_SOURCE_NOT_ADMITTED"
        elif not species_pass:
            status = "no_applicable_retrieval_eligible_source"
            failure = "SOURCE_SCOPE_UNKNOWN" if scope_reject.get("SOURCE_SPECIES_SCOPE_UNKNOWN_OR_MISMATCH") else "SPECIES_SCOPE_CONFLICT"
        elif not top:
            status = "fewer_than_five_applicable_candidates"
            failure = "RERANKING_FAILURE"
        elif len(top) < 5:
            status = "fewer_than_five_applicable_candidates"
            failure = "LOW_APPLICABLE_CANDIDATE_POOL"
        else:
            status = "reranked_top5_complete"
            failure = None
        row = {"question_id": q["question_id"], "species": q.get("species_chinese"), "category": q.get("inferred_category"), "question_text": q["question_text"], "query": query, "intent": profile["intent"], "scope_allowed_source_ids": sorted(allowed), "candidate_sources_in_scope_allowlist_present": len(present), "corpus_applicable_source_count": len({c["source_id"] for c in corpus_candidates}), "corpus_applicable_chunk_count": len(corpus_candidates), "bm25_global_candidate_count": len(bm_global), "bm25_candidate_count": len(bm_raw), "bm25_global_top100": bm_global, "bm25_top100": bm_raw, "dense_global_candidate_count": len(dense_global), "dense_candidate_count": len(dense_raw), "dense_global_top100": dense_global, "dense_top100": dense_raw, "rrf_candidate_count": len(fused), "rrf_candidates_top100": rrf_raw, "source_qualification_pass_count": len(source_pass), "source_qualification_rejected_reasons": dict(source_reject), "species_applicability_pass_count": len(species_pass), "species_scope_rejected_reasons": dict(scope_reject), "reranker_candidate_count": len(rerank_in), "reranked_top5": top, "final_top5_count": len(top), "retrieval_status": status, "retrieval_failure_reason": failure, "corpus_version": manifest["corpus_version"], "query_excludes_answers_and_rubrics": True, "retrieval_config": {"bm25": "SQLite FTS5; raw corpus-wide ranking plus allowed-source ranking", "dense": "BGE-M3 Ollama", "dense_digest": builder.BGE_DIGEST, "rrf_k": 60, "reranker": "BAAI/bge-reranker-v2-m3", "reranker_revision": builder.RERANKER_SNAPSHOT.name, "top_k": 5}}
        final.append(row)
        failures.append({"question_id": row["question_id"], "species": row["species"], "category": row["category"], "possible_source_count_from_allowlist": row["candidate_sources_in_scope_allowlist_present"], "corpus_applicable_source_count": row["corpus_applicable_source_count"], "bm25_raw_global_candidate_count": row["bm25_global_candidate_count"], "bm25_allowed_source_candidate_count": row["bm25_candidate_count"], "dense_raw_global_candidate_count": row["dense_global_candidate_count"], "dense_allowed_source_candidate_count": row["dense_candidate_count"], "rrf_fused_candidate_count": row["rrf_candidate_count"], "source_qualification_pass_count": row["source_qualification_pass_count"], "species_applicability_pass_count": row["species_applicability_pass_count"], "reranker_candidate_count": row["reranker_candidate_count"], "final_top5_count": row["final_top5_count"], "failure_reason": failure, "top5_chunk_ids": [x["chunk_id"] for x in top], "source_qualification_rejected_reasons": dict(source_reject), "species_scope_rejected_reasons": dict(scope_reject)})
        if pos % 30 == 0: print(f"retrieval {pos}/180 complete", flush=True)
    write_jsonl(run / "retrieval_results_v3_final.jsonl", final)
    write_jsonl(run / "retrieval_failure_resolution_180.jsonl", failures)
    print(json.dumps({"questions": len(final), "retrieval_status": dict(Counter(r["retrieval_status"] for r in final)), "failure_reason": dict(Counter(r["retrieval_failure_reason"] for r in final)), "average_candidates": {k: round(sum(r[k] for r in final)/len(final), 2) for k in ["bm25_candidate_count", "dense_candidate_count", "rrf_candidate_count", "source_qualification_pass_count", "species_applicability_pass_count", "reranker_candidate_count", "final_top5_count"]}}, ensure_ascii=True, indent=2))
    db.close()


if __name__ == "__main__":
    main()
