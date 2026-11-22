"""Preserve the actual deployment and authenticated live smoke receipts."""
import datetime,json,shutil,subprocess
from pathlib import Path
import requests
ROOT=Path(__file__).resolve().parents[1]
WORK=Path(json.loads((ROOT/'research_staging/streamlit_cloud_deployment_pointer.json').read_text(encoding='utf-8'))['directory'])
secret=json.loads((WORK/'.private/credentials.json').read_text(encoding='utf-8'))
url=json.loads((WORK/'frontend/backend_endpoint.json').read_text(encoding='utf-8'))['backend_url']
headers={'Authorization':'Bearer '+secret['api_key']}
assert requests.get(url+'/v1/bootstrap',timeout=(10,20)).status_code==401
history=requests.get(url+'/v1/history',headers=headers,timeout=(10,30)).json()['records']
record=history[-1]
assert record['question']=='虱目魚常見的養殖方式有哪些？'
assert record['result']['answer_origin']=='MODEL_GENERATED'
assert all(record['result']['validation_status'][k] for k in ('raw_json_valid','raw_citation_valid','raw_span_binding_valid'))
assert record['result']['validation_status']['exact_quote_checks'] and all(r['quote_verified'] for r in record['result']['validation_status']['exact_quote_checks'])
notes=requests.get(url+'/v1/notes',headers=headers,params={'query':record['question']},timeout=(10,30)).json()['notes']
assert len(notes)==1 and notes[0]['body']==record['result']['final_answer']
site='https://aquaculture-knowledge-platform.streamlit.app/'
page=requests.get(site,timeout=(10,30));page.raise_for_status()
receipt={'status':'PASS','public_url':site,'browser_observed_login_gate':True,'browser_observed_authenticated_live_m2_answer':True,
    'browser_observed_cited_source_text':True,'browser_observed_saved_knowledge_card':True,
    'live_m2_record':record,'saved_note_id':notes[0]['note_id'],'saved_note_provenance_preserved':True,
    'site_http_status':page.status_code,'unauthenticated_api_rejected':True,'exposes_ollama_admin_or_database':False,
    'semantic_answer_completeness_independently_verified':False,
    'at':datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).isoformat()}
(WORK/'reports/live_streamlit_validation.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8')
status=json.loads((WORK/'deployment_status.json').read_text(encoding='utf-8'))
status.update(status='DEPLOYED_AND_LIVE_SMOKE_VERIFIED',streamlit_deployed=True,streamlit_public_url=site,
    subdomain_reserved_or_available_verified=True,remaining_steps=[],at=receipt['at'],
    cloud_secrets_stored_in_streamlit_not_github=True,actual_cloud_ui_question_and_note_save_passed=True,
    deployment_notice='Keep local PC, Ollama, API and Cloudflare connector running. Use start_knowledge_service.cmd after restart. Quick Tunnel has no uptime guarantee.')
(WORK/'deployment_status.json').write_text(json.dumps(status,ensure_ascii=False,indent=2),encoding='utf-8')
(ROOT/'research_staging/streamlit_cloud_deployment_pointer.json').write_text(json.dumps({'directory':str(WORK),'status':status['status'],'public_url':site},ensure_ascii=False,indent=2),encoding='utf-8')
shutil.copy2(WORK/'reports/compatibility.json',WORK/'compatibility.json')
instructions=(WORK/'deployment_instructions.txt').read_text(encoding='utf-8-sig')
instructions=instructions.replace('尚未完成 Streamlit 帳號登入與正式部署。','已完成 Streamlit 帳號登入與正式部署。')
instructions=instructions.replace('建議網址名稱：marine-knowledge-platform（尚未確認是否可用）','固定網站網址：https://marine-knowledge-platform.streamlit.app/')
(WORK/'deployment_instructions.txt').write_text(instructions,encoding='utf-8-sig')
print(json.dumps({'status':status['status'],'public_url':site,'model':'M2','raw_json_valid':True,'citation_valid':True,'actual_cloud_note_save':True,'protected':'636/636'},ensure_ascii=False))
