# Retrieval 指標定義

本文件定義未來 retrieval baseline 的量測方式；Phase 8 只建立 corpus 與標註框架，尚未執行任何 retrieval benchmark，也不代表 retrieval 品質已改善。

## Evidence relevance

每題可有 `required_chunks` 與 `acceptable_chunks`。若 required 集合非空，完整召回判定需要召回全部 required evidence；acceptable evidence 可替代相應 required evidence 的條件必須在標註資料中明確表達，不能由 evaluator 自行推測。對只需一份充分 evidence 的題目，可用一個 acceptable group 表示替代答案證據。Context-only parent 不計入 retrieval hit，除非題目明確將其列為可接受的 evidence expansion 結果；即使如此，應分開報告。

## 指標

- `Recall@K_chunk`：Top-K 中命中的 required chunks 數除 required chunks 數；另報 `all_required_recall@K`，表示是否召回全部必要 chunks。替代 evidence 依人工定義的 acceptable group 計入，不以相似度自動替代。
- `Recall@K_page`：Top-K evidence 涵蓋的 required document/page pairs 除以標註的 required page pairs。頁碼使用來源頁碼，跨頁 evidence 以 distinct page pair 計數。
- `Recall@K_document`：Top-K 中命中的 required documents 數除 required documents 數；同文件多個 chunks 不重複計數。
- `Precision@K`：Top-K 中屬於人工 acceptable evidence 的唯一 chunks 數除實際回傳的唯一 chunks 數。排除 context-only 和 excluded records；另列 parent expansion 指標。
- `MRR`：第一個 acceptable evidence 的 reciprocal rank，未命中為 0。Multi-document 題另外報告首個完整 evidence set 的 rank。
- `nDCG@K`：依人工 relevance grade（例如 0/1/2）計算 DCG/IDCG；標註時需先定義各 evidence 的等級。沒有 relevance grade 的題不計 nDCG。

## 報告切分

以題目/資料集 split 報 macro average 與 per-category、per-species 結果，並列出可評估題數和因 `blocked`、`draft` 或缺 reference 而排除的題數。不得混用尚未 reviewed/locked 的 Gold records。來源/版本切分政策見 `evaluation_split_policy.md`。
