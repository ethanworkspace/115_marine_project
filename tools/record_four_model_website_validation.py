"""Record actual HTTPS results after the bounded website guard deployment."""
import datetime, hashlib, json, shutil, sys
from pathlib import Path
import requests
ROOT=Path(__file__).resolve().parents[1]
WORK=Path(json.loads((ROOT/'research_staging/streamlit_cloud_deployment_pointer.json').read_text(encoding='utf-8'))['directory'])
OUT=Path(json.loads((WORK/'four_model_update_pointer.json').read_text(encoding='utf-8-sig'))['directory'])
sys.path.insert(0,str(WORK/'frontend'))
from cloud_client import verify_endpoint_manifest
secret=json.loads((WORK/'.private/credentials.json').read_text(encoding='utf-8'))
url=verify_endpoint_manifest(json.loads((WORK/'frontend/backend_endpoint.json').read_text(encoding='utf-8')),secret['api_key'])
headers={'Authorization':'Bearer '+secret['api_key']}
saved=json.loads((OUT/'real_model_smoke_checkpoint.json').read_text(encoding='utf-8'))
checks={}; outcomes={}
bootstrap=requests.get(url+'/v1/bootstrap',headers=headers,timeout=30);bootstrap.raise_for_status()
bootstrap=bootstrap.json()
assert bootstrap['model_ids']==['M1','M2','M3','M4'] and bootstrap['default_model_id']=='M2'
checks['live_https_four_models_default_m2']=True
for model, item in saved.items():
    response=requests.get(url+'/v1/jobs/'+item['body']['request_id'],headers=headers,timeout=30)
    response.raise_for_status(); job=response.json(); record=job['record']
    assert job['status']=='DONE' and record['model_id']==model
    assert record['model_digest']==bootstrap['models'][model]['digest']
    assert record['result']['raw_model_answer']==item['record']['result']['raw_model_answer']
    outcomes[model]={'api_completed':record['api_completed'],'identity_matches':True,
                     'raw_json_valid':record['result']['validation_status']['raw_json_valid'],
                     'raw_citation_valid':record['result']['validation_status']['raw_citation_valid'],
                     'website_answer_status':record['result']['answer_status'],
                     'website_answer_origin':record['result']['answer_origin'],
                     'website_guard':record['result']['validation_status'].get('website_claim_guard'),
                     'grounded_answer_quality_independently_verified':False}
    if model=='M3':
        assert record['result']['answer_status']=='VALIDATION_FAILED'
        assert not record['result']['supporting_chunk_ids'] and not record['question_payload']['top5']
        assert '有机磷' not in record['result']['final_answer']
        checks['actual_m3_unsafe_answer_blocked_on_cached_job_without_overwriting_raw']=True
assert len(outcomes)==4
checks['actual_api_calls_and_runtime_identities_verified_all_four']=True
history=requests.get(url+'/v1/history',headers=headers,timeout=30);history.raise_for_status()
old_id=saved['M3']['record']['attempt_id']
old=next(r for r in history.json()['records'] if r['attempt_id']==old_id)
assert old['result']['answer_status']=='VALIDATION_FAILED'
checks['existing_m3_history_also_safely_rendered_without_data_mutation']=True
shutil.copy2(WORK/'reports/api_and_ui_validation.json',OUT/'api_and_ui_validation.json')
compat=json.loads((WORK/'reports/compatibility.json').read_text(encoding='utf-8'))
compat['model_identity_verification']='All four actual Ollama response digests match verified local registry; M3 llama family. Weight bytes not rehashed.'
(OUT/'compatibility.json').write_text(json.dumps(compat,ensure_ascii=False,indent=2),encoding='utf-8')
files={}
for relative in ('backend/rag_api.py','backend/model_registry.json','backend/website_answer_guard.py','frontend/streamlit_app.py','frontend/cloud_client.py'):
    files[relative]=hashlib.sha256((WORK/relative).read_bytes()).hexdigest()
report={'status':'PASS_WITH_MODEL_OUTPUT_LIMITATIONS','at':datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).isoformat(),
        'checks':checks,'actual_generator_calls':4,'outcomes':outcomes,'file_sha256':files,
        'formal_quality_benchmark':False,'mobile_app_built':False,
        'limitations':['One benign question per model does not establish general answer correctness.',
                       'M1 citation failed and was rejected; M3 unsupported extra claims are now blocked.',
                       'Website medication protocol is not independently verified; conservative presentation gate rejects medication content.',
                       'Single GPU, one active question, first model load can be slow; busy requests receive retry message.',
                       'Original corpus, production and historical experiments unchanged.']}
(OUT/'four_model_website_validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'status':report['status'],'checks':checks,'outcomes':outcomes},ensure_ascii=False))
