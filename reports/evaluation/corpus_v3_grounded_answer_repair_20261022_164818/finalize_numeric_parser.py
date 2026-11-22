"""After all frozen API calls finish, replay one corrected numeric tokenizer.

All raw responses, the original frozen policy and first postprocessing stay intact.
No Prompt, Context, reference, formula or model is changed. No API calls here.
"""
import sys,json,importlib.util
sys.dont_write_bytecode=True
from fair_grounded_rag import W,jl,write,append
from bootstrap_repair import sha
from run_regression import verify_freeze
def main():
 verify_freeze();gens=jl(W/'regression_results_200.jsonl');safe=jl(W/'safety_results_24.jsonl');assert len(gens)==200 and len(safe)==24
 s=(W/'fair_grounded_rag.py').read_text(encoding='utf-8');start=s.index('def numeric(s):');end=s.index('def content_problem(',start)
 s=s[:start]+'from numeric_grounding_v3 import numeric\n'+s[end:]
 s=s.replace("numeric(parsed['answer'])","numeric(parsed['answer'],cited+[byid[cid]['source_id'] for cid in cited])")
 s=s.replace("if e['state']=='EVIDENCE_PARTIAL' and not parsed['missing_information']:raise ValueError('PARTIAL_ANSWER_MISSING_EXPLICIT_INFORMATION_GAPS')","if e['state']=='EVIDENCE_PARTIAL':vs['raw_partial_disclosure_valid']=bool(parsed['missing_information'])")
 s=s.replace("if status=='ANSWERED_PARTIAL' and not missing:missing=['部分必要答案元素未由本次引用完整涵蓋。']","if status=='ANSWERED_PARTIAL' and not missing:\n     missing=list(e['missing_information']) or ['部分必要答案元素未由本次引用完整涵蓋。'];vs['system_added_missing_information']=True")
 (W/'fair_grounded_rag_final.py').write_text(s,encoding='utf-8')
 spec=importlib.util.spec_from_file_location('final_engine',W/'fair_grounded_rag_final.py');mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod);rt=mod.FairRag()
 rmap={r['question_id']:r for r in jl(W/'shared_contexts_180.jsonl')};rmap.update({r['question_id']:r for r in jl(W/'negative_safety_cases_frozen.jsonl')});changes=[]
 for items,name in [(gens,'regression_results_200_final.jsonl'),(safe,'safety_results_24_final.jsonl')]:
  output=[]
  for g in items:
   r=rmap[g['question_id']];out,v=rt.postprocess(r,g['model_id'],g['raw_model_response'],rt.evidence(r));ng={**g,'original_generation_validation_result':g['result'],'original_generation_validation':g['validation'],'result':out,'validation':v,'postprocessing_version':'numeric-tokenizer-v3-uniform-replay','raw_generation_and_prompt_unchanged':True,'new_api_call_for_replay':False};output.append(ng)
   if out!=g['result']:changes.append({'question_id':g['question_id'],'model_id':g['model_id'],'before_status':g['result']['answer_status'],'after_status':out['answer_status'],'before_origin':g['result']['answer_origin'],'after_origin':out['answer_origin'],'before_reason':g['validation']['raw_validation_reason'],'after_reason':v['raw_validation_reason'],'raw_response_unchanged':True})
  (W/name).write_text(''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in output),encoding='utf-8')
 # One active isolated app and scorer use final validated parsing. Original
 # generation programs/configuration remain reproducible frozen artifacts.
 (W/'fair_streamlit_app_final.py').write_text((W/'fair_streamlit_app.py').read_text(encoding='utf-8').replace('from fair_grounded_rag import','from fair_grounded_rag_final import'),encoding='utf-8')
 (W/'score_regression_final.py').write_text((W/'score_regression.py').read_text(encoding='utf-8').replace('from fair_grounded_rag import','from fair_grounded_rag_final import').replace("jl(W/'regression_results_200.jsonl')","jl(W/'regression_results_200_final.jsonl')"),encoding='utf-8')
 (W/'validate_live_app_final.py').write_text((W/'validate_live_app.py').read_text(encoding='utf-8').replace('fair_streamlit_app.py','fair_streamlit_app_final.py'),encoding='utf-8')
 (W/'test_answer_policy_final.py').write_text((W/'test_answer_policy.py').read_text(encoding='utf-8').replace('from fair_grounded_rag import','from fair_grounded_rag_final import'),encoding='utf-8')
 write('numeric_parser_correction_audit.json',{'applied_after_frozen_generation_completed':True,'generation_records_unchanged':True,'all_positive_and_negative_records_replayed':224,'changes':changes,'change_n':len(changes),'why':'Fix punctuation concatenation and partial numeric matches inside actual supplied/cited IDs. Retain real decimals, percentages, units and unsupported-value rejection. For a source-verified partial answer lacking disclosure, preserve raw failure and add known source-profile information gaps only to the final system envelope, force ANSWERED_PARTIAL. No desired answer or question ID rule.','raw_missing_information_not_rewritten':True,'partial_model_disclosure_failure_separately_flagged':True,'no_new_api_inference':True,'source_or_species_safety_not_disabled':True})
 names=['fair_grounded_rag_final.py','numeric_grounding_v3.py','fair_streamlit_app_final.py','score_regression_final.py','regression_results_200_final.jsonl','safety_results_24_final.jsonl','fixed_denominator_scoring_policy.json']
 write('final_active_policy_manifest.json',{'generation_freeze_manifest':str(W/'answer_policy_frozen_manifest.json'),'prompt_unchanged':True,'retrieval_unchanged':True,'reference_and_rubric_unchanged':True,'active_entrypoint':'fair_streamlit_app_final.py','parser_version':'numeric-tokenizer-v3','files':[{'path':n,'sha256':sha(W/n)} for n in names]})
 print('Uniform numeric parser replay completed; raw generation unchanged. Changed results:',len(changes),flush=True)
if __name__=='__main__':main()
