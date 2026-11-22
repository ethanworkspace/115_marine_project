"""Local tests, UI smoke and read-only compatibility checks; no human decisions."""
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.evaluation.human_support.workflow import OUT, file_sha, report


def run_tests(args, filename):
    r=subprocess.run([str(ROOT/'.venv/Scripts/python.exe'), '-m','unittest', *args], cwd=ROOT,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, encoding='utf-8', errors='replace',
        env=dict(os.environ, PYTHONIOENCODING='utf-8'))
    (OUT/filename).write_text(r.stdout,encoding='utf-8')
    count=re.search(r'Ran (\d+) tests?',r.stdout);skip=re.search(r'skipped=(\d+)',r.stdout)
    return dict(return_code=r.returncode,tests=int(count[1]) if count else None,
                skipped=int(skip[1]) if skip else 0,log=filename)


if __name__=='__main__':
    result=report()
    modules=['human_review_blinding','human_review_append_only','support_taxonomy',
        'citation_selection_failure','unsupported_by_context','atomicity_flag','human_metric_denominators',
        'ai_human_agreement','model_shortlist_v2','qwen_not_auto_promoted']
    tests={'full_suite':run_tests(['discover','-s','tests','-v'],'unittest_full.log'),
           'phase18_1':run_tests(['tests.evaluation.test_'+m for m in modules]+['-v'],'unittest_phase18_1.log')}
    (OUT/'test_summary.json').write_text(json.dumps(tests,indent=2)+'\n',encoding='utf-8')
    smoke={}
    for name,port in [('production',8767),('human_review_workbench',8779)]:
        url=f'http://127.0.0.1:{port}/_stcore/health'
        try:
            with urlopen(url,timeout=10) as r:
                smoke[name]=dict(url=url,status_code=r.status,body=r.read().decode('utf-8'))
        except Exception as exc:
            smoke[name]=dict(url=url,status_code=None,error=str(exc))
    (OUT/'streamlit_smoke.json').write_text(json.dumps(smoke,indent=2)+'\n',encoding='utf-8')
    probe='''import json
from streamlit.testing.v1 import AppTest
a=AppTest.from_file("tools/human_claim_citation_review_app.py").run(timeout=30)
print(json.dumps({"exceptions":len(a.exception),"error_messages":[x.value for x in a.exception],
"metrics":[{"label":x.label,"value":x.value} for x in a.metric],
"unselected_support_inputs":sum(x.value is None for x in a.selectbox if "支持" in x.label),
"human_decisions_submitted":False},ensure_ascii=True))
'''
    ui=subprocess.run([str(ROOT/'.venv/Scripts/python.exe'),'-c',probe],cwd=ROOT,
        stdout=subprocess.PIPE,stderr=subprocess.PIPE,encoding='utf-8',errors='replace',
        env=dict(os.environ,PYTHONIOENCODING='utf-8'))
    render=dict(return_code=ui.returncode,result=json.loads(ui.stdout.strip()) if ui.returncode==0 else None,
                stderr=ui.stderr)
    (OUT/'workbench_render_smoke.json').write_text(json.dumps(render,indent=2)+'\n',encoding='utf-8')
    verification=subprocess.run([str(ROOT/'.venv/Scripts/python.exe'),'scripts/phase18_1_snapshot.py','--verify'],
        cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,encoding='utf-8',errors='replace')
    (OUT/'compatibility_log.txt').write_text(verification.stdout,encoding='utf-8')
    compatibility=json.loads((OUT/'compatibility.json').read_text(encoding='utf-8'))
    before=json.loads((OUT/'protected_before.json').read_text(encoding='utf-8'))
    db=ROOT/'rag_store.sqlite3';s=db.stat()
    compatibility.update(sqlite_before=before['rag_store.sqlite3'],
        sqlite_after=dict(sha256=file_sha(db),size=s.st_size,mtime_ns=s.st_mtime_ns),
        production_http_200=smoke['production']['status_code']==200,
        workbench_http_200=smoke['human_review_workbench']['status_code']==200,
        no_runtime_installation=True, no_model_invocation=True)
    (OUT/'compatibility.json').write_text(json.dumps(compatibility,indent=2)+'\n',encoding='utf-8')
    # Render performed no saves. Revalidate history without manufacturing any human label.
    refreshed=report()
    completion=dict(status='workflow_completed_without_human_review',
        user_requested_no_review=True, primary_review_complete=refreshed['status']['primary_review_complete'],
        human_reviewed_outputs=refreshed['status']['outputs_reviewed'],
        human_reviewed_claims=refreshed['status']['claims_reviewed'],
        human_reviewed_pairs=refreshed['status']['pairs_reviewed'],
        actual_edge_benchmark_started=False, human_support_evidence_available=bool(refreshed['status']['claims_reviewed']),
        tests=tests,production_compatibility=compatibility['unchanged'],
        final_quality_model_selection_ready=False)
    (OUT/'completion.json').write_text(json.dumps(completion,indent=2)+'\n',encoding='utf-8')
    path=OUT/'phase18_1_summary.md'
    extra=['','## Tests and compatibility','',
        f'Full unittest suite: {tests["full_suite"]["tests"]}; existing optional skips: {tests["full_suite"]["skipped"]}; return code {tests["full_suite"]["return_code"]}.',
        f'New tests: {tests["phase18_1"]["tests"]}; return code {tests["phase18_1"]["return_code"]}.',
        f'Protected files: {compatibility["protected_count"]}; changed: {len(compatibility["changed"])}.',
        f'Production / new Workbench health: {smoke["production"]["status_code"]} / {smoke["human_review_workbench"]["status_code"]}.',
        f'SQLite size / mtime / SHA-256 unchanged: {compatibility["sqlite_before"]==compatibility["sqlite_after"]}.',
        f'Actual blind UI render exceptions: {render["result"]["exceptions"] if render["result"] else None}.',
        'Synthetic fixture decisions exist only in temporary unittest directories, never in real human review history.','']
    path.write_text(path.read_text(encoding='utf-8')+'\n'.join(extra),encoding='utf-8')
    sources=list((ROOT/'src/evaluation/human_support').glob('*.py'))
    sources+=list((ROOT/'scripts').glob('phase18_1*.py'))
    sources += [ROOT/'tools/human_claim_citation_review_app.py',ROOT/'docs/human_claim_citation_review_protocol.md']
    (OUT/'implementation_checksums.json').write_text(json.dumps({p.relative_to(ROOT).as_posix():file_sha(p)
        for p in sources},indent=2)+'\n',encoding='utf-8')
    (OUT/'output_checksums.json').write_text(json.dumps({p.relative_to(ROOT).as_posix():file_sha(p)
        for p in OUT.rglob('*') if p.is_file() and p.name!='output_checksums.json'},indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(completion=completion,smoke=smoke,render=render['result']),ensure_ascii=True),flush=True)
    if (verification.returncode or any(t['return_code'] for t in tests.values()) or ui.returncode
        or render['result'] and render['result']['exceptions'] or any(r['status_code']!=200 for r in smoke.values())):
        raise SystemExit(1)
