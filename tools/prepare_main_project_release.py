"""Build a scanned source-only main checkout; private research data stays local."""
import ast, collections, datetime, hashlib, json, os, re, shutil, subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'research_staging/maintenance/cleanup_publish_20261122'
DEST=OUT/'github_main_checkout'
WORK=Path(json.loads((ROOT/'research_staging/streamlit_cloud_deployment_pointer.json').read_text(encoding='utf-8'))['directory'])
DOC=ROOT/'docs/research_results'
SKIP={'.git','__pycache__','.pytest_cache','node_modules','site-packages','test_env','frontend_env','vendor','state','.private','github_checkout','github_main_checkout'}
CODE_EXT={'.py','.ps1','.mjs','.js','.css'}
CONTENT_EXT=CODE_EXT|{'.md','.txt','.json','.yaml','.yml','.toml','.html','.schema'}
GIT=r'C:\Program Files\Git\cmd\git.exe'

def read(path):return json.loads(path.read_text(encoding='utf-8-sig'))
def write(path,obj):path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf-8')
def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def walk(start,extensions):
    for base,dirs,files in os.walk(start,followlinks=False):
        dirs[:]=[d for d in dirs if d not in SKIP and not d.startswith('.venv') and not (Path(base)/d).is_symlink()]
        for name in files:
            path=Path(base)/name
            if not path.is_symlink() and path.suffix.lower() in extensions:yield path

def build_docs():
    DOC.mkdir(parents=True,exist_ok=True)
    metrics=read(ROOT/'reports/evaluation/unified_rag_v6_evaluation_20261121_164940/evaluation_metrics_11_source_qc.json')
    weighted=read(ROOT/'reports/evaluation/unified_rag_v6_weighted_selection_20261122_125959/weighted_model_selection.json')
    corpus=read(ROOT/'research_staging/unified_rag_v6_20261121_160441/corpus_manifest.json')
    cleanup=read(OUT/'cleanup_receipt.json')
    summary={k:metrics[k] for k in ('run_id','scope','human_gold_n','target_n','final_n','raw_attempt_n','questions','models','shared_context_precision','fixed_reference_policy','memory_scope','shared_gpu_memory')}
    summary['source_file']='reports/evaluation/unified_rag_v6_evaluation_20261121_164940/evaluation_metrics_11_source_qc.json'
    summary['source_sha256']=digest(ROOT/summary['source_file'])
    write(DOC/'evaluation_metrics_summary.json',summary)
    write(DOC/'weighted_selection_summary.json',{k:weighted[k] for k in ('created_at','source_run','policy','primary','sensitivity','same_top_model_in_declared_70_30_sensitivity','no_new_inference')})
    write(DOC/'corpus_status_summary.json',{'version':corpus['version'],'database_sha256':corpus['database_sha256'],'counts':corpus['counts'],
          'model_registry':read(WORK/'backend/model_registry.json'),'not_public_redistribution_of_originals':True})
    write(DOC/'maintenance_summary.json',{'date':'2026-11-22','deleted_files':cleanup['deleted_files'],'released_bytes':cleanup['released_bytes'],
          'deletion_reason_counts':dict(collections.Counter(r['reason'] for r in cleanup['deleted'])),
          'unreadable_cache_directories_preserved':len(cleanup['inaccessible_paths_left_unchanged']),
          'originals_results_models_and_environments_preserved':True,
          'protected_manifest_unchanged':636,'production_sqlite_sha256':'d7d06d4d2a57d0a57d05bcb6131ffb24aefb226c6bd36349dbc5118d33b11087',
          'local_receipt_sha256':digest(OUT/'cleanup_receipt.json')})
    for name,source in [('evaluation_report.md','reports/evaluation/unified_rag_v6_evaluation_20261121_164940/final_720_evaluation_report.md'),
                        ('model_recommendation.md','reports/evaluation/unified_rag_v6_model_recommendation_20261122_024407/model_recommendation_report.md'),
                        ('weighted_selection_report.md','reports/evaluation/unified_rag_v6_weighted_selection_20261122_125959/weighted_model_selection_report.md')]:
        shutil.copy2(ROOT/source,DOC/name)
    (DOC/'README.md').write_text('''# 可公開研究結果摘要\n\n本目錄由本機保存的 v6 JSON 與既有報告產生，不重新執行模型或改寫歷史分數。\n\n- `evaluation_metrics_summary.json`：11 項指標與各模型有效 N，採既有來源 QA 後結果。\n- `evaluation_report.md`：既有完整評測說明，包含原始與系統層差異及研究限制。\n- `model_recommendation.md`：固定分母結果、共同樣本與部署建議。\n- `weighted_selection_summary.json` / `weighted_selection_report.md`：使用者確認 70/30 的探索性選型；正規化假設另列，不能當作人工專家驗證。\n- `corpus_status_summary.json`：資料處理規模、模型登錄與 digest；不是所有內容均已通過專家審核。\n- `maintenance_summary.json`：本輪整理摘要；逐檔刪除收據保留本機。\n- `repository_validation.json`：本輪正式 tests/ 檢查結果，完成後更新。\n\n完整原始 JSONL、所有重試、參考答案、原始 Excel、來源全文與圖片留本機，不公開散布。Human Gold = 0；不可把少數來源群組衍生的題目當成互相獨立的專家真值。\n\n本輪網站修改是工程驗證，不代表重新測得四模型全部回答正確。\n''',encoding='utf-8')

