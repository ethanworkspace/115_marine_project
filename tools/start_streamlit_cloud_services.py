"""Start the local API/approved HTTPS connector and publish its endpoint only."""
import datetime,hashlib,json,os,re,shutil,subprocess,sys,time
from pathlib import Path
import psutil,requests
ROOT=Path(__file__).resolve().parents[1]
WORK=Path(json.loads((ROOT/'research_staging/streamlit_cloud_deployment_pointer.json').read_text(encoding='utf-8'))['directory'])
env=os.environ.copy()
env.update(PYTHONIOENCODING='utf-8',PYTHONDONTWRITEBYTECODE='1',PYTHONPATH=str(ROOT/'.venv-reranker/Lib/site-packages')+';'+str(ROOT/'.venv/Lib/site-packages'),GIT_TERMINAL_PROMPT='0',GCM_INTERACTIVE='never')
stamp=datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
def spawn(args,label):
    with (WORK/f'reports/{label}_stdout_{stamp}.log').open('ab') as out,(WORK/f'reports/{label}_stderr_{stamp}.log').open('ab') as err:
        return subprocess.Popen(args,cwd=ROOT,env=env,stdout=out,stderr=err,creationflags=subprocess.CREATE_NO_WINDOW)
try:
    response=requests.get('http://127.0.0.1:8765/health',timeout=3)
    assert response.json().get('service')=='marine-knowledge-api','Port belongs to another service.'
except requests.ConnectionError:
    proc=spawn([sys.executable,'-B',str(WORK/'backend/rag_api.py'),'--port','8765'],'api')
    (WORK/'state/api_process.json').write_text(json.dumps({'pid':proc.pid,'port':8765,'entrypoint':str(WORK/'backend/rag_api.py'),'local_url':'http://127.0.0.1:8765'}),encoding='utf-8')
    for _ in range(20):
        try:
            if requests.get('http://127.0.0.1:8765/health',timeout=2).json().get('service')=='marine-knowledge-api':break
        except requests.RequestException:pass
        time.sleep(.5)
    else:raise RuntimeError('Local API did not start; inspect reports.')
assert requests.get('http://127.0.0.1:8765/v1/bootstrap',timeout=3).status_code==401
process_file=WORK/'state/connector_process.json'
old=json.loads(process_file.read_text(encoding='utf-8-sig')) if process_file.exists() else {}
binary=WORK/'bin/cloudflared.exe'
try:
    connector=psutil.Process(old['pid'])
    running=Path(connector.exe()).resolve()==binary.resolve()
except (KeyError,psutil.NoSuchProcess,psutil.AccessDenied):running=False
if not running:
    expected=json.loads((WORK/'reports/cloudflared_download_integrity.json').read_text(encoding='utf-8'))['sha256']
    assert hashlib.file_digest(binary.open('rb'),'sha256').hexdigest()==expected
    check="(Get-AuthenticodeSignature -LiteralPath '"+str(binary).replace("'","''")+"').Status.ToString()"
    signature=subprocess.check_output(['powershell.exe','-NoProfile','-Command',check],text=True).strip()
    assert signature=='Valid','Connector signature invalid.'
    logfile=WORK/f'reports/connector_{stamp}.log'
    proc=spawn([str(binary),'tunnel','--url','http://127.0.0.1:8765','--no-autoupdate','--loglevel','info','--logfile',str(logfile)],'connector')
    process_file.write_text(json.dumps({'pid':proc.pid,'binary':str(binary),'upstream':'http://127.0.0.1:8765','logfile':str(logfile)}),encoding='utf-8')
subprocess.run([sys.executable,'-B',str(ROOT/'tools/record_streamlit_cloud_endpoint.py')],env=env,cwd=ROOT,check=True)
checkout=WORK/'github_checkout'
git=r'C:\Program Files\Git\cmd\git.exe'
def g(*args):return subprocess.check_output([git,'-C',str(checkout),*args],env=env,text=True).strip()
assert g('branch','--show-current')=='codex/streamlit-cloud'
assert g('remote','get-url','origin')=='https://github.com/ethanworkspace/115_marine_project.git'
assert not g('diff','--cached','--name-only'),'Unrelated staged files require review before endpoint update.'
target=checkout/'streamlit_cloud/backend_endpoint.json'
shutil.copy2(WORK/'frontend/backend_endpoint.json',target)
g('add','--','streamlit_cloud/backend_endpoint.json')
changed=g('diff','--cached','--name-only')
if changed:
    assert changed=='streamlit_cloud/backend_endpoint.json'
    g('-c','user.name=Ethan','-c','user.email=255327343+ethanworkspace@users.noreply.github.com','commit','-m','Refresh local knowledge API endpoint')
    g('push','origin','codex/streamlit-cloud')
print('Local knowledge service is ready. Keep this computer and Ollama running.')
