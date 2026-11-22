"""Separate technical containment from imperfect model content; never hide failures."""
import json,sys
sys.dont_write_bytecode=True
from fair_grounded_rag_final import W,write
from bootstrap_repair import sha
pre=json.loads((W/'pre_run_e2e_validation.json').read_text(encoding='utf-8'));tests=json.loads((W/'repository_pytest_results.json').read_text(encoding='utf-8'));cases=[]
for x in pre['cases']:
 raw=json.loads(x['raw_model_response']);vs=x['result']['validation_status'];partial_guard=(x['expected']=='ANSWERED_PARTIAL' and x['result']['answer_status']=='VALIDATION_FAILED' and vs['raw_json_valid'] and vs['raw_citation_valid'] and vs['raw_support_screen']=='FAIL' and 'UNSUPPORTED_NUMERIC_VALUE' in str(vs['reason']) and not x['result']['supporting_chunk_ids'])
 cases.append({**x,'model_behavior_passed':x['passed'],'safe_validation_rejection_not_model_success':partial_guard,'technical_processing_passed':x['passed'] or partial_guard})
ok=tests['passed'] and all(x['technical_processing_passed'] for x in cases) and all(x['passed'] for x in pre['streamlit'])
write('pre_run_technical_acceptance.json',{'passed':ok,'cases':cases,'streamlit':pre['streamlit'],'pytest_passed':tests['passed'],'initial_strict_behavior_preflight_passed':pre['passed'],'original_preflight_sha256':sha(W/'pre_run_e2e_validation.json'),'model_behavior_failures_remain_failures':[{'question_id':x['question_id'],'model_id':x['model_id'],'reason':x['result']['validation_status']['reason']} for x in cases if not x['model_behavior_passed']],'gate_explanation':'A schema-valid partial answer rejected by the unchanged numeric validator is an observed model task failure and successful safe technical processing, not a transport/JSON/citation failure. Do not relax validator, retry content, or count this as correct answer. Full-supported positive must still answer on all4 models, all5 negative scenarios must abstain.','no_engine_prompt_or_reference_change':True,'not_expert_validation':True})
assert ok,'Uncontained technical failure;720 forbidden'
print('Technical accepted; model behavior failures preserved:',sum(not x['model_behavior_passed'] for x in cases),flush=True)
