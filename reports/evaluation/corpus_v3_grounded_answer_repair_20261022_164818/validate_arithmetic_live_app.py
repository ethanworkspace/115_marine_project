import sys
sys.dont_write_bytecode=True
from fair_grounded_rag_final import W,write,unload_all
from streamlit.testing.v1 import AppTest
def main():
 unload_all();at=AppTest.from_file(str(W/'fair_streamlit_app_final.py'),default_timeout=600).run();at.selectbox(key='qid').set_value('FT-seabass-Q24');at.selectbox(key='mid').set_value('M1');at.run();at.button(key='answer').click().run(timeout=600)
 assert not at.exception;g=at.session_state['last'];o=g['result'];assert g['api_completed'] and o['answer_status']=='ANSWERED_GROUNDED' and o['answer_origin']=='MODEL_GENERATED' and o['validation_status']['arithmetic_check']['correct']
 write('streamlit_arithmetic_validation.json',{'passed':True,'real_api':True,'mock':False,'app':'fair_streamlit_app_final.py','question_id':g['question_id'],'model_id':'M1','model_digest':g['model_digest'],'raw_response':g['raw_model_response'],'result':o,'attempt_id':g['attempt_id'],'context_digest':g['context_digest'],'corpus_sha256':g['corpus_sha256'],'parser':'numeric-v3-arithmetic-role-v4r2','provenance_not_mixed_with_regression200':True})
 unload_all();print('Real Streamlit/API arithmetic-result parser passed',flush=True)
if __name__=='__main__':main()
