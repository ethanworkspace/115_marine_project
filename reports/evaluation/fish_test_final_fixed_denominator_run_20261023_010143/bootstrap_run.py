"""Immutable input copies and protection audit for the authorized final run."""
from pathlib import Path
import sys,json,hashlib,shutil,datetime,requests,sqlite3,subprocess
sys.dont_write_bytecode=True
W=Path(__file__).resolve().parent;R=W.parents[2]
P=W.parent/'corpus_v3_grounded_answer_repair_20261022_164818'
I=W.parent/'fish_test_corpus_v3_frozen_run_20261021_133102'
def sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return h.hexdigest()
def write(n,v):(W/n).write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def jl(p):return [json.loads(x) for x in Path(p).read_text(encoding='utf-8-sig').splitlines() if x.strip()]
def baseline():
 m=json.loads((R/'reports/evaluation/final_model_selection/phase20/protected_inputs_before.json').read_text(encoding='utf-8-sig'));rows=[]
 for x in m['files']:
  v=sha(R/x['path']) if (R/x['path']).is_file() else None;rows.append({**x,'actual_sha256':v,'unchanged':v==x['sha256']})
 return {'total':len(rows),'unchanged':sum(x['unchanged'] for x in rows),'files':rows,'at':datetime.datetime.now().astimezone().isoformat()}
def visit(p):
 for c in p.iterdir():
  if c.is_symlink() or (hasattr(c,'is_junction') and c.is_junction()):continue
  if c.is_dir():yield from visit(c)
  elif c.is_file():yield c
def main():
 for d in ['prompts','streams','runtime','test_logs','app','results','corpus','outputs','previews']:(W/d).mkdir(exist_ok=True)
 b=baseline();write('protected_before.json',b);assert b['total']==b['unchanged']==636
 history=[{'path':str(p),'sha256':sha(p)} for folder in [P,I] for p in visit(folder)]
 for p in (R/'fish test').glob('*.xlsx'):history.append({'path':str(p),'sha256':sha(p)})
 extra=json.loads((I/'additional_protected_before.json').read_text(encoding='utf-8'))
 for x in (extra['files'] if isinstance(extra,dict) else extra):
  p=R/x['path'];v=sha(p);assert v==x['sha256'];history.append({'path':str(p),'sha256':v})
 write('historical_inputs_before.json',{'files':history})
 fm=json.loads((P/'final_active_policy_manifest.json').read_text(encoding='utf-8'))
 for x in fm['files']:assert sha(P/x['path'])==x['sha256'],x['path']
 names=['fair_grounded_rag_final.py','numeric_grounding_v3.py','arithmetic_parser_v4.py','runtime_base.py','retrieval_pipeline.py','fair_streamlit_app_final.py','questions_original_180.jsonl','verified_reference_answers_v3.jsonl','evaluation_rubrics_v3_frozen.json','reference_runtime_profiles.json','runtime_evidence_profiles_frozen.json','question_requirement_profiles_reviewed_180.jsonl','frozen_source_manifest.json','frozen_evaluation_manifest.json','fixed_denominator_scoring_policy.json','shared_contexts_180.jsonl','regression_positive_contexts_50.jsonl','context_precision_label_reuse_audit.json','query_provenance_caveat.json','reference_subset_coverage.json','supplemental_retrieval_trace.jsonl','test_answer_policy_final.py','test_numeric_grounding_v3.py','test_partial_gap_completion.py','test_arithmetic_parser_v4.py']
 for n in names:shutil.copy2(P/n,W/n)
 shutil.copy2(P/'runtime/grounded_answer_engine_v2.py',W/'runtime/grounded_answer_engine_v2.py')
 # Path-derived helpers write exclusively to this new workspace.
 shutil.copy2(P/'bootstrap_repair.py',W/'bootstrap_repair.py')
 (W/'fair_grounded_rag.py').write_text('from fair_grounded_rag_final import *\n',encoding='utf-8')
 db=I/'corpus/marine_hybrid_rag_corpus_v3.sqlite3';assert sha(db)=='b51b14bfdad0c31a1f64c50d79b511eadf03ce0d55fd8e3d7e59b9a7d350a99e'
 shutil.copy2(db,W/'corpus/marine_hybrid_rag_corpus_v3.sqlite3')
 old='ROOT / "reports/evaluation/fish_test_corpus_v3_frozen_run_20261021_133102/corpus/marine_hybrid_rag_corpus_v3.sqlite3"'
 for n in ['runtime_base.py','retrieval_pipeline.py']:
  text=(W/n).read_text(encoding='utf-8');assert old in text;text=text.replace(old,'WORK / "corpus" / "marine_hybrid_rag_corpus_v3.sqlite3"');(W/n).write_text(text,encoding='utf-8')
 with sqlite3.connect(f'file:{W.as_posix()}/corpus/marine_hybrid_rag_corpus_v3.sqlite3?mode=ro',uri=True) as c:assert c.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
 tags=requests.get('http://127.0.0.1:11434/api/tags',timeout=30).json();mf=json.loads((W/'frozen_evaluation_manifest.json').read_text(encoding='utf-8'));ident={}
 for mid,s in mf['models'].items():
  actual=next(x for x in tags['models'] if x['name']==s['tag']);assert actual['digest']==s['digest'];show=requests.post('http://127.0.0.1:11434/api/show',json={'model':s['tag']},timeout=30).json();ident[mid]={'runtime':actual,'show':show}
 assert ident['M3']['show']['model_info']['general.architecture']=='llama'
 write('model_runtime_identity.json',{'models':ident,'model_weight_full_bytes_rehashed':False,'verification_method':'Exact Ollama full digest and current architecture/quantization metadata','tags':tags})
 rows=jl(W/'shared_contexts_180.jsonl');refs=jl(W/'verified_reference_answers_v3.jsonl');assert len(rows)==len({r['question_id'] for r in rows})==180
 assert sum(bool(r.get('logical_rubric')) for r in refs)==37 and sum(bool(r.get('expected_calculation')) for r in refs)==13
 write('bootstrap_validation.json',{'passed':True,'protected':b['unchanged'],'history_files':len(history),'corpus_sha256':sha(W/'corpus/marine_hybrid_rag_corpus_v3.sqlite3'),'context_n':len(rows),'any_context':sum(bool(r['top5']) for r in rows),'full_top5':sum(len(r['top5'])==5 for r in rows),'owner_approvals_preserved':True,'production_changed':False})
 print('Bootstrap verified',len(rows),'questions; protected636; model4 identities; readonly copied identical Corpus',flush=True)
if __name__=='__main__':main()
