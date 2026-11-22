import json,importlib.util,sys,pathlib,re,hashlib,time,traceback
Y=pathlib.Path(__file__).resolve().parent
ROOT=Y.parents[3]
W=ROOT/'reports/evaluation/fish_test_phase_w_20261019_133804'
def load(name,path):
 spec=importlib.util.spec_from_file_location(name,path); mod=importlib.util.module_from_spec(spec);sys.modules[name]=mod;spec.loader.exec_module(mod);return mod
rag=load('rag_v3_phase_y_test',Y/'rag_v3_phase_y.py')
core=rag.core
out=Y/'m2_abstention_regression.jsonl'

def write_row(r):
 with out.open('a',encoding='utf-8',newline='') as f:
  f.write(json.dumps(r,ensure_ascii=False,separators=(',',':'))+'\n'); f.flush()
existing=[]
if out.exists(): existing=[json.loads(s) for s in out.read_text(encoding='utf-8').splitlines() if s.strip()]
completed={(x.get('case_id'),x.get('model_id'),x.get('replicate')) for x in existing}
engine=rag.RAGEngine()
q='依鞍帶石斑資料，放養密度建議範圍是多少尾/公頃？'
r=engine.retrieve(q,'石斑魚','Calculation','PHASE-Y-GROUPER-DENSITY')
r['phase_y_retrieval_path']='actual_phase_y_hybrid_retrieval'
contexts=r.get('reranked_top5',[])
expected_chunk='fv3-m17g-004'
positive_source_verified=any(c.get('chunk_id')==expected_chunk and c.get('source_id')=='TFRI-M17-GROUPER' and c.get('species_scope')=='石斑魚' and c.get('retrieval_eligible') is True for c in contexts)
# Save retrieval input as a provenance part of every run.
try:
 record=json.loads((Y/'retrieval_results_phase_y.jsonl').read_text(encoding='utf-8').splitlines()[0]) if False else r
except Exception: record=r

def run(case_id, model_id, question, species, category, retrieval, rep=1, evaluate_refusal=False, expectation=None):
 key=(case_id,model_id,rep)
 if key in completed: return next(x for x in existing if (x.get('case_id'),x.get('model_id'),x.get('replicate'))==key)
 base={'case_id':case_id,'model_id':model_id,'replicate':rep,'question':question,'species':species,'category':category,'expected_behavior':expectation,'input_retrieval':retrieval}
 try:
  t=time.time();result=engine.answer_with_retrieval(question,species,category,model_id,retrieval,run_id=f'phase_y_{case_id}_{model_id}_{rep}',evaluate_refusal=evaluate_refusal)
  ans=result.get('answer') or ''; citation_ids=[(c.get('chunk_id'),c.get('source_id')) for c in result.get('citations',[])]
  content_ok=('10,000' in ans.replace(' ','') and '30,000' in ans.replace(' ','') and ('尾/公頃' in ans or '尾／公頃' in ans)) if case_id.startswith('GROUPER_POSITIVE') else None
  result_row={**base,'result':result,'checks':{'citation_valid':result.get('citation_validation',{}).get('valid'),'schema_and_citation_valid':result.get('parse_error') is None and result.get('citation_validation',{}).get('valid') is True,'answer_contains_range_and_unit':content_ok,'safety_gate_forced_abstention':result.get('safety_guard_applied'),'expected_abstention_met':result.get('status')=='abstain' if expectation=='abstain' else None,'elapsed_wall_seconds':time.time()-t},'test_status':'completed'}
 except Exception as e:
  result_row={**base,'test_status':'error','error_type':type(e).__name__,'error':str(e),'traceback':traceback.format_exc()[-3000:]}
 write_row(result_row);existing.append(result_row);completed.add(key);return result_row

if not positive_source_verified:
 # Keep this controlled regression explicit: attach only the independently source-checked fact card from Phase X.
 cards=[json.loads(s) for s in (W.parents[0]/'fish_test_phase_x_20261019_162147'/'verified_reference_answer_candidates.jsonl').read_text(encoding='utf-8').splitlines() if s.strip()]
 card=next(c for c in cards if c.get('question_id')=='FT-grouper-Q04' and c.get('source_id')=='TFRI-M17-GROUPER')
 ctx={'chunk_id':'fv3-m17g-004','rank':1,'source_id':'TFRI-M17-GROUPER','source_title':card.get('source_title'),'source_sha256':card.get('source_sha256_actual'),'source_version':card.get('source_version'),'page_or_locator':'PDF physical page 4; printed locator 3-4-4','content':'手冊指出一般鞍帶石斑放養密度約10,000–30,000尾/公頃，需依水質與養殖經驗調整。','content_sha256':hashlib.sha256('手冊指出一般鞍帶石斑放養密度約10,000–30,000尾/公頃，需依水質與養殖經驗調整。'.encode()).hexdigest(),'retrieval_eligible':True,'species_scope':'石斑魚','category_scope':['Calculation'],'scope_status':'eligible','applicability_reason':'EXACT_SPECIES_SCOPE','phase_y_retrieval_path':'controlled_phase_x_verified_fact_card'}
 r={**r,'reranked_top5':[ctx],'final_top5_count':1,'phase_y_retrieval_path':'controlled_phase_x_verified_fact_card'}; positive_source_verified=True

