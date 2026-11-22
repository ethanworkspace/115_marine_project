# Pilot Gold Dataset 標註指引

本指引供人工建立、覆核及鎖定 Gold QA 使用。`questions.jsonl` 目前只含空白 annotation slots；candidate inventory 只提供來源定位資訊，不是問題、Gold answer 或 Gold evidence。不得以模型生成內容填寫 gold 欄位。

## 標註狀態

- `draft`：尚未完成人工標註，可留白。
- `annotated`：標註者已填問題、答案判定、category、difficulty；answerable 題需有答案與 evidence，等待覆核。
- `reviewed`：不同於 annotator 的覆核者已逐項確認問題、答案、required/acceptable evidence、species、category、difficulty，並留下 review notes。
- `blocked`：來源驗證、原文品質或 evidence 有未解問題。高風險題在來源未驗證前維持此狀態；不可填入未核實的法規效力、藥物、劑量或停藥期結論。
- `locked`：可納入正式評估的凍結題目。必須具備問題、Gold answer（若預期 abstention，應以明確 abstention target 標註）、documents、pages、chunks、supporting claims、完成來源檢查及 reviewer。

## Answerability 與 abstention

- `answerable=true`：Evaluation Corpus 內有足夠、直接支持答案的 evidence，且沒有未解的來源衝突或高風險驗證阻礙。
- `expected_abstention=true`：Corpus 缺少回答必要資訊、可靠來源、有效版本，或 evidence 衝突尚未能解決。記錄中應寫明缺少哪些支持；不能把「沒有找到」解讀成領域事實上的不存在。
- 對同一問題，兩欄應由標註者一致判斷；不要只因 candidate 題材相似而判定可回答。

## Evidence 標註

- `required_chunks`：至少必須命中才能支持必要答案內容的 retrieval chunks。
- `acceptable_chunks`：經人工確認可替代 required evidence 的 retrieval chunk，或明確標明可作 context expansion 的 parent chunk。若 parent 只是背景材料，不得列為充分答案 evidence。
- `gold_chunks`：本題全部直接支持答案的 chunks；應是 `required_chunks` 與經核准替代 evidence 的實際 evidence 集合。
- `supporting_claims`：將答案拆成可核對的短 claim，逐項列出直接支持該 claim 的 chunk IDs。主題相關或只提供背景的 chunk 不算支持。
- 所有 document/page/chunk references 必須存在於 `corpus_v1.jsonl`，並可沿 provenance 回到頁面與來源 checksum。
- 同一 document 的相鄰 chunk 若涵蓋相同段落，不可同時被當作兩份獨立來源。

## 題型

- `fact`、`water_quality`、`disease`、`climate`、`sop`：依直接 evidence 標註，保留原始限制條件、魚種及適用情境。
- `multi_document`：至少兩份不同 document/version 的 evidence 必須共同支持答案；寫明各文件分別補足的資訊。
- `insufficient_information`：標記目前 corpus 的具體資訊缺口，並記錄已檢查的文件範圍；不要宣稱全領域都沒有該答案。
- `conflicting_sources`：保存所有互相矛盾的 source/chunk、版本與日期。不能自行選一方當正解。
- `ambiguous`：列明問題中哪個條件不明，以及不同合理解讀所需的 evidence。

## Duplicate source 與未驗證來源

- Exact duplicate 使用 evaluation corpus 的 canonical chunk 做檢索標的；原 duplicate copy 保留 provenance，但不得重複計分。
- `duplicate_source` 不能視為獨立 corroboration。若 document versions 不同且內容差異，必須人工判斷是否是真正版本衝突，不能只依 checksum 或檔名判定。
- source 未驗證時維持 `source_verification_status=pending`。一般題可先作 experimental retrieval 題的 draft；不能因此聲稱答案已權威驗證。
- 高風險題須先驗證來源；未完成時 `annotation_status=blocked`，`gold_answer` 與 evidence 欄位留空。

## 法規、用藥、停藥期與安全界線

必須人工確認官方來源、文件版本、法規狀態及適用日期。法規答案需記錄有效日期/條次；藥物或停藥期須直接引用適用於目標魚種、用途及法域的官方 evidence。不得從一般養殖文章推斷合法性、藥物核准、劑量或停藥期。未確認法律效力時保持 `blocked`，不能將 `unknown` 升成 `current`。

