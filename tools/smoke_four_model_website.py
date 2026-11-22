"""Real per-model API smoke, sequential GPU use, checkpointed; no benchmark scores."""
import datetime,json,sys,time,uuid
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
bootstrap=requests.get(url+'/v1/bootstrap',headers=headers,timeout=(10,30)).json()
assert bootstrap['model_ids']==['M1','M2','M3','M4'] and bootstrap['default_model_id']=='M2'
registry=json.loads((WORK/'backend/model_registry.json').read_text(encoding='utf-8'))['models']
state_file=OUT/'real_model_smoke_checkpoint.json'
state=json.loads(state_file.read_text(encoding='utf-8')) if state_file.exists() else {}
for model in ('M2','M1','M3','M4'):
    saved=state.get(model,{})
    if saved.get('status')=='DONE':continue
    body=saved.get('body') or {'question':'虱目魚常見的養殖方式有哪些？','model_id':model,'request_id':str(uuid.uuid4())}
    state[model]={'body':body,'status':'STARTED'}
    state_file.write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding='utf-8')
    start=time.monotonic()
    response=requests.post(url+'/v1/jobs',headers=headers,json=body,timeout=(10,30));response.raise_for_status();job=response.json()
    while job['status']=='RUNNING' and time.monotonic()-start<700:
        time.sleep(2);response=requests.get(url+'/v1/jobs/'+body['request_id'],headers=headers,timeout=(10,30));response.raise_for_status();job=response.json()
    assert job['status']=='DONE',(model,job.get('error',job['status']))
    record=job['record'];flags=record['result']['validation_status']
    identity=(record['model_id']==model and record['model_digest']==registry[model]['digest'])
    passed=bool(identity and record.get('api_completed') and flags['raw_json_valid'] and flags['raw_citation_valid'] and flags['raw_span_binding_valid'] and
                record['result']['answer_status'] in ('ANSWERED_GROUNDED','ANSWERED_PARTIAL') and flags['exact_quote_checks'] and all(q['quote_verified'] for q in flags['exact_quote_checks']))
    state[model].update(status='DONE',passed=passed,identity_matches=identity,record=record,elapsed_seconds=round(time.monotonic()-start,3))
    state_file.write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'model':model,'passed':passed,'identity_matches':identity,'answer_status':record['result']['answer_status'],
                      'origin':record['result']['answer_origin'],'raw_json_valid':flags['raw_json_valid'],'citation_valid':flags['raw_citation_valid']},ensure_ascii=False),flush=True)
results={'status':'PASS' if all(s.get('passed') for s in state.values()) and len(state)==4 else 'NEEDS_REVIEW',
         'real_models':state,'serial_execution':True,'mocked':False,'formal_model_quality_comparison':False,
         'at':datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).isoformat()}
(OUT/'four_model_real_api_smoke.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'status':results['status'],'completed_models':list(state)},ensure_ascii=False))
