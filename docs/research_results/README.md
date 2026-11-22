# 可公開研究結果摘要

本目錄由本機保存的 v6 JSON 與既有報告產生，不重新執行模型或改寫歷史分數。

- `evaluation_metrics_summary.json`：11 項指標與各模型有效 N，採既有來源 QA 後結果。
- `evaluation_report.md`：既有完整評測說明，包含原始與系統層差異及研究限制。
- `model_recommendation.md`：固定分母結果、共同樣本與部署建議。
- `weighted_selection_summary.json` / `weighted_selection_report.md`：使用者確認 70/30 的探索性選型；正規化假設另列，不能當作人工專家驗證。
- `corpus_status_summary.json`：資料處理規模、模型登錄與 digest；不是所有內容均已通過專家審核。
- `maintenance_summary.json`：本輪整理摘要；逐檔刪除收據保留本機。
- `repository_validation.json`：本輪正式 tests/ 檢查結果，完成後更新。

完整原始 JSONL、所有重試、參考答案、原始 Excel、來源全文與圖片留本機，不公開散布。Human Gold = 0；不可把少數來源群組衍生的題目當成互相獨立的專家真值。

本輪網站修改是工程驗證，不代表重新測得四模型全部回答正確。
