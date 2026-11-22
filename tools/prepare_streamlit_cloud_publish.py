"""Copy only scanned frontend files to the independent deployment checkout."""
import hashlib,json,shutil,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
WORK=Path(json.loads((ROOT/'research_staging/streamlit_cloud_deployment_pointer.json').read_text(encoding='utf-8'))['directory'])
checkout=WORK/'github_checkout'
assert (checkout/'.git').is_dir()
secret=json.loads((WORK/'.private/credentials.json').read_text(encoding='utf-8'))
manifest=json.loads((WORK/'reports/frontend_publish_allowlist.json').read_text(encoding='utf-8'))
dest=checkout/'streamlit_cloud';dest.mkdir(exist_ok=True)
names=[]
for record in manifest['files']:
    path=WORK/'frontend'/record['path'];data=path.read_bytes()
    assert hashlib.sha256(data).hexdigest()==record['sha256']
    assert all(s.encode() not in data for s in secret.values())
    target=dest/record['path'];target.parent.mkdir(parents=True,exist_ok=True)
    shutil.copy2(path,target);names.append('streamlit_cloud/'+record['path'])
git=r'C:\Program Files\Git\cmd\git.exe'
subprocess.run([git,'-C',str(checkout),'add','--']+names,check=True)
staged=subprocess.check_output([git,'-C',str(checkout),'diff','--cached','--name-only','-z']).decode().split('\0')
assert set(filter(None,staged))<=set(names)
for name in filter(None,staged):
    data=subprocess.check_output([git,'-C',str(checkout),'show',':'+name])
    assert all(s.encode() not in data for s in secret.values()),name
report={'allowlist_files':len(names),'staged_files':list(filter(None,staged)),'actual_secret_scan_passed':True,
        'corpus_model_or_private_config_uploaded':False}
(WORK/'reports/github_publish_preflight.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False))
