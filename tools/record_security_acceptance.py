"""Consolidate auditable security receipts, retaining cloud-browser limitations."""
import datetime,hashlib,json,subprocess
from pathlib import Path
from PIL import Image
ROOT=Path(__file__).resolve().parents[1]
WORK=Path(json.loads((ROOT/'research_staging/streamlit_cloud_deployment_pointer.json').read_text(encoding='utf-8'))['directory'])
AUDIT=Path(json.loads((WORK/'security_audit_pointer.json').read_text(encoding='utf-8-sig'))['directory'])
security=json.loads((AUDIT/'security_acceptance_results.json').read_text(encoding='utf-8'))
functional=json.loads((WORK/'reports/api_and_ui_validation.json').read_text(encoding='utf-8'))
live=json.loads((AUDIT/'live_api_safety_smoke.json').read_text(encoding='utf-8'))
deps_before=json.loads((AUDIT/'dependency_audit.json').read_text(encoding='utf-8'))
deps_after=json.loads((AUDIT/'dependency_audit_final.json').read_text(encoding='utf-8'))
compat=json.loads((WORK/'reports/compatibility.json').read_text(encoding='utf-8'))
assert security['status']==functional['status']==live['status']=='PASS'
vulnerabilities=[v for package in deps_before['dependencies'] for v in package.get('vulns',[])]
groups=[]
for vulnerability in vulnerabilities:
    identities={vulnerability['id'],*vulnerability.get('aliases',[])}
    matched=[g for g in groups if g & identities]
    for group in matched:identities|=group;groups.remove(group)
    groups.append(identities)
after_findings=sum(len(p.get('vulns',[])) for p in deps_after['dependencies'])
assert after_findings==0
assert compat['unchanged']==636 and compat['baseline_matches']
icon=WORK/'frontend/assets/aquaculture_fish_favicon_v1.png'
im=Image.open(icon)
git=r'C:\Program Files\Git\cmd\git.exe'
commit=subprocess.check_output([git,'-C',str(WORK/'github_checkout'),'rev-parse','HEAD'],text=True).strip()
report={'at':datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).isoformat(),
    'status':'CONDITIONAL_PASS_PENDING_DEPLOYED_STREAMLIT_BROWSER_ACCEPTANCE',
    'public_url':'https://aquaculture-knowledge-platform.streamlit.app/','frontend_commit':commit,
    'favicon':{'path':str(icon),'sha256':hashlib.sha256(icon.read_bytes()).hexdigest(),'width':im.width,'height':im.height,'transparent':im.mode=='RGBA' and im.getchannel('A').getextrema()==(0,255),'generation_method':'built-in image generation; copied unchanged into project'},
    'local_security_checks_passed':security['passed'],'functional_api_and_ui_checks_passed':len(functional['checks']),
    'authenticated_https_security_checks_passed':sum(live['checks'].values()),
    'live_api_cases':[{'case':r['case'],'answer_status':r['record']['result']['answer_status'],'answer_origin':r['record']['result']['answer_origin'],'api_completed':r['record'].get('api_completed'),'actual_credential_leak':r['actual_credential_leak']} for r in live['cases']],
    'git_history_blobs_scanned':security['git_history_blobs_scanned'],'actual_secret_or_private_key_pattern_findings':len(security['secret_findings']),
    'dependency_scan':{'scanner':'pip-audit / OSV','original_advisory_entries':len(vulnerabilities),'original_deduplicated_advisories':len(groups),'original_affected_packages':[{'name':p['name'],'version':p['version']} for p in deps_before['dependencies'] if p.get('vulns')],
        'final_dependencies_scanned':len(deps_after['dependencies']),'final_known_findings':after_findings,
        'updated_frontend_versions':{p['name']:p['version'] for p in deps_after['dependencies'] if p['name'] in ('streamlit','pillow','requests','pyarrow')},
        'scope':'Resolved frontend package versions, plus isolated backend Pillow override. Not a full audit of the legacy ML runtime, Windows, GPU driver or deployed cloud lock.'},
    'fixes':['Generated transparent pale-blue chibi fish favicon','Session login attempt throttling','HMAC-signed backend endpoint manifest','Strict backend URL validation','Limit media to images already published in cited answers','Reject external Prompt/Context and unsupported model fields','JSON-only bounded requests, connection timeout and maximum 16 worker connections','Origin blocking and JSON response security headers','Escaped notes and suppressed automatically loaded external answer images','Pillow 13 isolated patch and Streamlit upgrade compatible with Pillow 13'],
    'browser_verification':'BLOCKED_BY_PREVIOUS_AUTOMATIC_APPROVAL_REVIEW_CREDIT_LIMIT; no workaround attempted',
    'deployed_favicon_and_new_streamlit_runtime_verified':False,'production_and_active_corpus_unchanged':True,'protected_files_unchanged':'636/636',
    'remaining_limitations':security['limitations']+['Actual Streamlit cloud restart, rendering and favicon require owner confirmation or restored browser approval.','Cloud dependency versions after deployment have not been independently observed.','Questions, notes and source excerpts are relayed through Streamlit/Cloudflare under existing owner consent.'],
    'primary_references':['https://github.com/advisories/GHSA-27h8-gf7j-v5hc','https://pillow.readthedocs.io/en/stable/releasenotes/13.0.0.html','https://pypi.org/pypi/streamlit/1.67.0/json']}
