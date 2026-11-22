"""Phase 17: frozen model roster, full generation, and unchanged Phase 16 judging."""
from __future__ import annotations

import argparse
import ast
import importlib.metadata
import json
import os
import platform
import re
import subprocess
import threading
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import requests

from .core import COMMON_OPTIONS, CONDITIONS, judge_conflict, validate_manifest, assert_same_inputs
from ..generation.frozen import read_jsonl, sha256_file, validate_frozen_inputs
from ..generation.protocol_v2 import sha256_text
from ..generation.retry_v21 import build_attempt_record, should_retry
from ..generation.runner_v2 import _run_one_v2, format_v2_user_prompt
from ..ragas_eval.runner import load_rows, score_row, write_json
from ..ragas_eval.runtime import ENDPOINT, JUDGE_MODEL, append_jsonl, make_adapters, make_metrics, local_inventory

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / 'reports/evaluation/generation_models/phase17'
GEN = ROOT / 'reports/evaluation/generation'
MODELS = ('gemma2:9b', 'deepseek-r1:8b', 'qwen2.5-coder:7b', 'deepseek-r1:7b')


def load_json(p):
    return json.loads(Path(p).read_text(encoding='utf-8'))


def slug(name):
    return re.sub('[^a-zA-Z0-9]+', '_', name).strip('_')


def model_dir(name):
    return OUT / 'generators' / slug(name)


def common_rows():
    rows, hashes = load_rows()
    for condition, prefix in [('oracle', 'G0'), ('e4_top5', 'G1')]:
        folder = GEN / f'{prefix}_grounded_{"oracle" if prefix == "G0" else "e4_top5"}_generation_v2_2'
        manifest = {r['question_id']: r['contexts'] for r in read_jsonl(folder / 'context_manifest.jsonl')}
        for row in rows:
            if row['condition'] == condition:
                row['context_provenance'] = manifest[row['question_id']]
    return rows, hashes


def context_records(row):
    return [dict(c, text=t) for c, t in zip(row['context_provenance'], row['contexts'], strict=True)]


