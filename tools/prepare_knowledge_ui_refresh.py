"""Back up only the active isolated UI and verify protected inputs."""
import datetime, hashlib, json, shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT/'research_staging/app_sessions/launch_20261118_154253'
now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8)))
OUT = ROOT/'reports/ui'/('knowledge_platform_'+now.strftime('%Y%m%d_%H%M%S'))
OUT.mkdir(parents=True)
(OUT/'before').mkdir()
def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()
backups = []
for name in ('professional_platform.py','platform.css','launch_info.json','run_app.py'):
    p = APP/name
    shutil.copy2(p,OUT/'before'/name)
    backups.append({'path':str(p),'sha256':sha(p),'backup':str(OUT/'before'/name)})
rows = json.loads((ROOT/'reports/evaluation/final_model_selection/phase20/protected_inputs_before.json').read_text(encoding='utf-8-sig'))['files']
changed = [r['path'] for r in rows if not (ROOT/r['path']).is_file() or sha(ROOT/r['path'])!=r['sha256']]
active = json.loads((ROOT/'research_staging/unified_rag_active.json').read_text(encoding='utf-8-sig'))
baseline = {'at':now.isoformat(),'count':len(rows),'unchanged':len(rows)-len(changed),'changed':changed,
    'production_sqlite_sha256':sha(ROOT/'rag_store.sqlite3'),'active_corpus_sha256':sha(active['database']),
    'active_pointer_sha256':sha(ROOT/'research_staging/unified_rag_active.json')}
assert len(rows)==636 and not changed, baseline
assert baseline['production_sqlite_sha256']=='d7d06d4d2a57d0a57d05bcb6131ffb24aefb226c6bd36349dbc5118d33b11087'
assert baseline['active_corpus_sha256']==active['database_sha256']
(OUT/'baseline_before.json').write_text(json.dumps(baseline,indent=2),encoding='utf-8')
(OUT/'change_plan.json').write_text(json.dumps({'app':str(APP),'backups':backups,'scope':'UI presentation and personal knowledge notes only; no retrieval, model, source or scoring changes.'},indent=2),encoding='utf-8')
(ROOT/'research_staging/knowledge_ui_refresh_pointer.json').write_text(json.dumps({'directory':str(OUT)},indent=2),encoding='utf-8')
generated = Path(r'C:\Users\ethan\.codex\generated_images\01a0fcc1-5850-7712-a91d-7cda1f1a24a2')
for name, file in {'chat':'exec-44533a52-acc2-4072-b75d-07aa3cd66ba4.png','knowledge':'exec-23a4a37e-774c-4854-8c9f-8b95c9f60feb.png','history':'exec-64ebacce-4aae-42ac-b6d8-add06f465cf5.png'}.items():
    shutil.copy2(generated/file,APP/'assets'/('watercolor_'+name+'.png'))
print(json.dumps({'directory':str(OUT),'protected':baseline['unchanged'],'icons_copied':3}))
