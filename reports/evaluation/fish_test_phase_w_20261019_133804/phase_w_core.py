from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import re
import sqlite3
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
V = ROOT / "reports/evaluation/fish_test_phase_v_20261018_224918"
W = Path(__file__).resolve().parent
CORPUS = V / "corpus_v3_final"
QUESTIONS = V / "question_eligibility_v3.jsonl"
PHASE_E = ROOT / "reports/evaluation/fish_test_run_20261012_152244"
PHASE_U = ROOT / "reports/evaluation/fish_test_phase_u_20261018_195823"
OLLAMA = "http://127.0.0.1:11434"
BGE = "bge-m3:latest"
BGE_DIGEST = "7907646426070047a77226ac3e684fbbe8410524f7b4a74d02837e43f2146bab"
RERANKER = ROOT / ".venv-reranker/hf-cache/hub/models--BAAI--bge-reranker-v2-m3/snapshots/953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e"

FISH = ("虱目魚", "吳郭魚", "石斑魚", "鱸魚", "烏魚", "鰻魚")
MODELS = {
    "M1": ("deepseek-r1:7b", "755ced02ce7befdb13b7ca74e1e4d08cddba4986afdb63a480f2c93d3140383f"),
    "M2": ("qwen2.5-coder:7b", "dae161e27b0e90dd1856c8bb3209201fd6736d8eb66298e75ed87571486f4364"),
    "M3": ("hf.co/bartowski/DeepSeek-R1-Distill-Llama-8B-GGUF:Q4_K_M", "aab87d0e8a585cc6260d3a448e3f66ff2057d1cd6975c834151deeb1eae94b42"),
    "M4": ("gemma2:9b", "ff02c3702f322b9e075e9568332d96c0a7028002f1a5a056e0a6784320a4db0b"),
}
JUDGE = ("mistral-nemo:12b-instruct-2407-q4_K_M", "daf6737417121831e572a9c482e92a221ee0c33537f35f1f857c7b4f7191d")

def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))

def read_jsonl(path: Path):
    return [json.loads(x) for x in path.read_text(encoding="utf-8-sig").splitlines() if x.strip()]

def write_json(path: Path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

def write_jsonl(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(x, ensure_ascii=False, separators=(",", ":")) + "\n" for x in rows), encoding="utf-8")

def sha_file(path: Path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda: f.read(1024 * 1024), b""):
            h.update(b)
    return h.hexdigest()

def sha_text(text: str):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