def prepare():
    OUT.mkdir(parents=True, exist_ok=True)
    rows, hashes = common_rows()
    tree = ast.parse((ROOT / 'rag_core.py').read_text(encoding='utf-8'))
    assignments = [n.value for n in tree.body if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'MODELS' for t in n.targets)]
    if len(assignments) != 1:
        raise ValueError('Cannot identify a unique configured MODELS assignment')
    configured = tuple(ast.literal_eval(assignments[0]))
    if configured != MODELS:
        raise ValueError('Project configured model roster differs; stop before selecting candidates')
    inv = requests.get(ENDPOINT + '/api/tags', timeout=10).json()
    runtime = requests.get(ENDPOINT + '/api/version', timeout=10).json()
    if runtime.get('version') != '0.35.0':
        raise ValueError('Frozen Ollama runtime version differs')
    judge = load_json(ROOT / 'reports/evaluation/ragas/phase16/evaluator_manifest.json')
    candidates = []
    local = {m['name']: m for m in inv['models']}
    for name in MODELS:
        info = local.get(name)
        show = requests.post(ENDPOINT + '/api/show', json={'model': name}, timeout=20).json() if info else {}
        if 'error' in show:
            raise ValueError('Ollama show failed: ' + name)
        record = {'name': name, 'tag': name, 'digest': info.get('digest') if info else None,
                  'availability': 'available' if info else 'blocked_runtime',
                  'parameter_size': (info or {}).get('details', {}).get('parameter_size'),
                  'quantization': (info or {}).get('details', {}).get('quantization_level'),
                  'native_context_length': (info or {}).get('details', {}).get('context_length'),
                  'configured_context_length': 8192, 'generation_options': COMMON_OPTIONS,
                  'runtime': 'Ollama 0.35.0', 'model_show': show,
                  'baseline_reuse': name == MODELS[0],
                  'supported_parameters': {'temperature': 'Ollama request accepted', 'top_p': 'Ollama request accepted',
                                           'seed': 'Ollama API option; repeatability not guaranteed', 'num_predict': 'Ollama API option'},
                  'structured_output_mode': 'same Ollama /api/chat native JSON schema; no per-model parser',
                  'thinking_option': 'unspecified, identical to frozen Gemma invocation; no reasoning requested'}
        record['judge_conflict'] = judge_conflict(record, judge)
        candidates.append(record)
    manifest = {'phase': 17, 'timestamp': datetime.now(timezone.utc).isoformat(),
                'generators': candidates, 'generation_options': COMMON_OPTIONS,
                'question_count': 169, 'maximum_attempts': 2, 'benchmark_type': 'silver',
                'generation_source': 'corpus_grounded_ai', 'conditions': CONDITIONS,
                'input_hashes': hashes, 'prompt_sha256': sha256_file(ROOT / 'prompts/generation_v2.txt'),
                'schema_sha256': sha256_file(ROOT / 'schemas/generation_output_v2.schema.json'),
                'judge_manifest_sha256': sha256_file(ROOT / 'reports/evaluation/ragas/phase16/evaluator_manifest.json'),
                'judge': judge, 'ragas_version': importlib.metadata.version('ragas'),
                'bootstrap': {'iterations': 10000, 'seed': 17017, 'unit': 'question'},
                'error_thresholds': {'faithfulness': .5, 'answer_relevancy': .5, 'silver_reference_correctness': .5},
                'primary_cohort': 'answered-only, paired valid scores on the same question IDs',
                'deterministic_citation_comparison': 'all-question required chunk recall, fixed denominator; failure or abstention is zero',
                'primary_judge_conflict_policy': 'Conflicted Qwen judge metrics skipped; all deterministic/performance metrics still executed',
                'repeatability_policy': '30 new non-conflicted answered outputs, deterministic coverage-first by model/condition/style/category/species; two fresh full judge runs',
                'pareto_axes': {'faithfulness': 'max', 'silver_reference_correctness': 'max', 'citation_recall': 'max', 'p95_latency': 'min'},
                'pareto_note': 'Descriptive only; baseline historical allocation may differ; no automatic final model selection',
                'selection_rule': 'All four project configured local models before scoring; Gemma frozen baseline reused; no model download or result-based selection',
                'git_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()}
    validate_manifest(manifest)
    path = OUT / 'generator_comparison_manifest.json'
    if path.exists():
        prior = load_json(path)
        for key in ('generators', 'generation_options', 'input_hashes', 'prompt_sha256', 'schema_sha256', 'judge_manifest_sha256'):
            if prior[key] != manifest[key]:
                raise ValueError('Cannot resume with altered frozen ' + key)
    else:
        write_json(path, manifest)
        write_json(OUT / 'experiment_manifest.json', manifest)
        for m in candidates:
            write_json(OUT / 'generator_manifests' / (slug(m['name']) + '.json'), m)
    hardware = {'os': platform.platform(), 'python': platform.python_version(), 'cpu': platform.processor(),
                'ollama': runtime, 'gpu': subprocess.check_output(['nvidia-smi', '--query-gpu=name,memory.total,driver_version', '--format=csv,noheader'], text=True).strip(),
                'machine': platform.node(), 'performance_scope': 'Same evaluation machine; frozen Gemma timing is historical, loaded model/offload state may differ'}
    if not (OUT / 'hardware.json').exists():
        write_json(OUT / 'hardware.json', hardware)
    conflicts = {m['name']: {'judge_conflict': m['judge_conflict'], 'generator_digest': m['digest'], 'judge_digest': judge['model_digest'],
                            'judge_based_primary_eligible': not m['judge_conflict'], 'exploratory_self_judge_status': 'not_run' if m['judge_conflict'] else 'not_applicable'} for m in candidates}
    write_json(OUT / 'judge_conflicts.json', conflicts)
    write_json(OUT / 'self_judge_conflict.json', conflicts)
    limitations = {'reranker': {'status': 'not_reexecuted', 'reason': 'Windows Code Integrity / Smart App Control previously blocked c10_cuda.dll (WinError 4551)',
                               'prior_evidence': 'reports/evaluation/ragas/torch_code_integrity_events.json',
                               'frozen_e4_top5_used': True, 'metric_invalidation': False},
                   'tokenization': 'No Ollama /api/tokenize endpoint; different generator tokenizers cannot use Gemma prompt counts as reference. Audit actual prompt_eval_count, context margin and runtime truncation warnings; absence of warnings is an observed runtime audit, not an independent tokenizer proof.'}
    write_json(OUT / 'environment_limitations.json', limitations)
    print('Frozen four generators; Qwen self-judge conflict excluded from primary judge comparison', flush=True)


def validate_current():
    manifest = load_json(OUT / 'generator_comparison_manifest.json')
    validate_manifest(manifest)
    rows, hashes = common_rows()
    if manifest['input_hashes'] != hashes:
        raise ValueError('Protected inputs changed')
    for field, relative in [('prompt_sha256', 'prompts/generation_v2.txt'), ('schema_sha256', 'schemas/generation_output_v2.schema.json'), ('judge_manifest_sha256', 'reports/evaluation/ragas/phase16/evaluator_manifest.json')]:
        if sha256_file(ROOT / relative) != manifest[field]:
            raise ValueError('Frozen protocol or evaluator changed: ' + relative)
    inventory = {m['name']: m['digest'] for m in requests.get(ENDPOINT + '/api/tags', timeout=10).json()['models']}
    if any(m['availability'] == 'available' and inventory.get(m['name']) != m['digest'] for m in manifest['generators']):
        raise ValueError('Frozen model artifact changed')
    return manifest, rows


class MemorySampler:
    """Read-only device-wide VRAM and Ollama process-family working set samples."""
    def __init__(self):
        self.stop = threading.Event()
        self.samples = []
        self.errors = []
        self.thread = threading.Thread(target=self.run, daemon=True)

    def run(self):
        while not self.stop.is_set():
            try:
                gpu = subprocess.check_output(['nvidia-smi', '--query-gpu=memory.used', '--format=csv,noheader,nounits'], text=True, timeout=10)
                command = "@(Get-Process | Where-Object { $_.ProcessName -match 'llama|ollama' } | Select-Object Id,ProcessName,WorkingSet64,PrivateMemorySize64) | ConvertTo-Json -Compress"
                ram = subprocess.check_output(['powershell', '-NoProfile', '-Command', command], text=True, timeout=10)
                processes = json.loads(ram) if ram.strip() else []
                if isinstance(processes, dict):
                    processes = [processes]
                self.samples.append({'timestamp': time.time(), 'device_vram_used_mib': int(gpu.strip().splitlines()[0]),
                                     'ollama_working_set_bytes': sum(p['WorkingSet64'] for p in processes), 'processes': processes})
            except Exception as exc:
                self.errors.append(type(exc).__name__ + ': ' + str(exc))
            self.stop.wait(5)

    def finish(self):
        self.stop.set()
        self.thread.join(timeout=15)
        return {'sample_interval_seconds': 5, 'samples': self.samples, 'errors': self.errors,
                'peak_ram_bytes': max((s['ollama_working_set_bytes'] for s in self.samples), default=None),
                'peak_vram_bytes': None, 'peak_vram_reason': 'Process-specific CUDA allocation peak not exposed by Ollama; device-wide used memory separately reported',
                'peak_device_vram_used_mib': max((s['device_vram_used_mib'] for s in self.samples), default=None),
                'ram_scope': 'sum of Ollama process-family working sets, sampled; not unique physical memory or per-tensor peak'}


def unload_models():
    for m in requests.get(ENDPOINT + '/api/ps', timeout=10).json().get('models', []):
        r = requests.post(ENDPOINT + '/api/generate', json={'model': m['name'], 'keep_alive': 0}, timeout=120)
        r.raise_for_status()


def log_offset():
    p = Path(os.environ.get('LOCALAPPDATA', '')) / 'Ollama/server.log'
    return p, p.stat().st_size if p.exists() else None


def call_generation(**kwargs):
    """Identical request contract, plus full stream/thinking capture and log diagnostics."""
    schema = load_json(ROOT / 'schemas/generation_output_v2.schema.json')
    body = {'model': kwargs['model'], 'stream': True, 'format': schema, 'keep_alive': '30m',
            'messages': [{'role': 'system', 'content': kwargs['system_prompt']}, {'role': 'user', 'content': kwargs['user_prompt']}],
            'options': dict(COMMON_OPTIONS)}
    start = time.perf_counter()
    parts, thinking, events = [], [], []
    done, error, ttft, first_event = {}, None, None, None
    log, offset = log_offset()
    try:
        with requests.post(ENDPOINT + '/api/chat', json=body, stream=True, timeout=900) as response:
            response.raise_for_status()
            response.encoding = 'utf-8'
            for line in response.iter_lines(decode_unicode=True):
                if not line:
                    continue
                events.append(line)
                try:
                    event = json.loads(line)
                except json.JSONDecodeError as exc:
                    error = 'stream_event_json_error: ' + str(exc)
                    continue
                message = event.get('message') or {}
                delta, thought = message.get('content') or '', message.get('thinking') or ''
                if delta or thought:
                    if first_event is None:
                        first_event = time.perf_counter() - start
                if delta:
                    if ttft is None:
                        ttft = time.perf_counter() - start
                    parts.append(str(delta))
                if thought:
                    thinking.append(str(thought))
                if event.get('error'):
                    error = str(event['error'])
                if event.get('done'):
                    done = event
    except Exception as exc:
        error = type(exc).__name__ + ': ' + str(exc)
    if not error and not done:
        error = 'stream_interrupted: no final done event'
    raw = ''.join(parts)
    parsed, parse_error = None, None
    try:
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            parse_error = 'response_json_not_object'
    except json.JSONDecodeError as exc:
        parse_error = type(exc).__name__ + ': ' + str(exc)
    warnings, log_available = [], offset is not None
    if offset is not None:
        try:
            with log.open('rb') as f:
                f.seek(offset)
                lines = f.read().decode('utf-8', errors='replace').splitlines()
            warnings = [line for line in lines if 'truncat' in line.casefold() and ('prompt' in line.casefold() or 'input' in line.casefold())]
        except OSError:
            log_available = False
    prompt_tokens, count, duration = done.get('prompt_eval_count'), done.get('eval_count'), done.get('eval_duration')
    margin = 8192 - 1024 - prompt_tokens if prompt_tokens is not None else None
    audit = {'context_length': 8192, 'max_output_tokens': 1024, 'prompt_tokens': prompt_tokens,
             'remaining_context_margin': margin, 'runtime_truncation_warnings': warnings,
             'runtime_log_available': log_available, 'input_truncated': True if warnings else (False if log_available and margin is not None and margin >= 0 else None),
             'input_truncation_detection': 'actual prompt_eval_count, context margin and Ollama runtime truncation warning log; not cross-tokenizer Gemma count comparison',
             'context_capacity_failure': bool(warnings) or margin is not None and margin < 0}
    if audit['context_capacity_failure']:
        error = 'context_capacity_failure: frozen evidence input cannot be silently shortened'
    return {'raw_output': raw, 'raw_output_sha256': sha256_text(raw), 'response_received': bool(events),
            'parsed': parsed if isinstance(parsed, dict) else None, 'parse_error': parse_error, 'execution_error': error,
            'latency_seconds': time.perf_counter() - start, 'ttft_seconds': ttft, 'first_stream_token_seconds': first_event,
            'prompt_tokens': prompt_tokens, 'completion_tokens': count,
            'tokens_per_second': count / (duration / 1e9) if count is not None and duration else None,
            'load_duration_ns': done.get('load_duration'), 'done_reason': done.get('done_reason'),
            'context_window_budget': audit, 'raw_stream_events': events, 'raw_thinking': ''.join(thinking),
            'raw_thinking_sha256': sha256_text(''.join(thinking)), 'request_sha256': sha256_text(json.dumps(body, ensure_ascii=False, sort_keys=True)),
            'final_event': done}


def generate():
    manifest, base = validate_current()
    frozen = validate_frozen_inputs(ROOT)
    questions = {q['question_id']: q for q in frozen['questions']}
    prompt = (ROOT / 'prompts/generation_v2.txt').read_text(encoding='utf-8').strip()
    for m in manifest['generators']:
        name = m['name']
        if m['baseline_reuse'] or m['availability'] != 'available':
            continue
        folder = model_dir(name)
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / 'per_question.jsonl'
        existing = read_jsonl(path) if path.exists() else []
        saved = {(r['question_id'], r['condition']) for r in existing}
        if len(saved) != len(existing):
            raise ValueError('Duplicate generation checkpoint')
        if len(saved) == 338:
            continue
        unload_models()
        sampler = MemorySampler()
        sampler.thread.start()
        ps_samples = []
        for row in base:
            identity = (row['question_id'], row['condition'])
            if identity in saved:
                continue
            contexts = context_records(row)
            attempt_file = folder / 'attempts.jsonl'
            attempts = [a for a in read_jsonl(attempt_file) if (a['question_id'], a['condition']) == identity] if attempt_file.exists() else []
            if len(attempts) > 2:
                raise ValueError('Retry limit exceeded')
            while not attempts or should_retry(attempts[-1]['result'], attempt_number=attempts[-1]['attempt_number']):
                number = len(attempts) + 1
                captured = {}
                def call_fn(**kw):
                    value = call_generation(**kw)
                    captured.update(value)
                    return value
                result, raw = _run_one_v2(questions[row['question_id']], contexts,
                    condition='G0' if row['condition'] == 'oracle' else 'G1', model=name, base_url=ENDPOINT,
                    prompt=prompt, corpus_ids=set(frozen['corpus_by_id']), call_fn=call_fn)
                result.update(attempt_number=number, context_window_budget=captured['context_window_budget'])
                attempt = build_attempt_record(question_id=row['question_id'], attempt_number=number, result=result, raw=raw)
                attempt.update(condition=row['condition'], generator=name, captured_runtime=captured)
                append_jsonl(attempt_file, attempt)
                attempts.append(attempt)
            final = attempts[-1]['result']
            output = {**row, 'answer': final['answer'], 'status': final['status'], 'model': name, 'generator': name,
                      'judge_conflict': m['judge_conflict'], 'metrics': {}, 'generation_attempts': len(attempts),
                      'deterministic_generation': final,
                      'citation_failure': final['strict_citation_count'] != final['citation_count'] or final['missing_citation']}
            append_jsonl(path, output)
            saved.add(identity)
            print(f"generation {name} {row['condition']} {len(saved)}/338 {row['question_id']} {final['status']} attempts={len(attempts)} tokens={final['completion_tokens']}", flush=True)
            if len(saved) % 50 == 1:
                ps_samples.append(requests.get(ENDPOINT + '/api/ps', timeout=10).json())
        memory = sampler.finish()
        write_json(folder / 'memory.json', memory)
        ps_samples.append(requests.get(ENDPOINT + '/api/ps', timeout=10).json())
        write_json(folder / 'runtime_allocations.json', ps_samples)
        outputs = read_jsonl(path)
        assert_same_inputs(base, outputs)
        write_json(folder / 'experiment_manifest.json', {'generator': m, 'status': 'completed', 'rows': len(outputs),
            'question_count_per_condition': 169, 'input_hashes': manifest['input_hashes'], 'generation_options': COMMON_OPTIONS,
            'prompt_sha256': manifest['prompt_sha256'], 'schema_sha256': manifest['schema_sha256'],
            'maximum_attempts': 2, 'context_checksum_identical': True,
            'experiments': [f'G0_{slug(name)}_oracle_v1', f'G1_{slug(name)}_e4_top5_v1']})


def all_rows():
    manifest, base = validate_current()
    prior = {(r['question_id'], r['condition']): r for r in read_jsonl(ROOT / 'reports/evaluation/ragas/phase16/per_question_metrics.jsonl')}
    outputs = []
    for m in manifest['generators']:
        name = m['name']
        if m['baseline_reuse']:
            rows = [dict(r, generator=name, model=name, judge_conflict=False,
                         metrics=prior[(r['question_id'], r['condition'])]['metrics']) for r in base]
        elif m['availability'] == 'available':
            rows = read_jsonl(model_dir(name) / 'per_question.jsonl')
            if len(rows) != 338:
                raise ValueError(f'{name}: full generation incomplete')
            assert_same_inputs(base, rows)
        else:
            continue
        outputs.extend(rows)
    return manifest, outputs


def select_new_repeat(rows, count=30):
    candidates = [r for r in rows if r['generator'] != MODELS[0] and not r['judge_conflict'] and r['status'] == 'answered']
    chosen, seen = [], set()
    while candidates and len(chosen) < count:
        def coverage(r):
            return sum((k, str(r.get(k))) not in seen for k in ('generator', 'condition', 'species', 'category', 'query_style'))
        model_counts = Counter(r['generator'] for r in chosen)
        condition_counts = Counter((r['generator'], r['condition']) for r in chosen)
        r = min(candidates, key=lambda x: (model_counts[x['generator']],
            condition_counts[x['generator'], x['condition']], -coverage(x), x['generator'], x['condition'], x['question_id']))
        chosen.append(r)
        candidates.remove(r)
        seen.update((k, str(r.get(k))) for k in ('generator', 'condition', 'species', 'category', 'query_style'))
    return chosen


def judge_outputs():
    os.environ['RAGAS_DO_NOT_TRACK'] = 'true'
    os.environ['LANGCHAIN_TRACING_V2'] = 'false'
    manifest, rows = all_rows()
    subset = select_new_repeat(rows)
    ids = [{k: r[k] for k in ('generator', 'condition', 'question_id', 'query_style', 'category', 'species')} for r in subset]
    subset_path = OUT / 'judge_repeatability_subset.json'
    if subset_path.exists() and load_json(subset_path) != ids:
        raise ValueError('Repeatability subset changed')
    write_json(subset_path, ids)
    local_inventory()
    unload_models()
    judge, embeds = make_adapters(OUT / 'raw_evaluator_outputs.jsonl')
    metrics = make_metrics(judge, embeds)
    for m in manifest['generators']:
        name = m['name']
        if m['baseline_reuse'] or m['availability'] != 'available':
            continue
        folder = model_dir(name)
        scored = []
        for row in [r for r in rows if r['generator'] == name]:
            if m['judge_conflict']:
                result = {**row, 'metrics': {k: {'status': 'skipped', 'score': None, 'reason': 'self_judge_conflict; excluded from primary conclusions'} for k in metrics}}
            else:
                result = score_row(row, judge, metrics, stage='primary_' + slug(name), checkpoints=folder / 'judge_checkpoints.jsonl')
                result.update(contexts=row['contexts'], context_provenance=row['context_provenance'], deterministic_generation=row['deterministic_generation'])
            scored.append(result)
        # Checkpoint scores are immutable; this is a deterministic materialized view.
        write_jsonl(folder / 'scored_outputs.jsonl', scored)
    for run in (1, 2):
        scored = []
        for row in subset:
            result = score_row(row, judge, metrics, stage=f'repeat{run}_' + slug(row['generator']), checkpoints=OUT / f'repeat{run}_checkpoints.jsonl')
            scored.append(result)
        write_jsonl(OUT / f'repeat{run}.jsonl', scored)
    print(f'Judge complete; {len(subset)} new outputs repeated twice', flush=True)


def write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    with temp.open('w', encoding='utf-8', newline='\n') as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=True, allow_nan=False) + '\n')
    temp.replace(path)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['prepare', 'generate', 'judge', 'report'])
    action = parser.parse_args().action
    if action == 'report':
        from .report import report
        report()
    else:
        {'prepare': prepare, 'generate': generate, 'judge': judge_outputs}[action]()
