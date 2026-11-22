"""Isolated Phase S Streamlit application. Never imports or edits Production app.py."""
from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

RUN = Path(__file__).resolve().parents[1]
RAG_DIR = Path(__file__).resolve().parent
if str(RAG_DIR) not in sys.path:
    sys.path.insert(0, str(RAG_DIR))

from phase_s_rag import DB_PATH, MODEL_TAGS, PhaseSRAG, RerankerUnavailable

st.set_page_config(page_title="Marine Hybrid-RAG — Phase S", layout="wide")
st.title("Marine Hybrid-RAG — Phase S (隔離研究版)")
st.caption("本介面使用版本化的 Phase S 研究索引，不連接 Production、Evaluation Corpus v2 或歷史 E4。")

if not DB_PATH.is_file():
    st.error("Phase S 研究資料庫不存在，系統停止回答。")
else:
    st.info(f"研究資料庫：{DB_PATH.name}；正式切換：未執行。")

reranker_path = __import__("os").environ.get("PHASE_S_BGE_RERANKER_PATH")
if not reranker_path or not Path(reranker_path).is_dir():
    st.error("BGE Reranker v2-m3 的已核實本機權重缺失。為避免替代排序器造成不一致，本介面目前採 fail-closed，停用問答。")

question_text = st.text_area("問題", placeholder="輸入水產養殖問題")
species = st.selectbox("魚種", ["虱目魚", "吳郭魚", "石斑魚", "鱸魚", "烏魚", "鰻魚", "通用水產養殖"])
category = st.selectbox("類別", ["Fact", "Water Quality", "Disease", "Climate / Cold", "Medication / Law", "Calculation"])
model = st.selectbox("候選模型", list(MODEL_TAGS))

if st.button("檢索並回答", type="primary"):
    if not question_text.strip():
        st.warning("請先輸入問題。")
    else:
        engine = PhaseSRAG(DB_PATH)
        query = {"question_id": "interactive", "question_text": question_text, "species_chinese": species, "inferred_category": category}
        result = engine.ask(query, MODEL_TAGS[model])
        if result.get("status") == "blocked":
            st.error(result.get("reason", "系統尚未通過檢索驗收。"))
        else:
            st.json(result)

with st.expander("固定設定與限制"):
    st.write({
        "corpus_version": "phase_s_integrated_kb_v1",
        "database": str(DB_PATH),
        "reranker": "BAAI/bge-reranker-v2-m3 (required; unavailable locally)",
        "generator_models": MODEL_TAGS,
        "answer_policy": "證據不足時拒答；引用需核對來源、頁碼及逐字子字串。",
        "formal_evaluation": False,
        "production_switch": False,
    })