def main():
    assert (DEST/'.git').is_dir()
    build_docs()
    chosen={ROOT/name for name in ('README.md','.gitignore','LICENSE','app.py','rag_core.py','build_index.py','chat.py','requirements.txt','start_rag.ps1')}
    for name in ('src','scripts','tools','tests','config','configs','prompts','schemas','docs'):
        chosen.update(walk(ROOT/name,CONTENT_EXT))
    chosen.update(walk(ROOT/'reports',CODE_EXT))
    chosen.update(walk(ROOT/'research_staging/app_sessions/launch_20261118_154253',CODE_EXT))
    chosen.update(p for p in (WORK/'backend').iterdir() if p.suffix=='.py' or p.name=='model_registry.json')
    # Preserve the exact verified frontend from the deployed branch.
    frontend=read(WORK/'reports/frontend_publish_allowlist.json')
    for item in frontend['files']:
        source=WORK/'frontend'/item['path'];assert digest(source)==item['sha256']
        local=ROOT/'streamlit_cloud'/item['path'];local.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(source,local);chosen.add(local)
    secrets=[str(v).encode() for v in read(WORK/'.private/credentials.json').values() if isinstance(v,str) and len(v)>6]
    patterns=[re.compile(rb'(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,}|AKIA[0-9A-Z]{16}|sk-[A-Za-z0-9_-]{30,})'),
              re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----\s+[A-Za-z0-9+/=]{30,}')]
    problems=[];records=[];syntax=[]
    for path in sorted(chosen):
        rel=path.relative_to(ROOT);data=path.read_bytes()
        if len(data)>10*1024*1024:problems.append({'path':str(rel),'reason':'LARGE_UNREVIEWED_FILE'});continue
        if any(s in data for s in secrets) or any(p.search(data) for p in patterns):
            problems.append({'path':str(rel),'reason':'POTENTIAL_SECRET'});continue
        if path.suffix=='.py':
            try:ast.parse(data.decode('utf-8-sig'),filename=str(rel))
            except (UnicodeError,SyntaxError) as exc:syntax.append({'path':str(rel),'error':str(exc)})
        if path.suffix=='.json':
            try:json.loads(data.decode('utf-8-sig'))
            except (UnicodeError,ValueError) as exc:problems.append({'path':str(rel),'reason':'INVALID_JSON'})
        records.append({'path':rel.as_posix(),'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()})
    write(OUT/'publication_preflight.json',{'files':len(records),'bytes':sum(r['bytes'] for r in records),'secret_findings':problems,'python_syntax_errors':syntax,
          'private_data_or_corpus_published':False,'allowlist':records})
    assert not problems, 'Review publication_preflight.json; no secret contents printed.'
    # Keep historical source snapshots verbatim; syntax issues are reported rather
    # than silently modifying old experiments. Current code must parse.
    current_errors=[r for r in syntax if not r['path'].replace('\\','/').startswith('reports/')]
    assert not current_errors,current_errors
    for record in records:
        target=DEST/record['path'];target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(ROOT/record['path'],target)
    names=[r['path'] for r in records]
    for offset in range(0,len(names),80):
        subprocess.run([GIT,'-C',str(DEST),'add','-f','--']+names[offset:offset+80],check=True,stdout=subprocess.DEVNULL)
    staged=subprocess.check_output([GIT,'-C',str(DEST),'diff','--cached','--name-only','-z']).decode().split('\0')
    assert set(filter(None,staged))<=set(names)
    write(OUT/'publication_manifest.json',{'status':'SCANNED_AND_STAGED','target_branch':'main','files':records,'syntax_diagnostics':syntax,
          'private_originals_results_models_and_credentials_preserved_locally':True})
    print(json.dumps({'staged_files':len(list(filter(None,staged))),'allowlist_files':len(records),'bytes':sum(r['bytes'] for r in records),
                      'secret_findings':len(problems),'historical_syntax_diagnostics':len(syntax)},ensure_ascii=False))

if __name__=='__main__':main()
