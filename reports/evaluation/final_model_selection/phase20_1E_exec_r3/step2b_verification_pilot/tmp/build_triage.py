import json,pathlib,re,subprocess,datetime
R=pathlib.Path(r'C:\my project\115_marine_project'); O=R/'reports/evaluation/final_model_selection/phase20_1E_exec_r3/step2b_verification_pilot'
def w(n,x): (O/n).write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
log=O/'tmp/full_evaluation_retest.txt'; raw=log.read_text(encoding='utf-8',errors='replace')
fails=re.findall(r'^FAILED (tests/evaluation/\S+)$',raw,re.M)
teardown=re.findall(r'^_ ERROR at teardown of QuestionBankImportTests\.(\w+) _$',raw,re.M)
def describe(t):
 if 'dense_index_manifest' in t: return 'PermissionError WinError 5 creating nested temp index path; earlier parent creation reported FileNotFoundError WinError 3.','test body: temp index tree creation'
 if 'edge_report_write' in t: return 'PermissionError Errno 13 writing progress.json.tmp; tempdir cleanup denied.','test body: temp report write/cleanup'
 if 'failed_runtime_immutable' in t: return 'PermissionError Errno 13 writing dll test file; tempdir cleanup denied.','test body: temp file write/cleanup'
 if 'human_metric_denominators' in t: return 'PermissionError Errno 13 writing review_transactions.jsonl.','test body: review transaction temp write'
 if 'human_review_append_only' in t: return 'PermissionError writing review history or creating nested fish test path; cleanup denied.','test body: temp history write/directory create'
 if 'question_bank_import' in t: return 'PermissionError WinError 5 creating the fish test workspace path under tempdir.','test body: temp workspace path creation'
 if 'v22_retry_policy' in t: return 'PermissionError WinError 5 creating schemas directory under tempdir.','test body: temp schema directory creation'
 return 'PermissionError / WinError 5 creating nested test output under pytest temp root.','test body: temp output tree creation'
items=[]
for t in fails:
 msg,stage=describe(t)
 items.append({'test_id':t,'result_kind':'failed','exception_type':'PermissionError (WinError 5 / Errno 13); nested path can first raise FileNotFoundError WinError 3','failure_message':msg,'failure_stage':stage,'root_cause_category':'windows_sandbox_temporary_directory_permission','reproduction_status':'reproduced in full evaluation-suite rerun with isolated Step2B basetemp; not individually rerun','action_required':'Use approved writable/cleanable pytest temp root and rerun unchanged test.'})
for method in teardown:
 tid=next((x for x in fails if x.endswith('::'+method)),None)
 items.append({'test_id':tid or 'QuestionBankImportTests.'+method,'result_kind':'teardown_error','exception_type':'PermissionError (WinError 5)','failure_message':'TemporaryDirectory teardown could not remove/access the test temp folder.','failure_stage':'pytest TemporaryDirectory teardown','root_cause_category':'windows_sandbox_temporary_directory_permission','reproduction_status':'reproduced in full-suite rerun with isolated Step2B basetemp','action_required':'Rerun unchanged test using approved temp root with cleanup permission; do not change ACL/security.'})
probe='import sys,importlib.util,json; print(json.dumps({"python":sys.version,"executable":sys.executable,"modules":{m:bool(importlib.util.find_spec(m)) for m in ["pytest","docx","fitz","pymupdf"]}}))'
env=[]
for name,p in [('C:/Python314',pathlib.Path('C:/Python314/python.exe')),('Anaconda',pathlib.Path('C:/Users/ethan/anaconda3/python.exe')),('project .venv',R/'.venv/Scripts/python.exe'),('project .venv-ragas',R/'.venv-ragas/Scripts/python.exe'),('project .venv-reranker',R/'.venv-reranker/Scripts/python.exe')]:
 if not p.exists(): env.append({'name':name,'path':str(p),'exists':False}); continue
 q=subprocess.run([str(p),'-c',probe],capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=30)
 try: res=json.loads(q.stdout.strip().splitlines()[-1])
 except Exception: res={'stdout':q.stdout,'stderr':q.stderr}
 env.append({'name':name,'path':str(p),'exit_code':q.returncode,'probe':res})
w('test_failure_triage.json',{'suite_result':{'command':'pytest.exe -q -p no:cacheprovider --tb=short --basetemp <Step2B tmp>/pytest-basetemp tests/evaluation','runner':'C:/Users/ethan/anaconda3/Scripts/pytest.exe','python':'Python 3.14.6','exit_code':1,'passed':525,'skipped':6,'failed':len(fails),'errors':len(teardown),'subtests_passed':2,'raw_log':str(log),'raw_log_present':log.exists()},'failed_test_count':len(fails),'error_count':len(teardown),'items':items,
 'root_cause_summary':{'windows_sandbox_temp_permission':len(items),'interpreter_dependency_mismatch':'separate full-repository collection blocker, not cause established for eval-suite failures','missing_dependency_for_eval_failures':0,'confirmed_code_regression':0,'unresolved':0},'caveat':'Suite-level reproduction only; no assertion-level failure established and individual failures were not separately rerun.'})
w('test_environment_reproduction.json',{'timestamp_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'sandbox_mode':'workspace-write; repository is accessible, but Windows sandbox denies some pytest temp path create/write/cleanup operations.','isolated_temp_root':str(O/'tmp'),'evaluation_suite':{'passed':525,'skipped':6,'failed':len(fails),'errors':len(teardown),'exit_code':1,'raw_log':str(log)},'interpreter_probes':env,
 'full_repository_suite':{'status':'collection_blocked','collection_errors':9,'causes':['pytest temp path PermissionError (2)','ModuleNotFoundError: docx/python-docx','ModuleNotFoundError: pymupdf/fitz'],'interpretation':'Project .venv has python-docx/PyMuPDF but no pytest; Anaconda pytest is Python 3.14.6 and lacks docx/fitz; project venvs are Python 3.14.7.'},
 'observed_errors':['PermissionError Errno 13 / WinError 5 on temp file write, nested directory creation and cleanup.','Some nested path attempts first report FileNotFoundError WinError 3, then fail creating the parent with WinError 5.'],
 'changes_made':{'packages_installed':False,'tests_modified':False,'assertions_relaxed':False,'tests_skipped_or_deleted':False,'security_or_acl_changed':False},
 'action_required':'Provide approved writable/cleanable pytest temp root and use one interpreter containing pytest plus ingestion dependencies; rerun unchanged tests.'})
print(json.dumps({'failed':len(fails),'errors':len(teardown),'triage_items':len(items),'envs':len(env)}))