def source_and_baseline():
    rights = read_jsonl(PHASE_U / "source_rights_version_scope_audit_57_final.jsonl")
    owner = read_jsonl(PHASE_U / "source_owner_decision_update_57.jsonl")
    forensics = read_jsonl(V / "source_file_forensics_57.jsonl")
    blockers = read_jsonl(V / "source_blocker_resolution_50.jsonl")
    forensic_by = {r.get("source_record_id"): r for r in forensics}
    owner_by = {r.get("source_record_id"): r for r in owner}
    source_rows = []
    for r in rights:
        key = r.get("source_record_id")
        f = forensic_by.get(key, {})
        o = owner_by.get(key, {})
        admission_status = r.get("source_admission_status", "not_admitted")
        admitted = admission_status in ("admitted_scope_limited", "already_admitted_scope_limited")
        local = f.get("local_file") or r.get("local_file")
        path = ROOT / local if local else None
        actual = sha_file(path) if path and path.is_file() else None
        expected = f.get("sha256_expected") or r.get("source_sha256")
        source_rows.append({
            "source_record_id": key, "source_id": r.get("source_id") or f.get("source_id"),
            "title": r.get("source_title") or f.get("title"), "publisher": r.get("publisher") or f.get("publisher"),
            "official_url": r.get("source_url") or f.get("official_url"), "local_file": local,
            "owner_decision": o.get("owner_decision", "APPROVED"), "owner_decision_date": o.get("owner_decision_date", "2026-10-18"),
            "owner_approval_is_third_party_license": False, "sha256_expected": expected, "sha256_actual": actual,
            "checksum_status": "MATCH" if expected and actual == expected else ("MISMATCH" if expected and actual else "UNAVAILABLE"),
            "version": r.get("source_version") or "UNVERIFIED",
            "usage_basis": r.get("rights_status"),
            "owner_approved_processing": True, "formal_source_admission_recorded": admitted,
            "formally_admitted_scope": r.get("corpus_v3_inclusion_status") if admitted else None,
            "fulltext_index_rights_independently_verified": r.get("rights_status") == "verified_statutory_text_only_under_copyright_act_art9",
            "limited_fact_card_scope": "; ".join(r.get("scope_signals_not_verified", {}).keys()) if r.get("scope_signals_not_verified") else None,
            "admission_status": admission_status,
            "corpus_v3_inclusion_status": r.get("corpus_v3_inclusion_status"),
            "phase_v_fulltext_blocker": not admitted,
            "notes": "Owner approval authorizes processing workflow only; it does not establish third-party permission. Any existing researcher-authored card has a narrower scope than the original file." if not admitted else "Admission/use scope remains limited to the registry decision; no scope expansion."
        })
    # Carry independent per-package forensic outcomes without treating metadata gaps as license grants.
    by_blocker = {r.get("source_record_id"): r for r in blockers}
    for s in source_rows:
        if s["source_record_id"] in by_blocker:
            b = by_blocker[s["source_record_id"]]
            s["phase_v_blocker_codes"] = b.get("blocker_codes", [])
            s["phase_v_resolution"] = b.get("resolution")
            if b.get("checksum_match") is False:
                s["admission_status"] = "blocked_checksum_mismatch"
    old_ret = read_jsonl(V / "retrieval_results_v3_final.jsonl")
    old_ref = read_json(V / "question_reference_qualification_summary.json")
    eligibility = read_jsonl(V / "question_eligibility_v3.jsonl")
    manifest = read_json(CORPUS / "corpus_v3_final_manifest.json")
    baseline = {
        "phase": "W", "phase_v_workspace": str(V), "question_count": len(eligibility),
        "unique_question_ids": len({x["question_id"] for x in eligibility}),
        "phase_v_source_records": len(rights), "owner_approved_source_records": sum(x.get("owner_decision")=="APPROVED" for x in owner),
        "distinct_sha256_in_owner_matrix": len({x.get("source_sha256") or x.get("sha256_expected") for x in rights if x.get("source_sha256") or x.get("sha256_expected")}),
        "blocked_source_packages_phase_v": len(blockers), "source_checksum_matches_phase_v": sum(x.get("checksum_match") is True for x in blockers),
        "phase_v_corpus_version": manifest.get("corpus_version"), "phase_v_chunks": manifest.get("total_chunk_count"),
        "phase_v_retrieval_eligible_chunks": manifest.get("retrieval_eligible_chunk_count"), "phase_v_context_only_chunks": manifest.get("context_only_chunk_count"),
        "phase_v_top5_complete": sum(len(x.get("reranked_top5", [])) == 5 for x in old_ret),
        "phase_v_any_context": sum(bool(x.get("reranked_top5")) for x in old_ret),
        "phase_v_no_context": sum(not x.get("reranked_top5") for x in old_ret),
        "source_answer_candidates": old_ref.get("status_counts", {}).get("SOURCE_VERIFIED_AUTOMATED_CANDIDATE", 0),
        "answerable_verified_phase_v": old_ref.get("answerable_verified", 0), "human_gold": old_ref.get("human_gold", 0),
        "historical_evaluation_corpus_v2_modified": False, "production_sqlite_modified": False,
        "four_model_new_generation_before_phase_w": len(read_jsonl(V / "generator_results_v3_final.jsonl")),
        "source_resolution_status_counts": dict(Counter(x["admission_status"] for x in source_rows)),
        "caveat": "All 50 owner-approved blocked packages retain their rights/version/applicability limits; the owner decision is not a third-party license. DGBAS 2020 remains single-year descriptive Fact only."
    }
    write_jsonl(W / "source_resolution_final.jsonl", source_rows)
    write_json(W / "phase_w_baseline_reconciliation.json", baseline)
    return rights, owner, blockers, source_rows, eligibility, manifest, baseline

def norm_species(s):
    s = (s or "").strip()
    aliases = {"虱目": "虱目魚", "吳郭": "吳郭魚", "羅非魚": "吳郭魚", "烏魚": "烏魚", "鯔魚": "烏魚", "石斑": "石斑魚", "金目鱸": "鱸魚", "七星鱸": "鱸魚", "鱸魚": "鱸魚", "鰻魚": "鰻魚"}
    for a, b in aliases.items():
        if a in s: return b
    return s

