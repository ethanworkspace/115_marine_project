from pathlib import Path
import sys,json,hashlib,gc
W=Path(__file__).resolve().parent;sys.path.insert(0,str(W))
from rag_v3_runtime import RagV3Runtime
q='官方建議越冬溝內虱目魚的最高適宜密度是多少？'
rt=RagV3Runtime(); r=rt.answer(q,'虱目魚','M3')
r['system_pass']=not r['final_response'].get('abstained') and '1.3' in str(r['final_response'].get('answer')) and (r.get('final_citation_validation') or {}).get('status')=='PASS'
(W/'final_m3_citation_regression.json').write_text(json.dumps(r,ensure_ascii=False,indent=2),encoding='utf-8')
print('M3 regression',r['answer_origin'],r['system_pass'],flush=True)
del rt;gc.collect()
import torch
torch.cuda.empty_cache()
from streamlit.testing.v1 import AppTest
out={'type':'Streamlit AppTest with actual final v3 runtime, frozen reference profile and real M2 streaming API; not mock','status':'ERROR'}
try:
 at=AppTest.from_file(str(W/'streamlit_v3_app.py'),default_timeout=600).run()
 at.selectbox(key='species').select('虱目魚');at.selectbox(key='model_id').select('M2');at.text_area(key='question').set_value(q)
 at.button(key='run_query').click().run()
 result=at.session_state['last_result'];errors=[str(x.value) for x in at.exception]
 passed=not errors and result['corpus']['corpus_version']=='3.0.1-evidence-alignment' and result.get('raw_model_response') is not None and '1.3' in str(result['final_response'].get('answer')) and (result.get('final_citation_validation') or {}).get('status')=='PASS'
 out.update(status='PASS' if passed else 'FAIL',exceptions=errors,result=result,rendered_captions=[x.value for x in at.caption],rendered_expander_count=len(at.expander),model_direct=result['answer_origin']=='MODEL_GENERATED')
except Exception as e:out.update(error=repr(e))
(W/'streamlit_v3_validation.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
print('Streamlit',out['status'],flush=True)
