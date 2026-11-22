"""One real async M2 question over the approved HTTPS connector."""
import datetime,json,time,uuid
from pathlib import Path
import requests
ROOT=Path(__file__).resolve().parents[1]
WORK=Path(json.loads((ROOT/'research_staging/streamlit_cloud_deployment_pointer.json').read_text(encoding='utf-8'))['directory'])
secret=json.loads((WORK/'.private/credentials.json').read_text(encoding='utf-8'))
url=json.loads((WORK/'frontend/backend_endpoint.json').read_text(encoding='utf-8'))['backend_url']
headers={'Authorization':'Bearer '+secret['api_key']}
body={'question':'虱目魚常見的養殖方式有哪些？','model_id':'M2','selected_species':'虱目魚','request_id':str(uuid.uuid4())}
started=time.monotonic()
response=requests.post(url+'/v1/jobs',headers=headers,json=body,timeout=(10,30))
assert response.status_code==202,(response.status_code,response.text[:100])
job=response.json();polls=0
while job['status']=='RUNNING' and time.monotonic()-started<600:
    time.sleep(2);polls+=1
    response=requests.get(url+'/v1/jobs/'+body['request_id'],headers=headers,timeout=(10,30))
    response.raise_for_status();job=response.json()
assert job['status']=='DONE',job
record=job['record']
assert record['api_completed'] and record['model_digest']=='dae161e27b0e90dd1856c8bb3209201fd6736d8eb66298e75ed87571486f4364'
assert record['result']['validation_status']['raw_json_valid']
assert record['result']['validation_status']['raw_citation_valid']
assert all(r['quote_verified'] for r in record['result']['validation_status']['exact_quote_checks'])
again=requests.post(url+'/v1/jobs',headers=headers,json=body,timeout=(10,30)).json()
assert again['record']['attempt_id']==record['attempt_id']
report={'status':'PASS','actual_new_m2_generation':True,'async_https':True,'poll_count':polls,'elapsed_seconds':round(time.monotonic()-started,3),
        'idempotent_repeat_same_attempt':True,'request_id':body['request_id'],'request_payload':body,'record':record,
        'at':datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).isoformat()}
(WORK/'reports/real_async_https_m2_smoke.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({k:report[k] for k in ('status','actual_new_m2_generation','async_https','poll_count','elapsed_seconds','idempotent_repeat_same_attempt')},ensure_ascii=False))