def query_profile(q):
    text=q.get("question_text", "")
    species=norm_species(q.get("species", ""))
    cat=q.get("category", "")
    explicit_seabass = "金目鱸" if "金目鱸" in text else ("七星鱸" if "七星鱸" in text else None)
    numeric = bool(re.search(r"\d+(?:\.\d+)?\s*(?:°?C|℃|%|mg/L|g/L|psu|公分|公斤|尾|天|小時|分鐘|公頃|平方公尺|立方公尺)", text, re.I)) or any(x in text for x in ("範圍", "上限", "下限", "公式", "計算", "單位", "幾度", "多少"))
    if any(x in text for x in ("產量", "產值", "統計", "資料集", "生產量")):
        intent="official_statistics"; sources={"MOA-FISHERY-PRODUCTION-44084", "MOA-FISH-SPECIES-CODE-134250"}
        # DGBAS is only eligible for an explicitly requested single-year descriptive statistical fact.
        if re.search(r"2020|民國109|109年", text): sources.add("DGBAS-79395-2020")
        if re.search(r"2015|民國104|104年", text): sources.add("DGBAS-79395-2015")
    elif cat in ("Medication / Law", "Medication/Law", "Law", "法規") or any(x in text for x in ("法規", "條文", "法定", "停藥期", "核准", "用藥")):
        intent="legal_text"; sources={"MOA-FL014718-ACT"}
    else:
        intent="species_technical"; sources=set()
        if species=="虱目魚" and any(x in text for x in ("寒", "低溫", "寒流", "防寒", "越冬")): sources.add("FA-385-COLD")
        elif species=="吳郭魚" and any(x in text for x in ("寒", "低溫", "寒流", "防寒")): sources.add("FA-385-COLD")
        elif species=="石斑魚": sources.add("TFRI-M17-GROUPER")
        elif species=="烏魚": sources.add("TFRI-M17-MULLET")
        elif species=="鰻魚" and any(x in text for x in ("病", "疾病", "黴菌", "水黴", "細菌")): sources.add("TFRI-EEL-MOLD-2006")
        elif species=="鱸魚":
            if explicit_seabass=="金目鱸": sources.add("TFRI-M17-GOLD-SEABASS")
            elif explicit_seabass=="七星鱸": sources.add("TFRI-M17-SEVENSTAR")
            # Generic "鱸魚" is deliberately not expanded to a particular seabass species.
        # A category does not widen source scope. If no source has demonstrated applicability, leave empty.
    return {"species": species, "category": cat, "intent": intent, "allowed_source_ids": sorted(sources), "numeric_or_condition_sensitive": numeric, "seabass_subspecies": explicit_seabass}

