"""Record the approved site rename using local evidence only; no live-page access."""
import datetime,json,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
WORK=Path(json.loads((ROOT/'research_staging/streamlit_cloud_deployment_pointer.json').read_text(encoding='utf-8'))['directory'])
new_url='https://aquaculture-knowledge-platform.streamlit.app/'
name='Aquaculture Knowledge Platform'
git=r'C:\Program Files\Git\cmd\git.exe'
commit=subprocess.check_output([git,'-C',str(WORK/'github_checkout'),'rev-parse','HEAD'],text=True).strip()
assert commit.startswith('11374b2')
assert name in (WORK/'frontend/streamlit_app.py').read_text(encoding='utf-8')
assert name in (WORK/'frontend/cloud_client.py').read_text(encoding='utf-8')
tests=json.loads((WORK/'reports/api_and_ui_validation.json').read_text(encoding='utf-8'))
assert tests['status']=='PASS'
at=datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).isoformat()
report={'site_name':name,'chinese_name':'養殖漁業知識平台','requested_url':new_url,
        'previous_url':'https://marine-knowledge-platform.streamlit.app/','owner_approved_name_and_url':True,
        'frontend_commit':commit,'frontend_brand_changes_published':True,
        'streamlit_availability_ui_observed':'Available!','streamlit_save_changes_clicked':True,
        'browser_origin_reported_after_save':'https://aquaculture-knowledge-platform.streamlit.app',
        'new_url_content_verified':False,'new_url_live_generator_test_completed':False,
        'live_verification_status':'PENDING_OWNER_MANUAL_CHECK',
        'browser_blocker':'Automatic approval review blocked the new origin because the workspace credit limitation was not resolved. No alternative browser, raw protocol or HTTP page-verification workaround used.',
        'owner_choice':'Owner will open the new URL and verify manually; this choice is not a confirmation that verification passed.',
        'local_api_and_ui_checks_passed':len(tests['checks']),'model_corpus_and_credentials_changed':False,'at':at}
(WORK/'reports/site_rename_20261122.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
status_file=WORK/'deployment_status.json'
status=json.loads(status_file.read_text(encoding='utf-8'))
if 'previous_live_validation' not in status:
    status['previous_live_validation']={k:status.get(k) for k in ('streamlit_public_url','commit','at','actual_cloud_ui_question_and_note_save_passed')}
status.update(status='RENAMED_PENDING_OWNER_MANUAL_CHECK',site_name=name,chinese_name='養殖漁業知識平台',
    streamlit_public_url=new_url,desired_subdomain='aquaculture-knowledge-platform',commit=commit,at=at,
    new_url_content_verified=False,new_url_live_generator_test_completed=False,
    actual_cloud_ui_question_and_note_save_passed=False,
    remaining_steps=['Owner manually verifies the new URL, English name and question/knowledge views.'],
    validation_scope='Previous live smoke receipts remain historical; the renamed URL has not passed new live verification.')
status_file.write_text(json.dumps(status,ensure_ascii=False,indent=2),encoding='utf-8')
(ROOT/'research_staging/streamlit_cloud_deployment_pointer.json').write_text(json.dumps({'directory':str(WORK),'status':status['status'],'public_url':new_url},ensure_ascii=False,indent=2),encoding='utf-8')
instructions_file=WORK/'deployment_instructions.txt'
instructions=instructions_file.read_text(encoding='utf-8-sig').replace('https://marine-knowledge-platform.streamlit.app/',new_url)
note='\n網站名稱已改為 Aquaculture Knowledge Platform（養殖漁業知識平台）。新網址線上驗收待研究者自行確認；程式改名已發佈。\n'
if note not in instructions:instructions+=note
instructions_file.write_text(instructions,encoding='utf-8-sig')
print(json.dumps({'site_name':name,'new_url':new_url,'commit':commit,'live_verification':'PENDING_OWNER_MANUAL_CHECK','local_checks':'PASS'},ensure_ascii=False))
