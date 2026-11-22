"""Read evaluation progress without touching frozen inputs or invoking a model."""
import json
from collections import Counter
from pathlib import Path

root = Path(__file__).resolve().parents[1] / 'reports/evaluation/ragas/phase16'


def read(path):
    if not path.exists():
        return []
    result = []
    for line in path.read_text(encoding='utf-8').splitlines():
        try:
            result.append(json.loads(line))
        except json.JSONDecodeError:
            pass  # a live append may have an unfinished line; no metric is dropped from final reports
    return result


manifest = json.loads((root / 'experiment_manifest.json').read_text(encoding='utf-8'))
completed = read(root / 'per_question_metrics.jsonl')
checkpoints = read(root / 'metric_checkpoints.jsonl')
attempts = read(root / 'raw_evaluator_outputs.jsonl')
print(json.dumps({'status': manifest['status'], 'completed_rows': len(completed), 'target_rows': 338,
                  'completed_primary_metrics': sum(r['stage'] == 'primary' for r in checkpoints),
                  'target_primary_metrics': 990,
                  'metric_statuses': dict(Counter(r['result']['status'] for r in checkpoints if r['stage'] == 'primary')),
                  'judge_attempts': len(attempts),
                  'technical_retry_attempts': sum(r['attempt_number'] == 2 for r in attempts),
                  'repeat_run_1_rows': len(read(root / 'judge_repeat_run_1.jsonl')),
                  'repeat_run_2_rows': len(read(root / 'judge_repeat_run_2.jsonl'))}))
