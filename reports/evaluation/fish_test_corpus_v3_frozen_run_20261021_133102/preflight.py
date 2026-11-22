from pathlib import Path
import json,sys,copy,subprocess,os,hashlib,datetime
W=Path(__file__).resolve().parent;R=W.parents[2];sys.path.insert(0,str(W));sys.stdout.reconfigure(encoding='utf-8')
from frozen_runner import FrozenRag,MODELS,OPTIONS,SCHEMA,SYSTEM,POLICY,PROMPT_VERSION,digest,unload,write,jl,sha
PY=R/'reports/evaluation/fish_test_corpus_v3_evidence_alignment_20261021_022237/test_env/Scripts/python.exe'
def repository():
 env=os.environ.copy();env['PYTHONPATH']=os.pathsep.join([str(R/'.venv-reranker/Lib/site-packages'),str(R/'.venv/Lib/site-packages'),str(R)]);env['PYTHONIOENCODING']='utf-8'
 cmd=[str(PY),'-m','pytest','tests/','-q','-p','no:cacheprovider','--basetemp',str(W/'repository_pytest_temp')]
 with (W/'test_logs/repository_pytest.log').open('w',encoding='utf-8') as f:p=subprocess.run(cmd,cwd=R,env=env,stdout=f,stderr=subprocess.STDOUT)
 log=(W/'test_logs/repository_pytest.log').read_text(encoding='utf-8')
 versions=subprocess.run([str(PY),'-c',"import sys,pytest,torch,streamlit,docx,pymupdf,psutil; print(sys.executable);print(sys.version);print({k:globals()[k].__version__ for k in ['pytest','torch','streamlit','docx','pymupdf','psutil']})"],env=env,cwd=R,capture_output=True,text=True,encoding='utf-8')
 out={'command':cmd,'interpreter':str(PY),'exit_code':p.returncode,'summary_lines':[s for s in log.splitlines() if any(t in s for t in [' passed',' failed',' skipped','ERROR','collected'])][-30:],'full_log':str(W/'test_logs/repository_pytest.log'),'versions':versions.stdout,'version_error':versions.stderr,'scope':'all formal tests/; historical reports and temporary folders are outside test suite','production_environment_modified':False}
 write('repository_pytest_results.json',out);print(json.dumps(out,ensure_ascii=False),flush=True)
def smoke():
 rt=FrozenRag();rows=rt.rows;avail=jl(W/'corpus_evidence_availability_180.jsonl')
 positive=copy.deepcopy(rt.retrieval['FT-milkfish-Q04'])
 cases=[('FULL_SOURCE',positive),('PARTIAL_SOURCE',rt.retrieval['FT-tilapia-Q01']),('NO_CONTEXT',next(r for r in rows if not r['top5'])),('MEDICATION_UNVERIFIED',rt.retrieval['FT-tilapia-Q28']),('MISSING_CONDITIONS',rt.retrieval[next(a['question_id'] for a in avail if a['gap_classification']=='QUESTION_CONDITIONS_MISSING')])]
 wrong=copy.deepcopy(positive);wrong.update(species='鰻魚',question_id='CONTROLLED-WRONG-SPECIES',context_digest=digest(wrong['top5']));cases.append(('WRONG_SPECIES_CONTROLLED_CONTEXT',wrong))
 out=[];prior=jl(W/'smoke_results.jsonl') if (W/'smoke_results.jsonl').exists() else [];done={(r['model_id'],r['test_case']) for r in prior if r['prompt_version']==PROMPT_VERSION}
 from frozen_runner import append
 for mid in MODELS:
  for case,r in cases:
   if (mid,case) in done:continue
   a=rt.call(r,mid,stage='SMOKE');a['test_case']=case
   final=a['final_response'];passed=a['api_completed'] and a['raw_model_structure_valid']
   if case=='FULL_SOURCE':passed=passed and not final['abstained'] and '1.3' in str(final['answer']) and a['final_citation_validation']['status']=='PASS'
   else:passed=passed and final['abstained']
   a['test_passed']=bool(passed);append('smoke_results.jsonl',a);out.append(a);print(json.dumps({'model':mid,'case':case,'pass':passed,'origin':a['answer_origin'],'api_seconds':a['wall_seconds'],'raw_abstained':(a.get('parsed_model_response') or {}).get('abstained')},ensure_ascii=False),flush=True)
  unload(MODELS[mid]['tag'])
 results=[x for x in jl(W/'smoke_results.jsonl') if x['prompt_version']==PROMPT_VERSION];offline=[]
 d,p=rt.decision(positive)
 for name,raw in [('INVALID_JSON','not JSON'),('INVALID_CITATION',json.dumps({'answer':'1.3 kg/m³','abstained':False,'reason':'','citations':['NONEXISTENT-CHUNK']}))]:
  x=rt.postprocess(positive,raw,d,p);ok=not x['raw_model_structure_valid'] if name=='INVALID_JSON' else x['raw_citation_validation']['status']=='FAIL'
  offline.append({'case':name,'pass':ok,'actual':x,'method':'injected validator input, not an LLM API claim'})
 write('pre_run_e2e_validation.json',{'status':'PASS' if len(results)==24 and all(x['test_passed'] for x in results) and all(x['pass'] for x in offline) else 'FAIL','actual_generator_calls':len(results),'actual_api_completed':sum(x['api_completed'] for x in results),'passed_cases':sum(x['test_passed'] for x in results),'models':list(MODELS),'per_call_log':'smoke_results.jsonl','offline_fault_injection':offline,'controlled_context_case_separate':True,'production':False})
