"""Interactive research UI; all new output stays in the current session."""
from pathlib import Path
import sys
sys.dont_write_bytecode = True
SESSION = Path(__file__).resolve().parent
sys.path.insert(0, str(SESSION))
import streamlit as st
from answer_policy import SessionFairRag, FROZEN, VERSION, engine

st.set_page_config(page_title="Marine Hybrid-RAG 完整回覆", layout="wide")

@st.cache_resource
def load():
    return SessionFairRag(), {r["question_id"]: r for r in engine.jl(FROZEN / "shared_contexts_180.jsonl")}

runtime, questions = load()
st.title("Marine Hybrid-RAG 問答")
st.caption("每題提供完整回覆：有據直接回答、部分支持說明範圍、無據提供具體缺口與查核方向。")
qid = st.selectbox("問題", list(questions), format_func=lambda key: key + " " + questions[key]["question"], key="qid")
model = st.selectbox("模型", ["M1", "M2", "M3", "M4"], index=1, key="mid")
st.caption("Corpus SHA-256：" + runtime.runtime.db_sha256)
if st.button("產生完整回覆", key="answer"):
    try:
        with st.spinner("本機模型處理中…"):
            st.session_state["last"] = runtime.call(questions[qid], model, stage="INTERACTIVE_COMPLETE_RESPONSE")
    except Exception as exc:
        st.error("本次服務未能完成模型呼叫，請確認Ollama連線及模型是否可用後重試。")
        with st.expander("連線錯誤"):
            st.code(str(exc))

if "last" in st.session_state:
    record = st.session_state["last"]
    result = record["result"]
    labels = {"ANSWERED_GROUNDED": "來源支持的回答", "ANSWERED_PARTIAL": "部分來源支持的回答", "INSUFFICIENT_EVIDENCE": "完整回覆：資料缺口與查核方向", "VALIDATION_FAILED": "完整回覆：模型輸出未通過驗證"}
    st.subheader(labels[result["answer_status"]])
    st.write(result["final_answer"])
    origins = {"MODEL_GENERATED": "模型直接生成", "DETERMINISTIC_EVIDENCE_EXTRACTION": "確定性來源摘取", "SYSTEM_GUIDANCE": "系統查核說明，並非模型直接答對"}
    st.caption("回答來源：" + origins.get(result["answer_origin"], result["answer_origin"]))
    st.caption("作答策略版本：" + VERSION)
    contexts = {c["chunk_id"]: c for c in questions[record["question_id"]]["top5"]}
    source_ids = result["supporting_chunk_ids"] or record["evidence_decision"]["supporting_chunk_ids"]
    for chunk_id in source_ids:
        chunk = contexts[chunk_id]
        with st.expander(chunk["source_id"] + " · " + chunk_id, expanded=True):
            st.write(chunk["source_quote"])
            st.caption(chunk["source_version"])
            st.caption(chunk["exact_locator"])
    with st.expander("原始模型回覆與驗證狀態"):
        st.code(record["raw_model_response"])
        st.json(result["validation_status"])
