import sys,json,shutil,importlib.util
sys.dont_write_bytecode=True
from fair_grounded_rag import W,jl,write
from bootstrap_repair import sha
from run_regression import verify_freeze
def main():
 verify_freeze();prior=json.loads((W/'final_active_policy_manifest.json').read_text(encoding='utf-8'));snap=W/'postprocess_v3_checkpoint';snap.mkdir(exist_ok=True)
 for x in prior['files']:
  assert sha(W/x['path'])==x['sha256'];target=snap/x['path'];target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(W/x['path'],target)
 write('postprocess_v3_checkpoint_manifest.json',{'files':[{'original_path':x['path'],'snapshot_path':str(snap/x['path']),'sha256':x['sha256']} for x in prior['files']],'original_manifest':prior,'purpose':'Immutable checkpoint of initial postprocessing, no raw generation changed'})
 engine=(W/'fair_grounded_rag_final.py').read_text(encoding='utf-8');a=engine.index('def parse_arithmetic(');b=engine.index('class Sample:',a);engine=engine[:a]+'from arithmetic_parser_v4 import parse_arithmetic\n'+engine[b:];(W/'fair_grounded_rag_final.py').write_text(engine,encoding='utf-8')
 spec=importlib.util.spec_from_file_location('arith_final_engine',W/'fair_grounded_rag_final.py');mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod);rt=mod.FairRag();rmap={r['question_id']:r for r in jl(W/'shared_contexts_180.jsonl')};rmap.update({r['question_id']:r for r in jl(W/'negative_safety_cases_frozen.jsonl')});refs=rt.refs;changes=[];logical_unchanged=0
 for original,final in [('regression_results_200.jsonl','regression_results_200_final.jsonl'),('safety_results_24.jsonl','safety_results_24_final.jsonl')]:
  previous={(g['question_id'],g['model_id']):g for g in jl(W/final)};new=[]
  for g in jl(W/original):
   r=rmap[g['question_id']];out,v=rt.postprocess(r,g['model_id'],g['raw_model_response'],rt.evidence(r));old=previous[g['question_id'],g['model_id']]
   if refs.get(g['question_id'],{}).get('logical_rubric'):
    assert out==old['result'] and v==old['validation'];logical_unchanged+=1
   if (out['answer_status'],out['answer_origin'])!=(old['result']['answer_status'],old['result']['answer_origin']):changes.append({'question_id':g['question_id'],'model_id':g['model_id'],'before_origin':old['result']['answer_origin'],'after_origin':out['answer_origin'],'before_status':old['result']['answer_status'],'after_status':out['answer_status']})
   new.append({**g,'original_generation_validation_result':g['result'],'original_generation_validation':g['validation'],'result':out,'validation':v,'postprocessing_version':'numeric-v3-arithmetic-result-role-v4','raw_generation_and_prompt_unchanged':True,'new_api_call_for_replay':False})
  (W/final).write_text(''.join(json.dumps(g,ensure_ascii=False)+'\n' for g in new),encoding='utf-8')
 write('arithmetic_parser_correction_audit.json',{'source_reference_and_expected_values_unchanged':True,'raw_responses_unchanged':True,'all224_replayed_same_policy':True,'logical_model_question_pairs_unchanged':logical_unchanged,'logical_in_progress_scoring_inputs_unchanged':True,'behavior_changes_n':len(changes),'changes':changes,'selection_policy':'Prefer explicit requested result role and equation RHS; distinguish operands, rates and required total; never choose a candidate by matching reference value','regression_examples':'Width4 followed by source range28–32; salinity21-8=13 followed by source threshold20; 4 intervals of1.5 months; simplified per-hectare rate versus total','new_api_calls':0})
 names=['fair_grounded_rag_final.py','numeric_grounding_v3.py','arithmetic_parser_v4.py','fair_streamlit_app_final.py','score_regression_final.py','regression_results_200_final.jsonl','safety_results_24_final.jsonl','fixed_denominator_scoring_policy.json']
 write('final_active_policy_manifest.json',{'generation_freeze_manifest':str(W/'answer_policy_frozen_manifest.json'),'prompt_unchanged':True,'retrieval_unchanged':True,'reference_and_rubric_unchanged':True,'active_entrypoint':'fair_streamlit_app_final.py','parser_version':'numeric-v3-arithmetic-result-role-v4','files':[{'path':n,'sha256':sha(W/n)} for n in names]})
 print('Uniform arithmetic parser replay completed; behavior changes',len(changes),'all Logical pairs unchanged',logical_unchanged,flush=True)
if __name__=='__main__':main()
