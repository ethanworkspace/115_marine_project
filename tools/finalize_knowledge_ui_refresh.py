"""Record UI verification and recheck immutable research inputs."""
import datetime, hashlib, json
from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT/'research_staging/app_sessions/launch_20261118_154253'
OUT = Path(json.loads((ROOT/'research_staging/knowledge_ui_refresh_pointer.json').read_text(encoding='utf-8'))['directory'])
def read(p): return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def sha(p):
    with Path(p).open('rb') as stream: return hashlib.file_digest(stream,'sha256').hexdigest()
def dump(p,value): Path(p).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')

checks = read(OUT/'streamlit_functional_validation.json')
assert checks['status']=='PASS'
rows = read(ROOT/'reports/evaluation/final_model_selection/phase20/protected_inputs_before.json')['files']
changed = [r['path'] for r in rows if not (ROOT/r['path']).is_file() or sha(ROOT/r['path'])!=r['sha256']]
active = read(ROOT/'research_staging/unified_rag_active.json')
before = read(OUT/'baseline_before.json')
compatibility = {'checked_at':datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).isoformat(),
    'protected_count':len(rows),'protected_unchanged':len(rows)-len(changed),'changed_protected_files':changed,
    'production_sqlite_sha256':sha(ROOT/'rag_store.sqlite3'),'active_corpus_sha256':sha(active['database']),
    'active_pointer_sha256':sha(ROOT/'research_staging/unified_rag_active.json'),
    'production_modified':False,'production_switched':False,'new_720_run':False,
    'scope':'Presentation of the existing isolated localhost app and separate personal notes only.'}
assert len(rows)==636 and not changed
for key in ('production_sqlite_sha256','active_corpus_sha256','active_pointer_sha256'):
    assert compatibility[key]==before[key], key
weighted = ROOT/'reports/evaluation/unified_rag_v6_weighted_selection_20261122_125959'
for row in read(weighted/'result_record.json')['artifacts']:
    assert sha(row['path'])==row['sha256'], row['path']
compatibility['recorded_weighted_selection_artifacts_unchanged']=True
dump(OUT/'compatibility.json',compatibility)

icons = []
for name in ('chat','knowledge','history'):
    path = APP/'assets'/('watercolor_'+name+'.png')
    with Image.open(path) as img:
        assert img.mode=='RGBA'
        alpha = img.getchannel('A').getextrema()
        assert alpha[0]==0 and alpha[1]>0
        icons.append({'path':str(path),'sha256':sha(path),'width':img.width,'height':img.height,'mode':img.mode,'transparent_alpha_verified':True})
raw = [json.loads(line) for line in (APP/'generator_attempts.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
smoke = [r for r in raw if r.get('question')=='虱目魚常見的養殖方式有哪些？' and r.get('at','')>before['at']]
if smoke:
    record = smoke[-1]
    dump(OUT/'live_question_smoke.json',record)
    smoke_summary = {k:record.get(k) for k in ('attempt_id','question_id','model_id','model_digest','api_completed','api_error','context_count','context_digest','prompt_version')}
    smoke_summary.update(answer_status=record['result']['answer_status'],answer_origin=record['result']['answer_origin'],
        raw_json_valid=record['result']['validation_status'].get('raw_json_valid'),
        citation_count=len(record['result'].get('supporting_chunk_ids',[])))
else:
    smoke_summary = {'status':'NOT_COMPLETED_OR_NOT_RECORDED'}
changes = ['knowledge_platform.py','platform_watercolor.css','knowledge_notes.py','run_app.py','restart_app.ps1','launch_info.json']
files = [{'path':str(APP/name),'sha256':sha(APP/name)} for name in changes]
report = {'status':'UI_FUNCTIONAL_VALIDATION_PASSED','site':'http://127.0.0.1:8501/',
    'navigation':['知識問答','小知識','本次紀錄'],
    'retired_navigation':['來源資料','資料管理','法規核對'],
    'design':'Pale blue watercolor raster icons, generous whitespace, native Streamlit components, restrained rounded cards.',
    'features':['自由問答','原180題問答','小知識新增與編輯','小知識搜尋與魚種／主題分類','回答收藏為小知識','本機持久保存與JSON匯出','回答引用收於展開區'],
    'knowledge_notes_database':str(APP/'user_data/knowledge_notes.sqlite3'),
    'personal_notes_automatically_indexed_in_rag':False,
    'page_startup_does_not_initialize_retriever_or_generator':True,
    'existing_answer_safety_policy_unchanged':True,
    'ui_checks':checks,'live_question_smoke':smoke_summary,'generated_icons':icons,'application_files':files,
    'compatibility':compatibility,'backup_directory':str(OUT/'before')}
dump(OUT/'ui_refresh_report.json',report)
dump(OUT/'ui_refresh_artifacts.json',{'files':[{'path':str(p),'sha256':sha(p)} for p in sorted(OUT.iterdir()) if p.is_file() and p.name!='ui_refresh_artifacts.json']})
print(json.dumps({'protected':compatibility['protected_unchanged'],'ui_checks':len(checks['checks']),'live_smoke':smoke_summary,'report':str(OUT/'ui_refresh_report.json')},ensure_ascii=False))
