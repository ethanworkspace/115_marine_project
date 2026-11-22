import json, importlib.util
from pathlib import Path
ROOT=Path(r"C:\my project\115_marine_project")
L=ROOT/"reports/evaluation/fish_test_phase_l_20261016_190457"
spec=importlib.util.spec_from_file_location("phase_l",L/"phase_l_runner.py")
m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
print("ROOTS",str(m.RUN),str(m.PHASE_I),str(m.DOC_MANIFEST))
fixed=m.load_fixed_50(); print("fixed",len(fixed)); print("row",json.dumps(fixed[0],ensure_ascii=False))
trace=[json.loads(x) for x in (m.RUN/"retrieval_trace.jsonl").read_text(encoding="utf-8-sig").splitlines() if x.strip()]
print("trace",len(trace),"keys",sorted(trace[0].keys()),"example",json.dumps(trace[0],ensure_ascii=False)[:2500])
q=[json.loads(x) for x in (m.RUN/"fish_test_questions_normalized.jsonl").read_text(encoding="utf-8-sig").splitlines() if x.strip()]
print("questions",len(q),"keys",sorted(q[0].keys()),"example",json.dumps(q[0],ensure_ascii=False)[:2000])
print("model_call source",m.model_call.__code__.co_firstlineno)
print("page sample",repr(m.load_source_page(fixed[0]).get("page_text","")[:500]))
