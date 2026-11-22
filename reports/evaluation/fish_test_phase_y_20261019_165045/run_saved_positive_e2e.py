import json,importlib.util,sys,pathlib,hashlib,time,traceback,re
Y=pathlib.Path(__file__).resolve().parent
out=Y/'positive_model_e2e_results.jsonl'
def load(name,path):
 spec=importlib.util.spec_from_file_location(name,path);mod=importlib.util.module_from_spec(spec);sys.modules[name]=mod;spec.loader.exec_module(mod);return mod
rag=load('rag_v3_phase_y_saved_e2e',Y/'rag_v3_phase_y.py')
engine=rag.RAGEngine(); question='依鞍帶石斑資料，放養密度建議範圍是多少尾/公頃？'; species='石斑魚'; category='Calculation'
retrieval=engine.retrieve(question,species,category,'PHASE-Y-GROUPER-DENSITY-SAVED')
ctx=retrieval.get('reranked_top5',[])
source_ok=any(c.get('chunk_id')=='fv3-m17g-004' and c.get('source_id')=='TFRI-M17-GROUPER' and c.get('species_scope')=='石斑魚' and c.get('retrieval_eligible') is True for c in ctx)
if not source_ok: raise RuntimeError('Actual Phase Y retrieval did not return the verified grouper density chunk; no controlled card substitution is used in this saved end-to-end test.')
existing=[]
if out.exists():
 for line in out.read_text(encoding='utf-8').splitlines():
  if line.strip():
   try: existing.append(json.loads(line))
   except json.JSONDecodeError: pass
done={(r.get('model_id'),r.get('replicate')) for r in existing if r.get('test_status')=='COMPLETED'}
for model,rep in [('M2',1),('M2',2),('M2',3),('M2',4),('M1',2),('M3',1),('M4',1)]:
 if (model,rep) in done:
  continue
 run_id=f'phase_y_saved_positive_{model}_{rep}'
 try:
  t=time.time();result=engine.answer_with_retrieval(question,species,category,model,retrieval,run_id=run_id)
  answer=result.get('answer') or ''
  has_range=('10,000' in answer and '30,000' in answer)
  has_unit=('尾/公頃' in answer or '尾／公頃' in answer)
  row={'case_id':'GROUper_STOCKING_DENSITY_POSITIVE','run_id':run_id,'model_id':model,'replicate':rep,'question_id':retrieval['question_id'],'question':question,'species':species,'category':category,'retrieval':retrieval,'result':result,'checks':{'verified_context_present':source_ok,'effective_answered':result.get('status')=='answered','range_matches_source':has_range,'unit_matches_source':has_unit,'citation_valid':result.get('citation_validation',{}).get('valid') is True,'citation_points_to_expected_chunk':any(c.get('chunk_id')=='fv3-m17g-004' and c.get('source_id')=='TFRI-M17-GROUPER' for c in result.get('citations',[])),'model_raw_abstained':result.get('model_reported_status')=='abstain','system_fallback_used':bool(result.get('deterministic_evidence_fallback')),'elapsed_total_seconds':time.time()-t},'test_status':'COMPLETED','evaluation_status':'ENGINEERING_REGRESSION_NOT_MODEL_ACCURACY','not_human_gold':True}
 except Exception as e:
  row={'case_id':'GROUper_STOCKING_DENSITY_POSITIVE','run_id':run_id,'model_id':model,'replicate':rep,'question':question,'retrieval':retrieval,'test_status':'ERROR','error_type':type(e).__name__,'error':str(e),'traceback':traceback.format_exc()[-2500:]}
 with out.open('a',encoding='utf-8',newline='') as f:f.write(json.dumps(row,ensure_ascii=False,separators=(',',':'))+'\n');f.flush()
 fallback=(row.get('result',{}).get('deterministic_evidence_fallback') or {}).get('method') if row.get('result') else None
 print(json.dumps({'model_id':model,'replicate':rep,'status':row.get('result',{}).get('status') if row.get('result') else row.get('test_status'),'raw_model_status':row.get('result',{}).get('model_reported_status') if row.get('result') else None,'fallback':fallback,'checks':row.get('checks')},ensure_ascii=False),flush=True)
print('DONE',len([s for s in out.read_text(encoding='utf-8').splitlines() if s.strip()]))
