import json,sys,time
from pathlib import Path
W=Path(__file__).resolve().parent
ROOT=W.parents[2]
for p in (ROOT/'.venv-reranker/Lib/site-packages', ROOT/'.venv/Lib/site-packages', ROOT, W/'app'):
 if str(p) not in sys.path: sys.path.insert(0,str(p))
from streamlit.testing.v1 import AppTest
app=W/'app'/'streamlit_app.py'
question='寒流來襲時，列出三項官方建議避免的魚塭操作。'
at=AppTest.from_file(str(app),default_timeout=240).run()
at.text_area[0].set_value(question)
at.selectbox[0].select('吳郭魚')
at.selectbox[1].select('Climate / Cold')
at.selectbox[2].select('M1')
t0=time.time()
at.button[0].click().run(timeout=240)
result={
 'status':'passed' if not at.exception and any('檢索狀態' in str(x.value) for x in at.subheader) else ('failed' if at.exception else 'completed_without_expected_output'),
 'question':question,
 'selected_species':'吳郭魚','selected_category':'Climate / Cold','selected_model':'M1',
 'exception_count':len(at.exception),'exceptions':[str(x) for x in at.exception],
 'success_count':len(at.success),'warning_count':len(at.warning),'error_count':len(at.error),
 'elapsed_seconds':time.time()-t0,
 'notes':'A real Streamlit form submission through the isolated RAG engine. Generator output here is a UI smoke, outside the canonical 720-row evaluation.'
}
(W/'rag_v3_streamlit_interaction_validation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(result,ensure_ascii=False,indent=2))