def freeze():
 e=json.loads((W/'pre_run_e2e_validation.json').read_text(encoding='utf-8'));repo=json.loads((W/'repository_pytest_results.json').read_text(encoding='utf-8'));app=json.loads((W/'streamlit_validation.json').read_text(encoding='utf-8'))
 live=json.loads((W/'live_retrieval_validation.json').read_text(encoding='utf-8'))
 assert e['status']=='PASS' and repo['exit_code']==0 and app['status']=='PASS' and live['status']=='PASS','TECHNICAL_GATE_NOT_PASSED'
 files=['frozen_runner.py','rag_v3_runtime.py','retrieve_and_verify_180.py','runtime/grounded_answer_engine_v2.py','corpus/marine_hybrid_rag_corpus_v3.sqlite3','frozen_corpus_and_contexts_180.jsonl','verified_reference_answers_v3.jsonl','evaluation_rubrics_v3_frozen.json','reference_runtime_profiles.json','runtime_evidence_profiles_frozen.json','semantic_clause_equivalence_registry.json','context_precision_label_status.json','retrieved_chunk_support_labels.jsonl','score_frozen_run.py']
 files+=['frozen_source_manifest.json','reranker_file_identity.json','frozen_streamlit_app.py','corpus_evidence_availability_180.jsonl','questions_original_180.jsonl']
 config=json.loads((W/'evaluation_configuration_frozen.json').read_text(encoding='utf-8'))
 write('frozen_evaluation_manifest.json',{'run_id':W.name,'frozen_at':datetime.datetime.now().astimezone().isoformat(),'evaluation_type':'EXPLORATORY_REGRESSION; NOT_UNSEEN_HOLDOUT; NOT_HUMAN_GOLD','frozen_files':[{'path':n,'sha256':sha(W/n)} for n in files],'corpus':config['corpus'],'retrieval':{k:config[k] for k in ['bm25','dense','rrf_k','reranker','record_dedupe','top_k']},'models':config['models'],'prompt_version':PROMPT_VERSION,'system':SYSTEM,'policy':POLICY,'schema':SCHEMA,'generation_options':OPTIONS,'sequential_model_order':list(MODELS),'warmup_excluded':True,'retry_policy':'2 transport/API attempts maximum, never retry valid response to improve content','source_verification_label':'AUTO_SOURCE_VERIFIED','human_gold':0,'technical_gate':'PASS','scoring_policy_approval_status':'NO_AGGREGATE_SCORE_OR_WINNER','raw_answer_vs_system_separated':True,'memory_scope':'system_level_sampled_peak','no_prompt_or_index_mutation_during_run':True})
 print('FROZEN_MANIFEST_SAVED',flush=True)
if __name__=='__main__':{'repository':repository,'smoke':smoke,'freeze':freeze}[sys.argv[1]]()
