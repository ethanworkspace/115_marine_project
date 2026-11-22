"""Verify actual Git index blobs, not just the copied source files."""
import hashlib,json,re,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'research_staging/maintenance/cleanup_publish_20261122';DEST=OUT/'github_main_checkout'
WORK=Path(json.loads((ROOT/'research_staging/streamlit_cloud_deployment_pointer.json').read_text(encoding='utf-8'))['directory'])
GIT=r'C:\Program Files\Git\cmd\git.exe'
secrets=[v.encode() for v in json.loads((WORK/'.private/credentials.json').read_text(encoding='utf-8')).values() if isinstance(v,str) and len(v)>6]
pattern=re.compile(rb'(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,}|AKIA[0-9A-Z]{16}|sk-[A-Za-z0-9_-]{30,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----\s+[A-Za-z0-9+/=]{30,})')
records=[]
for entry in subprocess.check_output([GIT,'-C',str(DEST),'ls-files','-s','-z']).split(b'\0'):
    if not entry:continue
    head,name=entry.split(b'\t',1);mode,oid,stage=head.decode().split();path=name.decode()
    assert stage=='0' and mode!='120000'
    assert not any(part in {'.private','state','vendor','site-packages','my_data','fish test','rag_assets','data'} for part in Path(path).parts),path
    assert not path.endswith(('.sqlite3','.gguf','.safetensors','.pdf','.docx','.xlsx','.jsonl','.log')),path
    assert Path(path).name not in {'credentials.json','owner_access_code.txt','secrets.toml'},path
    records.append({'path':path,'oid':oid})
ids=list(dict.fromkeys(r['oid'] for r in records))
proc=subprocess.run([GIT,'-C',str(DEST),'cat-file','--batch'],input=('\n'.join(ids)+'\n').encode(),capture_output=True,check=True)
cursor=0;blobs={};issues=[]
for oid in ids:
    end=proc.stdout.index(b'\n',cursor);header=proc.stdout[cursor:end].decode().split();assert header[0]==oid and header[1]=='blob'
    size=int(header[2]);data=proc.stdout[end+1:end+1+size];cursor=end+size+2
    assert size<10*1024*1024
    if any(s in data for s in secrets) or pattern.search(data):issues.append({'oid':oid,'reason':'POTENTIAL_SECRET'})
    blobs[oid]={'bytes':size,'sha256':hashlib.sha256(data).hexdigest()}
assert not issues,'Potential secret found; details withheld.'
report={'status':'PASS','tracked_files':len(records),'unique_blobs_scanned':len(ids),'secret_findings':0,
        'private_raw_data_or_index_files':0,'maximum_blob_bytes':max(r['bytes'] for r in blobs.values()),
        'staged_files':[r|blobs[r['oid']] for r in records]}
(OUT/'git_index_security_validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({k:v for k,v in report.items() if k!='staged_files'}))
