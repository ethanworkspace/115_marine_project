"""Real HTTP and UI checks; generator smoke is explicitly separate."""
import ast,hashlib,importlib.util,json,os,sys,threading,time,uuid
from pathlib import Path
import requests
ROOT=Path(__file__).resolve().parents[1]
WORK=Path(json.loads((ROOT/'research_staging/streamlit_cloud_deployment_pointer.json').read_text(encoding='utf-8'))['directory'])
secret=json.loads((WORK/'.private/credentials.json').read_text(encoding='utf-8'))
spec=importlib.util.spec_from_file_location('cloud_backend_test',WORK/'backend/rag_api.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
service=module.Service(WORK/'reports/test_api_state')
server=module.Server(('127.0.0.1',0),service)
thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
url='http://127.0.0.1:'+str(server.server_port)
headers={'Authorization':'Bearer '+secret['api_key']}
checks={}
try:
    assert requests.get(url+'/health',timeout=10).status_code==200
    assert requests.get(url+'/v1/bootstrap',timeout=10).status_code==401
    assert requests.get(url+'/v1/notes',headers={'Authorization':'Bearer invalid'},timeout=10).status_code==401
    checks['api_requires_valid_key']=True
    bootstrap=requests.get(url+'/v1/bootstrap',headers=headers,timeout=10).json()
    assert len(bootstrap['questions'])==180 and bootstrap['model_ids']==['M1','M2','M3','M4'] and bootstrap['default_model_id']=='M2'
    assert not any('source_file' in r for r in bootstrap['sources'].values())
    checks['bootstrap_retains_180_questions_without_gold_or_local_paths']=True
    for body in ({'question':'test','request_id':str(uuid.uuid4()),'top5':[]},
                 {'question':'test','request_id':str(uuid.uuid4()),'model_id':'UNAPPROVED_MODEL'},
                 {'question':'','request_id':str(uuid.uuid4())}):
        assert requests.post(url+'/v1/ask',headers=headers,json=body,timeout=10).status_code==400
    assert service.runtime is None
    checks['invalid_questions_and_external_context_rejected_before_model_load']=True
    for body in ({'question':'','request_id':str(uuid.uuid4())},{'question':'test','request_id':'not-a-uuid'}):
        assert requests.post(url+'/v1/jobs',headers=headers,json=body,timeout=10).status_code==400
    live_record=json.loads((WORK/'reports/real_m2_api_smoke.json').read_text(encoding='utf-8'))
    cached_body={'question':live_record['question'],'model_id':'M2','request_id':str(uuid.uuid4())}
    digest=hashlib.sha256(json.dumps(cached_body,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    with service.db() as con:con.execute('INSERT INTO requests (request_id,payload_digest,response_json) VALUES (?,?,?)',(cached_body['request_id'],digest,json.dumps(live_record,ensure_ascii=False)))
    cached=requests.post(url+'/v1/jobs',headers=headers,json=cached_body,timeout=10).json()
    assert cached['status']=='DONE' and cached['record']['attempt_id']==live_record['attempt_id']
    recovered=requests.get(url+'/v1/jobs/'+cached_body['request_id'],headers=headers,timeout=10).json()
    assert recovered['record']==cached['record']
    assert requests.post(url+'/v1/jobs',headers=headers,json=cached_body|{'question':'different'},timeout=10).status_code==400
    assert service.runtime is None
    checks['async_resume_returns_actual_cached_record_without_regeneration']=True
    note={'title':'雲端介面測試','body':'僅存於隔離測試筆記庫。','species':'通用','topic':'其他'}
    created=requests.post(url+'/v1/notes',headers=headers,json=note,timeout=10).json()['note_id']
    notes=requests.get(url+'/v1/notes',headers=headers,params={'query':'介面測試'},timeout=10).json()['notes']
    assert any(r['note_id']==created for r in notes)
    checks['notes_round_trip_over_authenticated_http']=True
    note.update(note_id=created,title='雲端介面測試已編輯')
    assert requests.post(url+'/v1/notes',headers=headers,json=note,timeout=10).status_code==200
    assert service.notes.get(created)['title'].endswith('已編輯')
    checks['notes_update_persists_on_backend']=True
    assert requests.get(url+'/v1/media/..%2F..%2Fsecret',headers=headers,timeout=10).status_code==404
    checks['media_rejects_path_traversal']=True
    os.environ.update(RAG_BACKEND_URL=url,RAG_API_KEY=secret['api_key'],APP_ACCESS_CODE=secret['app_access_code'],MARINE_ALLOW_LOOPBACK='1')
    sys.path.insert(0,str(WORK/'frontend'))
    from streamlit.testing.v1 import AppTest
    app=AppTest.from_file(str(WORK/'frontend/streamlit_app.py'),default_timeout=45).run(timeout=45)
    assert not app.exception
    assert any('工作區存取碼'==x.label for x in app.text_input)
    assert not any(x.key=='free_answer' for x in app.button)
    checks['cloud_ui_gate_precedes_private_data']=True
    app.text_input(key='cloud_access_input').set_value(secret['app_access_code'])
    app.button(key='FormSubmitter:cloud_login-進入知識平台').click().run(timeout=45)
    assert not app.exception,[e.message for e in app.exception]
    assert app.button(key='free_answer').label=='開始問答'
    assert app.selectbox(key='platform_model').options==['M1 · DeepSeek R1 · Qwen 7B','M2 · Qwen2.5 Coder · 7B','M3 · DeepSeek R1 · Llama 8B','M4 · Gemma 2 · 9B']
    assert app.selectbox(key='platform_model').value=='M2'
    for model in ('M1','M3','M4','M2'):
        app.selectbox(key='platform_model').set_value(model).run(timeout=45)
        assert not app.exception and app.selectbox(key='platform_model').value==model
    checks['cloud_ui_four_models_switchable_default_m2']=True
    app.radio(key='platform_question_mode').set_value('挑選問題').run(timeout=45)
    assert len(app.selectbox(key='platform_question').options)==180
    checks['cloud_ui_original_question_bank']=True
    app.button(key='nav_knowledge').click().run(timeout=45)
    assert not app.exception and app.button(key='new_note')
    app.button(key='new_note').click().run(timeout=45)
    app.text_input(key='note_title').set_value('雲端表單測試')
    app.text_area(key='note_body').set_value('透過真正HTTP儲存，非雲端暫存SQLite。')
    app.button(key='FormSubmitter:knowledge_note_form-儲存小知識').click().run(timeout=45)
    assert not app.exception,[e.message for e in app.exception]
    assert service.notes.list('雲端表單測試')
    checks['cloud_ui_note_form_uses_backend_storage']=True
    app.button(key='nav_history').click().run(timeout=45)
    assert not app.exception
    checks['cloud_ui_history_without_local_research_log']=True
finally:
    server.shutdown();server.server_close()
report={'status':'PASS','checks':checks,'actual_local_http':True,'generator_called':False,'generator_mocked':False,
    'separate_test_notes_database':True,'cloud_package_does_not_contain_corpus_or_credentials':True}
(WORK/'reports/api_and_ui_validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False))
