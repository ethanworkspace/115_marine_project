from pathlib import Path
import sys
sys.dont_write_bytecode=True
W=Path(__file__).resolve().parent;sys.path.insert(0,str(W))
import streamlit as st
from fair_grounded_rag import FairRag,jl
st.set_page_config(page_title='Marine Hybrid-RAG 有據問答',layout='wide')
@st.cache_resource
def load():return FairRag(),{r['question_id']:r for r in jl(W/'shared_contexts_180.jsonl')}
rt,rows=load();st.title('Marine Hybrid-RAG 有據問答');st.caption('隔離 Corpus v3 · 來源核驗型研究回歸 · 不是 Human Gold')
qid=st.selectbox('問題',list(rows),format_func=lambda k:k+' '+rows[k]['question'],key='qid');mid=st.selectbox('模型',['M1','M2','M3','M4'],index=1,key='mid')
st.caption('Corpus SHA-256：'+rt.runtime.db_sha256)
if st.button('依來源回答',key='answer'):
 with st.spinner('本機模型處理中…'):st.session_state['last']=rt.call(rows[qid],mid,stage='STREAMLIT')
if 'last' in st.session_state:
 g=st.session_state['last'];out=g['result'];st.subheader(out['answer_status']);st.write(out['final_answer']);st.caption('回答來源：'+out['answer_origin'])
 if out['missing_information']:st.write('尚缺資訊');st.write(out['missing_information'])
 byid={c['chunk_id']:c for c in rows[g['question_id']]['top5']}
 for cid in out['supporting_chunk_ids']:
  c=byid[cid]
  with st.expander(c['source_id']+' · '+cid,expanded=True):st.write(c['source_quote']);st.caption(c['source_version']);st.caption(c['exact_locator'])
 with st.expander('模型原始回覆與驗證'):st.code(g['raw_model_response']);st.json(out['validation_status'])
