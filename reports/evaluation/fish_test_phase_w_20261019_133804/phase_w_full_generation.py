from __future__ import annotations
import ctypes, importlib.util, json, os, subprocess, sys, threading, time, traceback
from collections import Counter
from pathlib import Path

W=Path(__file__).resolve().parent
ROOT=W.parents[2]
V=ROOT/"reports/evaluation/fish_test_phase_v_20261018_224918"
for name,path in (("phase_w_core",W/"phase_w_core.py"),("rag_v3_phase_w",W/"app"/"rag_v3_phase_w.py")):
    spec=importlib.util.spec_from_file_location(name,path); mod=importlib.util.module_from_spec(spec); sys.modules[name]=mod; spec.loader.exec_module(mod)
core=sys.modules["phase_w_core"]; Engine=sys.modules["rag_v3_phase_w"].RAGEngine
retrievals=core.read_jsonl(W/"retrieval_results_v3_updated.jsonl")
questions=core.read_jsonl(V/"question_eligibility_v3.jsonl")
retrieval_by={r["question_id"]:r for r in retrievals}
q_by={q["question_id"]:q for q in questions}
if len(retrievals)!=180 or set(retrieval_by)!=set(q_by): raise RuntimeError("Question/retrieval ID mismatch")
out_path=W/"generator_results_v3.jsonl"
done=set()
if out_path.exists():
    for r in core.read_jsonl(out_path):
        if r.get("status") in ("answered","abstain","invalid_output"):
            done.add((r.get("question_id"),r.get("model_id")))

state={"model_id":None,"question_id":None,"active":False}
stop=threading.Event(); sample_lock=threading.Lock(); samples=[]

class MEMORYSTATUSEX(ctypes.Structure):
    _fields_=[("dwLength",ctypes.c_ulong),("dwMemoryLoad",ctypes.c_ulong),("ullTotalPhys",ctypes.c_ulonglong),("ullAvailPhys",ctypes.c_ulonglong),("ullTotalPageFile",ctypes.c_ulonglong),("ullAvailPageFile",ctypes.c_ulonglong),("ullTotalVirtual",ctypes.c_ulonglong),("ullAvailVirtual",ctypes.c_ulonglong),("ullAvailExtendedVirtual",ctypes.c_ulonglong)]

def sample_hardware():
    ram=None; ram_load=None; gpu_used=None; gpu_total=None; gpu_status="unavailable"
    try:
        x=MEMORYSTATUSEX(); x.dwLength=ctypes.sizeof(MEMORYSTATUSEX)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(x)):
            ram=(x.ullTotalPhys-x.ullAvailPhys)/(1024**3); ram_load=x.dwMemoryLoad
    except Exception: pass
    try:
        r=subprocess.run(["nvidia-smi","--query-gpu=memory.used,memory.total","--format=csv,noheader,nounits"],capture_output=True,text=True,timeout=4)
        if r.returncode==0 and r.stdout.strip():
            a=r.stdout.strip().splitlines()[0].split(","); gpu_used=int(a[0].strip()); gpu_total=int(a[1].strip()); gpu_status="nvidia-smi system-level sample"
    except Exception as e: gpu_status=f"unavailable: {type(e).__name__}"
    return {"sampled_at_unix":time.time(),"model_id":state["model_id"],"question_id":state["question_id"],"system_ram_used_gib":ram,"system_ram_load_percent":ram_load,"dedicated_vram_used_mib":gpu_used,"dedicated_vram_total_mib":gpu_total,"shared_gpu_memory_mib":None,"measurement_scope":"system_level_sampled_peak","gpu_measurement_status":gpu_status}

def sampler():
    while not stop.wait(2.0):
        row=sample_hardware()
        with sample_lock:
            samples.append(row)
        with (W/"hardware_samples_v3.jsonl").open("a",encoding="utf-8") as f:
            f.write(json.dumps(row,ensure_ascii=False,separators=(",",":"))+"\n")
        if len(samples)%15==0:
            with (W/"hardware_samples_v3.jsonl").open("a",encoding="utf-8") as f: f.flush()

def append_row(row):
    with out_path.open("a",encoding="utf-8") as f:
        f.write(json.dumps(row,ensure_ascii=False,separators=(",",":"))+"\n"); f.flush(); os.fsync(f.fileno())

