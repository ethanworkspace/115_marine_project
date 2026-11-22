"""Fixed cohorts and dependency-light comparison functions."""
from __future__ import annotations

import math
import statistics
from itertools import combinations

from ..ragas_eval.core import METRICS, bootstrap, valid_score

SEED = 17017
ITERATIONS = 10000
COMMON_OPTIONS = dict(temperature=0, top_p=1.0, seed=15015, num_predict=1024, num_ctx=8192)
CONDITIONS = ('oracle', 'e4_top5')


def judge_conflict(generator: dict, judge: dict) -> bool:
    return bool(generator.get('digest') and generator['digest'] == judge.get('model_digest'))


def validate_manifest(manifest: dict) -> None:
    names = [m['name'] for m in manifest['generators']]
    if len(names) != len(set(names)) or 'gemma2:9b' not in names:
        raise ValueError('Duplicate candidates or missing frozen Gemma baseline')
    if manifest['generation_options'] != COMMON_OPTIONS:
        raise ValueError('Generation configuration changed')
    if manifest['question_count'] != 169 or manifest['maximum_attempts'] != 2:
        raise ValueError('Frozen question count or retry limit changed')
    for model in manifest['generators']:
        if model['availability'] == 'available' and not model.get('digest'):
            raise ValueError('Available generator must have a digest')
        if model.get('generation_options', COMMON_OPTIONS) != COMMON_OPTIONS:
            raise ValueError('Per-model generation configuration changed')


def assert_same_inputs(left: list[dict], right: list[dict]) -> None:
    keys = ('question_id', 'condition', 'question', 'contexts', 'context_provenance', 'reference_answer')
    a = {(r['question_id'], r['condition']): r for r in left}
    b = {(r['question_id'], r['condition']): r for r in right}
    if len(a) != len(left) or len(b) != len(right) or set(a) != set(b):
        raise ValueError('Question identities differ or duplicate')
    for identity in a:
        if any(a[identity].get(k) != b[identity].get(k) for k in keys):
            raise ValueError(f'Frozen prompt/context input differs: {identity}')


def scalar(row: dict, metric: str):
    if metric in METRICS:
        rec = row.get('metrics', {}).get(metric, {})
        return rec['score'] if row['status'] == 'answered' and valid_score(rec) else None
    d = row['deterministic_generation']
    if metric == 'silver_token_f1':
        return (d.get('silver_reference_similarity') or {}).get('f1') if row['status'] == 'answered' else None
    if metric == 'citation_recall':
        # All-question required-chunk recall, fixed denominator; failure/abstention is 0.
        return d['required_evidence_citation']['strict_recall_all_questions'] if row['status'] == 'answered' else 0.0
    if metric == 'abstention':
        return float(row['status'] == 'insufficient_evidence')
    raise ValueError('Unknown metric: ' + metric)


def pair_compare(left: list[dict], right: list[dict], *, primary_judge: bool = True) -> dict:
    a, b = ({r['question_id']: r for r in rows} for rows in (left, right))
    if len(a) != len(left) or len(b) != len(right) or set(a) != set(b):
        raise ValueError('Cross-model question IDs differ')
    result = {}
    for metric in (*METRICS, 'silver_token_f1', 'citation_recall', 'abstention'):
        if metric in METRICS and not primary_judge:
            result[metric] = dict(status='excluded_judge_conflict', n=0, mean=None, ci95=[None, None])
            continue
        pairs = [(qid, scalar(a[qid], metric), scalar(b[qid], metric)) for qid in sorted(a)]
        valid = [(qid, x, y) for qid, x, y in pairs if x is not None and y is not None]
        values = [y - x for _, x, y in valid]
        ci = bootstrap(values, iterations=ITERATIONS, seed=SEED)
        result[metric] = {**ci, 'direction': 'right - left', 'question_ids': [q for q, _, _ in valid],
                          'n_excluded': len(a) - len(valid),
                          'clearly_separated_on_silver_sample': bool(values) and (ci['ci95'][0] > 0 or ci['ci95'][1] < 0),
                          'cohort': 'both answered and valid' if metric != 'citation_recall' and metric != 'abstention' else 'all matched questions'}
    return result


def stats(values: list) -> dict:
    v = sorted(float(x) for x in values if isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x))
    from ..ragas_eval.core import quantile
    return dict(n=len(v), mean=statistics.fmean(v) if v else None,
                median=statistics.median(v) if v else None, p95=quantile(v, .95),
                min=min(v) if v else None, max=max(v) if v else None)


def total_latency_or_none(values: list):
    """Unknown attempt duration makes total duration unknown, never zero."""
    if not values or any(not isinstance(v, (int, float)) or isinstance(v, bool)
                         or not math.isfinite(v) or v < 0 for v in values):
        return None
    return sum(values)


def pareto(points: list[dict], axes: dict[str, str]) -> dict:
    """Descriptive point-estimate frontier; never a weighted composite or final selection."""
    eligible = [p for p in points if p.get('primary_eligible') and all(isinstance(p.get(k), (int, float)) and math.isfinite(p[k]) for k in axes)]
    def dominates(a, b):
        signs = {k: 1 if direction == 'max' else -1 for k, direction in axes.items()}
        return all(signs[k] * a[k] >= signs[k] * b[k] for k in axes) and any(signs[k] * a[k] > signs[k] * b[k] for k in axes)
    return {'axes': axes, 'non_dominated': [p['generator'] for p in eligible if not any(dominates(q, p) for q in eligible)],
            'excluded': [p['generator'] for p in points if p not in eligible],
            'interpretation': 'Descriptive point estimates; no composite score, confidence dominance, or automatic model winner'}
