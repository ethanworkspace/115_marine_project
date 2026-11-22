"""Correlate real browser observations with immutable local API records."""
import datetime,json,re,sqlite3,subprocess
from pathlib import Path
import requests
ROOT=Path(__file__).resolve().parents[1]
WORK=Path(json.loads((ROOT/'research_staging/streamlit_cloud_deployment_pointer.json').read_text(encoding='utf-8'))['directory'])
AUDIT=Path(json.loads((WORK/'cloud_acceptance_pointer.json').read_text(encoding='utf-8-sig'))['directory'])
timezone=datetime.timezone(datetime.timedelta(hours=8))
start=datetime.datetime.strptime(AUDIT.name.removeprefix('cloud_acceptance_'),'%Y%m%d_%H%M%S').replace(tzinfo=timezone)
secret=json.loads((WORK/'.private/credentials.json').read_text(encoding='utf-8'))
with sqlite3.connect((WORK/'state/cloud_requests.sqlite3').as_uri()+'?mode=ro',uri=True) as con:
    records=[json.loads(r[0]) for r in con.execute('SELECT response_json FROM requests ORDER BY rowid')]
records=[r for r in records if datetime.datetime.fromisoformat(r['at'])>=start]
positive=[r for r in records if r['question']=='虱目魚常見的養殖方式有哪些？'][-1]
negative=[r for r in records if 'RAG_API_KEY' in r['question'] and '.private/credentials.json' in r['question']][-1]
assert positive['api_completed'] and positive['result']['answer_origin']=='MODEL_GENERATED'
assert positive['model_digest']=='dae161e27b0e90dd1856c8bb3209201fd6736d8eb66298e75ed87571486f4364'
flags=positive['result']['validation_status']
assert flags['raw_json_valid'] and flags['raw_citation_valid'] and flags['raw_span_binding_valid']
assert len(flags['exact_quote_checks'])==2 and all(r['quote_verified'] for r in flags['exact_quote_checks'])
assert negative['result']['answer_status']=='INSUFFICIENT_EVIDENCE'
for record in (positive,negative):
    assert all(value not in json.dumps(record,ensure_ascii=False) for value in secret.values())
before=json.loads((AUDIT/'notes_before.json').read_text(encoding='utf-8'))
with sqlite3.connect((WORK/'state/knowledge_notes.sqlite3').as_uri()+'?mode=ro',uri=True) as con:
    con.row_factory=sqlite3.Row;after=[dict(r) for r in con.execute('SELECT * FROM knowledge_notes')]
assert len(before)==len(after)==1
for old,new in zip(before,after):
    assert {k:v for k,v in old.items() if k!='updated_at'}=={k:v for k,v in new.items() if k!='updated_at'}
    assert new['updated_at']>old['updated_at']
(AUDIT/'notes_after.json').write_text(json.dumps(after,ensure_ascii=False,indent=2),encoding='utf-8')
log=(AUDIT/'cloud_reboot_log_snapshot.txt').read_text(encoding='utf-8')
new_log=log.rsplit('Starting up repository:',1)[-1]
versions={re.sub('[-_.]+','-',name).lower():version for name,version in re.findall(r'\+ ([A-Za-z0-9_.-]+)==([A-Za-z0-9.+!-]+)',new_log)}
for package,version in {'streamlit':'1.67.0','pillow':'13.0.0','requests':'2.34.2','pyarrow':'24.0.0'}.items():assert versions[package]==version
checks={
    'new_url_and_english_name_visible':True,'deployed_favicon_visually_matches_blue_chibi_fish':True,
    'cloud_streamlit_1_67_and_pillow_13_observed_in_logs':True,'wrong_access_code_rejected':True,
    'correct_access_code_opens_private_question_ui':True,'actual_m2_grounded_answer_displayed':True,
    'raw_model_json_and_citation_checks_valid':True,'two_source_quotes_expand_in_ui':True,
    'sensitive_request_did_not_disclose_actual_credentials':True,'existing_knowledge_card_read_and_saved':True,
    'knowledge_content_and_provenance_preserved':True,'question_history_reopens_same_grounded_result':True}
compat=json.loads((WORK/'reports/compatibility.json').read_text(encoding='utf-8'))
assert compat['unchanged']==636 and compat['baseline_matches']
observed_scan={'scope':'Packages observable in the latest cloud dependency install log; not a complete host inventory.','observed_package_versions':versions}
try:
    queries=[{'package':{'name':name,'ecosystem':'PyPI'},'version':version} for name,version in sorted(versions.items())]
    response=requests.post('https://api.osv.dev/v1/querybatch',json={'queries':queries},timeout=(10,30))
    response.raise_for_status();data=response.json();assert len(data['results'])==len(queries)
    observed_scan.update(status='COMPLETED',queries=queries,results=data['results'],
                         advisory_entries=sum(len(r.get('vulns',[])) for r in data['results']))
except (requests.RequestException,ValueError,KeyError,AssertionError) as exc:
    observed_scan.update(status='NOT_COMPLETED',reason=type(exc).__name__)