engine=Engine(); started=time.time(); errors=0; new_count=0
thread=threading.Thread(target=sampler,daemon=True); thread.start()
try:
    for mid in ("M1","M2","M3","M4"):
        print(f"START {mid}: pending {sum((q,mid) not in done for q in q_by)}",flush=True)
        for qid,q in q_by.items():
            if (qid,mid) in done: continue
            state.update({"model_id":mid,"question_id":qid,"active":True})
            retrieval=retrieval_by[qid]
            contexts=retrieval.get("reranked_top5",[])
            context_digest=core.sha_text(json.dumps([{k:c.get(k) for k in ("chunk_id","source_id","content_sha256","source_version","page_or_locator")} for c in contexts],ensure_ascii=False,sort_keys=True))
            result=None; err=None
            for attempt in range(2):
                try:
                    result=engine.answer_with_retrieval(q.get("question_text",""),q.get("species",""),q.get("category",""),mid,retrieval,"phase_w_integrated_v1",evaluate_refusal=True)
                    result["api_attempts"]=attempt+1
                    break
                except Exception as e:
                    err=f"{type(e).__name__}: {e}"
                    if attempt==0: time.sleep(1)
            if result is None:
                errors+=1
                result={"run_id":"phase_w_integrated_v1","question_id":qid,"model_id":mid,"model_tag":core.MODELS[mid][0],"model_digest":core.MODELS[mid][1],"generator_called":False,"status":"api_error","error":err,"api_attempts":2,"citation_validation":{"valid":False,"reason":"generation request failed"},"timing":None}
            result["species"]=q.get("species"); result["category"]=q.get("category"); result["question_text"]=q.get("question_text")
            result["retrieval_ref"]={"question_id":qid,"corpus_version":retrieval.get("corpus_version"),"top5_count":len(contexts),"chunk_ids":[c["chunk_id"] for c in contexts],"context_digest":context_digest,"retrieval_status":retrieval.get("retrieval_status")}
            # Keep the full user prompt and response, but avoid duplicating the full retrieval record in 4 model rows.
            result.pop("retrieval",None)
            result["question_answer_status"]="EXPECTED_ABSTENTION_CANDIDATE" if result.get("safety_guard_applied") else ("NOT_EVALUABLE_REFERENCE" if result.get("status")=="answered" else "MODEL_ABSTAINED")
            append_row(result); new_count+=1
            if new_count%10==0 or errors:
                print(f"{new_count} new tasks; completed={len(done)+new_count}/720; api_errors={errors}; current={mid}/{qid}; status={result.get('status')}; contexts={len(contexts)}",flush=True)
finally:
    state.update({"active":False,"model_id":None,"question_id":None}); stop.set(); thread.join(timeout=5)

all_rows=core.read_jsonl(out_path)
by_model={}
for mid in core.MODELS:
    mr=[x for x in all_rows if x.get("model_id")==mid]
    by_model[mid]={"records":len(mr),"generator_api_calls":sum(x.get("generator_called") is True for x in mr),"answered_effective":sum(x.get("status")=="answered" for x in mr),"effective_abstentions":sum(x.get("status")=="abstain" for x in mr),"safety_guard_overrides":sum(x.get("safety_guard_applied") is True for x in mr),"structured_or_citation_invalid":sum(x.get("citation_validation",{}).get("valid") is False for x in mr),"api_errors":sum(x.get("status")=="api_error" for x in mr),"tps_n":sum((x.get("timing") or {}).get("tps") is not None for x in mr)}
all_samples=core.read_jsonl(W/"hardware_samples_v3.jsonl") if (W/"hardware_samples_v3.jsonl").exists() else []
peaks={"measurement_scope":"system_level_sampled_peak","system_ram_used_gib_max":max((x["system_ram_used_gib"] for x in all_samples if x.get("system_ram_used_gib") is not None),default=None),"dedicated_vram_used_mib_max":max((x["dedicated_vram_used_mib"] for x in all_samples if x.get("dedicated_vram_used_mib") is not None),default=None),"shared_gpu_memory_mib":None,"sample_count":len(all_samples)}
core.write_json(W/"generator_run_summary_v3.json",{"run_id":"phase_w_integrated_v1","target_records":720,"completed_records":len(all_rows),"new_records_this_execution":new_count,"models":by_model,"api_errors":errors,"hardware_peaks":peaks,"started_unix":started,"finished_unix":time.time(),"resume_enabled":True,"source_accuracy_gold":False,"note":"Each question uses one shared Phase W retrieval context. Context-insufficient tasks call the generator only for abstention behavior measurement; a deterministic post-generation safety gate forces the displayed result to abstain. Raw model output is preserved separately."})
print(json.dumps({"new_records":new_count,"completed_records":len(all_rows),"errors":errors,"models":by_model,"hardware_peaks":peaks},ensure_ascii=True,indent=2),flush=True)
