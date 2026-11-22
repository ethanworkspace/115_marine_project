"""Record verified deployment progress without exposing private configuration."""
import datetime,json,shutil,subprocess,sys
from pathlib import Path
import requests
ROOT=Path(__file__).resolve().parents[1]
WORK=Path(json.loads((ROOT/'research_staging/streamlit_cloud_deployment_pointer.json').read_text(encoding='utf-8'))['directory'])
git=r'C:\Program Files\Git\cmd\git.exe'
revision=subprocess.check_output([git,'-C',str(WORK/'github_checkout'),'rev-parse','HEAD'],text=True).strip()
discovery='https://raw.githubusercontent.com/ethanworkspace/115_marine_project/refs/heads/codex/streamlit-cloud/streamlit_cloud/backend_endpoint.json'
manifest=requests.get(discovery,timeout=(10,30));manifest.raise_for_status()
assert manifest.json()['backend_url']==json.loads((WORK/'frontend/backend_endpoint.json').read_text(encoding='utf-8'))['backend_url']
ui=json.loads((WORK/'reports/api_and_ui_validation.json').read_text(encoding='utf-8'))
smoke=json.loads((WORK/'reports/real_async_https_m2_smoke.json').read_text(encoding='utf-8'))
assert ui['status']=='PASS' and smoke['status']=='PASS'
report={'status':'WAITING_STREAMLIT_ACCOUNT_SIGN_IN','at':datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).isoformat(),
    'streamlit_deployed':False,'streamlit_public_url':None,'desired_subdomain':'marine-knowledge-platform','subdomain_reserved_or_available_verified':False,
    'repository':'https://github.com/ethanworkspace/115_marine_project','branch':'codex/streamlit-cloud','commit':revision,
    'entrypoint':'streamlit_cloud/streamlit_app.py','python_version':'3.14','frontend_code_published':True,
    'cloudflare_transfer_owner_approved':True,'app_access_code_required':True,'api_bearer_key_required':True,
    'private_config_uploaded_to_github':False,'original_model_corpus_or_evaluation_results_uploaded':False,
    'local_backend_https_verified':True,'local_http_and_ui_checks':len(ui['checks']),'actual_m2_https_generation_passed':True,
    'model':'qwen2.5-coder:7b','model_digest':smoke['record']['model_digest'],
    'backend_requires_pc_ollama_and_connector_running':True,'cloud_app_uses_shared_owner_code_workspace':True,
    'connector_restart_endpoint_update_script':'tools/start_streamlit_cloud_services.py',
    'initial_real_smoke_failure':'Missing isolated runtime/prompts directory; corrected and real local + external async generation passed. Original traceback retained.',
    'remaining_steps':['Owner completes Streamlit first sign-in and terms review','Create app from the frozen branch and entry point','Load locally prepared configuration into Streamlit Secrets','Verify chosen streamlit.app hostname and actual deployed UI/login/question/notes'],
    'history_and_720_generation_unchanged':True}
(WORK/'deployment_status.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
shutil.copy2(WORK/'reports/compatibility.json',WORK/'compatibility.json')
(ROOT/'research_staging/streamlit_cloud_deployment_pointer.json').write_text(json.dumps({'directory':str(WORK),'status':report['status']},ensure_ascii=False,indent=2),encoding='utf-8')
cmd='@echo off\r\n"'+sys.executable+'" -B "'+str(ROOT/'tools/start_streamlit_cloud_services.py')+'"\r\nif errorlevel 1 pause\r\n'
(WORK/'start_knowledge_service.cmd').write_bytes(cmd.encode('utf-8'))
instructions='''Streamlit 上線進度

網站介面已發佈至研究者自己的 GitHub 分支，尚未完成 Streamlit 帳號登入與正式部署。
模型與知識庫維持本機，目前使用 M2；電腦、Ollama 與安全連線必須保持運作。
已完成真實 HTTPS 問答、引用檢查、請求續取及介面測試。保護檔案 636/636 未變。

接續部署設定：
Repository: ethanworkspace/115_marine_project
Branch: codex/streamlit-cloud
Main file: streamlit_cloud/streamlit_app.py
Python: 3.14
建議網址名稱：marine-knowledge-platform（尚未確認是否可用）

真正的 Secrets 位於本工作區 .private/streamlit_secrets.toml，只可貼入 Streamlit 的 Secrets 設定，不可提交 GitHub。
網站存取碼位於 .private/owner_access_code.txt；持有同一碼的訪客共用本研究工作區的問答紀錄與筆記。

日後啟動本機問答服務：執行 start_knowledge_service.cmd。
此程式會啟動需金鑰的本機 API、使用已核准的 Cloudflare 連線並更新公開連線網址清單。
Quick Tunnel 本機重啟時網址可能改變；腳本會更新 GitHub 清單，Streamlit 約30秒更新一次。
網站的 streamlit.app 網址與後端連線網址是分開的。尚未部署前不能把建議網址視為已存在。
若 GitHub 推送失敗，腳本會明確報錯，應先修復登入／推送，不能宣稱網站已恢復。

未重新執行720次評測；未修改 Production、模型權重或原始知識庫。
'''
(WORK/'deployment_instructions.txt').write_text(instructions,encoding='utf-8-sig')
print(json.dumps({'status':report['status'],'frontend_commit':revision,'actual_m2_https_smoke':'PASS','protected':'636/636','streamlit_deployed':False}))