def chunk_applicable(c, q, profile):
    meta=json.loads(c.get("metadata_json") or "{}")
    source=c.get("source_id")
    scope=meta.get("species_scope", "")
    if isinstance(scope, list): scope="|".join(scope)
    scopes={x.strip() for x in str(scope).split("|") if x.strip()}
    species=profile["species"]
    if source in ("DGBAS-79395-2015", "DGBAS-79395-2020", "MOA-FISHERY-PRODUCTION-44084", "MOA-FISH-SPECIES-CODE-134250"):
        if profile["intent"]!="official_statistics": return False, "STATISTICAL_SOURCE_REQUIRES_STATISTICAL_QUERY"
        if source.startswith("DGBAS") and not re.search(r"2020|民國109|109年" if source.endswith("2020") else r"2015|民國104|104年", q.get("question_text", "")):
            return False, "STATISTICS_REFERENCE_YEAR_NOT_EXPLICIT"
        return True, "OFFICIAL_STATISTICAL_LABEL_ONLY"
    if source=="MOA-FL014718-ACT":
        return profile["intent"]=="legal_text", "GENERAL_STATUTE_ONLY_NO_DRUG_SPECIFIC_CLAIM"
    categories=meta.get("category_scope", [])
    if isinstance(categories, str): categories=[categories]
    if categories and q.get("category") not in categories:
        text=q.get("question_text", "")
        # Temperature questions can be supported by a climate card or a water-temperature card.
        if not (any(t in text for t in ("水溫", "溫度", "適溫", "低溫", "寒害", "寒流")) and any(x in categories for x in ("Water Quality", "Climate / Cold"))):
            return False, "CATEGORY_SCOPE_MISMATCH"
    if source=="TFRI-M17-GOLD-SEABASS" and species=="鱸魚" and "金目鱸" not in q.get("question_text", ""):
        return False, "SEABASS_SUBSPECIES_NOT_SPECIFIED"
    if source=="TFRI-M17-SEVENSTAR" and species=="鱸魚" and "七星鱸" not in q.get("question_text", ""):
        return False, "SEABASS_SUBSPECIES_NOT_SPECIFIED"
    if species in scopes:
        return True, "EXACT_SPECIES_SCOPE"
    if "general_aquaculture" in scopes and not profile["numeric_or_condition_sensitive"]:
        return True, "GENERAL_AQUACULTURE_NON_NUMERIC_ONLY"
    if source=="FA-385-COLD" and "general_aquaculture" in scopes and species in ("虱目魚", "吳郭魚"):
        return True, "EXPLICIT_MULTI_SPECIES_SCOPE"
    if source=="TFRI-M17-GOLD-SEABASS" and species=="鱸魚" and "金目鱸" in q.get("question_text", ""):
        return True, "EXACT_SUBSPECIES_SCOPE"
    if source=="TFRI-M17-SEVENSTAR" and species=="鱸魚" and "七星鱸" in q.get("question_text", ""):
        return True, "EXACT_SUBSPECIES_SCOPE"
    return False, "SPECIES_SCOPE_NOT_VERIFIED"

def load_retriever_dependencies():
    for p in (ROOT/".venv-reranker/Lib/site-packages", ROOT/".venv/Lib/site-packages", ROOT):
        if str(p) not in sys.path: sys.path.insert(0, str(p))
    import numpy as np
    import requests
    from src.evaluation.reranker_runtime import CrossEncoderRuntime
    return np, requests, CrossEncoderRuntime

