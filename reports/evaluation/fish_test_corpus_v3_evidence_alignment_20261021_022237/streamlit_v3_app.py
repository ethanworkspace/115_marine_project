from __future__ import annotations
import sys
from pathlib import Path

import streamlit as st

WORK = Path(__file__).resolve().parent
if str(WORK) not in sys.path:
    sys.path.insert(0, str(WORK))
from rag_v3_runtime import RagV3Runtime


@st.cache_resource(show_spinner="載入隔離 Corpus v3、BGE-M3 與 reranker…")
def get_runtime() -> RagV3Runtime:
    return RagV3Runtime(load_reranker=True)


st.set_page_config(page_title="Marine Hybrid-RAG — Corpus v3", layout="wide")
st.title("Marine Hybrid-RAG — 隔離研究 Corpus v3")
runtime = get_runtime()
corpus = runtime.corpus_status()
st.caption(f"{corpus['corpus_id']} · v{corpus['corpus_version']} · SHA-256 {corpus['database_sha256']}")
st.warning("隔離研究環境；不是 Production、Evaluation Corpus v2 或正式答案基準。")

species = st.selectbox("目標魚種", runtime.pipe.SPECIES, key="species")
model_id = st.selectbox("Generator", ["M1", "M2", "M3", "M4"], index=1, key="model_id")
question = st.text_area("問題", key="question", height=110)
if st.button("以 Corpus v3 檢索並回答", key="run_query"):
    if not question.strip():
        st.error("請輸入問題。")
    else:
        with st.spinner("檢索、來源適用性檢查及回答中…"):
            result = runtime.answer(question.strip(), species, model_id)
        st.session_state["last_result"] = result

result = st.session_state.get("last_result")
if result:
    final = result.get("final_response") or {}
    st.subheader("回答")
    if final.get("abstained"):
        st.info(f"證據不足或安全限制：{final.get('reason')}")
    else:
        st.write(final.get("answer"))
    st.caption(f"Evidence: {result.get('evidence_decision',{}).get('state')} · Answer origin: {result.get('answer_origin')}")
    details = (result.get("final_citation_validation") or result.get("citation_validation") or {}).get("citations", [])
    if details:
        st.subheader("來源與原文位置")
        for citation in details:
            with st.expander(f"{citation['source_id']} · {citation['chunk_id']}", expanded=True):
                st.write(citation["locator"])
                st.write(citation["quote"])
                st.caption(f"版本：{citation['source_version']} · SHA-256：{citation['source_sha256']}")
    top5 = result.get("retrieval", {}).get("top5", [])
    st.caption(f"實際合格 Context：{len(top5)}（不足五筆時不補造）")
    st.json({"model": result.get("model"), "corpus": result.get("corpus"), "citation_validation": result.get("citation_validation"), "error": result.get("error")})
