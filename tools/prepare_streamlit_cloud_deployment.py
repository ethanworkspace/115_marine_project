"""Prepare an isolated, allowlisted Streamlit frontend and private API workspace."""
import datetime,hashlib,json,secrets,shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
APP=ROOT/'research_staging/app_sessions/launch_20261118_154253'
stamp=datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).strftime('%Y%m%d_%H%M%S')
OUT=ROOT/'research_staging/deployment'/('streamlit_cloud_'+stamp)
for name in ('frontend/assets','frontend/.streamlit','backend','state/runtime','reports','.private','bin'):(OUT/name).mkdir(parents=True,exist_ok=True)
(OUT/'.private/.gitignore').write_text('*\n!.gitignore\n',encoding='utf-8')
credentials={'api_key':secrets.token_urlsafe(48),'app_access_code':secrets.token_urlsafe(18)}
(OUT/'.private/credentials.json').write_text(json.dumps(credentials),encoding='utf-8')
for name in ('ocean_watercolor_chibi_background.png','watercolor_chat.png','watercolor_knowledge.png','watercolor_history.png'):
    shutil.copy2(APP/'assets'/name,OUT/'frontend/assets'/name)
shutil.copy2(APP/'platform_watercolor.css',OUT/'frontend/platform_watercolor.css')
shutil.copy2(APP/'knowledge_platform.py',OUT/'reports/local_ui_reference.py')
(OUT/'deployment_plan.json').write_text(json.dumps({'provider':'Streamlit Community Cloud','status':'BUILDING_NOT_DEPLOYED',
    'github_repository':'ethanworkspace/hybrid-rag-aquaculture-knowledge-platform','branch':'main',
    'repository_frontend_path':'streamlit_cloud/streamlit_app.py','desired_subdomain':'marine-knowledge-platform',
    'requested_public_url':'https://marine-knowledge-platform.streamlit.app','url_not_reserved_or_verified':True,
    'backend_local_url':'http://127.0.0.1:8765','model_id':'M2','models_and_corpus_uploaded':False,
    'requires_local_computer_online':True,'initial_access':'Access-code protected; shared owner workspace',
    'upload_scope':'Only frontend application code, generated interface images, CSS, dependency and public configuration files.'},ensure_ascii=False,indent=2),encoding='utf-8')
active=json.loads((ROOT/'research_staging/unified_rag_active.json').read_text(encoding='utf-8-sig'))
def sha(p):
    with Path(p).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()
baseline={'production_sqlite_sha256':sha(ROOT/'rag_store.sqlite3'),'active_corpus_sha256':sha(active['database']),
    'active_pointer_sha256':sha(ROOT/'research_staging/unified_rag_active.json')}
assert baseline['production_sqlite_sha256']=='d7d06d4d2a57d0a57d05bcb6131ffb24aefb226c6bd36349dbc5118d33b11087'
assert baseline['active_corpus_sha256']==active['database_sha256']
(OUT/'reports/baseline_before.json').write_text(json.dumps(baseline,indent=2),encoding='utf-8')
(ROOT/'research_staging/streamlit_cloud_deployment_pointer.json').write_text(json.dumps({'directory':str(OUT),'status':'BUILDING_NOT_DEPLOYED'},indent=2),encoding='utf-8')
print(json.dumps({'directory':str(OUT),'frontend_images':4,'secrets_created_locally_not_printed':True}))
