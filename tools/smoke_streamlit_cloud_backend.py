"""One real M2 API call, separate from frozen evaluations."""
import json,uuid
from pathlib import Path
import requests
ROOT=Path(__file__).resolve().parents[1]
WORK=Path(json.loads((ROOT/'research_staging/streamlit_cloud_deployment_pointer.json').read_text(encoding='utf-8'))['directory'])
credentials=json.loads((WORK/'.private/credentials.json').read_text(encoding='utf-8'))
expected='dae161e27b0e90dd1856c8bb3209201fd6736d8eb66298e75ed87571486f4364'
tags=requests.get('http://127.0.0.1:11434/api/tags',timeout=10).json()['models']
assert next(m['digest'] for m in tags if m['name']=='qwen2.5-coder:7b')==expected
response=requests.post('http://127.0.0.1:8765/v1/ask',headers={'Authorization':'Bearer '+credentials['api_key']},
    json={'question':'虱目魚常見的養殖方式有哪些？','model_id':'M2','request_id':str(uuid.uuid4())},timeout=(10,600))
assert response.status_code==200,(response.status_code,response.text[:300])
record=response.json()['record']
assert record['model_digest']==expected and record['api_completed'] and not record['api_error']
assert record['result']['answer_status'] in ('ANSWERED_GROUNDED','ANSWERED_PARTIAL','INSUFFICIENT_EVIDENCE','VALIDATION_FAILED')
assert record['result']['final_answer']
assert all(x['quote_verified'] for x in record['result']['validation_status'].get('exact_quote_checks',[]) if x.get('chunk_id') in record['result'].get('supporting_chunk_ids',[]))
(WORK/'reports/real_m2_api_smoke.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'status':'REAL_API_COMPLETED','model_id':record['model_id'],'model_digest':record['model_digest'],
    'answer_status':record['result']['answer_status'],'answer_origin':record['result']['answer_origin'],
    'raw_json_valid':record['result']['validation_status'].get('raw_json_valid'),'citation_count':len(record['result'].get('supporting_chunk_ids',[])),
    'not_a_720_evaluation':True},ensure_ascii=False))
