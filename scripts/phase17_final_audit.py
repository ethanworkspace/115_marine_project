"""Finish unit tests, HTTP smoke and immutable-file verification after evaluation."""
import json
import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.evaluation.generation_models.runner import OUT, validate_current
from src.evaluation.generation.frozen import sha256_file
from src.evaluation.ragas_eval.runner import write_json
from scripts.phase17_snapshot import snapshot
import requests

def run_tests(python, args, log):
    env = dict(os.environ, PYTHONIOENCODING='utf-8')
    result = subprocess.run([str(python), '-m', 'unittest', *args], cwd=ROOT,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, encoding='utf-8', errors='replace', env=env)
    log.write_text(result.stdout, encoding='utf-8')
    count = re.search(r'Ran (\d+) tests?', result.stdout)
    skipped = re.search(r'skipped=(\d+)', result.stdout)
    return {'return_code': result.returncode, 'tests': int(count[1]) if count else None,
            'skipped': int(skipped[1]) if skipped else 0, 'passed_run': result.returncode == 0,
            'runtime': str(python.relative_to(ROOT)), 'log': str(log.relative_to(ROOT))}

manifest, _ = validate_current()
modules = ['generator_manifest','same_prompt_all_models','same_context_all_models','same_generation_config',
           'judge_conflict_detection','cross_model_pairing','cross_model_bootstrap','quality_efficiency',
           'pareto_analysis','no_composite_score','retrieval_hit_model_comparison','model_latency_report','phase17_judge_subset']
tests = {'full_suite': run_tests(ROOT / '.venv/Scripts/python.exe', ['discover','-s','tests','-v'], OUT / 'unittest_full.log'),
         'new_phase17': run_tests(ROOT / '.venv-ragas/Scripts/python.exe', ['tests.evaluation.test_' + n for n in modules] + ['-v'], OUT / 'unittest_evaluator_runtime.log')}
write_json(OUT / 'test_summary.json', tests)
smoke = subprocess.run([str(ROOT / '.venv-reranker/Scripts/python.exe'), '-c',
    'import torch,json; print(json.dumps({"torch_version":torch.__version__,"cuda_available":torch.cuda.is_available()}))'],
    cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, encoding='utf-8', errors='replace')
(OUT / 'reranker_final_import_smoke.log').write_text(smoke.stdout, encoding='utf-8')
limits = json.loads((OUT / 'environment_limitations.json').read_text(encoding='utf-8'))
limits['reranker'].setdefault('initial_import_smoke', limits['reranker'].get('final_import_smoke'))
limits['reranker']['final_import_smoke'] = {'status': 'available' if smoke.returncode == 0 else 'unavailable',
    'return_code': smoke.returncode, 'output': smoke.stdout, 'retrieval_executed': False,
    'scope': 'torch import and CUDA availability only; no model load or reranker scoring'}
write_json(OUT / 'environment_limitations.json', limits)
response = requests.get('http://127.0.0.1:8767/_stcore/health', timeout=10)
write_json(OUT / 'production_smoke.json', {'status_code': response.status_code, 'body': response.text,
    'url': response.url, 'e4_reexecuted': False, 'production_prompt_modified': False})
before = json.loads((OUT / 'protected_before.json').read_text(encoding='utf-8'))
interruption_path = OUT / 'execution_interruption.json'
if interruption_path.exists():
    interruption = json.loads(interruption_path.read_text(encoding='utf-8'))
    with (OUT / 'raw_evaluator_outputs.jsonl').open('rb') as stream:
        prefix_digest = hashlib.sha256(stream.read(interruption['raw_trace_prefix_bytes'])).hexdigest()
    resume_valid = prefix_digest == interruption['raw_trace_prefix_sha256']
    write_json(OUT / 'resume_integrity.json', {'previous_raw_trace_prefix_unchanged': resume_valid,
        'prefix_bytes': interruption['raw_trace_prefix_bytes'], 'prefix_sha256': prefix_digest})
    if not resume_valid:
        raise RuntimeError('Previously captured evaluator trace changed during resume')
after = snapshot()
changed = [key for key in before if before[key] != after.get(key)]
write_json(OUT / 'compatibility.json', {'protected_count': len(before), 'changed': changed, 'unchanged': not changed,
    'sqlite_before': before['rag_store.sqlite3'], 'sqlite_after': after.get('rag_store.sqlite3'),
    'existing_runtimes_unchanged': not any(n.startswith(('.venv/', '.venv-reranker/', '.venv-ragas/')) for n in changed),
    'production_http_200': response.status_code == 200})
sources = {}
for base in ('src/evaluation/generation_models',):
    for p in (ROOT / base).rglob('*.py'):
        sources[p.relative_to(ROOT).as_posix()] = sha256_file(p)
for p in (ROOT / 'scripts').glob('phase17*.py'):
    sources[p.relative_to(ROOT).as_posix()] = sha256_file(p)
write_json(OUT / 'implementation_checksums.json', sources)
outputs = {p.relative_to(ROOT).as_posix(): sha256_file(p) for p in OUT.rglob('*') if p.is_file() and p.name != 'output_checksums.json'}
write_json(OUT / 'output_checksums.json', outputs)
print(json.dumps({'tests':tests, 'protected_count':len(before), 'changed':changed, 'production_http':response.status_code}))
if changed or response.status_code != 200 or any(t['return_code'] for t in tests.values()):
    raise SystemExit(1)
