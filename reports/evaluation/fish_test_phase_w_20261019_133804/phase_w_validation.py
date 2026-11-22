from __future__ import annotations
import hashlib, importlib.util, json, sqlite3, sys
from pathlib import Path

W=Path(__file__).resolve().parent; ROOT=W.parents[2]
V=ROOT/"reports/evaluation/fish_test_phase_v_20261018_224918"; C=V/"corpus_v3_final"
for p in (ROOT/".venv-reranker/Lib/site-packages",ROOT/".venv/Lib/site-packages",ROOT,W/"app"):
    if str(p) not in sys.path: sys.path.insert(0,str(p))
def load(name,path):
    sp=importlib.util.spec_from_file_location(name,path); m=importlib.util.module_from_spec(sp); sys.modules[name]=m; sp.loader.exec_module(m); return m
core=load("phase_w_core",W/"phase_w_core.py")
smoke_path=W/"rag_v3_smoke_validation.json"
smoke=core.read_json(smoke_path if smoke_path.exists() else W/"rag_v3_end_to_end_validation.json")
manifest=core.read_json(C/"corpus_v3_final_manifest.json")
def sha(path):
    h=hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""): h.update(b)
    return h.hexdigest()
chunks=core.read_jsonl(C/"corpus_chunks_v3_final.jsonl")
by_id={x["chunk_id"]:x for x in chunks}
retrieval=core.read_jsonl(W/"retrieval_results_v3_updated.jsonl")
errors=[]; checked=0
for r in retrieval:
    for c in r.get("reranked_top5",[]):
        original=by_id.get(c["chunk_id"])
        if not original: errors.append({"question_id":r["question_id"],"chunk_id":c["chunk_id"],"reason":"chunk_id_missing_from_corpus"}); continue
        if original.get("retrieval_eligible") is not True: errors.append({"question_id":r["question_id"],"chunk_id":c["chunk_id"],"reason":"context_only_or_excluded"})
        if original.get("text")!=c.get("content"): errors.append({"question_id":r["question_id"],"chunk_id":c["chunk_id"],"reason":"content_mismatch"})
        if original.get("source_id")!=c.get("source_id"): errors.append({"question_id":r["question_id"],"chunk_id":c["chunk_id"],"reason":"source_id_mismatch"})
        if sha.__name__ and hashlib.sha256(c.get("content","").encode()).hexdigest()!=c.get("content_sha256"): errors.append({"question_id":r["question_id"],"chunk_id":c["chunk_id"],"reason":"content_digest_mismatch"})
        checked+=1
chunk_file=C/"corpus_chunks_v3_final.jsonl"; sqlite_file=C/"corpus_v3_final.sqlite3"; vector_file=C/"dense_vectors_v3_final.f32"
integrity={"corpus_version":manifest.get("corpus_version"),"chunk_records":len(chunks),"retrieval_eligible":sum(x.get("retrieval_eligible") is True for x in chunks),"context_only":sum(x.get("retrieval_eligible") is False for x in chunks),"chunk_jsonl_sha256_actual":sha(chunk_file),"chunk_jsonl_sha256_expected":manifest.get("chunk_jsonl_sha256"),"chunk_jsonl_checksum_match":sha(chunk_file)==manifest.get("chunk_jsonl_sha256"),"sqlite_sha256_actual":sha(sqlite_file),"sqlite_sha256_expected":manifest.get("sqlite_sha256"),"sqlite_checksum_match":sha(sqlite_file)==manifest.get("sqlite_sha256"),"dense_vectors_sha256_actual":sha(vector_file),"dense_vectors_sha256_expected":manifest.get("embedding_index",{}).get("vector_file_sha256"),"dense_vectors_checksum_match":sha(vector_file)==manifest.get("embedding_index",{}).get("vector_file_sha256"),"retrieval_records":len(retrieval),"top5_contexts_checked":checked,"context_trace_errors":errors,"all_contexts_retraceable":not errors}
core.write_json(W/"corpus_and_retrieval_integrity_v3.json",integrity)

species_tests=[]
def test_scope(sid, species, category, question, expected):
    candidates=[x for x in chunks if x.get("source_id")==sid and x.get("retrieval_eligible")]
    c=next((x for x in candidates if category in (json.loads(x.get("metadata_json") or "{}").get("category_scope") or [])),candidates[0])
    q={"species":species,"category":category,"question_text":question}
    p=core.query_profile(q); ok,reason=core.chunk_applicable(c,q,p)
    species_tests.append({"source_id":sid,"chunk_id":c["chunk_id"],"target_species":species,"category":category,"question":question,"expected_applicable":expected,"actual_applicable":ok,"reason":reason,"pass":ok==expected})
test_scope("TFRI-M17-GROUPER","吳郭魚","Fact","吳郭魚密度",False)
test_scope("TFRI-M17-GROUPER","石斑魚","Calculation","鞍帶石斑放養密度",True)
test_scope("TFRI-M17-GOLD-SEABASS","鱸魚","Water Quality","鱸魚水溫範圍",False)
test_scope("TFRI-M17-GOLD-SEABASS","鱸魚","Water Quality","金目鱸水溫範圍",True)
test_scope("FA-385-COLD","鰻魚","Climate / Cold","鰻魚寒害管理",False)
test_scope("FA-385-COLD","吳郭魚","Climate / Cold","吳郭魚寒害管理",True)
scope_report={"test_count":len(species_tests),"passed":sum(x["pass"] for x in species_tests),"tests":species_tests,"owner_approval_not_license":True}
core.write_json(W/"species_scope_regression_validation.json",scope_report)

app_report={"status":"pending","tested_file":str(W/"app"/"streamlit_app.py"),"notes":[]}
try:
    from streamlit.testing.v1 import AppTest
    at=AppTest.from_file(str(W/"app"/"streamlit_app.py"),default_timeout=20).run()
    app_report={"status":"passed" if not at.exception else "failed","exception_count":len(at.exception),"tested_file":str(W/"app"/"streamlit_app.py"),"title_count":len(at.title),"selectbox_count":len(at.selectbox),"text_area_count":len(at.text_area),"button_count":len(at.button),"exceptions":[str(x) for x in at.exception],"notes":["AppTest covers initial isolated application render only; API retrieval/generation were validated through real model smoke tests."]}
except Exception as e:
    app_report={"status":"failed","tested_file":str(W/"app"/"streamlit_app.py"),"exception":f"{type(e).__name__}: {e}","notes":["AppTest could not run in current environment."]}
interaction_path=W/"rag_v3_streamlit_interaction_validation.json"
if interaction_path.exists():
    interaction=core.read_json(interaction_path)
    app_report={"initial_render":app_report,"interactive_form_smoke":interaction,"status":"passed" if app_report.get("status")=="passed" and interaction.get("status")=="passed" and interaction.get("exception_count")==0 else "failed"}
core.write_json(W/"rag_v3_streamlit_validation.json",app_report)
result={"corpus_integrity":integrity,"species_scope_regression":scope_report,"streamlit":app_report,"smoke_passed":smoke.get("full_system_smoke_passed"),"isolated_runtime_validation_passed":not errors and scope_report["passed"]==scope_report["test_count"] and app_report.get("status")=="passed" and smoke.get("full_system_smoke_passed")}
core.write_json(W/"rag_v3_validation_preflight.json",result)
print(json.dumps(result,ensure_ascii=True,indent=2))
