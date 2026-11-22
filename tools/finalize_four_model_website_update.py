"""Finalize deployment receipts after observed live browser verification."""
import datetime, hashlib, json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
WORK=Path(json.loads((ROOT/'research_staging/streamlit_cloud_deployment_pointer.json').read_text(encoding='utf-8'))['directory'])
OUT=Path(json.loads((WORK/'four_model_update_pointer.json').read_text(encoding='utf-8-sig'))['directory'])
browser=json.loads((OUT/'live_browser_validation.json').read_text(encoding='utf-8'))
api=json.loads((OUT/'four_model_website_validation.json').read_text(encoding='utf-8'))
assert all(browser['checks'].values()) and all(api['checks'].values())
assert (OUT/'website_four_model_menu.jpg').stat().st_size>1000
compat=json.loads((OUT/'compatibility.json').read_text(encoding='utf-8'))
assert compat['unchanged']==636 and compat['baseline_matches']
registry=json.loads((WORK/'backend/model_registry.json').read_text(encoding='utf-8'))
status=json.loads((WORK/'deployment_status.json').read_text(encoding='utf-8'))
status.update(status='PASS_WITH_DOCUMENTED_LIMITATIONS',at=datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).isoformat(),
              commit='3ed6a4faf690c43ba51479b509040646a7db08be',
              website_model_ids=list(registry['models']),default_model_id='M2',
              four_model_update_report=str(OUT),four_model_real_api_calls_completed=True,
              four_model_live_dropdown_verified=True,mobile_app_built_this_update=False,
              last_website_change='Restored four verified local models, M2 default; bounded public answer claim guard.',
              validation_scope='Four actual model API calls; local UI/security/claim regressions; live website selection and real M4 question. Model quality limitations documented.')
(WORK/'deployment_status.json').write_text(json.dumps(status,ensure_ascii=False,indent=2),encoding='utf-8')
(WORK/'four_model_update_pointer.json').write_text(json.dumps({'directory':str(OUT),'status':'COMPLETE_WITH_DOCUMENTED_LIMITATIONS'},ensure_ascii=False,indent=2),encoding='utf-8')
text='''網站四模型切換完成（2026-11-22，Asia/Taipei）

網址：https://aquaculture-knowledge-platform.streamlit.app/
回答模型選單已移到主問答區，M1/M2/M3/M4 均可切換，預設 M2。
M3 核對為 DeepSeek-R1-Distill-Llama-8B GGUF，非 Qwen3 的 deepseek-r1:8b。
手機 App 本輪未建置。

已完成驗證
四款模型真實 HTTPS/API 呼叫完成，回傳 digest 與核實登錄一致。
真實線上選單已逐一切換四款模型，預設 M2；另有真實線上 M4 問答。
12 項本機 HTTP/UI 檢查、63 項安全回歸及 5 組輸出守門回歸通過。
這些測試不代表四模型的養殖答案均正確，也不是正式能力評測。

實際輸出限制
同一筆虱目魚養殖方式問題：M2/M4 回傳列舉養殖方式與可定位引用。
M1 引用驗證失敗，保留原始回答並顯示待核對。
M3 曾加入無充分支持的管理數值及用藥內容；新網站守門已攔截該輸出，包含歷史問答讀取。
原始 M3 輸出仍保留於測試證據；未將安全攔截算為模型答對。
目前網站沒有獨立核實的藥品/適應症/劑量/停藥協定，新增保守規則會攔下模型的用藥內容；此規則不是完整語意驗證器。
單張 RTX 4060 8GB 顯示卡依序處理問答；切換模型需等待載入，忙碌時需稍後再試。
網站仍須本機電腦、Ollama、API 與 Cloudflare 連線服務持續運作。

保護基線
Frozen Manifest 636/636 相符；正式 SQLite、現用 Corpus 與指標檔雜湊均未改變。
未重算所有模型權重 bytes；已核對四模型 Ollama/回應 digest。
未重跑 720 次，未改寫歷史研究結果。

程式與證據
後端：backend/rag_api.py、backend/model_registry.json、backend/website_answer_guard.py。
前端：frontend/streamlit_app.py；雲端只發佈前端與 README。
發佈 commit：3ed6a4faf690c43ba51479b509040646a7db08be。
four_model_real_api_smoke.json 保留安全修正前的實際發現，狀態仍為 NEEDS_REVIEW，未改寫為全面通過。
four_model_website_validation.json 記錄修正後 HTTPS/歷史輸出攔截。
live_browser_validation.json 記錄線上選單與問答驗證。
compatibility.json 保留 636 筆重新計算結果。
'''
(OUT/'website_update_report.txt').write_text(text,encoding='utf-8')
manifest={str(p.relative_to(OUT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in OUT.iterdir() if p.is_file() and p.name!='update_reproducibility_manifest.json'}
(OUT/'update_reproducibility_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'status':status['status'],'report':str(OUT/'website_update_report.txt'),'protected_unchanged':636},ensure_ascii=False))
