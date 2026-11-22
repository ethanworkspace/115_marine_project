"""Synthetic tests and read-only compatibility checks, with no actual edge execution."""
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.request import urlopen

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from src.evaluation.edge.inputs import OUT,TARGET,BUNDLE
from src.evaluation.edge.report import prepare
from src.evaluation.generation.frozen import sha256_file


def tests(args,log):
    r=subprocess.run([str(ROOT/'.venv/Scripts/python.exe'),'-m','unittest',*args],cwd=ROOT,
        stdout=subprocess.PIPE,stderr=subprocess.STDOUT,encoding='utf-8',errors='replace',
        env=dict(os.environ,PYTHONIOENCODING='utf-8'))
    (OUT/log).write_text(r.stdout,encoding='utf-8')
    count=re.search(r'Ran (\d+) tests?',r.stdout);skips=re.search(r'skipped=(\d+)',r.stdout)
    return dict(return_code=r.returncode,tests=int(count[1]) if count else None,
                skipped=int(skips[1]) if skips else 0,log=log)


if __name__=='__main__':
    manifest=prepare()
    if manifest['edge_execution_ready']:
        raise SystemExit('This final tooling audit does not start a hardware benchmark; use the separate guarded execution path')
    names=['target_device_manifest','edge_subset_frozen','same_context_all_models_edge',
        'model_identity_edge','cold_warm_separation','ttft_definition','reasoning_token_handling',
        'memory_metric_semantics','hardware_quality_status_separation','no_edge_composite_score',
        'context_length_groups','edge_behavior_preservation']
    result={'full_suite':tests(['discover','-s','tests','-v'],'unittest_full.log'),
            'new_phase19':tests(['tests.evaluation.test_'+n for n in names]+['-v'],'unittest_phase19.log')}
    (OUT/'test_summary.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    url='http://127.0.0.1:8767/_stcore/health'
    try:
        with urlopen(url,timeout=10) as r:smoke=dict(url=url,status_code=r.status,body=r.read().decode('utf-8'))
    except Exception as exc:smoke=dict(url=url,status_code=None,error=str(exc))
    (OUT/'production_smoke.json').write_text(json.dumps(smoke,indent=2)+'\n',encoding='utf-8')
    r=subprocess.run([str(ROOT/'.venv/Scripts/python.exe'),'scripts/phase19_snapshot.py','--verify'],cwd=ROOT,
        stdout=subprocess.PIPE,stderr=subprocess.STDOUT,encoding='utf-8',errors='replace')
    (OUT/'compatibility_log.txt').write_text(r.stdout,encoding='utf-8')
    compatibility=json.loads((OUT/'compatibility.json').read_text(encoding='utf-8'))
    before=json.loads((OUT/'protected_before.json').read_text(encoding='utf-8'))
    db=ROOT/'rag_store.sqlite3';s=db.stat()
    compatibility.update(sqlite_before=before['rag_store.sqlite3'],
        sqlite_after=dict(sha256=sha256_file(db),size=s.st_size,mtime_ns=s.st_mtime_ns),
        production_http_200=smoke['status_code']==200,no_model_download=True,no_runtime_installation=True,
        no_real_generator_requests=True,no_retrieval_execution=True,
        synthetic_fixtures_only=True)
    (OUT/'compatibility.json').write_text(json.dumps(compatibility,indent=2)+'\n',encoding='utf-8')
    completion=dict(status='tooling_completed_target_not_specified',edge_execution_ready=False,
        actual_models_benchmarked=[],actual_cold_requests=0,actual_warm_requests=0,
        acceptance_thresholds_defined=False,benchmark_scope='generator_only',
        actual_device_feasibility_established=False,phase19B_ready=False,phase20_integration_ready=False,
        final_quality_winner_selected=False,tests=result,production_compatibility=compatibility['unchanged'])
    (OUT/'completion.json').write_text(json.dumps(completion,indent=2)+'\n',encoding='utf-8')
    p=OUT/'phase19_summary.md'
    extra=['','## Tests and compatibility','',
        f'Full unittest suite: {result["full_suite"]["tests"]}; existing optional skips: {result["full_suite"]["skipped"]}; return code {result["full_suite"]["return_code"]}.',
        f'Phase 19 synthetic tests: {result["new_phase19"]["tests"]}; return code {result["new_phase19"]["return_code"]}.',
        f'Protected files: {compatibility["protected_count"]}; changed files: {len(compatibility["changed"])}.',
        f'Production Streamlit health: HTTP {smoke["status_code"]}.',
        f'SQLite size / mtime / SHA-256 unchanged: {compatibility["sqlite_before"]==compatibility["sqlite_after"]}.',
        'All runtime tests used synthetic transports; no actual model generation, unload, sensor benchmark or model acquisition.',
        'Actual target/runtime feasibility, quality preservation and performance are not established.','']
    p.write_text(p.read_text(encoding='utf-8')+'\n'.join(extra),encoding='utf-8')
    sources=list((ROOT/'src/evaluation/edge').glob('*.py'))+list((ROOT/'scripts').glob('phase19*.py'))
    sources += [ROOT/'schemas/edge_target_device.schema.json',TARGET,ROOT/'docs/phase19_edge_execution_guide.md']
    (OUT/'implementation_checksums.json').write_text(json.dumps({p.relative_to(ROOT).as_posix():sha256_file(p)
        for p in sources},indent=2)+'\n',encoding='utf-8')
    (OUT/'output_checksums.json').write_text(json.dumps({p.relative_to(ROOT).as_posix():sha256_file(p)
        for p in OUT.rglob('*') if p.is_file() and p.name!='output_checksums.json'},indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(completion=completion,compatibility=compatibility,smoke=smoke)),flush=True)
    if r.returncode or smoke['status_code']!=200 or any(t['return_code'] for t in result.values()):raise SystemExit(1)