(AUDIT/'security_acceptance_summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
prompt='單一淡藍與淺青色Q版魚、簡單清楚輪廓、深藍眼睛、淡雅水彩紋理、置中、透明背景、無文字；適用16px及32px網站圖示。'
(AUDIT/'favicon_generation_provenance.json').write_text(json.dumps({'method':'built-in imagegen','prompt_summary_zh':prompt,'asset':report['favicon'],'source_generated_file':r'C:\Users\ethan\.codex\generated_images\01a0fcc1-5850-7712-a91d-7cda1f1a24a2\exec-0950bf6c-5c61-41c6-889a-7074c4eeecf2.png'},ensure_ascii=False,indent=2),encoding='utf-8')
text=f'''養殖漁業知識平台：圖示修改與安全驗收

判定：有條件通過；雲端 Streamlit 畫面與 favicon 尚待人工驗收。
網址：{report['public_url']}
部署程式版本：{commit}

完成：
1. 已生成並接入透明背景淡藍色Q版魚圖示；原始生成圖片未以程式改繪。
2. 本機安全測試 {security['passed']} 項通過；實際HTTP與Streamlit AppTest功能檢查 {len(functional['checks'])} 項通過。
3. 既有HTTPS後端安全檢查 {sum(live['checks'].values())} 項通過；有據M2問答與索取私密資料的負向案例均保存真實結果。
4. Git歷史 {security['git_history_blobs_scanned']} 個Blob未發現實際API金鑰、存取碼或所檢查的私鑰／Token格式。
5. 原Pillow12.3.0掃描有{len(vulnerabilities)}筆弱點條目，依識別碼與別名合併為{len(groups)}組；已在隔離環境升級Pillow13.0.0及相容的Streamlit1.67.0。
6. 最終前端相依套件{len(deps_after['dependencies'])}份，OSV掃描未回報已知弱點；這不代表沒有未知漏洞，也不代表已完成部署主機或完整ML環境稽核。
7. 補上登入嘗試節流、網址清單HMAC簽章、後端網址驗證、引用圖片授權、跨來源阻擋、請求格式與資源限制、輸出防護。
8. 正式SQLite、目前Corpus與636/636 Frozen檔案均維持原SHA-256；未重跑720次評測。

重要限制：
- 存取碼為單一共用研究工作區；不是逐人帳號與多租戶隔離。
- 登入節流是單一瀏覽器Session層級，可藉新Session繞過；後端另有限制錯誤金鑰嘗試。
- 電腦、Ollama與Cloudflare連線需要保持運作，Quick Tunnel沒有服務穩定性承諾。
- 既有瀏覽器自動核准審查額度限制尚未解除，本輪未訪問受阻網站，也未用其他HTTP／瀏覽器方式繞過驗收限制。
- 請研究者確認新魚圖示、登入、問答、小知識及雲端依賴安裝均正常。無法據此宣稱整個公開系統已完成專業滲透測試或全面安全認證。

權威依據：
https://github.com/advisories/GHSA-27h8-gf7j-v5hc
https://pillow.readthedocs.io/en/stable/releasenotes/13.0.0.html
https://pypi.org/pypi/streamlit/1.67.0/json
'''
(AUDIT/'security_acceptance_report.txt').write_text(text,encoding='utf-8-sig')
status_file=WORK/'deployment_status.json';status=json.loads(status_file.read_text(encoding='utf-8'))
status.update(status=report['status'],commit=commit,last_security_audit=str(AUDIT),favicon_asset=str(icon),
              deployed_favicon_and_new_streamlit_runtime_verified=False,remaining_steps=['Owner verifies the deployed favicon and application after the dependency update; browser approval remains blocked.'])
status_file.write_text(json.dumps(status,ensure_ascii=False,indent=2),encoding='utf-8')
(ROOT/'research_staging/streamlit_cloud_deployment_pointer.json').write_text(json.dumps({'directory':str(WORK),'status':report['status'],'public_url':report['public_url']},ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({k:report[k] for k in ('status','local_security_checks_passed','functional_api_and_ui_checks_passed','authenticated_https_security_checks_passed','protected_files_unchanged')},ensure_ascii=False))
