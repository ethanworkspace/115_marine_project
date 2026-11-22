import json
from pathlib import Path

ROOT = Path(r"C:\my project\115_marine_project")
P = ROOT / "reports/evaluation/fish_test_phase_l_20261016_190457"

def readj(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))

def readl(path):
    out=[]
    for n,line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(),1):
        if line.strip():
            try: out.append(json.loads(line))
            except Exception as e: print("BAD",path.name,n,repr(e))
    return out

for name in ["pilot_50_chunk_results_v3.jsonl","pilot_50_chunk_results_v3_reconciled.jsonl","pilot_10_chunk_results_v3_reconciled.jsonl","judge_call_archive_v3.jsonl"]:
    rows=readl(P/name)
    print("FILE",name,"ROWS",len(rows))
    if rows: print("KEYS",sorted(rows[0].keys()))

rows=readl(P/"pilot_50_chunk_results_v3_reconciled.jsonl")
for r in rows:
    if r.get("validated_pair_status")=="ANNOTATION_ERROR":
        print("ERR", json.dumps({k:r.get(k) for k in ["question_id","species","category","question_text","chunk_id","document_id","rank","validated_final_label","round_1","round_2","postrun_validation_v2"]},ensure_ascii=False))

from importlib.util import spec_from_file_location, module_from_spec
spec=spec_from_file_location("phase_l",P/"phase_l_runner.py")
mod=module_from_spec(spec); spec.loader.exec_module(mod)
fixed=mod.load_fixed_50()
print("FIXED50",len(fixed),"QIDS",sorted({r["question_id"] for r in fixed}))
for r in fixed:
    if r["question_id"] in {"FT-mullet-Q01","FT-grouper-Q01","FT-milkfish-Q01"}:
        print("ROW",json.dumps({k:r.get(k) for k in ["question_id","question_species","question_text","chunk_id","document_id","rank","page","source_id","source_title","source_version","document_species","document_file_path","chunk_text"]},ensure_ascii=False))

allq=readl(ROOT/"reports/evaluation/fish_test_run_20261012_152244/fish_test_questions_normalized.jsonl")
print("ALLQ",len(allq),"QKEYS",sorted(allq[0].keys()) if allq else [])
print("SAMPLEQ",json.dumps(allq[0],ensure_ascii=False))

print("TOP LEVEL SUMMARY")
s=readj(P/"phase_l_postrun_summary.json")
print(json.dumps(s,ensure_ascii=False,indent=2)[:10000])

print("RUNNER FUNCS")
src=(P/"phase_l_runner.py").read_text(encoding="utf-8-sig")
for term in ["def load_fixed_50","def load_source_page","def spans_for","def model_call","def assess_species_scope","def preflight","OLLAMA"]:
    idx=src.find(term)
    print("TERM",term,"AT",idx)
    if idx>=0: print(src[idx:idx+1800])
