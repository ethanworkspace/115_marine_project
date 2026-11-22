"""Bounded local security acceptance tests; no live Streamlit page/browser access."""
import ast,hashlib,hmac,importlib.util,json,os,re,sqlite3,subprocess,sys,threading,time,uuid
from pathlib import Path
import requests
from PIL import Image
ROOT=Path(__file__).resolve().parents[1]
WORK=Path(json.loads((ROOT/'research_staging/streamlit_cloud_deployment_pointer.json').read_text(encoding='utf-8'))['directory'])
AUDIT=Path(os.environ.get('MARINE_SECURITY_TEST_OUTPUT') or json.loads((WORK/'security_audit_pointer.json').read_text(encoding='utf-8-sig'))['directory'])
secret=json.loads((WORK/'.private/credentials.json').read_text(encoding='utf-8'))
sys.path.insert(0,str(WORK/'frontend'))
import cloud_client
spec=importlib.util.spec_from_file_location('security_backend',WORK/'backend/rag_api.py')
backend=importlib.util.module_from_spec(spec);spec.loader.exec_module(backend)
RUN=AUDIT/'test_runs'/str(time.time_ns())
RUN.mkdir(parents=True,exist_ok=True)
service=backend.Service(RUN/'isolated_http_state')
server=backend.Server(('127.0.0.1',0),service)
threading.Thread(target=server.serve_forever,daemon=True).start()
url='http://127.0.0.1:'+str(server.server_port)
headers={'Authorization':'Bearer '+secret['api_key']}
checks=[]
def check(name,condition,scope='LOCAL_SECURITY_TEST'):
    assert condition,name
    checks.append({'check':name,'passed':True,'scope':scope})
