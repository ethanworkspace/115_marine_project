from pathlib import Path
import sys
import streamlit as st
W=Path(__file__).resolve().parent;sys.path.insert(0,str(W))
from frozen_runner import FrozenRag
st.set_page_config(page_title='Marine Hybrid-RAG 凍結研究評測',layout='wide')
@st.cache_resource
def runtime():return FrozenRag()
rt=runtime();st.title('Corpus v3 凍結研究問答');st.caption(f"隔離研究 · {rt.runtime.corpus_status()['corpus_version']} · {rt.runtime.db_sha256}")
st.warning('探索性回歸評測；不是 Production 或 Human Gold。採用已凍結的 Hybrid-RAG、Reranker 與來源篩選結果。')
qid=st.selectbox('原始題目',list(rt.retrieval),key='question_id',format_func=lambda k:f"{k} — {rt.retrieval[k]['question']}")
mid=st.selectbox('模型',['M1','M2','M3','M4'],index=1,key='model_id')
if st.button('依固定證據回答',key='run_query'):
 with st.spinner('真實本機模型串流推論…'):st.session_state['last_result']=rt.call(rt.retrieval[qid],mid,stage='STREAMLIT')
if 'last_result' in st.session_state:
 r=st.session_state['last_result'];f=r['final_response']
 if f['abstained']:st.info(f"拒答／限制：{f['reason']}")
 else:st.write(f['answer'])
 st.caption(f"Answer origin: {r['answer_origin']} · Raw model JSON: {r['raw_model_structure_valid']}")
 for c in f.get('citation_details',[]):
  with st.expander(f"{c['source_id']} · {c['chunk_id']}",expanded=True):st.write(c['quote']);st.write(c['locator']);st.caption(c['source_version'])
 with st.expander('原始模型回答及驗證'):st.code(r['raw_model_response']);st.json(r['raw_citation_validation'])
 st.caption(f"固定 Context: {r['context_count']}筆 · Digest: {r['context_digest']}")
