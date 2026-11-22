"""Validate completed local judge outputs without rescoring frozen answers."""
import hashlib
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.evaluation.ragas_eval.runner import load_rows
from src.evaluation.ragas_eval.runtime import JUDGE_MODEL, JUDGE_DIGEST, OPTIONS, sha_text
from src.evaluation.ragas_eval.core import METRICS

PHASE = ROOT / 'reports/evaluation/ragas/phase16'
read = lambda p: [json.loads(line) for line in p.read_text(encoding='utf-8').splitlines() if line]
manifest = json.loads((PHASE / 'experiment_manifest.json').read_text(encoding='utf-8'))
evaluator = json.loads((PHASE / 'evaluator_manifest.json').read_text(encoding='utf-8'))
assert manifest['status'] == 'completed'
assert evaluator['judge_model'] == JUDGE_MODEL and evaluator['model_digest'] == JUDGE_DIGEST
assert evaluator['generation_parameters'] == OPTIONS
sources, hashes = load_rows()
assert manifest['input_hashes'] == hashes
records = read(PHASE / 'per_question_metrics.jsonl')
expected = {(r['condition'], r['question_id']): r for r in sources}
actual = {(r['condition'], r['question_id']): r for r in records}
assert len(records) == len(actual) == len(expected) == 338
assert set(actual) == set(expected)
statuses = Counter()
for key, r in actual.items():
    original = expected[key]
    for field in ('question', 'answer', 'reference_answer', 'status'):
        assert r[field] == original[field]
    assert set(r['metrics']) == set(METRICS)
    for metric, value in r['metrics'].items():
        statuses[value['status']] += 1
        if r['status'] == 'answered':
            assert value['status'] in {'valid', 'failed'}
            if value['status'] == 'valid':
                assert math.isfinite(value['score'])
        else:
            assert value['status'] == 'not_applicable' and value['score'] is None

traces = read(PHASE / 'raw_evaluator_outputs.jsonl')
groups = defaultdict(list)
for row in traces:
    assert row['raw_output_sha256'] == sha_text(row['raw_output'])
    assert row['prompt_sha256'] == sha_text(row['prompt'])
    if row.get('raw_response'):
        assert row['raw_response']['model'] == JUDGE_MODEL
    payload = {'model': JUDGE_MODEL, 'messages': [{'role': 'user', 'content': row['prompt']}],
               'format': row['output_schema'], 'stream': False, 'think': False,
               'keep_alive': '30m', 'options': OPTIONS}
    assert row['request_sha256'] == sha_text(json.dumps(payload, sort_keys=True))
    key = tuple(row[k] for k in ('stage', 'condition', 'question_id', 'metric', 'call_id', 'sample_index'))
    groups[key].append(row)
for attempts in groups.values():
    assert [r['attempt_number'] for r in attempts] in ([1], [1, 2])
    assert len({r['request_sha256'] for r in attempts}) == 1

repeat_keys = {(r['condition'], r['question_id']) for r in manifest['repeatability_subset']}
assert len(repeat_keys) == 30
for number in (1, 2):
    repeat = read(PHASE / f'judge_repeat_run_{number}.jsonl')
    assert len(repeat) == 30
    assert {(r['condition'], r['question_id']) for r in repeat} == repeat_keys

result = {'status': 'valid', 'frozen_rows_verified': 338, 'conditions_paired': 169,
          'metric_statuses': dict(statuses), 'repeatability_rows_per_run': 30,
          'judge': JUDGE_MODEL, 'judge_digest': JUDGE_DIGEST, 'mixed_judge_scores': False,
          'raw_attempt_count': len(traces), 'raw_checksums_valid': True,
          'request_parameters_valid': True, 'retry_policy_valid': True,
          'technical_retry_attempts': sum(r['attempt_number'] == 2 for r in traces),
          'attempt_failures': dict(Counter(r['failure_reason'] for r in traces if r.get('failure_reason'))),
          'new_answer_generation': False, 'research_note': 'AI-generated Silver; local judge-based evaluation'}
(PHASE / 'execution_validation.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
print(json.dumps(result))
