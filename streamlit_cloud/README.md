# 水產養殖知識平台（Streamlit介面）

這個目錄僅包含雲端介面、原創圖示與背景。M2、RAG、來源原件與筆記儲存在私有本機服務。

Community Cloud入口：`streamlit_cloud/streamlit_app.py`。請在Secrets設定`RAG_BACKEND_DISCOVERY_URL`、`RAG_API_KEY`及`APP_ACCESS_CODE`，不要提交任何真正金鑰。部署使用Python 3.14。連線清單僅含公開後端網址，不能代替API金鑰；本機連線重啟時須更新該清單。

啟動命令：`streamlit run streamlit_app.py`。後端未設定或離線時會顯示連線狀態，不會生成示範答案。現階段為存取碼保護的單一研究工作區；持有同一存取碼的人共用雲端問答紀錄及小知識，並非多使用者隔離服務。
