from __future__ import annotations

import json
import sys
from pathlib import Path

import streamlit as st

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import phase_aa_runtime as runtime

cases = [json.loads(line) for line in (HERE / "independent_test_set.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
answerable = [row for row in cases if row.get("source_card_chunk_id")]
case_by_id = {row["test_id"]: row for row in answerable}

st.set_page_config(page_title="Phase AA Research Fact RAG", layout="wide")
st.title("Marine Hybrid-RAG｜Phase AA 隔離研究驗證")
st.caption("只使用獨立、重新核驗的短事實卡；非正式 Corpus v3、非 Human Gold，不提供未核實的養殖或用藥建議。")
if not runtime.DB_PATH.is_file():
    st.error("隔離研究索引不存在。")
    st.stop()

case_id = st.selectbox("凍結測試案例", list(case_by_id), format_func=lambda key: f"{key}｜{case_by_id[key]['question_text']}")
case = case_by_id[case_id]
st.write("**問題**", case["question_text"])
st.write("**目標魚種**", case["target_species"])
model_id = st.selectbox("本機 Generator", list(runtime.MODEL_TABLE), index=1)

if st.button("執行隔離檢索", type="primary"):
    result = runtime.retrieve(case["question_text"], case["target_species"], top_k=5)
    st.session_state["aa_retrieval"] = result
    st.session_state["aa_retrieved_case_id"] = case_id

retrieval = st.session_state.get("aa_retrieval")
if retrieval:
    st.subheader("檢索結果")
    st.json(retrieval["candidate_counts"])
    if not retrieval["reranked_top"]:
        st.warning("目前沒有符合來源與魚種範圍的事實卡。")
    for row in retrieval["reranked_top"]:
        with st.expander(f"{row['rank']}｜{row['source_id']}｜{row['locator']}", expanded=row["rank"] == 1):
            st.write(row["text"])
            st.caption(f"版本：{row['source_version']}｜來源 SHA-256：{row['source_sha256']}｜Chunk：{row['chunk_id']}")
    if st.button("以所選模型執行有據回答"):
        active_case = case_by_id[st.session_state.get("aa_retrieved_case_id", case_id)]
        spans = runtime.spans_from_retrieval(retrieval)
        profile = runtime.profile_for_case(active_case, spans)
        result = runtime.run_generator(profile, spans, model_id, active_case["test_id"], retrieval)
        st.session_state["aa_generation"] = result

generation = st.session_state.get("aa_generation")
if generation:
    st.subheader("回答結果")
    st.write("**來源類型**", generation.get("answer_origin"))
    st.write("**系統判定**", (generation.get("evidence_decision") or {}).get("state"))
    final = generation.get("final_response") or {}
    st.write("**狀態**", final.get("status"))
    st.write("**回答／拒答原因**", final.get("answer") or generation.get("abstention_reason"))
    st.write("**引用**", final.get("citations", []))
    with st.expander("完整追溯紀錄"):
        st.json(generation)
