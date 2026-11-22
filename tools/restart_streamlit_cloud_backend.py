"""Restart only the deployment API owned by this workspace; preserve logs/state."""
import datetime,json,os,sqlite3,subprocess,time
from pathlib import Path
import psutil,requests
ROOT=Path(__file__).resolve().parents[1]
WORK=Path(json.loads((ROOT/'research_staging/streamlit_cloud_deployment_pointer.json').read_text(encoding='utf-8'))['directory'])
record=json.loads((WORK/'state/api_process.json').read_text(encoding='utf-8-sig'))
database=WORK/'state/cloud_requests.sqlite3'
if database.exists():
    with sqlite3.connect(database.as_uri()+'?mode=ro',uri=True) as con:
        assert con.execute("SELECT count(*) FROM jobs WHERE status='RUNNING'").fetchone()[0]==0,'A live question is still running; do not interrupt it.'
entry=str(WORK/'backend/rag_api.py').lower()
owned=[]
try:
    parent=psutil.Process(record['pid'])
    for proc in [parent]+parent.children(recursive=True):
        try:
            if any(str(arg).lower()==entry for arg in proc.cmdline()):owned.append(proc)
        except (psutil.NoSuchProcess,psutil.AccessDenied):pass
    assert owned,'Refusing to stop a process whose API entry point cannot be verified.'
except psutil.NoSuchProcess:pass
for proc in reversed(owned):
    try:proc.terminate()
    except psutil.NoSuchProcess:pass
_,alive=psutil.wait_procs(owned,timeout=5)
for proc in alive:
    try:
        if any(str(arg).lower()==entry for arg in proc.cmdline()):proc.kill()
    except psutil.NoSuchProcess:pass
assert not any(c.status=='LISTEN' and c.laddr.port==8765 for c in psutil.net_connections(kind='tcp')),'Port 8765 is still occupied.'
stamp=datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
interpreter=ROOT/'reports/evaluation/fish_test_corpus_v3_evidence_alignment_20261021_022237/test_env/Scripts/python.exe'
env=os.environ.copy()
env.update(PYTHONIOENCODING='utf-8',PYTHONDONTWRITEBYTECODE='1',PYTHONPATH=str(ROOT/'.venv-reranker/Lib/site-packages')+';'+str(ROOT/'.venv/Lib/site-packages'))
with (WORK/f'reports/api_stdout_{stamp}.log').open('ab') as out,(WORK/f'reports/api_stderr_{stamp}.log').open('ab') as err:
    proc=subprocess.Popen([str(interpreter),'-B',str(WORK/'backend/rag_api.py'),'--port','8765'],cwd=ROOT,env=env,stdout=out,stderr=err,creationflags=subprocess.CREATE_NO_WINDOW)
(WORK/'state/api_process.json').write_text(json.dumps({'pid':proc.pid,'port':8765,'entrypoint':str(WORK/'backend/rag_api.py'),'local_url':'http://127.0.0.1:8765'}),encoding='utf-8')
for _ in range(20):
    try:
        if requests.get('http://127.0.0.1:8765/health',timeout=2).json().get('service')=='marine-knowledge-api':break
    except requests.RequestException:pass
    time.sleep(.5)
else:raise RuntimeError('API restart did not become healthy; inspect retained logs.')
print(json.dumps({'restarted_verified_api_only':True,'previous_pids':[p.pid for p in owned],'health':'ok'}))
