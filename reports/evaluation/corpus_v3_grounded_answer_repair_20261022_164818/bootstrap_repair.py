from pathlib import Path
import sys,json,hashlib,shutil,datetime,requests
sys.dont_write_bytecode=True
W=Path(__file__).resolve().parent;R=W.parents[2];I=W.parent/'fish_test_corpus_v3_frozen_run_20261021_133102'
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
 return {'total':len(rows),'unchanged':sum(x['unchanged'] for x in rows),'files':rows,'at':datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).isoformat()}
def snapshot():
 paths=[]
 def visit(p):
  for c in p.iterdir():
   if c.is_symlink() or (hasattr(c,'is_junction') and c.is_junction()):continue
   if c.is_dir():visit(c)
   elif c.is_file():paths.append({'path':str(c),'sha256':sha(c)})
 visit(I)
 for p in (R/'fish test').glob('*.xlsx'):paths.append({'path':str(p),'sha256':sha(p)})
 return paths
if __name__=='__main__':
 b=baseline();write('protected_before.json',b);assert b['total']==b['unchanged']==636
 write('historical_inputs_before.json',{'files':snapshot()})
 names=['questions_original_180.jsonl','verified_reference_answers_v3.jsonl','evaluation_rubrics_v3_frozen.json','reference_runtime_profiles.json','runtime_evidence_profiles_frozen.json','question_requirement_profiles_reviewed_180.jsonl','frozen_source_manifest.json','frozen_evaluation_manifest.json','retrieved_chunk_support_labels.jsonl']
 for n in names:shutil.copy2(I/n,W/n)
 (W/'runtime').mkdir(exist_ok=True)
 shutil.copy2(I/'runtime/grounded_answer_engine_v2.py',W/'runtime/grounded_answer_engine_v2.py')
 dbexpr='ROOT / "reports/evaluation/fish_test_corpus_v3_frozen_run_20261021_133102/corpus/marine_hybrid_rag_corpus_v3.sqlite3"'
 for src,dest in [('retrieve_and_verify_180.py','retrieval_pipeline.py'),('rag_v3_runtime.py','runtime_base.py')]:
  s=(I/src).read_text(encoding='utf-8');s=s.replace('DB = WORK / "corpus" / "marine_hybrid_rag_corpus_v3.sqlite3"','DB = '+dbexpr).replace('WORK / "retrieve_and_verify_180.py"','WORK / "retrieval_pipeline.py"').replace('sqlite3.connect(DB)','sqlite3.connect(f"file:{DB}?mode=ro", uri=True)');(W/dest).write_text(s,encoding='utf-8')
 tags=requests.get('http://127.0.0.1:11434/api/tags',timeout=20).json();m=json.loads((I/'frozen_evaluation_manifest.json').read_text(encoding='utf-8'))
 for mid,s in m['models'].items():assert next(x for x in tags['models'] if x['name']==s['tag'])['digest']==s['digest']
 show=requests.post('http://127.0.0.1:11434/api/show',json={'model':m['models']['M3']['tag']},timeout=30).json();assert show['model_info']['general.architecture']=='llama'
 write('model_identity.json',{'models':m['models'],'M3_actual_metadata':show,'model_weight_full_bytes_rehashed':False,'method':'Exact Ollama digest plus saved/current architecture metadata'})
 for n in ['prompts','streams','test_logs','app','results']:(W/n).mkdir(exist_ok=True)
 write('bootstrap_integrity.json',{'database':str(I/'corpus/marine_hybrid_rag_corpus_v3.sqlite3'),'sha256':sha(I/'corpus/marine_hybrid_rag_corpus_v3.sqlite3'),'production':False,'historical_owner_approvals_preserved':True})
 print('Isolated bootstrap complete; model digests and baseline verified',flush=True)
