# Phase 18.1 — 盲化人工 Claim-Citation Support Audit

本工具只覆核 Phase 18 已凍結的 48 outputs、122 primary claims、310 pairs。
它不是 Human Gold Benchmark 或 Expert Gold QA。AI audit 與人工資料分開保存。
使用者已指定本輪不進行 review；不得因此由 AI 代填，或將瀏覽紀錄算成覆核。

## 啟動與使用

獨立 Workbench：`tools/human_claim_citation_review_app.py`，預設 http://127.0.0.1:8779。
使用現有 `.venv` 啟動 Streamlit，不修改 production app。
報告更新使用 `.venv/Scripts/python.exe scripts/phase18_1_human_audit.py --report`。
這兩個工具都不呼叫 Generator、Retriever 或 Judge。

1. 第一位實際覆核者登記 reviewer ID、角色及 primary assignment。
2. 阅读問題、完整 frozen answer、claim 原文及位置，不修改任何文字。
3. 分別閱讀每一筆 cited chunk，選支持程度及 provenance validity。
4. 閱讀本題其他 provided context，判定是否能在其他地方找到支持，必要時明確選 context ID。
5. 判定整個 cited set 是否共同支持 claim；這是人工判定，不能由 pair label 自動預填。
6. 選 atomicity；compound、not_factual、ambiguous 仍留在主要分母，不另抽取／拆分。
7. 明確確認人工閱讀後提交；標籤修改會新增 revision，不覆寫舊紀錄。

所有選項初始空白，不能複製 AI label。第二位 reviewer 看不到第一位判定。
當一筆 cited chunk fully supported 時，其他 context 支持可明確選 not_applicable。
若選 supported_elsewhere／partially_supported_elsewhere，必須人工指定其他 context IDs。
Citation ID 不存在時仍保留該 frozen pair；不能假造 chunk 或有效 provenance。

## 支持與 attribution

| cited support | other context | attribution |
|---|---|---|
| fully_supported | 任意合法值 | correct_citation_support |
| partially_supported | 任意合法值 | partial_citation_support |
| not_supported | supported_elsewhere | citation_selection_failure |
| not_supported | not_supported_anywhere | unsupported_by_provided_context |
| cannot_determine | 任意合法值 | cannot_determine |
| not_supported | partial / unknown | cannot_determine |

`unsupported_by_provided_context` 只表示本題 Evidence 沒有提供支持，不能解讀為現實世界錯誤。
Semantic support 與 provenance validity 分開；有效頁碼不等於內容支持。
Answer-level citation association 並不自動證明 claim-level binding。

## 完成與分母

主要目標：122 claims 全部由第一位 reviewer 提交，包含 310 pairs。
另 2 outputs 沒有 frozen claim，需另保存人工閱讀 notes，才能記為完整 48 outputs。
進度按 unique frozen ID 計，不以 revision 次數增加完成數。
Human support rate 分母為已覆核原始 claims，明列 n；未覆核時為 null。
完整 review 的主要分母仍為 122，不因 atomicity flag 移除任何 claim。
Provenance 分別報 pair 分母及 unique answer/citation 分母。

完成 primary review 前不解除 model blinding供分模型報告；Workbench 永遠保持盲化。
每模型只有 12 outputs，且樣本含過度抽樣 retrieval miss，只作 descriptive。

## 第二位 reviewer

已預先固定 36 claims（每個模型 9 claims），平衡 style、category、species、hit/miss。
該 sample 固定於人工 review 前，不能從爭議案例另挑 agreement sample。
第二位 reviewer 必須是不同 ID，不能看到 primary labels。
真正有 paired submissions 後才報 raw agreement、Cohen kappa、完整 confusion matrix。
類別不平衡／單一類別時 kappa 可能無法解讀，percent agreement 必須並列。

## Append-only integrity

`review_transactions.jsonl` 是 authoritative hash-chained journal。
`human_claim_reviews.jsonl`、`human_citation_reviews.jsonl` 是 append-only projections。
每次 revision 保留 previous value、new value、reviewer ID/role、UTC timestamp。
Windows/POSIX file lock 序列化寫入；成功 journal commit 後若 projection 寫入中斷，只追加缺少的事件。
不完整 journal line、篡改過去事件或不一致 provenance 必須 fail explicitly，不默默丟棄。
支援 locally verifiable integrity；不是身分驗證系統或防止擁有檔案寫入權者蓄意偽造的安全邊界。

## 模型 shortlist

未有人工作業時維持 Phase 18 provisional status；不自動宣稱 strong candidate。
Qwen 若完整 primary audit 的 12 outputs 同時滿足事前門檻：full support ≥80%、
unsupported-by-context ≤5%、cannot-determine ≤10%，才可成 conditional candidate。
這不是 composite score，不能建立整體優越結論；仍缺獨立 Generation quality judge。
Gemma reference-alignment bias、Judge conflict、schema reliability、效能限制仍需保留。
