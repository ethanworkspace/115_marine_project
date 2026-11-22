"""Streamlit AppTest drives the real local M2 API; no model/retrieval mocks."""
import sys,json,time
sys.dont_write_bytecode=True
from fair_grounded_rag import W,jl,write,unload_all
from run_regression import verify_freeze
from streamlit.testing.v1 import AppTest
def main():
 verify_freeze();rows=jl(W/'shared_contexts_180.jsonl');negative=next(r for r in rows if not r['top5']);tests=[];unload_all()
 for qid,expected in [('FT-tilapia-Q09','ANSWERED_GROUNDED'),(negative['question_id'],'INSUFFICIENT_EVIDENCE')]:
  at=AppTest.from_file(str(W/'fair_streamlit_app_final.py'),default_timeout=600);at.run();assert not at.exception
  at.selectbox(key='qid').set_value(qid);at.selectbox(key='mid').set_value('M2');at.run();at.button(key='answer').click().run(timeout=600)
  assert not at.exception;g=at.session_state['last'];out=g['result'];assert g['api_completed'] and out['answer_status']==expected
  assert g['corpus_sha256']=='b51b14bfdad0c31a1f64c50d79b511eadf03ce0d55fd8e3d7e59b9a7d350a99e'
  texts=[x.value for x in at.markdown];captions=[x.value for x in at.caption];display='\n'.join(texts+captions)
  assert out['final_answer'] in display and out['answer_origin'] in display
  if expected=='ANSWERED_GROUNDED':assert out['supporting_chunk_ids'] and out['answer_origin']=='MODEL_GENERATED' and at.expander
  else:assert out['missing_information']
  tests.append({'question_id':qid,'expected':expected,'passed':True,'actual_generator':True,'model_id':'M2','model_digest':g['model_digest'],'attempt_id':g['attempt_id'],'result':out,'displayed_markdown':texts,'displayed_captions':captions,'citation_expander_n':len(at.expander),'exceptions':[]})
 unload_all();write('streamlit_real_validation.json',{'passed':True,'mock_used':False,'real_api_calls':len(tests),'tests':tests,'app_path':str(W/'fair_streamlit_app_final.py'),'corpus_read_only':True,'not_production':True})
 print('Real Streamlit/API/source display validation passed',flush=True)
if __name__=='__main__':main()
