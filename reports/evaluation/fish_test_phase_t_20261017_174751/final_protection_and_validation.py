import hashlib,json,time
from pathlib import Path
from collections import Counter
ROOT=Path.cwd(); OUT=ROOT/'reports/evaluation/fish_test_phase_t_20261017_174751'; S=ROOT/'reports/evaluation/fish_test_phase_s_integrated_20261017_173906'
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
 return h.hexdigest()
def readj(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def readjl(p):return [json.loads(x) for x in p.read_text(encoding='utf-8-sig').splitlines() if x.strip()]
def writej(n,x):(OUT/n).write_text(json.dumps(x,ensure_ascii=False,indent=2),encoding='utf-8')

# Final protected-file hash recheck, after all Phase T writes.
pre=readjl(OUT/'frozen_baseline_pre_finalize.jsonl'); paths={r['path']:r['expected_sha256'] for r in pre}; post=[]
for i,(rel,expected) in enumerate(sorted(paths.items()),1):
 p=ROOT/rel; actual=sha(p) if p.is_file() else None
 post.append({'stage':'phase_t_post_finalize','path':rel,'expected_sha256':expected,'actual_sha256':actual,'status':'unchanged' if actual==expected else ('missing_or_unreadable' if actual is None else 'mismatch')})
 if i%150==0:print(f'protected post-hash {i}/636',flush=True)
(OUT/'frozen_baseline_post_finalize.jsonl').write_text(''.join(json.dumps(x,ensure_ascii=False,separators=(',',':'))+'\n' for x in post),encoding='utf-8')
sumry={'stage':'phase_t_post_finalize','expected_unique_files':636,'checked_count':len(post),'matching_count':sum(x['status']=='unchanged' for x in post),'mismatch_count':sum(x['status']!='unchanged' for x in post),'complete':len(paths)==636 and len(post)==636 and all(x['status']=='unchanged' for x in post),'sqlite_sha256':sha(ROOT/'rag_store.sqlite3'),'sqlite_expected_sha256':'d7d06d4d2a57d0a57d05bcb6131ffb24aefb226c6bd36349dbc5118d33b11087'}
sumry['sqlite_matches']=sumry['sqlite_sha256']==sumry['sqlite_expected_sha256'];writej('frozen_baseline_post_finalize_summary.json',sumry)

# Record official model-card identity metadata used by the local runtime.
r=readj(OUT/'reranker_runtime_validation.json');r['official_model_card']={'url':'https://huggingface.co/BAAI/bge-reranker-v2-m3','license':'Apache-2.0 (official model card metadata)','repository_revision_page':'https://huggingface.co/BAAI/bge-reranker-v2-m3/tree/953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e','revision_verified_on_official_hub':True,'official_architecture':'XLM-Roberta sequence classifier; multilingual reranker','review_access_date':'2026-10-17'};writej('reranker_runtime_validation.json',r)

# Correct test status and exact run outcomes.
integ=readj(OUT/'rag_end_to_end_validation.json');integ['gate3_tests']['repository_pytest']='FAIL; 80 collection errors, existing WinError 5/PermissionError in temp directories';integ['gate3_tests']['repository_pytest_full_log']='repository_pytest_full.log';integ['gate3_tests']['phase_t_unittest']='3/3 PASS';integ['gate3_tests']['streamlit_apptest']='PASS mock fail-closed';writej('rag_end_to_end_validation.json',integ)
ready=readj(OUT/'rag_evaluation_readiness.json');ready['gate3_system_integration']['full_repository_pytest']='FAIL (80 collection errors, WinError 5)';ready['gate3_system_integration']['pytest_log']='repository_pytest_full.log';ready['gate3_system_integration']['isolated_unit_tests']='3/3 PASS';ready['gate3_system_integration']['streamlit_apptest']='PASS (mock fail-closed mode)';writej('rag_evaluation_readiness.json',ready)

# Parse every produced JSON/JSONL and assert the exact retrieval/eligibility cardinalities.
json_files=[p for p in OUT.rglob('*.json') if p.is_file()]
jsonl_files=[p for p in OUT.rglob('*.jsonl') if p.is_file()]
json_errors=[];jsonl_errors=[]
for p in json_files:
 try:readj(p)
 except Exception as e:json_errors.append({'path':str(p.relative_to(OUT)),'error':str(e)})
for p in jsonl_files:
 try:readjl(p)
 except Exception as e:jsonl_errors.append({'path':str(p.relative_to(OUT)),'error':str(e)})
retr=readjl(OUT/'retrieval_results_v3.jsonl');elig=readjl(OUT/'question_eligibility_v3.jsonl')
assert len(retr)==180 and len({x['question_id'] for x in retr})==180
assert len(elig)==180 and len({x['question_id'] for x in elig})==180
assert sum(x['final_top5_count']==5 for x in retr)==20
assert sum(x['final_top5_count']==0 for x in retr)==160
assert not json_errors and not jsonl_errors
validation={'json_files_checked':len(json_files),'jsonl_files_checked':len(jsonl_files),'json_parse_errors':json_errors,'jsonl_parse_errors':jsonl_errors,'retrieval_rows':len(retr),'unique_retrieval_question_ids':len({x['question_id'] for x in retr}),'eligibility_rows':len(elig),'unique_eligibility_question_ids':len({x['question_id'] for x in elig}),'full_reranked_top5':sum(x['final_top5_count']==5 for x in retr),'no_candidates':sum(x['final_top5_count']==0 for x in retr),'generator_calls':0,'pre_post_protected_manifest_identical':sumry['complete'] and readj(OUT/'frozen_baseline_pre_finalize_summary.json')['complete'] and sumry['matching_count']==readj(OUT/'frozen_baseline_pre_finalize_summary.json')['matching_count'],'sqlite_matches':sumry['sqlite_matches'],'status':'PASS_FOR_ARTIFACTS_AND_PROTECTION' if sumry['complete'] and not json_errors and not jsonl_errors else 'FAIL'}
writej('phase_t_artifact_validation.json',validation)
compat={'phase':'Marine Hybrid-RAG Phase T','run_id':OUT.name,'source_workspace':'reports/evaluation/fish_test_phase_s_integrated_20261017_173906','historical_phase_s_artifacts_modified':False,'protected_frozen_manifest_before':{'checked':readj(OUT/'frozen_baseline_pre_finalize_summary.json')['checked_count'],'matching':readj(OUT/'frozen_baseline_pre_finalize_summary.json')['matching_count'],'complete':readj(OUT/'frozen_baseline_pre_finalize_summary.json')['complete']},'protected_frozen_manifest_after':{'checked':sumry['checked_count'],'matching':sumry['matching_count'],'complete':sumry['complete']},'rag_store_sqlite_sha256':sumry['sqlite_sha256'],'rag_store_matches_expected':sumry['sqlite_matches'],'phase_e_original_generator_sha256_preserved':True,'evaluation_corpus_v2_and_historical_e4_modified':False,'production_modified':False,'model_weights_modified':False,'source_admission_this_phase':0,'formal_corpus_v3_built':False,'e4_final_built':False,'generator_results':0,'retrieval_results':180,'final_top5_complete':20,'benchmark_eligible_v3':0,'formal_winner':None,'test_status':{'isolated_unittest':'3/3 PASS','streamlit_apptest':'PASS mock fail-closed','repository_pytest':'FAIL 80 collection errors, WinError 5'},'artifact_validation':validation['status']}
writej('compatibility.json',compat)

# Patch the final report with exact after-check/test state.
p=OUT/'phase_t_final_report.md';txt=p.read_text(encoding='utf-8');txt=txt.replace('最終 636/636 結果見 `frozen_baseline_post_finalize_summary.json`。',f"最終 Frozen Manifest：{sumry['matching_count']}/{sumry['checked_count']} matching；SQLite SHA-256 `{sumry['sqlite_sha256']}`，位於 `frozen_baseline_post_finalize_summary.json`。")
txt=txt.replace('完整 repository pytest 未執行：所有現有 Python 環境均無 pytest module/executable；未安裝套件、未放寬權限。','完整 repository pytest 實際執行失敗：80 個 collection errors，既有暫存目錄觸發 WinError 5；未清除目錄、未安裝套件或放寬權限。')
p.write_text(txt,encoding='utf-8')
print(json.dumps({'frozen_after':sumry,'json_files':len(json_files),'jsonl_files':len(jsonl_files),'retrieval_rows':len(retr),'complete_top5':20,'empty':160,'errors':len(json_errors)+len(jsonl_errors),'validation':validation['status']},ensure_ascii=True))
