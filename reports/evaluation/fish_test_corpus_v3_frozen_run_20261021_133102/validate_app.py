from pathlib import Path
import sys,json,hashlib,gc
W=Path(__file__).resolve().parent;sys.path.insert(0,str(W));sys.stdout.reconfigure(encoding='utf-8')
from frozen_runner import FrozenRag,unload,write
from streamlit.testing.v1 import AppTest
out={'status':'ERROR','method':'Real Streamlit AppTest, real M2 API, frozen v3 SQLite and context; no mocked Generator'}
try:
 at=AppTest.from_file(str(W/'frozen_streamlit_app.py'),default_timeout=600).run()
 at.selectbox(key='question_id').select('FT-milkfish-Q04');at.selectbox(key='model_id').select('M2');at.button(key='run_query').click().run()
 result=at.session_state['last_result'];errors=[str(x.value) for x in at.exception]
 passed=not errors and result['api_completed'] and result['raw_model_structure_valid'] and not result['final_response']['abstained'] and '1.3' in result['final_response']['answer'] and result['final_citation_validation']['status']=='PASS'
 out.update(status='PASS' if passed else 'FAIL',exceptions=errors,result=result,rendered_expander_count=len(at.expander),captions=[x.value for x in at.caption])
except Exception as e:out['error']=repr(e)
write('streamlit_validation.json',out);unload('qwen2.5-coder:7b');print(out['status'],flush=True)
