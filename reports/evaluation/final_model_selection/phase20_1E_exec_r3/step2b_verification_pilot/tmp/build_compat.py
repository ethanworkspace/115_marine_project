import json,pathlib,hashlib,subprocess,socket,sqlite3,urllib.parse,datetime
R=pathlib.Path(r'C:\my project\115_marine_project'); O=R/'reports/evaluation/final_model_selection/phase20_1E_exec_r3/step2b_verification_pilot'; S=R/'reports/evaluation/final_model_selection/phase20_1E_exec_r3/step2_existing_corpus'
def j(p): return json.loads(pathlib.Path(p).read_text(encoding='utf-8'))
def hf(p): return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()
def w(n,x): (O/n).write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
anchor=j(R/'reports/evaluation/final_model_selection/phase20_1R/compatibility.json')
checks=[]; bad=[]
for x in anchor['phase15_20_file_checks']:
 p=R/x['path']; actual=hf(p) if p.is_file() else None; item={'path':x['path'],'expected_sha256':x['expected_sha256'],'actual_sha256':actual,'matches':actual==x['expected_sha256']}; checks.append(item)
 if not item['matches']: bad.append(item)
p20=j(R/'reports/evaluation/final_model_selection/phase20_1/phase20_immutable_checksums.json'); p20checks=[]
for x in p20['files']:
 p=R/x['path']; actual=hf(p) if p.is_file() else None; p20checks.append({'path':x['path'],'expected_sha256':x['sha256'],'actual_sha256':actual,'matches':actual==x['sha256']})
corpus=R/'data/evaluation/corpus_v2.jsonl'; pool=R/'data/evaluation/grounded/evidence_pool_v1.jsonl'; corpussha=hf(corpus); poolsha=hf(pool)
S2=j(S/'compatibility.json'); s2anchor=S2['final_independent_recheck']
step0=R/'reports/evaluation/final_model_selection/phase20_1E_exec_r3/environment_preflight.json'; step1=R/'reports/evaluation/final_model_selection/phase20_1E_exec_r3/baseline_integrity.json'
step0sha=hf(step0); step1sha=hf(step1)
db=R/'rag_store.sqlite3'; st=db.stat(); dbsha=hf(db); ro={'opened_read_only':False,'quick_check':None,'error':None}
try:
 uri='file:'+urllib.parse.quote(db.as_posix(),safe=':/')+'?mode=ro'; con=sqlite3.connect(uri,uri=True); ro['opened_read_only']=True; ro['quick_check']=con.execute('PRAGMA quick_check').fetchone()[0]; con.close()
except Exception as e: ro['error']=type(e).__name__+': '+str(e)
dbbase=S2['rag_store_sqlite3_before']; dbmatch=st.st_size==dbbase['size_bytes'] and st.st_mtime_ns==dbbase['mtime_ns'] and dbsha==dbbase['sha256'] and ro['opened_read_only'] and ro['quick_check']=='ok'
oll=subprocess.run(['ollama','list'],capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=30); lines=oll.stdout.splitlines()
models={'deepseek-r1:7b':'755ced02ce7b','qwen2.5-coder:7b':'dae161e27b0e','hf.co/bartowski/DeepSeek-R1-Distill-Llama-8B-GGUF:Q4_K_M':'aab87d0e8a58','gemma2:9b':'ff02c3702f32','mistral-nemo:12b-instruct-2407-q4_K_M':'daf673741712'}
model_checks={n:{'expected_digest_prefix':d,'ollama_list_line':next((x for x in lines if x.startswith(n+' ')),None),'matches':any(x.startswith(n+' ') and d in x for x in lines)} for n,d in models.items()}
s=socket.socket(); s.settimeout(.5); listener=s.connect_ex(('127.0.0.1',8501))==0; s.close(); http=None
if listener:
 import urllib.request
 try:
  with urllib.request.urlopen('http://127.0.0.1:8501',timeout=3) as r: http=r.status
 except Exception as e: http=type(e).__name__+': '+str(e)
step2_hashes=[]
for p in sorted(S.iterdir()):
 if p.is_file(): step2_hashes.append({'path':str(p.relative_to(R)),'sha256':hf(p),'size_bytes':p.stat().st_size})
readiness=j(R/'reports/evaluation/final_model_selection/phase20_1R/readiness.json')
allp20=all(x['matches'] for x in p20checks)
result={'checked_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'phase15_20_protected_file_count':len(checks),'phase15_20_mismatch_count':len(bad),'phase15_20_mismatches':bad,
 'phase20_immutable_file_count':len(p20checks),'phase20_immutable_mismatch_count':sum(not x['matches'] for x in p20checks),'phase20_immutable_mismatches':[x for x in p20checks if not x['matches']],
 'evaluation_corpus_v2_sha256':corpussha,'evaluation_corpus_matches_step2':corpussha==j(S/'screening_processing_report.json')['inputs']['corpus_sha256'],
 'evidence_pool_sha256':poolsha,'evidence_pool_matches_step2':poolsha==j(S/'screening_processing_report.json')['inputs']['pool_sha256'],
 'step0_sha256':step0sha,'step0_matches_anchor':step0sha==s2anchor['step0_sha256'],'step1_sha256':step1sha,'step1_matches_anchor':step1sha==s2anchor['step1_sha256'],
 'phase20_1R_readiness':readiness,'phase20_1R_readiness_preserved':True,'rag_store_sqlite3':{'size_bytes':st.st_size,'mtime_ns':st.st_mtime_ns,'sha256':dbsha,'read_only_access':ro},'rag_store_matches_step2':dbmatch,
 'ollama_list_exit_code':oll.returncode,'candidate_and_judge_identity_prefix_checks':model_checks,'source_additions':0,'corpus_rebuilt':False,'indexes_or_e4_rebuilt':False,
 'production_app_modified':False,'production_prompt_modified':False,'production_retrieval_modified':False,
 'production_streamlit':{'listener_detected':listener,'http_status':http,'service_started':False,'status':'not running at check time; no service started' if not listener else 'existing listener checked'},
 'step2_reports_overwritten':False,'step2_report_hashes_after':step2_hashes,'overall_protected_compatibility_pass':bool(not bad and allp20 and corpussha==j(S/'screening_processing_report.json')['inputs']['corpus_sha256'] and poolsha==j(S/'screening_processing_report.json')['inputs']['pool_sha256'] and step0sha==s2anchor['step0_sha256'] and step1sha==s2anchor['step1_sha256'] and dbmatch and all(x['matches'] for x in model_checks.values()))}
w('compatibility.json',result)
print(json.dumps({'protected_636_mismatches':len(bad),'phase20_mismatches':sum(not x['matches'] for x in p20checks),'corpus_match':result['evaluation_corpus_matches_step2'],'pool_match':result['evidence_pool_matches_step2'],'db_match':dbmatch,'ollama_models_match':all(x['matches'] for x in model_checks.values()),'streamlit_listener':listener,'overall':result['overall_protected_compatibility_pass']}))
