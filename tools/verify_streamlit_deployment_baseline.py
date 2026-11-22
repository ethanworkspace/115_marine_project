"""Recompute protected file digests without opening any database for writing."""
import hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
WORK=Path(json.loads((ROOT/'research_staging/streamlit_cloud_deployment_pointer.json').read_text(encoding='utf-8'))['directory'])
baseline=json.loads((WORK/'reports/baseline_before.json').read_text(encoding='utf-8'))
manifest=json.loads((ROOT/'reports/evaluation/final_model_selection/phase20/protected_inputs_before.json').read_text(encoding='utf-8'))
def sha(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()
checks=[]
for entry in manifest['files']:
    path=ROOT/entry['path']
    actual=sha(path) if path.is_file() else None
    checks.append({'path':entry['path'],'sha256':actual,'unchanged':actual==entry['sha256']})
active=json.loads((ROOT/'research_staging/unified_rag_active.json').read_text(encoding='utf-8-sig'))
current={'production_sqlite_sha256':sha(ROOT/'rag_store.sqlite3'),'active_corpus_sha256':sha(Path(active['database'])),
         'active_pointer_sha256':sha(ROOT/'research_staging/unified_rag_active.json')}
assert len(checks)==636 and all(r['unchanged'] for r in checks)
assert baseline==current
report={'protected_files_total':len(checks),'unchanged':sum(r['unchanged'] for r in checks),'baseline_matches':True,
        **current,'protected_file_checks':checks,'model_weight_bytes_rehashed_this_task':False,
        'model_identity_verification':'M2 actual Ollama digest checked in real smoke test; historical model weights not rewritten',
        'cloud_frontend_only_published':True,'original_production_not_modified':True}
(WORK/'reports/compatibility.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({k:v for k,v in report.items() if k!='protected_file_checks'},ensure_ascii=False))
