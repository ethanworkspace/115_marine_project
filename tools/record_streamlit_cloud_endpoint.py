"""Verify the private API through its HTTPS connector and prepare cloud secrets."""
import datetime,hashlib,hmac,json,re,time
from pathlib import Path
import requests
ROOT=Path(__file__).resolve().parents[1]
WORK=Path(json.loads((ROOT/'research_staging/streamlit_cloud_deployment_pointer.json').read_text(encoding='utf-8'))['directory'])
process=json.loads((WORK/'state/connector_process.json').read_text(encoding='utf-8-sig'))
url=None
for _ in range(45):
    log=Path(process['logfile'])
    if log.exists():
        matches=re.findall(r'https://[a-z0-9-]+\.trycloudflare\.com',log.read_text(encoding='utf-8',errors='replace'))
        if matches:url=matches[0];break
    time.sleep(1)
assert url,'Cloudflare connector did not supply a URL; check the saved logs.'
secret=json.loads((WORK/'.private/credentials.json').read_text(encoding='utf-8'))
health=None
for _ in range(10):
    try:
        result=requests.get(url+'/health',timeout=(10,10))
        if result.status_code==200 and result.json().get('service')=='marine-knowledge-api':health=True;break
    except (requests.RequestException,ValueError):pass
    time.sleep(1)
assert health,'The actual HTTPS backend could not be verified.'
assert requests.get(url+'/v1/bootstrap',timeout=(10,20)).status_code==401
data=requests.get(url+'/v1/bootstrap',headers={'Authorization':'Bearer '+secret['api_key']},timeout=(10,30)).json()
assert len(data['questions'])==180
manifest={'backend_url':url,'updated_at':datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).isoformat(),
    'service':'marine-knowledge-api','credentials_not_in_this_file':True,'signature_version':'hmac-sha256-v1'}
manifest['signature']=hmac.new(secret['api_key'].encode(),json.dumps(manifest,sort_keys=True,separators=(',',':')).encode(),hashlib.sha256).hexdigest()
(WORK/'frontend/backend_endpoint.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
discovery='https://raw.githubusercontent.com/ethanworkspace/hybrid-rag-aquaculture-knowledge-platform/refs/heads/codex/streamlit-cloud/streamlit_cloud/backend_endpoint.json'
lines=['RAG_BACKEND_DISCOVERY_URL = '+json.dumps(discovery),'RAG_API_KEY = '+json.dumps(secret['api_key']),'APP_ACCESS_CODE = '+json.dumps(secret['app_access_code'])]
(WORK/'.private/streamlit_secrets.toml').write_text('\n'.join(lines)+'\n',encoding='utf-8')
(WORK/'.private/owner_access_code.txt').write_text(secret['app_access_code']+'\n',encoding='utf-8')
report={'https_backend_verified':True,'unauthenticated_private_routes_rejected':True,'original_questions':180,
    'backend_url':url,'discovery_url':discovery,'secrets_created_locally_not_printed':True,
    'connector_restarts_require_endpoint_manifest_update':True,'streamlit_frontend_deployed':False}
(WORK/'reports/https_backend_validation.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps(report))