def retrieve_180(questions, output_path: Path | None = None):
    np, requests, CrossEncoderRuntime=load_retriever_dependencies()
    tags=requests.get(f"{OLLAMA}/api/tags", timeout=10).json().get("models", [])
    bge=[m for m in tags if m.get("name")==BGE]
    if not bge or bge[0].get("digest", "").removeprefix("sha256:")!=BGE_DIGEST: raise RuntimeError("BGE-M3 digest mismatch")
    chunks=read_jsonl(CORPUS/"corpus_chunks_v3_final.jsonl")
    eligible=[c for c in chunks if c.get("retrieval_eligible")]
    matrix=np.memmap(CORPUS/"dense_vectors_v3_final.f32", dtype=np.float32, mode="r", shape=(len(eligible), 1024))
    ids=[c["chunk_id"] for c in eligible]
    order_digest=hashlib.sha256("\n".join(ids).encode()).hexdigest()
    manifest=read_json(CORPUS/"corpus_v3_final_manifest.json")
    if order_digest != manifest["embedding_index"]["matrix_order_ids_sha256"]: raise RuntimeError("Embedding order digest mismatch")
    db=sqlite3.connect(CORPUS/"corpus_v3_final.sqlite3")
    fts_count,fts_min,fts_max=db.execute("SELECT count(*),min(rowid),max(rowid) FROM chunks_fts").fetchone()
    if fts_count!=len(eligible) or fts_min!=1 or fts_max!=len(eligible): raise RuntimeError("FTS identity binding failed")
    fts_map={i+1:c["chunk_id"] for i,c in enumerate(eligible)}
    qrows=[]
    for e in questions:
        qrows.append({"question_id":e["question_id"],"species":e.get("species"),"category":e.get("category"),"question_text":e.get("question_text", ""),"query":f"{e.get('species','')} {e.get('question_text','')}".strip()})
    all_vec=[]
    for i in range(0,len(qrows),32):
        batch=[x["query"] for x in qrows[i:i+32]]
        response=requests.post(f"{OLLAMA}/api/embed",json={"model":BGE,"input":batch,"truncate":False,"keep_alive":"20m"},timeout=180)
        response.raise_for_status(); vectors=np.asarray(response.json()["embeddings"],dtype=np.float32)
        if vectors.shape!=(len(batch),1024): raise RuntimeError(f"Unexpected query embedding shape {vectors.shape}")
        vectors/=np.maximum(np.linalg.norm(vectors,axis=1,keepdims=True),1e-12); all_vec.append(vectors)
    qvecs=np.vstack(all_vec)
    reranker=CrossEncoderRuntime(RERANKER,device="cuda",max_length=512,batch_size=4)
    results=[]
    for i,(q,qvec) in enumerate(zip(qrows,qvecs),1):
        profile=query_profile(q); allow=set(profile["allowed_source_ids"])
        scoped=[]; scope_reason=Counter()
        for c in eligible:
            if c.get("source_id") not in allow: continue
            ok,why=chunk_applicable(c,q,profile)
            scope_reason[why]+=1
            if ok: scoped.append(c)
        scope_ids={c["chunk_id"] for c in scoped}; by_id={c["chunk_id"]:c for c in scoped}
        terms=[]
        text=q["query"]
        for token in re.findall(r"[A-Za-z]+|\d+(?:\.\d+)?|[\u3400-\u9fff]{1,}",text):
            if re.fullmatch(r"[\u3400-\u9fff]+",token):
                if len(token)==1: terms.append(token)
                else: terms += [token[j:j+2] for j in range(len(token)-1)]
            else: terms.append(token.lower())
        terms=list(dict.fromkeys(x for x in terms if x))
        bm=[]
        if terms and scoped:
            expression=" OR ".join('"'+t.replace('"','""')+'"' for t in terms)
            try:
                for rowid,score in db.execute("SELECT rowid,bm25(chunks_fts) FROM chunks_fts WHERE chunks_fts MATCH ? ORDER BY bm25(chunks_fts), rowid LIMIT 500",[expression]).fetchall():
                    cid=fts_map.get(rowid)
                    if cid in scope_ids: bm.append({"chunk_id":cid,"score":float(score)})
                    if len(bm)>=100: break
            except sqlite3.OperationalError: bm=[]
        bm_rank={x["chunk_id"]:r for r,x in enumerate(bm,1)}
        local=[j for j,c in enumerate(eligible) if c["chunk_id"] in scope_ids]
        dense=[]
        if local:
            sims=matrix[local] @ qvec
            ix=np.argsort(-sims,kind="stable")[:min(100,len(local))]
            dense=[{"chunk_id":eligible[local[int(k)]]["chunk_id"],"score":float(sims[int(k)])} for k in ix]
        dense_rank={x["chunk_id"]:r for r,x in enumerate(dense,1)}
        fused={}
        for group in (bm,dense):
            for rank,row in enumerate(group,1): fused[row["chunk_id"]]=fused.get(row["chunk_id"],0.0)+1/(60+rank)
        fids=sorted(fused,key=lambda x:(-fused[x],x))[:100]
        rrf=[{"chunk_id":cid,"rank":r,"score":fused[cid],"bm25_rank":bm_rank.get(cid),"dense_rank":dense_rank.get(cid)} for r,cid in enumerate(fids,1)]
        rin=[{"chunk_id":cid,"text":by_id[cid]["text"],"rank":r,"source_id":by_id[cid]["source_id"],"rrf_score":fused[cid]} for r,cid in enumerate(fids,1)]
        reranked=reranker.rerank(q["query"],rin) if rin else []
        top=[]
        for rank,x in enumerate(reranked[:5],1):
            c=by_id[x["chunk_id"]]; m=json.loads(c.get("metadata_json") or "{}")
            applicable, app_reason = chunk_applicable(c,q,profile)
            top.append({"chunk_id":c["chunk_id"],"rank":rank,"source_id":c["source_id"],"source_title":m.get("source_title"),"source_url":m.get("source_url"),"source_sha256":c["source_sha256"],"source_version":c["source_version"],"page_or_locator":c["record_locator"],"content":c["text"],"content_sha256":sha_text(c["text"]),"retrieval_eligible":True,"category_scope":m.get("category_scope"),"species_scope":m.get("species_scope"),"species_taxonomy":m.get("species_taxonomy"),"source_cluster_id":m.get("source_cluster_id"),"rrf_rank":x.get("rank"),"rrf_score":x.get("rrf_score"),"reranker_rank":x.get("reranker_rank"),"reranker_score":x.get("reranker_score"),"bm25_rank":bm_rank.get(c["chunk_id"]),"dense_rank":dense_rank.get(c["chunk_id"]),"applicability_reason":app_reason,"scope_status":"eligible"})
        row={"question_id":q["question_id"],"species":q["species"],"category":q["category"],"question_text":q["question_text"],"query":q["query"],"intent":profile["intent"],"requirement_profile":profile,"allowed_source_ids":sorted(allow),"corpus_applicable_source_count":len({c["source_id"] for c in scoped}),"corpus_applicable_chunk_count":len(scoped),"bm25_candidate_count":len(bm),"bm25_top100":bm,"dense_candidate_count":len(dense),"dense_top100":dense,"rrf_candidate_count":len(rrf),"rrf_candidates_top100":rrf,"source_qualification_pass_count":len(scoped),"species_applicability_pass_count":len(scoped),"scope_rejection_reasons":dict(scope_reason),"reranker_candidate_count":len(rin),"reranked_top5":top,"final_top5_count":len(top),"retrieval_status":"reranked_top5_complete" if len(top)==5 else ("no_applicable_retrieval_eligible_source" if not scoped else "fewer_than_five_applicable_candidates"),"retrieval_failure_reason":None if len(top)==5 else ("SOURCE_MISSING_OR_SCOPE_FILTERED" if not scoped else "ELIGIBLE_CANDIDATE_POOL_BELOW_FIVE"),"corpus_version":manifest["corpus_version"],"query_excludes_answers_and_rubrics":True,"retrieval_config":{"bm25":"SQLite FTS5; corpus v3 frozen tokenization","dense":"BGE-M3 Ollama", "dense_digest":BGE_DIGEST,"rrf_k":60,"reranker":"BAAI/bge-reranker-v2-m3","reranker_revision":RERANKER.name,"top_k":5}}
        results.append(row)
        if i%30==0: print(f"retrieval {i}/180",flush=True)
    db.close()
    write_jsonl(output_path or (W/"retrieval_results_v3_updated.jsonl"),results)
    return results