## Calculation

Gold answer 必須保存輸入值、單位、公式、假設、換算步驟及四捨五入規則。公式或安全前提須有直接 corpus evidence；單純算術可由確定性計算器重算。標註者不得把缺漏的池體積、濃度、有效成分或換水比例自行補成假設值。

## 覆核與鎖定

Reviewer 逐條檢查 answer claims、source/date/legal status、頁碼與 chunk references。所有 supporting claims 都有直接 evidence、參照完整且無未解衝突，才可設為 `locked`。未鎖定題目不得用來報告最終 QA 成績。

## Development Workbench 實際步驟

1. 從 `data/gold/development/questions.jsonl` 開啟一個 draft work item。candidate 只用來定位來源，candidate chunk 不會自動加入任何 Gold 欄位。
2. 在 Workbench 查看文件標題、document ID、頁碼、來源 checksum、parser provenance、child text 及 parent context；用同頁、同 section、同 document 範圍瀏覽或搜尋相關 chunks。
3. 只根據直接閱讀的來源撰寫一個清楚、可由 evidence 判定的 `question`。核實物種才填 `species`；標題候選不能取代 evidence 核對。
4. 人工撰寫 `gold_answer`，逐項選 `required_chunks` 與可能的 `acceptable_chunks`，並記錄每個 answer claim 的 `supporting_claims`。保存時才建立對應 chunk 的 text snapshot、頁碼與 checksum。
5. 設定 answerability、expected abstention、人工確認的 category、difficulty、notes 與 annotator。answerable 題須有人工撰寫的答案，並選至少一個 required 或 acceptable evidence；確認 abstention 題可不引用答案 evidence，但須說明資訊缺口。先存成 `annotated`；需通過 Gold linter。
6. `annotation_queue` 只列 draft；`review_queue` 列 annotated；`completed_queue` 列 reviewed。利用 category、species、difficulty、document、status 篩選。Workbench dashboard 顯示標註進度與 Phase 9 readiness，readiness 不會啟動 benchmark。
7. 由不同於 annotator 的 reviewer 重讀問題與原文，分別確認題目與答案有 evidence 支持、required/acceptable chunks 合理、species 不超出 evidence、category 與 difficulty 合理，並寫 `review_notes`。逐項確認 `question_verified`、`evidence_verified` 後才可轉為 `reviewed`。Development 題不需要鎖定；Workbench 不提供 `locked` 操作。

### 問題範例（格式示意，非 corpus Gold 題）

- Good pattern：`在［已選來源］中，［明確條件］下列出的［單一屬性］是什麼？` 問題範圍需能被已選 chunk 直接回答。
- Bad pattern：`這種魚最近狀況不好，該怎麼處理？` 缺少魚種、症狀、環境與目的，可能跨疾病診斷、用藥與管理建議，超出單一 evidence 的支持範圍。
- Bad pattern：`某魚種的水質與疾病管理方式為何？` 同時涵蓋多個主題，也沒有界定來源、條件或答案範圍。

### Evidence 選擇與 metadata

- `required_chunks` 要直接支持不可缺少的答案內容；若刪除其中一個 chunk 就無法完整作答，才列為 required。
- `acceptable_chunks` 是人工確認可替代必要 evidence 的來源。Parent context 預設只能協助理解，只有被 reviewer 確認可直接支持答案時才列為 acceptable；不能因為 parent 與 child 有文字重複就自動選取。
- 避免問出比 evidence 更廣的結論。例如來源只描述單一魚種、單一成長階段或特定條件，題目不可擴大成所有魚種或所有情境。
- 如果 species 不明，將 `species` 留空並在 notes 說明查核結果；不要以鄰近文件或候選標題猜測。
- topic、section 或疾病 metadata 缺漏時，可閱讀原頁補充人工標註；不得回寫或假裝來源原本有該 metadata。記錄欄位來源與不確定性。
- OCR、表格或 parent context 無法直接確認時，停止標註並轉為 `blocked`，附上 page 與原因。