(AUDIT/'cloud_observed_dependency_scan.json').write_text(json.dumps(observed_scan,ensure_ascii=False,indent=2),encoding='utf-8')
commit=subprocess.check_output([r'C:\Program Files\Git\cmd\git.exe','-C',str(WORK/'github_checkout'),'rev-parse','FETCH_HEAD'],text=True).strip()
at=datetime.datetime.now(timezone).isoformat()
report={'status':'PASS_WITH_DOCUMENTED_LIMITATIONS','at':at,'public_url':'https://aquaculture-knowledge-platform.streamlit.app/',
        'checks':checks,'passed_checks':len(checks),'published_remote_commit':commit,
        'cloud_commit_hash_directly_observed':False,'release_match_evidence':['new English title','new fish favicon','new pinned package versions'],
        'initial_finding':'Cloud still served the old release after page refresh; a normal Streamlit Reboot app pulled and installed the current release.',
        'normal_cloud_reboot_performed':True,'initial_favicon_download_tool_timeout':True,'favicon_verified_by_normal_browser_image_preview':True,
        'favicon_url':'https://aquaculture-knowledge-platform.streamlit.app/~/+/media/57434086a7dd9c0f521ac98c5bc6299b.png',
        'favicon_dimensions_observed':[1254,1254],'deployed_favicon_byte_sha256_verified':False,
        'positive_record':positive,'negative_record':negative,'knowledge_note_count':len(after),
        'observed_cloud_dependency_versions':versions,'observed_dependency_scan_status':observed_scan['status'],
        'observed_dependency_advisory_entries':observed_scan.get('advisory_entries'),
        'protected_files':'636/636','production_sqlite_sha256':compat['production_sqlite_sha256'],
        'limitations':['A bounded functional and security smoke test, not a penetration-test certification.','The negative request produced an evidence-gap guidance message, not a specialized private-data refusal message.','One shared-code workspace; no per-user isolation.','Local PC, Ollama and connector must remain running; Quick Tunnel has no uptime guarantee.','No expert validation of aquaculture answer accuracy or Human Gold was added.']}
(AUDIT/'cloud_acceptance_results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
text=f'''Aquaculture Knowledge Platform：線上驗收補充報告

網址：{report['public_url']}
日期：{at}
結果：指定線上功能驗收通過；保留研究工作區及安全限制。

本輪實際觀察與處理：
- 重新整理後發現雲端仍顯示舊名稱；透過Streamlit正常Reboot app載入目前GitHub版本。
- 網頁標題已是Aquaculture Knowledge Platform；直接預覽實際favicon為淡藍Q版魚，1254×1254。未宣稱已取得部署圖示的SHA-256。
- 雲端安裝日誌確認Streamlit1.67.0、Pillow13.0.0、Requests2.34.2、PyArrow24.0.0。
- 錯誤存取碼會拒絕；正確存取碼可進入問答頁。
- 一筆本輪真實M2有據問答已顯示；原始JSON與引用驗證有效，兩段引文可展開回查。
- 私密資訊索取案例未外洩實際API金鑰或存取碼；目前回覆為證據缺口說明。
- 小知識可讀取及重新儲存；數量仍為1張，內容及來源追溯資料不變，只更新儲存時間。
- 問答紀錄可重新選取本輪有據回答。
- 636/636保護檔案及正式SQLite雜湊不變。

可觀察的雲端套件：{len(versions)}份；OSV掃描狀態：{observed_scan['status']}；弱點條目數：{observed_scan.get('advisory_entries','N/A')}。
這只涵蓋安裝日誌可觀察的套件，不代表已完成整個雲端主機與ML環境的安全稽核。

限制：共用存取碼、非逐人帳號；非專業滲透測試認證；電腦與本機服務需保持運作；未新增Human Gold或專業答案正確率。
保留前輪安全報告，不將當時未驗證狀態改寫為歷史上已通過。
'''
(AUDIT/'cloud_acceptance_report.txt').write_text(text,encoding='utf-8-sig')
(AUDIT/'compatibility.json').write_text(json.dumps(compat,ensure_ascii=False,indent=2),encoding='utf-8')
status_file=WORK/'deployment_status.json';status=json.loads(status_file.read_text(encoding='utf-8'))
status.update(status=report['status'],at=at,streamlit_public_url=report['public_url'],
              deployed_favicon_and_new_streamlit_runtime_verified=True,new_url_content_verified=True,
              new_url_live_generator_test_completed=True,
              actual_cloud_ui_question_and_note_save_passed=True,last_cloud_acceptance=str(AUDIT),
              browser_access_restored=True,remaining_steps=[],validation_scope='Renamed URL and security release passed 12 bounded live UI checks; limitations remain documented in the cloud acceptance report.')
status_file.write_text(json.dumps(status,ensure_ascii=False,indent=2),encoding='utf-8')
(WORK/'cloud_acceptance_pointer.json').write_text(json.dumps({'directory':str(AUDIT),'status':report['status']},ensure_ascii=False,indent=2),encoding='utf-8')
(ROOT/'research_staging/streamlit_cloud_deployment_pointer.json').write_text(json.dumps({'directory':str(WORK),'status':report['status'],'public_url':report['public_url']},ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'status':report['status'],'online_checks':len(checks),'cloud_package_count':len(versions),'osv_status':observed_scan['status'],'observed_advisory_entries':observed_scan.get('advisory_entries'),'protected':'636/636'},ensure_ascii=False))
