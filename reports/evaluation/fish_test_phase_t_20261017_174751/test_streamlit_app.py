import json, os
from pathlib import Path
from streamlit.testing.v1 import AppTest
root=Path.cwd(); out=root/'reports/evaluation/fish_test_phase_t_20261017_174751'
os.environ['PHASE_T_APPTEST_MODE']='1'
at=AppTest.from_file(str(out/'rag_v3/phase_t_app.py'),default_timeout=20).run()
assert not at.exception, [e.message for e in at.exception]
at.selectbox[0].set_value('鰻魚')
at.text_area[0].set_value('請提供鰻魚適用的水質安全範圍')
at.button[0].click().run()
assert not at.exception, [e.message for e in at.exception]
assert len(at.warning)>0
record={'app':'phase_t_app.py','app_test_mode':'mock_fail_closed','initial_render':'PASS','query_submit':'PASS','warning_rendered':bool(at.warning),'generator_calls':0,'status':'PASS'}
(out/'streamlit_apptest.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(record,ensure_ascii=True))