def make_profiles_and_references(questions, retrieval):
    byret={r["question_id"]:r for r in retrieval}
    refs=read_jsonl(V/"question_reference_answers_180.jsonl")
    ref_by={r["question_id"]:r for r in refs}
    corpus_chunks={r["chunk_id"]:r for r in read_jsonl(CORPUS/"corpus_chunks_v3_final.jsonl")}
    profiles=[]; outputs=[]
    for q in questions:
        p=query_profile(q); text=q.get("question_text", "")
        req=[]
        if any(x in text for x in ("溫度", "水溫", "適溫", "低溫", "幾度")): req.append("temperature_value_or_condition")
        if any(x in text for x in ("範圍", "上限", "下限")): req.append("requested_range_or_limit")
        if any(x in text for x in ("公式", "計算", "多少", "幾")): req.append("numeric_answer_or_calculation")
        if any(x in text for x in ("法規", "條文", "停藥期", "用藥", "核准")): req.append("legal_version_and_scope")
        if not req: req.append("direct_answer_to_question")
        profile={"question_id":q["question_id"],"target_species":q.get("species"),"category":q.get("category"),"required_answer_elements":req,"requires_numeric_value_or_unit":p["numeric_or_condition_sensitive"],"required_conditions":["species applicability","source version/effective date where material"],"source_version_requirements":"must match the applicable fact/law version; unknown version remains unresolved","query_text_hash":sha_text(text)}
        profiles.append(profile)
        r=byret[q["question_id"]]; v=ref_by.get(q["question_id"],{})
        # Prior auto candidates are never promoted without a strict, exact card/source match and frozen human rubric.
        status="NOT_EVALUABLE"
        if not r["reranked_top5"]:
            status="EXPECTED_ABSTENTION_CANDIDATE"
        elif v.get("source_status")=="SOURCE_VERIFIED_AUTOMATED_CANDIDATE":
            status="AI_ASSISTED_CANDIDATE_REQUIRES_RUBRIC_REVIEW"
        refsrow={"question_id":q["question_id"],"species":q.get("species"),"category":q.get("category"),"original_question":q.get("question_text"),"source_id":None,"exact_evidence_span":None,"source_version":None,"expected_answer":None,"required_conditions":profile["required_conditions"],"logical_rubric":None,"arithmetic_formula":None,"expected_abstention":not bool(r["reranked_top5"]),"verification_status":status,"corpus_version":r["corpus_version"],"human_gold_reviewed":False,"prior_candidate_status":v.get("source_status"),"prior_candidate_evidence_span_ids":[x.get("fact_id") for x in v.get("evidence_spans",[])],"reason":"No independently frozen reference rubric is available. Retrieval context and model outputs are not treated as gold. Empty retrieval is an exploratory safe-abstention case, not an answer-accuracy sample."}
        outputs.append(refsrow)
    write_jsonl(W/"question_requirement_profiles_180.jsonl",profiles)
    write_jsonl(W/"reference_answers_v3.jsonl",outputs)
    rubrics={"version":"phase_w_rubrics_v1","status":"frozen_for_reporting_only_no_professional_accuracy_rubrics","human_gold":False,"formal_logical_accuracy":{"eligible_question_count":0,"reason":"No reviewer-approved source-backed rubric set in Phase V; do not score professional correctness."},"formal_arithmetic_accuracy":{"eligible_question_count":0,"reason":"Formula protocol, units, reference values and tolerance are not independently verified as a complete set."},"context_precision_at_5":{"eligible_question_count":0,"reason":"No trusted binary relevance labels; new retrieval is not itself a relevance annotation."},"rule":"Do not infer answer keys from M1-M4 outputs or from top-5 retrieval text."}
    write_json(W/"evaluation_rubrics_v3.json",rubrics)
    return profiles, outputs, rubrics

