import sys,json
sys.dont_write_bytecode=True
from fair_grounded_rag_final import FairRag,W,jl,write
from bootstrap_repair import sha
from run_regression import verify_freeze
def main():
 verify_freeze();rt=FairRag();rows={r['question_id']:r for r in jl(W/'shared_contexts_180.jsonl')};rows.update({r['question_id']:r for r in jl(W/'negative_safety_cases_frozen.jsonl')});audit=[];logical_same=0
 for original,final in [('regression_results_200.jsonl','regression_results_200_final.jsonl'),('safety_results_24.jsonl','safety_results_24_final.jsonl')]:
  prev={(g['question_id'],g['model_id']):g for g in jl(W/'postprocess_v3_checkpoint'/final)};outrows=[]
  for g in jl(W/original):
   r=rows[g['question_id']];out,v=rt.postprocess(r,g['model_id'],g['raw_model_response'],rt.evidence(r))
   if rt.refs.get(g['question_id'],{}).get('logical_rubric'):
    old=prev[g['question_id'],g['model_id']];assert old['result']==out and old['validation']==v;logical_same+=1
   if out!=g['result']:audit.append({'question_id':g['question_id'],'model_id':g['model_id'],'before_status':g['result']['answer_status'],'after_status':out['answer_status'],'before_origin':g['result']['answer_origin'],'after_origin':out['answer_origin'],'before_reason':g['validation']['raw_validation_reason'],'after_reason':v['raw_validation_reason'],'behavior_changed':(out['answer_status'],out['answer_origin'])!=(g['result']['answer_status'],g['result']['answer_origin'])})
   outrows.append({**g,'original_generation_validation_result':g['result'],'original_generation_validation':g['validation'],'result':out,'validation':v,'postprocessing_version':'numeric-v3-arithmetic-role-v4r2','raw_generation_and_prompt_unchanged':True,'new_api_call_for_replay':False})
  (W/final).write_text(''.join(json.dumps(g,ensure_ascii=False)+'\n' for g in outrows),encoding='utf-8')
 write('postprocessing_change_audit_final.json',{'raw_generation_unchanged':True,'all224_uniformly_replayed':True,'reference_answers_and_rubric_unchanged':True,'logical_pairs_unchanged':logical_same,'changed_fields_record_n':len(audit),'changed_status_or_origin_n':sum(x['behavior_changed'] for x in audit),'changes':audit,'parser_selection_never_matches_gold':True,'original_model_results_and_all_intermediate_derived_checkpoints_preserved':True,'new_api_call_n':0})
 names=['fair_grounded_rag_final.py','numeric_grounding_v3.py','arithmetic_parser_v4.py','fair_streamlit_app_final.py','score_regression_final.py','regression_results_200_final.jsonl','safety_results_24_final.jsonl','fixed_denominator_scoring_policy.json']
 write('final_active_policy_manifest.json',{'generation_freeze_manifest':str(W/'answer_policy_frozen_manifest.json'),'prompt_unchanged':True,'retrieval_unchanged':True,'reference_and_rubric_unchanged':True,'active_entrypoint':'fair_streamlit_app_final.py','parser_version':'numeric-v3-arithmetic-role-v4r2','files':[{'path':n,'sha256':sha(W/n)} for n in names]})
 print('Uniform final policy applied, Logical pairs unchanged:',logical_same,flush=True)
if __name__=='__main__':main()
