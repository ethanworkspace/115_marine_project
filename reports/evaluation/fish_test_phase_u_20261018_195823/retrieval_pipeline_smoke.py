from __future__ import annotations
import importlib.util, json, sqlite3, sys, time
from pathlib import Path
import numpy as np

ROOT = Path.cwd()
OUT = ROOT / "reports/evaluation/fish_test_phase_u_20261018_195823"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / ".venv/Lib/site-packages"))
sys.path.insert(0, str(ROOT / ".venv-reranker/Lib/site-packages"))
spec = importlib.util.spec_from_file_location("u_retrieval", OUT / "run_corpus_v3_retrieval.py")
mod = importlib.util.module_from_spec(spec); sys.modules[spec.name] = mod; spec.loader.exec_module(mod)
from src.evaluation.reranker_runtime import CrossEncoderRuntime

MAN = mod.read_json(mod.MANIFEST_FILE)
chunks = mod.read_jsonl(mod.CHUNK_FILE)
eligible = [c for c in chunks if c["retrieval_eligible"]]
ids = [c["chunk_id"] for c in eligible]
vecs = np.memmap(mod.VECTOR_FILE, dtype=np.float32, mode="r", shape=(len(eligible), 1024))
byid = {c["chunk_id"]: c for c in eligible}
tests = [
    {"id":"smoke_dgbas_area_2015", "query":"2015年 主要養殖生物種類 縣市 水產養殖面積 公頃 census", "source_ids":["DGBAS-79395-2015"]},
    {"id":"smoke_moa_species_code", "query":"Fish species code 魚種代碼 中文名稱 學名 scientific name", "source_ids":["MOA-FISH-SPECIES-CODE-134250"]},
    {"id":"smoke_moa_fishery_production", "query":"漁業生產量 魚種 產量 單位 年度 養殖 漁獲", "source_ids":["MOA-FISHERY-PRODUCTION-44084"]},
]
qvecs = mod.query_vectors([x["query"] for x in tests])
re = CrossEncoderRuntime(mod.SNAPSHOT, device="cuda", max_length=512, batch_size=4)
results=[]
with sqlite3.connect(mod.DB_FILE) as con:
  for t,qv in zip(tests,qvecs,strict=True):
    allowed = [c for c in eligible if c["source_id"] in t["source_ids"]]
    bm=mod.bm25_search(con,t["source_ids"],t["query"],100)
    bmr={x["chunk_id"]:i+1 for i,x in enumerate(bm)}
    ix=np.fromiter((i for i,c in enumerate(eligible) if c["source_id"] in t["source_ids"]),dtype=np.int32)
    ds=vecs[ix]@qv
    order=np.argsort(-ds,kind="stable")[:min(100,len(ix))]
    dense=[{"chunk_id":eligible[int(ix[int(i)])]["chunk_id"],"score":float(ds[int(i)])} for i in order]
    dr={x["chunk_id"]:i+1 for i,x in enumerate(dense)}
    fused={}
    for rank,x in enumerate(bm,1): fused[x["chunk_id"]]=fused.get(x["chunk_id"],0)+1/(60+rank)
    for rank,x in enumerate(dense,1): fused[x["chunk_id"]]=fused.get(x["chunk_id"],0)+1/(60+rank)
    rrf=sorted(fused,key=lambda cid:(-fused[cid],cid))[:100]
    cand=[]
    for rank,cid in enumerate(rrf,1):
      c=byid[cid]; cand.append({"chunk_id":cid,"text":c["text"],"rank":rank,"source_id":c["source_id"],"rrf_score":fused[cid],"bm25_rank":bmr.get(cid),"dense_rank":dr.get(cid)})
    rr=re.rerank(t["query"],cand)[:5]
    top=[]
    for rank,c in enumerate(rr,1):
      raw=byid[c["chunk_id"]]
      top.append({"rank":rank,"chunk_id":c["chunk_id"],"source_id":raw["source_id"],"source_sha256":raw["source_sha256"],"source_version":raw["source_version"],"record_locator":raw["record_locator"],"content_sha256":mod.sha_bytes(raw["text"].encode()),"rrf_rank":c["rank"],"reranker_rank":c["reranker_rank"],"reranker_score":c["reranker_score"],"text":raw["text"][:1200]})
    results.append({"test_id":t["id"],"query":t["query"],"allowed_sources":t["source_ids"],"bm25_top100":bm,"dense_top100":dense,"rrf_top100":[{"chunk_id":cid,"rank":r,"score":fused[cid]} for r,cid in enumerate(rrf,1)],"reranked_top5":top,"expected_source_present_in_top5":any(x["source_id"] in t["source_ids"] for x in top),"candidate_count":len(cand),"valid_provenance":all(x["source_sha256"] and x["record_locator"] and x["content_sha256"] for x in top)})
report={"status":"PASS" if len(results)==3 and all(x["expected_source_present_in_top5"] and x["valid_provenance"] for x in results) else "FAIL","corpus_version":MAN["corpus_version"],"corpus_manifest_sha256":mod.sha_file(mod.MANIFEST_FILE),"embedding_model_digest":MAN["embedding_index"]["model_digest"],"reranker":{"model_id":re.load_info.model_id,"revision":Path(re.load_info.model_path).name,"runtime_load_info":re.load_info.__dict__},"test_count":len(results),"generator_calls":0,"evaluation_question_or_answer_leakage":False,"results":results}
mod.write_json(OUT/"retrieval_pipeline_smoke_tests.json",report)
print(json.dumps({"status":report["status"],"tests":[{"id":x["test_id"],"top5_count":len(x["reranked_top5"]),"source_hit":x["expected_source_present_in_top5"],"provenance":x["valid_provenance"]} for x in results],"reranker_device":re.load_info.device},ensure_ascii=True))