def main():
    rights, owner, blockers, sources, qs, corpus_manifest, baseline=source_and_baseline()
    source_counts=Counter(x["admission_status"] for x in sources)
    if len(qs)!=180 or len({x["question_id"] for x in qs})!=180: raise RuntimeError("Phase V question IDs not exactly 180 unique")
    results=retrieve_180(qs)
    profiles, refs, rubrics=make_profiles_and_references(qs,results)
    cats=Counter(x.get("category") for x in qs); species=Counter(x.get("species") for x in qs)
    retrieval_summary={"question_count":len(results),"complete_top5":sum(x["final_top5_count"]==5 for x in results),"partial_nonempty":sum(0<x["final_top5_count"]<5 for x in results),"no_context":sum(x["final_top5_count"]==0 for x in results),"any_context":sum(x["final_top5_count"]>0 for x in results),"total_contexts":sum(x["final_top5_count"] for x in results),"by_category":{},"by_species":{},"failure_reasons":dict(Counter(x.get("retrieval_failure_reason") for x in results if x.get("retrieval_failure_reason"))),"mean_candidate_count":sum(x["corpus_applicable_chunk_count"] for x in results)/len(results),"corpus_version":corpus_manifest["corpus_version"],"note":"Counts reflect source- and species-qualified chunks, not answerability or P@5 relevance."}
    for key, groups in (("by_category",cats),("by_species",species)):
        for group in groups:
            part=[r for r in results if (r.get("category") if key=="by_category" else r.get("species"))==group]
            retrieval_summary[key][group]={"questions":len(part),"any_context":sum(bool(r["reranked_top5"]) for r in part),"complete_top5":sum(r["final_top5_count"]==5 for r in part),"contexts":sum(r["final_top5_count"] for r in part)}
    write_json(W/"retrieval_summary_v3_updated.json",retrieval_summary)
    write_json(W/"corpus_v3_updated_manifest.json",{
      **corpus_manifest,"phase_w_view":"isolated read-only use of Phase V immutable Corpus v3; no source additions or re-embedding performed",
      "phase_w_updated_at":"2026-10-19","phase_w_corpus_updated":False,"retrieval_policy_version":"phase_w_scope_policy_v1",
      "rights_policy":"Only Phase V retrieval-eligible rows plus existing researcher-authored limited fact cards; Phase V's 50 blocked fulltext sources remain excluded. Owner approval is not third-party license.",
      "retrieval_results_file":"retrieval_results_v3_updated.jsonl","retrieval_summary":retrieval_summary
    })
    print(json.dumps({"baseline":baseline,"retrieval":retrieval_summary,"source_status_counts":source_counts},ensure_ascii=True,indent=2))

if __name__=="__main__": main()
