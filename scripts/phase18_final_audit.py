"""Tests, blind UI smoke, protected-file checks and final Phase 18 inventories."""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from src.evaluation.validity.runner import OUT,check_inputs,write_json
from src.evaluation.generation.frozen import sha256_file
import requests


def run_tests(python,args,filename):
    r=subprocess.run([str(python),'-m','unittest',*args],cwd=ROOT,
        stdout=subprocess.PIPE,stderr=subprocess.STDOUT,encoding='utf-8',errors='replace',
        env=dict(os.environ,PYTHONIOENCODING='utf-8'))
    (OUT/filename).write_text(r.stdout,encoding='utf-8')
    count=re.search(r'Ran (\d+) tests?',r.stdout);skip=re.search(r'skipped=(\d+)',r.stdout)
    return {'return_code':r.returncode,'tests':int(count[1]) if count else None,
        'skipped':int(skip[1]) if skip else 0,'log':filename}


if __name__=='__main__':
    check_inputs()
    modules=['independent_judge_conflict','stratified_judge_sample','claim_extraction',
        'claim_citation_binding','citation_entailment_schema','blind_human_audit',
        'reference_metric_split','reference_bias_flag','model_shortlist','edge_benchmark_subset']
    tests={'full_suite':run_tests(ROOT/'.venv/Scripts/python.exe',['discover','-s','tests','-v'],'unittest_full.log'),
        'new_phase18':run_tests(ROOT/'.venv-ragas/Scripts/python.exe',
            ['tests.evaluation.test_'+m for m in modules]+['-v'],'unittest_phase18.log')}
    write_json(OUT/'test_summary.json',tests)
    urls={'production':'http://127.0.0.1:8767/_stcore/health',
          'human_audit_workbench':'http://127.0.0.1:8778/_stcore/health'}
    smoke={}
    for n,url in urls.items():
        try:
            r=requests.get(url,timeout=10);smoke[n]={'url':url,'status_code':r.status_code,'body':r.text}
        except Exception as e:smoke[n]={'url':url,'status_code':None,'error':str(e)}
    write_json(OUT/'streamlit_smoke.json',smoke)
    # Render the actual blind UI without any save interaction or fake human event.
    probe='''import json
from streamlit.testing.v1 import AppTest
a=AppTest.from_file("tools/claim_citation_audit_app.py").run(timeout=30)
print(json.dumps({"exceptions":len(a.exception),"error_messages":[x.value for x in a.exception],
"metrics":[{"label":x.label,"value":x.value} for x in a.metric],
"selectbox_labels":[x.label for x in a.selectbox],"human_input_submitted":False},ensure_ascii=True))
'''
    ui=subprocess.run([str(ROOT/'.venv/Scripts/python.exe'),'-c',probe],cwd=ROOT,
        stdout=subprocess.PIPE,stderr=subprocess.PIPE,encoding='utf-8',errors='replace',
        env=dict(os.environ,PYTHONIOENCODING='utf-8'))
    write_json(OUT/'workbench_render_smoke.json',{'return_code':ui.returncode,
        'result':json.loads(ui.stdout.strip()) if ui.returncode==0 else None,'stderr':ui.stderr})
    verification=subprocess.run([str(ROOT/'.venv-ragas/Scripts/python.exe'),'scripts/phase18_snapshot.py','--verify'],
        cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,encoding='utf-8',errors='replace')
    (OUT/'compatibility_log.txt').write_text(verification.stdout,encoding='utf-8')
    compatibility=json.loads((OUT/'compatibility.json').read_text(encoding='utf-8'))
    before=json.loads((OUT/'protected_before.json').read_text(encoding='utf-8'))
    sqlite=ROOT/'rag_store.sqlite3';s=sqlite.stat()
    compatibility.update(sqlite_before=before['rag_store.sqlite3'],
        sqlite_after={'sha256':sha256_file(sqlite),'size':s.st_size,'mtime_ns':s.st_mtime_ns},
        production_http_200=smoke['production']['status_code']==200,
        workbench_http_200=smoke['human_audit_workbench']['status_code']==200)
    write_json(OUT/'compatibility.json',compatibility)
    summary=OUT/'phase18_summary.md'
    base=summary.read_text(encoding='utf-8').split('\n## Tests and compatibility')[0]
    extra=['','## Tests and compatibility','',
        f'Full suite: {tests["full_suite"]["tests"]} cases, {tests["full_suite"]["skipped"]} existing optional skips, return code {tests["full_suite"]["return_code"]}.',
        f'Phase 18 isolated tests: {tests["new_phase18"]["tests"]} cases, return code {tests["new_phase18"]["return_code"]}.',
        f'Protected files: {compatibility["protected_count"]}; changed files: {len(compatibility["changed"])}.',
        f'Production / blind Workbench health: {smoke["production"]["status_code"]} / {smoke["human_audit_workbench"]["status_code"]}.',
        f'SQLite size / mtime / SHA-256 unchanged: {compatibility["sqlite_before"]==compatibility["sqlite_after"]}.',
        'Blind UI rendered without a save interaction; no fabricated human review, no Generator regeneration or hardware execution.','']
    summary.write_text(base+'\n'+'\n'.join(extra),encoding='utf-8')
    sources={p.relative_to(ROOT).as_posix():sha256_file(p) for p in (ROOT/'src/evaluation/validity').glob('*.py')}
    for p in (ROOT/'scripts').glob('phase18*.py'):sources[p.relative_to(ROOT).as_posix()]=sha256_file(p)
    for p in [ROOT/'tools/claim_citation_audit_app.py',ROOT/'docs/edge_benchmark_protocol.md']:
        sources[p.relative_to(ROOT).as_posix()]=sha256_file(p)
    write_json(OUT/'implementation_checksums.json',sources)
    write_json(OUT/'output_checksums.json',{p.relative_to(ROOT).as_posix():sha256_file(p)
        for p in OUT.rglob('*') if p.is_file() and p.name!='output_checksums.json'})
    print(json.dumps({'tests':tests,'compatibility':compatibility,'blind_ui_return_code':ui.returncode}),flush=True)
    if (verification.returncode or any(t['return_code'] for t in tests.values()) or ui.returncode
            or ui.returncode==0 and json.loads(ui.stdout.strip())['exceptions']
            or any(v['status_code']!=200 for v in smoke.values())):
        raise SystemExit(1)
