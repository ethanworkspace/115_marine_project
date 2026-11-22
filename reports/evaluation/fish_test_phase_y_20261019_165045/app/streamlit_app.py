from __future__ import annotations

import streamlit as st

import sys
from pathlib import Path
Y = Path(__file__).resolve().parents[1]
if str(Y) not in sys.path: sys.path.insert(0, str(Y))
from rag_v3_phase_y import RAGEngine

st.set_page_config(page_title="Marine Hybrid-RAG v3 (Phase Y)", page_icon="🐟", layout="wide")
st.title("Marine Hybrid-RAG v3 — 隔離研究版")
st.caption("使用 Phase Y 隔離 Corpus v3；回答只依可追溯且符合範圍的證據。此介面不連接 Production。")

with st.form("query_form"):
    question = st.text_area("問題", placeholder="輸入水產養殖問題", height=110)
    c1, c2 = st.columns(2)
    species = c1.selectbox("目標魚種", ["虱目魚", "吳郭魚", "石斑魚", "鱸魚", "烏魚", "鰻魚", "通用養殖"])
    category = c2.selectbox("類別", ["Fact", "Water Quality", "Disease", "Climate / Cold", "Medication / Law", "Calculation"])
    model_id = st.selectbox("模型", ["M1", "M2", "M3", "M4"])
    submitted = st.form_submit_button("檢索並回答")

if submitted:
    if not question.strip():
        st.error("請先輸入問題。")
    else:
        try:
            engine = RAGEngine()
            with st.spinner("正在使用隔離研究索引檢索…"):
                retrieval = engine.retrieve(question.strip(), species, category)
            st.subheader("檢索狀態")
            st.write({"狀態": retrieval["retrieval_status"], "合格候選": retrieval["corpus_applicable_chunk_count"], "Top-5 實際數量": retrieval["final_top5_count"], "Corpus": retrieval["corpus_version"]})
            result = engine.answer_with_retrieval(question.strip(), species, category, model_id, retrieval)
            if result["status"] == "answered" and result["citation_validation"].get("valid"):
                st.success(result.get("answer") or "已完成回答。")
            elif result["status"] == "invalid_output":
                st.error("模型輸出未通過 JSON 或來源引用檢查，系統已阻止顯示該答案。")
            else:
                st.warning(result.get("answer") or result.get("abstention_reason") or "證據不足，系統拒答。")
            st.caption(f"引用驗證：{result['citation_validation'].get('reason')}")
            for cite in result.get("citations", []):
                st.write(f"來源：{cite.get('source_id')} · {cite.get('locator')} · Chunk {cite.get('chunk_id')}")
            with st.expander("查看實際 Evidence Context"):
                for c in retrieval.get("reranked_top5", []):
                    st.markdown(f"**Rank {c['rank']} · {c['source_id']} · {c.get('page_or_locator')}**")
                    st.write(c["content"])
        except Exception as exc:
            st.error(f"研究版 RAG 執行失敗：{type(exc).__name__}: {exc}")

