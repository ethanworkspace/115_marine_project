"""AppTest covers the real corpus path and source views, not mocked generators."""
import json
from pathlib import Path
import sys
from streamlit.testing.v1 import AppTest
ROOT=Path(__file__).resolve().parents[1]
APP=ROOT/'research_staging/app_sessions/launch_20261118_154253/professional_platform.py'
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(APP.parent))
ptr=json.loads((ROOT/'research_staging/unified_rag_build_pointer.json').read_text());report=Path(ptr['report_directory'])
at=AppTest.from_file(str(APP),default_timeout=120).run()
result={'application':str(APP),'initial_exceptions':[str(x.message) for x in at.exception],'generator_mocked':False,'generator_invoked_by_apptest':False,'real_generator_results_separate':True}
at.radio(key='platform_page').set_value('資料管理').run()
result['library_exceptions']=[str(x.message) for x in at.exception]
result['library_metrics']=[{'label':m.label,'value':m.value} for m in at.metric]
result['library_table_rows']=len(at.dataframe[0].value) if len(at.dataframe) else 0
at.radio(key='platform_page').set_value('來源資料').run()
result['source_exceptions']=[str(x.message) for x in at.exception]
result['passed']=not any(result[k] for k in ['initial_exceptions','library_exceptions','source_exceptions']) and result['library_table_rows']==66
(report/'streamlit_validation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(result,ensure_ascii=False))
if not result['passed']: raise SystemExit(1)
