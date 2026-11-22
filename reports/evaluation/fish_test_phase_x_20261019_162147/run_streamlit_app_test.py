import json,sys,os
from pathlib import Path
ROOT=Path.cwd(); W=ROOT/'reports/evaluation/fish_test_phase_w_20261019_133804'; X=ROOT/'reports/evaluation/fish_test_phase_x_20261019_162147'
os.environ['PYTHONDONTWRITEBYTECODE']='1'
for p in [str(W/'app'), str(ROOT/'.venv/Lib/site-packages')]:
 if p not in sys.path: sys.path.insert(0,p)
from streamlit.testing.v1 import AppTest
p=W/'app'/'streamlit_app.py'
try:
 at=AppTest.from_file(str(p),default_timeout=20).run()
 obj={'status':'passed' if not at.exception else 'failed','tested_file':str(p),'exception_count':len(at.exception),'exceptions':[str(x) for x in at.exception],'title_count':len(at.title),'selectbox_count':len(at.selectbox),'text_area_count':len(at.text_area),'form_submit_button_count':len(at.button),'scope':'real Streamlit AppTest initial render; no retrieval/generator call; Phase W recorded actual interaction separately'}
except Exception as e:
 obj={'status':'failed','tested_file':str(p),'exception':f'{type(e).__name__}: {e}','scope':'real Streamlit AppTest initial render'}
(X/'streamlit_app_test_x.json').write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(obj,ensure_ascii=False,indent=2))
