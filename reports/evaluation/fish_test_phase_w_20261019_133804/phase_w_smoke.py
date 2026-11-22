from __future__ import annotations
import importlib.util, json, sys, time, traceback
from pathlib import Path

W=Path(__file__).resolve().parent
core_path=W/"phase_w_core.py"
app_path=W/"app"/"rag_v3_phase_w.py"
for name,path in (("phase_w_core",core_path),("rag_v3_phase_w",app_path)):
    spec=importlib.util.spec_from_file_location(name,path); mod=importlib.util.module_from_spec(spec); sys.modules[name]=mod; spec.loader.exec_module(mod)
core=sys.modules["phase_w_core"]; engine=sys.modules["rag_v3_phase_w"].RAGEngine()

queries=[
 {"question_id":"SMOKE-EVIDENCE-GROUPER","species":"石斑魚","category":"Calculation","question_text":"依鞍帶石斑資料，放養密度建議範圍是多少尾/公頃？"},
 {"question_id":"SMOKE-FEW-EEL","species":"鰻魚","category":"Disease","question_text":"水黴病相關描述及診斷限制是什麼？"},
 {"question_id":"SMOKE-NO-EVIDENCE","species":"鰻魚","category":"Water Quality","question_text":"鰻魚池溶氧應維持多少 mg/L？"},
 {"question_id":"SMOKE-SCOPE-CONFLICT","species":"鱸魚","category":"Water Quality","question_text":"鱸魚的最佳水溫範圍是多少？"},
]
retrieval=core.retrieve_180(queries,output_path=W/"smoke_retrieval_results.jsonl")
out=[]; started=time.time()
for q,r in zip(queries,retrieval):
  for mid in ("M1","M2","M3","M4"):
    try:
      row=engine.answer_with_retrieval(q["question_text"],q["species"],q["category"],mid,r,"phase_w_smoke")
      row["smoke_case"]=q["question_id"]
      row["context_count"]=r["final_top5_count"]
      row["expected_test_type"]="eligible_evidence" if r["final_top5_count"] else ("species_scope_conflict" if q["question_id"].endswith("CONFLICT") else "no_evidence")
      out.append(row)
    except Exception as e:
      out.append({"run_id":"phase_w_smoke","question_id":r["question_id"],"smoke_case":q["question_id"],"model_id":mid,"generator_called":False,"status":"error","error":f"{type(e).__name__}: {e}","traceback":traceback.format_exc(),"context_count":r["final_top5_count"]})
    core.write_jsonl(W/"smoke_generation_results.jsonl",out)
    print(f"smoke {q['question_id']} {mid} status={out[-1].get('status')} called={out[-1].get('generator_called')}",flush=True)

all_models={}
for mid,(tag,digest) in core.MODELS.items():
  all_models[mid]={"tag":tag,"expected_digest":digest,"actual_digest":None}
try:
  import requests
  tags=requests.get(f"{core.OLLAMA}/api/tags",timeout=10).json().get("models",[])
  for mid,(tag,digest) in core.MODELS.items():
    actual=next((x.get("digest","").removeprefix("sha256:") for x in tags if x.get("name")==tag),None)
    all_models[mid]["actual_digest"]=actual
    all_models[mid]["identity_match"]=actual==digest
except Exception as e:
  for x in all_models.values(): x["identity_error"]=f"{type(e).__name__}: {e}"

calls=[x for x in out if x.get("generator_called")]
answered=[x for x in calls if x.get("status")=="answered"]
validation={
 "phase":"W", "smoke_cases":len(queries), "expected_coverage":["evidence","limited_context","no_evidence","species_scope_conflict"],
 "retrieval":{"cases":[{"question_id":r["question_id"],"context_count":r["final_top5_count"],"sources":sorted({x["source_id"] for x in r["reranked_top5"]}),"status":r["retrieval_status"]} for r in retrieval]},
 "models":all_models,"generator_calls":len(calls),"deterministic_abstentions":sum(x.get("generator_called") is False and x.get("status")=="abstain" for x in out),
 "valid_json_and_citation_results":sum(x.get("citation_validation",{}).get("valid") is True for x in out),
 "answered_outputs":len(answered),"invalid_or_error_outputs":sum(x.get("status") in ("invalid_output","error") or x.get("citation_validation",{}).get("valid") is False for x in out),
 "all_four_models_real_api_smoke_passed":all(x.get("identity_match") for x in all_models.values()) and len({x.get("model_id") for x in calls})==4 and len(calls)>=4,
 "citation_smoke_passed":all(x.get("citation_validation",{}).get("valid") is True for x in out),
 "safe_empty_context_abstention_passed":all(x.get("status")=="abstain" and not x.get("generator_called") for x in out if x.get("context_count")==0),
 "full_system_smoke_passed":False,"started_at_unix":started,"duration_seconds":time.time()-started,
 "limitations":["Smoke generation is not a correctness benchmark.","No Context Precision labels or professional Gold answers were created.","A deterministic abstention path bypasses generators by policy."]}
validation["full_system_smoke_passed"]=bool(validation["all_four_models_real_api_smoke_passed"] and validation["citation_smoke_passed"] and validation["safe_empty_context_abstention_passed"] and validation["invalid_or_error_outputs"]==0 and validation["answered_outputs"]>0)
core.write_json(W/"rag_v3_end_to_end_validation.json",validation)
print(json.dumps({"validation":validation,"results":len(out)},ensure_ascii=True,indent=2))
