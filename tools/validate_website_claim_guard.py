"""Verify public suppression against the actual failing M3 response and controls."""
import copy, json, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
WORK=Path(json.loads((ROOT/'research_staging/streamlit_cloud_deployment_pointer.json').read_text(encoding='utf-8'))['directory'])
OUT=Path(json.loads((WORK/'four_model_update_pointer.json').read_text(encoding='utf-8-sig'))['directory'])
sys.path.insert(0,str(WORK/'backend'))
from website_answer_guard import protect_website_answer, VERSION
state=json.loads((OUT/'real_model_smoke_checkpoint.json').read_text(encoding='utf-8'))
checks={}
raw=state['M3']['record']; saved=copy.deepcopy(raw)
protected=protect_website_answer(raw)
assert raw==saved and protected['result']['raw_model_answer']==raw['result']['raw_model_answer']
assert protected['result']['answer_status']=='VALIDATION_FAILED'
assert '有机磷' not in protected['result']['final_answer']
assert not protected['question_payload']['top5'] and not protected['result']['supporting_chunk_ids']
checks['actual_m3_unsupported_medication_and_numbers_suppressed_raw_preserved']=True
for model in ('M1','M2','M4'):
    assert protect_website_answer(state[model]['record'])==state[model]['record']
checks['other_actual_model_records_not_silently_changed']=True
example=copy.deepcopy(state['M2']['record'])
example['result']['final_answer']='放養密度一般為每公頃50萬尾。'
assert protect_website_answer(example)['result']['answer_status']=='VALIDATION_FAILED'
checks['unrequested_management_number_blocked']=True
example['question']='放養密度是多少？'
assert protect_website_answer(example)['result']['answer_status']=='ANSWERED_PARTIAL'
checks['requested_numbers_remain_subject_to_existing_source_validation']=True
for text in ('可用藥物治療。','停藥期7天。','使用有機磷劑。'):
    example['result']['final_answer']=text
    assert protect_website_answer(example)['result']['answer_status']=='VALIDATION_FAILED'
checks['medication_requires_verified_protocol_not_citation_existence']=True
report={'version':VERSION,'status':'PASS','checks':checks,
        'scope':'bounded regression, not exhaustive claim entailment or expert verification',
        'human_gold':False}
(OUT/'website_claim_guard_validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False))