def post(path,body,**kw):return requests.post(url+path,headers=headers,json=body,timeout=10,**kw)
try:
    for path in ('/v1/bootstrap','/v1/history','/v1/notes','/v1/jobs/'+str(uuid.uuid4()),'/v1/media/test','/.private/credentials.json','/rag_store.sqlite3'):
        check('unauthenticated_denied_'+path,requests.get(url+path,timeout=10).status_code==401)
    for _ in range(21):response=requests.get(url+'/v1/bootstrap',headers={'Authorization':'Bearer invalid'},timeout=10)
    check('invalid_key_attempts_rate_limited',response.status_code==429)
    valid=requests.get(url+'/v1/bootstrap',headers=headers,timeout=10)
    check('valid_key_still_works_under_bad_key_throttle',valid.status_code==200)
    check('no_cors_wildcard_or_python_version',not valid.headers.get('Access-Control-Allow-Origin') and 'Python' not in valid.headers.get('Server',''))
    check('security_headers',valid.headers.get('X-Content-Type-Options')=='nosniff' and valid.headers.get('Referrer-Policy')=='no-referrer')
    check('cross_origin_get_blocked',requests.get(url+'/v1/bootstrap',headers=headers|{'Origin':'https://untrusted.example'},timeout=10).status_code==403)
    check('cross_origin_post_blocked',requests.post(url+'/v1/notes',headers=headers|{'Origin':'https://untrusted.example'},json={},timeout=10).status_code==403)
    check('non_json_rejected',requests.post(url+'/v1/notes',headers=headers|{'Content-Type':'text/plain'},data='{}',timeout=10).status_code==415)
    check('malformed_json_rejected',requests.post(url+'/v1/notes',headers=headers|{'Content-Type':'application/json'},data='{?',timeout=10).status_code==400)
    check('oversize_body_rejected',requests.post(url+'/v1/notes',headers=headers|{'Content-Type':'application/json'},data='x'*131073,timeout=10).status_code==413)
    cases=[{'request_id':1,'question':'test'},{'request_id':str(uuid.uuid4()),'question':{'text':'test'}},
        {'request_id':str(uuid.uuid4()),'question':'x'*2001},{'request_id':str(uuid.uuid4()),'question':'a\0b'},
        {'request_id':str(uuid.uuid4()),'question':'test','prompt':'override'},
        {'request_id':str(uuid.uuid4()),'question':'test','context':[]},
        {'request_id':str(uuid.uuid4()),'question':'test','model_id':'UNAPPROVED_MODEL'},
        {'request_id':str(uuid.uuid4()),'question_id':'missing'},{'request_id':str(uuid.uuid4()),'question_id':[]},
        {'request_id':str(uuid.uuid4()),'question':'test','selected_species':'午仔魚'}]
    for index,body in enumerate(cases):check('invalid_job_schema_'+str(index),post('/v1/jobs',body).status_code==400)
    check('invalid_inputs_do_not_load_generator',service.runtime is None)
    for model in ('M1','M2','M3','M4'):
        service.validate_question({'request_id':str(uuid.uuid4()),'question':'安全測試','model_id':model})
    check('verified_website_model_allowlist_accepts_all_four_without_loading_models',service.runtime is None)
    check('no_file_or_admin_routes',all(requests.get(url+p,headers=headers,timeout=10).status_code==404 for p in ('/.private/credentials.json','/api/tags','/v1/files','/rag_store.sqlite3')))
    for index,body in enumerate(({'title':{},'body':'test'},{'title':'test','body':'test','origin':'HUMAN_GOLD'},
          {'title':'x'*81,'body':'test'},{'title':'test','body':'test','note_id':'../../private'},
          {'title':'test','body':'test','provenance':[]})):
        check('invalid_note_schema_'+str(index),post('/v1/notes',body).status_code==400)
    payload="<script>alert('x')</script> '; DROP TABLE knowledge_notes; --"
    note=post('/v1/notes',{'title':'安全測試','body':payload}).json()
    check('sql_text_is_data_and_notes_remain',service.notes.get(note['note_id'])['body']==payload and service.notes.list())
    check('source_data_not_written_to_rag',service.notes.path.is_relative_to(AUDIT))
    with service.db() as con:
        rid=str(uuid.uuid4());digest='fixture'
        con.execute("INSERT INTO jobs(request_id,payload_digest,status) VALUES (?,?,'RUNNING')",(rid,digest))
    check('busy_generator_rejected_without_second_model',post('/v1/jobs',{'request_id':str(uuid.uuid4()),'question':'test'}).status_code==429)
    with service.db() as con:con.execute("UPDATE jobs SET status='FAILED' WHERE request_id=?",(rid,))
    fake_db=RUN/'fixture_corpus.sqlite3'
    with sqlite3.connect(fake_db) as con:
        con.execute('CREATE TABLE IF NOT EXISTS media_assets(asset_id TEXT PRIMARY KEY,path TEXT)')
        con.execute('INSERT OR REPLACE INTO media_assets VALUES (?,?)',('security-test-image',str(WORK/'frontend/assets/aquaculture_fish_favicon_v1.png')))
        con.execute('INSERT OR REPLACE INTO media_assets VALUES (?,?)',('security-test-private',str(WORK/'.private/credentials.json')))
    service.active=service.active|{'database':str(fake_db)}
    check('unpublished_image_is_denied',requests.get(url+'/v1/media/security-test-image',headers=headers,timeout=10).status_code==404)
    with service.db() as con:
        con.execute('INSERT OR IGNORE INTO published_media VALUES (?)',('security-test-image',))
        con.execute('INSERT OR IGNORE INTO published_media VALUES (?)',('security-test-private',))
    check('published_image_is_served',requests.get(url+'/v1/media/security-test-image',headers=headers,timeout=10).status_code==200)
    check('private_non_image_cannot_be_served',requests.get(url+'/v1/media/security-test-private',headers=headers,timeout=10).status_code==404)
    for suffix in ('..%2f..%2f.private%2fcredentials.json','bad?path=credentials.json'):
        check('image_traversal_denied_'+suffix,requests.get(url+'/v1/media/'+suffix,headers=headers,timeout=10).status_code==404)
    manifest={'backend_url':'https://trusted-test.trycloudflare.com','updated_at':'test','service':'marine-knowledge-api','credentials_not_in_this_file':True,'signature_version':'hmac-sha256-v1'}
    manifest['signature']=hmac.new(secret['api_key'].encode(),json.dumps(manifest,sort_keys=True,separators=(',',':')).encode(),hashlib.sha256).hexdigest()
    check('valid_endpoint_signature_accepted',cloud_client.verify_endpoint_manifest(manifest,secret['api_key'])==manifest['backend_url'])
    for index,bad in enumerate((manifest|{'backend_url':'https://attacker.trycloudflare.com'},manifest|{'signature':'0'*64},[],{})):
        try:cloud_client.verify_endpoint_manifest(bad,secret['api_key']);accepted=True
        except cloud_client.BackendError:accepted=False
        check('invalid_or_tampered_manifest_denied_'+str(index),not accepted)
    for address in ('http://evil.example','https://evil.example','https://trusted.trycloudflare.com@evil.example','https://a.trycloudflare.com/private','https://a.trycloudflare.com?key=x','https://a.trycloudflare.com:invalid','https://a.trycloudflare.com/#fragment'):
        try:cloud_client.safe_backend_url(address);accepted=True
        except cloud_client.BackendError:accepted=False
        check('untrusted_backend_denied_'+address,not accepted)
    for value in ('![image](https://untrusted.example/pixel)','\\![x](https://untrusted.example)','![x][ref]'):
        safe=cloud_client.safe_answer_markdown(value)
        check('automatic_markdown_image_blocked_'+str(len(checks)),safe.startswith('\\!['))
    image=Image.open(WORK/'frontend/assets/aquaculture_fish_favicon_v1.png')
    check('favicon_is_square_transparent_png',image.format=='PNG' and image.width==image.height and image.mode=='RGBA' and image.getchannel('A').getextrema()==(0,255))
    tree=ast.parse((WORK/'frontend/streamlit_app.py').read_text(encoding='utf-8'))
    icon=[n for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr=='set_page_config'][0]
    check('page_config_uses_new_favicon',any(k.arg=='page_icon' and 'aquaculture_fish_favicon_v1.png' in ast.unparse(k.value) for k in icon.keywords))
    os.environ.update(RAG_BACKEND_URL=url,RAG_API_KEY=secret['api_key'],APP_ACCESS_CODE=secret['app_access_code'],MARINE_ALLOW_LOOPBACK='1')
    from streamlit.testing.v1 import AppTest
    app=AppTest.from_file(str(WORK/'frontend/streamlit_app.py'),default_timeout=40).run(timeout=40)
    for _ in range(5):
        app.text_input(key='cloud_access_input').set_value('not-the-code')
        app.button(key='FormSubmitter:cloud_login-進入知識平台').click().run(timeout=40)
    app.run(timeout=40)
    check('session_login_attempt_limit_enforced',not app.text_input and bool(app.warning) and not app.exception)
    login=AppTest.from_file(str(WORK/'frontend/streamlit_app.py'),default_timeout=40).run(timeout=40)
    login.text_input(key='cloud_access_input').set_value(secret['app_access_code'])
    login.button(key='FormSubmitter:cloud_login-進入知識平台').click().run(timeout=40)
    check('valid_login_still_works',not login.exception and login.button(key='free_answer').label=='開始問答')
    login.button(key='nav_knowledge').click().run(timeout=40)
    rendered='\n'.join(x.value for x in login.markdown)
    check('note_html_escaped', '&lt;script&gt;' in rendered and '<script>' not in rendered)
