from pathlib import Path
import json, hashlib, shutil, sqlite3, datetime

W=Path(__file__).resolve().parent
R=W.parents[2]
OLD=R/'reports/evaluation/fish_test_corpus_v3_integration_20261021_003519'
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
 return h.hexdigest()
def jl(p):return [json.loads(s) for s in p.read_text(encoding='utf-8-sig').splitlines() if s.strip()]
def wr(p,d):p.write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
for d in ['corpus','runtime','input_snapshot','evidence_review','test_logs']: (W/d).mkdir(exist_ok=True)
files=['corpus_v3_manifest.json','source_admission_v3.json','approved_official_sources_v3.json','official_raw_data_integrity_report.json','evaluation_readiness_v3.json','corpus_v3_source_coverage.json']
inputs=[]
for name in files:
 p=OLD/name;inputs.append({'path':str(p),'sha256':sha(p),'size_bytes':p.stat().st_size});shutil.copy2(p,W/'input_snapshot'/name)
for name in ['rag_v3_runtime.py','retrieve_and_verify_180.py','streamlit_v3_app.py']:
 shutil.copy2(OLD/name,W/name)
shutil.copy2(OLD/'runtime/grounded_answer_engine_v2.py',W/'runtime/grounded_answer_engine_v2.py')
db=OLD/'corpus/marine_hybrid_rag_corpus_v3.sqlite3';shutil.copy2(db,W/'corpus/marine_hybrid_rag_corpus_v3.sqlite3')
inputs.append({'path':str(db),'sha256':sha(db),'size_bytes':db.stat().st_size,'immutable_input':True})
qf=R/'reports/evaluation/fish_test_phase_a_20261012/fish_test_questions_normalized.jsonl'
qs=jl(qf)
(W/'questions_original_180.jsonl').write_text(''.join(json.dumps(q,ensure_ascii=False)+'\n' for q in qs),encoding='utf-8')
with (W/'evidence_review/questions_for_review.md').open('w',encoding='utf-8') as f:
 for q in qs:f.write(f"{q['question_id']} [{q['inferred_category']}] {q['question_text']}\n")
c=sqlite3.connect(db);c.row_factory=sqlite3.Row
qarecs=[]
for r in c.execute("SELECT source_record_id,eligibility_status,original_record_json FROM source_records WHERE source_id='MOA-TFRI-OPEN-114846' ORDER BY source_record_id"):
 x=json.loads(r['original_record_json']);qarecs.append({'source_record_id':r['source_record_id'],'current_eligibility':r['eligibility_status'],**x})
(W/'evidence_review/tfri_original_956.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in qarecs),encoding='utf-8')
wr(W/'input_provenance_manifest.json',{'created_at':datetime.datetime.now().astimezone().isoformat(),'inputs':inputs,'question_count':len(qs),'source_qa_records':len(qarecs),'production_switch':False})
print(json.dumps({'workspace':str(W),'question_count':len(qs),'qa_records':len(qarecs),'input_database_sha256':sha(db)},ensure_ascii=True))
