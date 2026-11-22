import os
from pathlib import Path
import streamlit as st

st.set_page_config(page_title="Phase T Research RAG", layout="wide")
st.title("Phase T｜隔離研究 RAG 驗證")
st.caption("研究候選索引；不連接 Production。答案資格未核驗時不呼叫生成模型。")

class DemoGate:
    def retrieve(self, question):
        return {"question_id": "demo", "retrieval_status": "insufficient_retrieval_evidence", "final_top5_count": 0, "reranked_top5": []}
    def answer(self, question, model_tag, answer_gate=None):
        return {"status": "insufficient_evidence", "reason": "來源答案 Gate 尚未通過", "generator_called": False}

@st.cache_resource
def load_rag():
    if os.environ.get("PHASE_T_APPTEST_MODE") == "1":
        return DemoGate()
    from phase_t_rag import PhaseTRAG
    return PhaseTRAG()

species = st.selectbox("魚種", ["虱目魚", "吳郭魚", "石斑魚", "鱸魚", "烏魚", "鰻魚", "通用養殖"])
question_text = st.text_area("問題")
if st.button("檢索並回答", type="primary"):
    q = {"question_id": "interactive", "species_chinese": species, "question_text": question_text, "inferred_category": "UNCLASSIFIED"}
    rag = load_rag()
    trace = rag.retrieve(q)
    st.session_state["phase_t_trace"] = trace
    if trace["final_top5_count"] < 5:
        st.warning("目前候選來源不足；已停止生成。")
    for row in trace["reranked_top5"]:
        with st.expander(f"{row['rank']}. {row['source_title']}｜{row['chunk_id']}"):
            st.write(row["content"])
            st.caption(f"來源：{row['source_id']}；頁碼／定位：{row.get('page') or row.get('locator')}")
