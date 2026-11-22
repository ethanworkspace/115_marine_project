from __future__ import annotations
import importlib.util,json,sys
from pathlib import Path
W=Path(__file__).resolve().parent
for name,path in (("phase_w_core",W/"phase_w_core.py"),("rag_v3_phase_w",W/"app"/"rag_v3_phase_w.py")):
 sp=importlib.util.spec_from_file_location(name,path); m=importlib.util.module_from_spec(sp); sys.modules[name]=m; sp.loader.exec_module(m)
core=sys.modules["phase_w_core"]; engine=sys.modules["rag_v3_phase_w"].RAGEngine()
r=next(x for x in core.read_jsonl(W/"smoke_retrieval_results.jsonl") if x["question_id"]=="SMOKE-NO-EVIDENCE")
rows=[]
for mid in ("M1","M2","M3","M4"):
 row=engine.answer_with_retrieval(r["question_text"],r["species"],r["category"],mid,r,"phase_w_refusal_gate_smoke",evaluate_refusal=True)
 row.pop("retrieval",None); row["retrieval_ref"]={"question_id":r["question_id"],"top5_count":len(r.get("reranked_top5",[])),"context_digest":core.sha_text("")}
 rows.append(row); core.write_jsonl(W/"refusal_gate_test.jsonl",rows)
 print(mid,row.get("model_reported_status"),row.get("status"),row.get("safety_guard_applied"),row.get("citation_validation"),flush=True)
validation={"generator_calls":sum(x.get("generator_called") is True for x in rows),"safe_effective_abstentions":sum(x.get("status")=="abstain" and x.get("safety_guard_applied") is True for x in rows),"model_raw_outputs":sum(x.get("model_reported_status") is not None for x in rows),"pass":len(rows)==4 and all(x.get("status")=="abstain" and x.get("safety_guard_applied") is True and x.get("citation_validation",{}).get("valid") is True for x in rows),"note":"Raw model outputs are retained; only the safety-guarded response is considered effective output when no qualified context exists."}
core.write_json(W/"refusal_gate_test_summary.json",validation); print(json.dumps(validation,ensure_ascii=True,indent=2))
