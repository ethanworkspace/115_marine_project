# Hybrid-RAG Aquaculture Knowledge Platform｜養殖漁業知識平台

臺灣水產養殖 Hybrid-RAG 知識問答與四模型評測專案，涵蓋虱目魚、吳郭魚、石斑魚、鱸魚、烏魚及鰻魚。

網站：[養殖漁業知識平台](https://aquaculture-knowledge-platform.streamlit.app/)（需工作區存取碼）。更新日期：2026-11-22。

GitHub 專案：[hybrid-rag-aquaculture-knowledge-platform](https://github.com/ethanworkspace/hybrid-rag-aquaculture-knowledge-platform)。

## 現行系統

- 自由問答、180 題問題瀏覽、小知識卡片與問答紀錄。
- M1–M4 四模型切換，預設 **M2**，逐次核對模型 digest。
- BM25 / SQLite FTS5、BGE-M3 Dense、RRF k=60、BGE Reranker v2-m3。
- 來源、魚種、證據、JSON 與引用檢查；缺少證據時明確說明資訊缺口。
- 區分模型生成、確定性摘取、拒答及驗證失敗，不把系統回補算成模型直接作答成功。

```text
本機原始文件 / 官方資料快照
 → Parser / OCR / 表格處理 / 語義切分 / 來源定位
 → 隔離 SQLite / FTS5 / BGE-M3 向量與圖像索引
 → Hybrid Retrieval / RRF / Reranker / 來源與魚種檢查
 → 本機 Ollama / 回答引擎 / JSON 與引用驗證
 → Streamlit 雲端介面
```

現用隔離知識庫是 `marine-unified-v6-20261121_160441`。根目錄 `app.py`、`rag_core.py` 與 `rag_store.sqlite3` 為保留的舊版入口及正式基線，不代表目前網站使用的版本。

模型、來源原件、資料庫、筆記與問答服務保留本機；雲端前端經已授權的 Cloudflare HTTPS 連線轉送問答與圖片請求。**不是所有流量皆只在本機的架構。**Ollama 管理介面與資料庫不直接公開。

電腦、Ollama、API 及連線服務需持續運作；RTX 4060 8GB 依序處理問答，首次載入及切換模型可能較慢。Quick Tunnel 不保證持續可用。目前為共用存取碼的單一工作區，共用問答紀錄及小知識，沒有多使用者資料隔離。

## 四模型

| ID | 模型 | 已核對標籤 | 量化 |
|---|---|---|---|
| M1 | DeepSeek-R1-Distill-Qwen-7B | `deepseek-r1:7b` | Q4_K_M |
| M2 | Qwen2.5-Coder-7B-Instruct | `qwen2.5-coder:7b` | Q4_K_M |
| M3 | DeepSeek-R1-Distill-Llama-8B | `hf.co/bartowski/DeepSeek-R1-Distill-Llama-8B-GGUF:Q4_K_M` | Q4_K_M |
| M4 | Gemma2-9B-It | `gemma2:9b` | Q4_0 |

M3 必須是 **Llama 8B**；本機 `deepseek-r1:8b` 曾核實為 Qwen3，不能替代。Embedding 使用 `bge-m3:latest`，Reranker 為已核實的 `BAAI/bge-reranker-v2-m3`。完整 digest 見公開狀態摘要及本機登錄。

## 知識庫規模與使用範圍

以下為已保存的 v6 Manifest 計數，代表處理規模，**不代表每段均經專家核實**。

| 項目 | 數量 |
|---|---:|
| 來源登錄 / 原始文件身分 | 100 / 98 |
| 文件頁面 | 1,278 |
| Chunk | 24,283 |
| Retrieval-eligible / Context-only | 13,794 / 10,489 |
| 圖像資產與圖像向量 | 6,637 |
| 表格元素 | 486 |

原件與衍生資料保存在 `my_data/RAG來源資料總庫/`，已依官方法規、歷史法規、養殖技術、疾病、水質氣候、用藥、統計及圖片表格分類。OCR、複雜表格與部分適用性仍保留待複核狀態。

研究負責人准入不等於第三方公開散布許可。政府資料開放授權僅適用已核實的實際資源；第三方全文、圖片及向量庫不隨程式庫公開。DGBAS 2020 僅限單年度描述性 Fact；用藥許可快照不代表現行處方，不能推導未記載的劑量、頻率或停藥期。

## 目錄與資料保留

| 路徑 | 用途 |
|---|---|
| `streamlit_cloud/` | 網站前端、原創圖示與背景 |
| `src/` | 資料解析、評測與 v4–v6 檢索；v6 仍依賴共用的 v4/v5 模組 |
| `scripts/`、`tools/` | 研究流程、建置、驗證、評測與部署工具 |
| `tests/` | Repository 測試 |
| `config/`、`configs/`、`schemas/`、`prompts/` | 處理設定、結構規格與 Prompt |
| `docs/` | 方法文件、檔案導覽與可公開的聚合結果 |
| `research_staging/app_sessions/` | 隔離應用程式；狀態與日誌只留本機 |
| `research_staging/deployment/` | 本機服務程式快照，不含憑證與 vendor |
| `my_data/`、`data/`、`fish test/`、`rag_assets/` | 原件、歷史 Corpus、題庫與素材，只留本機 |
| `reports/` | 完整結果、JSONL 與 Excel 留本機；僅同步程式快照至 GitHub |

見 [檔案導覽](docs/PROJECT_LAYOUT.md) 與 [研究結果摘要](docs/research_results/README.md)。本輪沒有移動資料庫或改寫歷史引用路徑。

## 啟動前端

公開 repository 不含第三方原件、索引、模型或憑證。完整問答依賴已配置的私有後端，不能只下載程式就重建所有研究資料。

```powershell
python -m venv .venv-web
.\.venv-web\Scripts\python.exe -m pip install -r streamlit_cloud/requirements.txt
.\.venv-web\Scripts\python.exe -m streamlit run streamlit_cloud/streamlit_app.py
```

在 Streamlit Secrets 設定 `RAG_BACKEND_DISCOVERY_URL`、`RAG_API_KEY`、`APP_ACCESS_CODE`，範例見 `streamlit_cloud/.streamlit/secrets.toml.example`。不要提交真正金鑰或存取碼。

雲端採 Python 3.14；Parser、ML 與測試使用既有隔離環境，前端 requirements 不能代替完整研究環境。現有 Windows 機器可使用本機保留的 `research_staging/deployment/streamlit_cloud_20261122_143650/start_knowledge_service.cmd` 啟動服務；該檔依賴本機憑證與環境，不對外同步。

目前 Community Cloud 追蹤 **`main`**，入口 `streamlit_cloud/streamlit_app.py`；網站與後端連線清單統一使用 main。

## 測試與研究結果

使用已配置的研究 Interpreter 執行正式測試：

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
python -m pytest tests -q -p no:cacheprovider
```

部分整合測試依賴本機歷史 Manifest、來源與模型。在只有公開程式碼的環境，缺少私有資料時不能宣稱完整通過；測試依賴與本次結果見公開摘要。

現行 v6 已保存 **180 題 × 4 模型 = 720 筆最終生成**，重試原始紀錄另存。11 項指標：Faithfulness、Judge Answer Relevance、BGE-M3 Cosine、Structured IFR、TTFT、TPS、System RAM、Dedicated VRAM、Context Precision@5、Logical Accuracy、Arithmetic Accuracy，各自保留有效 N。

使用者已確認品質 70%／效能 30% 的探索性選型方案，該方案推薦 **M2**。正規化仍含公開假設，總分不等於答對率、正式凍結論文分數或統計顯著性；網站仍保留四模型切換。

Human Gold 為 **0**。50 題自動來源核驗子集包含 37 題 Logical 與 13 題 Arithmetic，來源群組有限。P@5 只能報告實際 Context 與可靠標籤一致的子集。RAM／VRAM 為系統層級採樣峰值，JSON IFR 不代表語意遵循或專業正確性。

2026-11-22 已實際呼叫四模型並驗證線上切換。M1 引用失敗、M3 無據延伸的案例已保留原始結果並攔截相關網站輸出；守門檢查不是完整的專業正確性保證。

## 整理與保護

本輪只清除可重建的程式快取，以及經 SHA-256 與 ZIP 格式檢查確認損毀、未入庫的下載檔及副本。刪除收據保留在本機 `research_staging/maintenance/cleanup_publish_20261122/`。

原件、Python 環境、模型、資料庫、歷史索引、生成紀錄與 Excel 全部保留；不可存取的快取不強行更改權限。Frozen Manifest 維持 **636/636**。正式 SQLite SHA-256：

```text
d7d06d4d2a57d0a57d05bcb6131ffb24aefb226c6bd36349dbc5118d33b11087
```

根目錄 `LICENSE` 不擴張至第三方來源、模型或資料集；另依各自條款與適用範圍使用。