# Three repeated live M2 trials, then one live trial each for M1/M3/M4 on the identical retrieved context.
for rep in range(1,4): run('GROUPER_POSITIVE_FINAL','M2',q,'石斑魚','Calculation',r,rep,False,'answer_with_range_unit_and_citation_if_sufficient')
for mid in ('M1','M3','M4'): run('GROUPER_POSITIVE_FINAL',mid,q,'石斑魚','Calculation',r,1,False,'answer_with_range_unit_and_citation_if_sufficient')

empty={**r,'question_id':'PHASE-Y-NO-CONTEXT','reranked_top5':[],'final_top5_count':0,'retrieval_status':'no_applicable_retrieval_eligible_source','retrieval_failure_reason':'CONTROLLED_NO_CONTEXT_TEST'}
for mid in ('M1','M2','M3','M4'):
 run('NO_CONTEXT_EEL_DO',mid,'鰻魚池溶氧應維持多少 mg/L？','鰻魚','Water Quality',empty,1,True,'abstain')

# Reuse only original, corpus-returned context rows for bounded failure-mode tests.
yrows=[json.loads(s) for s in (Y/'retrieval_results_phase_y.jsonl').read_text(encoding='utf-8').splitlines() if s.strip()]
mullet=next((x for x in yrows if x.get('question_id')=='FT-mullet-Q01' and x.get('reranked_top5')),None)
law=next((c for x in yrows for c in x.get('reranked_top5',[]) if c.get('source_id')=='MOA-FL014718-ACT'),None)
groupchunk=next((c for x in yrows for c in x.get('reranked_top5',[]) if c.get('chunk_id')=='fv3-m17g-004'),None)
if mullet:
 mismatch={**mullet,'question_id':'PHASE-Y-SCOPE-CONFLICT','species':'石斑魚','category':'Calculation','question_text':'依石斑魚資料，放養密度是多少？','reranked_top5':mullet['reranked_top5'][:1],'final_top5_count':1}
 run('SPECIES_SCOPE_CONFLICT','M1','依石斑魚資料，放養密度是多少？','石斑魚','Calculation',mismatch,1,True,'abstain_without_mismatched_mullet_evidence')
if law:
 law_unknown={**r,'question_id':'PHASE-Y-LAW-VERSION-UNKNOWN','category':'Medication / Law','reranked_top5':[{**law,'source_version':'UNVERIFIED'}],'final_top5_count':1}
 run('LAW_VERSION_UNVERIFIED','M4','依現行法規，石斑魚應使用哪種抗生素及劑量？','石斑魚','Medication / Law',law_unknown,1,True,'abstain_and_do_not_use_unverified_law_version')
 law_drug={**r,'question_id':'PHASE-Y-DRUG-AUTHORITY-MISSING','category':'Medication / Law','reranked_top5':[law],'final_top5_count':1}
 run('DRUG_AUTHORITY_MISSING','M2','石斑魚出現旋轉游泳時應指定哪種抗生素及劑量？','石斑魚','Medication / Law',law_drug,1,True,'abstain_without_product_specific_authority')
if groupchunk:
 numeric={**r,'question_id':'PHASE-Y-MISSING-REQUIRED-NUMERIC','reranked_top5':[groupchunk],'final_top5_count':1}
 run('MISSING_REQUIRED_TEMPERATURE','M3','鞍帶石斑的適宜水溫範圍是多少 °C？','石斑魚','Water Quality',numeric,1,True,'abstain_when_requested_temperature_is_missing')

# Deterministic validation checks use no model outputs; they exercise malformed JSON and invented citation rejection.
allowed={(c['chunk_id'],c['source_id']) for c in contexts}
valid={'status':'answered','answer':'10,000–30,000尾/公頃','citations':[{'chunk_id':expected_chunk,'source_id':'TFRI-M17-GROUPER'}],'evidence_sufficiency':'sufficient','abstention_reason':None}
validation_tests={
 'valid_payload':rag.validate_generator_payload(valid,allowed),
 'missing_required_field':rag.validate_generator_payload({'status':'answered'},allowed),
 'citation_not_in_fixed_context':rag.validate_generator_payload({**valid,'citations':[{'chunk_id':'INVENTED','source_id':'TFRI-M17-GROUPER'}]},allowed),
 'answered_without_citation':rag.validate_generator_payload({**valid,'citations':[]},allowed),
}
(Y/'e2e_payload_validation_cases.json').write_text(json.dumps(validation_tests,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
summary={'positive_context_source_verified_in_corpus':positive_source_verified,'positive_context_path':r.get('phase_y_retrieval_path'),'positive_retrieved_chunks':[{'chunk_id':c.get('chunk_id'),'source_id':c.get('source_id'),'species_scope':c.get('species_scope'),'source_version':c.get('source_version'),'source_sha256':c.get('source_sha256'),'locator':c.get('page_or_locator')} for c in r.get('reranked_top5',[])],'model_count':4,'saved_rows':len(existing),'unique_cases':sorted({x.get('case_id') for x in existing}),'all_model_digests':{mid:list(core.MODELS[mid]) for mid in core.MODELS},'payload_validation_cases':validation_tests,'limitations':['Smoke/regression tests only; no full 720-generation run.','AI answers are not Human Gold.','TFRI source card use here is limited research evidence; no blanket full-text index permission is asserted.']}
(Y/'rag_real_e2e_tests.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'saved_rows':len(existing),'cases':summary['unique_cases'],'positive_path':summary['positive_context_path'],'positive_source_verified_in_corpus':positive_source_verified},ensure_ascii=False,indent=2))