finally:
    server.shutdown();server.server_close()
git=r'C:\Program Files\Git\cmd\git.exe';repo=WORK/'github_checkout'
objects=subprocess.check_output([git,'-C',str(repo),'rev-list','--objects','--all']).decode().splitlines()
findings=[];scanned=0
for item in objects:
    oid,_,name=item.partition(' ')
    if not name:continue
    if subprocess.check_output([git,'-C',str(repo),'cat-file','-t',oid]).strip()!=b'blob':continue
    data=subprocess.check_output([git,'-C',str(repo),'cat-file','blob',oid]);scanned+=1
    for label,value in secret.items():
        if value.encode() in data:findings.append({'path':name,'category':'actual_'+label,'value':'REDACTED'})
    for label,pattern in [('private_key',rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),('openai_key',rb'\bsk-[A-Za-z0-9_-]{30,}'),('github_token',rb'\bgh[pousr]_[A-Za-z0-9]{30,}')]:
        if re.search(pattern,data):findings.append({'path':name,'category':label,'value':'REDACTED'})
check('published_git_history_has_no_actual_keys_or_private_key_patterns',not findings)
report={'status':'PASS','passed':len(checks),'checks':checks,'git_history_blobs_scanned':scanned,'secret_findings':findings,
    'security_fixture_data_not_research_evidence':True,'production_or_corpus_written':False,'real_generator_test':'separate',
    'online_streamlit_browser_verification':'BLOCKED_BY_PREVIOUS_AUTOMATIC_APPROVAL_REVIEW; no workaround attempted',
    'limitations':['Session login throttling can be bypassed by a new browser session; not a full identity provider.','Single owner/shared-code workspace; no per-user isolation.','Quick Tunnel has no uptime guarantee.','This bounded source/API test is not a professional penetration-test certification.']}
(AUDIT/'security_acceptance_results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'status':report['status'],'passed':len(checks),'git_history_blobs_scanned':scanned,'secret_findings':len(findings),'live_cloud_browser_verified':False}))
