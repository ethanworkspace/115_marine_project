from __future__ import annotations

import json
from pathlib import Path

import streamlit as st

import phase_z_runtime as runtime

HERE = Path(__file__).resolve().parent
cases = runtime.read_jsonl(HERE / "independent_test_set.jsonl")
case_by_id = {row["test_id"]: row for row in cases}

st.set_page_config(page_title="Phase Z Grounded RAG Smoke", layout="wide")
st.title("Phase Z 有據回答驗收")
st.caption("隔離研究用事實卡測試；非正式 Evaluation Corpus、非 Human Gold。")

case_ids = list(case_by_id)
case_id = st.selectbox("測試案例", case_ids, format_func=lambda key: f"{key}｜{case_by_id[key]['question_text']}")
model_id = st.selectbox("Generator", list(runtime.MODEL_TABLE))
st.write("**問題**", case_by_id[case_id]["question_text"])
st.write("**目標魚種**", case_by_id[case_id]["target_species"])

if st.button("執行真實 Generator / 證據閘", type="primary"):
    result = runtime.run_model(case_id, model_id)
    st.session_state["phase_z_last_result"] = result
    st.session_state["phase_z_last_result_json"] = json.dumps(result, ensure_ascii=False, indent=2)

result = st.session_state.get("phase_z_last_result")
if result:
    st.subheader("結果")
    st.write("**Answer origin**", result.get("answer_origin"))
    st.write("**模型原始狀態**", result.get("model_reported_status"))
    final = result.get("final_response") or {}
    st.write("**狀態**", final.get("status"))
    st.write("**回答／拒答說明**", final.get("answer") or result.get("abstention_reason"))
    st.write("**引用來源**", final.get("citations", []))
    st.write("**生成器是否呼叫**", result.get("generator_called"))
    st.write("**證據狀態**", (result.get("evidence_decision") or {}).get("state"))
    with st.expander("完整可追溯紀錄"):
        st.json(result)
