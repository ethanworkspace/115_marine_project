"""Dependency-light pairing, cohorts, statistics and failure-preserving summaries."""
from __future__ import annotations

import math
import random
import statistics
from collections import Counter, defaultdict
from typing import Any

METRICS = ('faithfulness', 'answer_relevancy', 'silver_reference_correctness')
CONDITIONS = ('oracle', 'e4_top5')
LOW_THRESHOLDS = {name: 0.5 for name in METRICS}
SEED = 16016
ITERATIONS = 10000


def pair_inputs(rows: list[dict], expected_count: int | None = 169) -> dict[str, dict[str, dict]]:
    paired: dict[str, dict[str, dict]] = defaultdict(dict)
    for row in rows:
        condition = row.get('condition')
        qid = row.get('question_id')
        if condition not in CONDITIONS or not qid:
            raise ValueError('Unknown condition or missing question_id')
        if row.get('benchmark_type') != 'silver' or row.get('silver_reference') is not True:
            raise ValueError('Only explicitly labelled Silver references are supported')
        if condition in paired[qid]:
            raise ValueError(f'Duplicate paired input {qid}/{condition}')
        if not isinstance(row.get('contexts'), list) or not all(isinstance(x, str) and x for x in row['contexts']):
            raise ValueError('Invalid contexts')
        paired[qid][condition] = row
    if expected_count is not None and len(paired) != expected_count:
        raise ValueError(f'Expected {expected_count} paired questions, found {len(paired)}')
    allowed_difference = {'condition', 'answer', 'contexts', 'generation_attempts', 'final_output_source'}
    for qid, conditions in paired.items():
        if set(conditions) != set(CONDITIONS):
            raise ValueError(f'Unpaired question {qid}')
        a, b = conditions['oracle'], conditions['e4_top5']
        for key in (set(a) | set(b)) - allowed_difference:
            if a.get(key) != b.get(key):
                raise ValueError(f'Unexpected paired difference: {qid}/{key}')
    return dict(paired)


def answered_only(rows: list[dict]) -> list[dict]:
    return [r for r in rows if r.get('status') == 'answered']


def quantile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    values = sorted(values)
    index = (len(values) - 1) * p
    lo, hi = math.floor(index), math.ceil(index)
    return values[lo] + (values[hi] - values[lo]) * (index - lo)


def bootstrap(values: list[float], iterations: int = ITERATIONS, seed: int = SEED) -> dict:
    if not values:
        return {'mean': None, 'ci95': [None, None], 'n': 0, 'iterations': iterations, 'seed': seed}
    rng = random.Random(seed)
    n = len(values)
    means = [sum(values[rng.randrange(n)] for _ in range(n)) / n for _ in range(iterations)]
    return {'mean': statistics.fmean(values), 'ci95': [quantile(means, .025), quantile(means, .975)],
            'n': n, 'iterations': iterations, 'seed': seed,
            'interpretation': 'Uncertainty within this AI-generated Silver benchmark sample only'}


def valid_score(record: dict) -> bool:
    value = record.get('score')
    return record.get('status') == 'valid' and isinstance(value, (float, int)) and not isinstance(value, bool) and math.isfinite(value)


def metric_summary(rows: list[dict], metric: str, *, ci: bool = True) -> dict:
    eligible = answered_only(rows)
    values = [float(r['metrics'][metric]['score']) for r in eligible if valid_score(r.get('metrics', {}).get(metric, {}))]
    failed = [r for r in eligible if r.get('metrics', {}).get(metric, {}).get('status') == 'failed']
    pending = [r for r in eligible if r.get('metrics', {}).get(metric, {}).get('status') not in {'valid', 'failed', 'skipped'}]
    skipped = [r for r in eligible if r.get('metrics', {}).get(metric, {}).get('status') == 'skipped']
    return {'metric': metric, 'judge_based': True, 'cohort': 'answered_only',
            'n_all_questions': len(rows), 'n_total': len(eligible), 'n_valid': len(values),
            'n_failed': len(failed), 'n_pending': len(pending), 'n_skipped': len(skipped),
            'n_abstained_excluded': len(rows) - len(eligible),
            'mean': statistics.fmean(values) if values else None,
            'median': statistics.median(values) if values else None,
            'std': statistics.stdev(values) if len(values) > 1 else (0.0 if values else None),
            'bootstrap': bootstrap(values) if ci else None,
            'failure_reasons': dict(Counter(r['metrics'][metric].get('failure_reason', 'unknown') for r in failed)),
            'reference_note': 'AI-generated Silver reference; not human expert correctness' if metric == METRICS[2] else None}


def summarize(rows: list[dict], *, ci: bool = True) -> dict:
    return {'benchmark_type': 'silver', 'generation_source': 'corpus_grounded_ai',
            'n_questions': len(rows), 'status_counts': dict(Counter(r['status'] for r in rows)),
            'answered_rate': len(answered_only(rows)) / len(rows) if rows else None,
            'abstention_rate': sum(r['status'] == 'insufficient_evidence' for r in rows) / len(rows) if rows else None,
            'metrics': {m: metric_summary(rows, m, ci=ci) for m in METRICS},
            'interpretation': 'Judge-based metrics on AI-generated Silver answers; no composite score'}


def paired_comparison(rows: list[dict]) -> dict:
    by_key = {(r['question_id'], r['condition']): r for r in rows}
    ids = sorted({r['question_id'] for r in rows})
    result = {}
    for metric in METRICS:
        differences, valid_ids = [], []
        for qid in ids:
            a, b = by_key.get((qid, 'oracle')), by_key.get((qid, 'e4_top5'))
            if a and b and a['status'] == b['status'] == 'answered':
                ra, rb = a.get('metrics', {}).get(metric, {}), b.get('metrics', {}).get(metric, {})
                if valid_score(ra) and valid_score(rb):
                    differences.append(rb['score'] - ra['score'])
                    valid_ids.append(qid)
        result[metric] = {**bootstrap(differences), 'direction': 'G1 - G0', 'paired_question_ids': valid_ids,
                          'n_excluded_pairs': len(ids) - len(valid_ids), 'cohort': 'both answered with valid metric scores'}
    return result


def retrieval_split(rows: list[dict]) -> dict:
    e4 = [r for r in rows if r['condition'] == 'e4_top5']
    hit = [r for r in e4 if r['required_evidence_complete_in_top5']]
    miss = [r for r in e4 if not r['required_evidence_complete_in_top5']]
    return {'hit': summarize(hit), 'miss': summarize(miss),
            'hit_and_answered': summarize(answered_only(hit)),
            'miss_question_ids': [r['question_id'] for r in miss],
            'interpretation': 'Observational diagnostic; incomplete required evidence does not establish hallucination or causality'}


def error_labels(row: dict, thresholds: dict[str, float] = LOW_THRESHOLDS) -> list[str]:
    labels = []
    hit = row['required_evidence_complete_in_top5']
    answered = row['status'] == 'answered'
    if row['condition'] == 'e4_top5' and not hit:
        labels.append('retrieval_miss')
        if answered:
            labels.append('answered_without_required_evidence')
    if hit and not answered:
        labels.append('false_abstention_candidate')
    names = {'faithfulness': 'retrieval_hit_generation_low_faithfulness',
             'answer_relevancy': 'retrieval_hit_low_relevance',
             'silver_reference_correctness': 'retrieval_hit_low_reference_correctness'}
    for metric, record in row.get('metrics', {}).items():
        if record.get('status') == 'failed':
            labels.append('judge_evaluation_failure')
        elif hit and answered and metric in thresholds and valid_score(record) and record['score'] < thresholds[metric]:
            labels.append(names[metric])
    if row.get('citation_failure'):
        labels.append('citation_failure')
    return sorted(set(labels))


def repeatability(a: list[dict], b: list[dict]) -> dict:
    left = {(r['question_id'], r['condition']): r for r in a}
    right = {(r['question_id'], r['condition']): r for r in b}
    if set(left) != set(right):
        raise ValueError('Judge repeatability row identities differ')
    result = {}
    for metric in METRICS:
        pairs = []
        for key in sorted(left):
            x, y = left[key].get('metrics', {}).get(metric, {}), right[key].get('metrics', {}).get(metric, {})
            if valid_score(x) and valid_score(y):
                pairs.append((x['score'], y['score']))
        xs, ys = [x for x, y in pairs], [y for x, y in pairs]
        corr = None
        if len(pairs) >= 2 and statistics.pstdev(xs) > 0 and statistics.pstdev(ys) > 0:
            corr = statistics.correlation(xs, ys)
        result[metric] = {'n_total': len(left), 'n_valid_pairs': len(pairs), 'n_failed_or_skipped_pairs': len(left) - len(pairs),
                          'exact_agreement': sum(x == y for x, y in pairs) / len(pairs) if pairs else None,
                          'mean_absolute_difference': statistics.fmean(abs(x - y) for x, y in pairs) if pairs else None,
                          'pearson_correlation': corr, 'categorical_agreement': None,
                          'categorical_note': 'Continuous metric; no artificial categorical agreement reported'}
    return result


def select_repeat_subset(rows: list[dict], per_condition: int = 15) -> list[dict]:
    # Deterministic coverage-first selection, without looking at metric scores.
    result = []
    for condition in CONDITIONS:
        candidates = sorted((r for r in answered_only(rows) if r['condition'] == condition), key=lambda r: r['question_id'])
        seen: set[tuple[str, str]] = set()
        chosen = []
        while candidates and len(chosen) < per_condition:
            def new_coverage(r):
                return sum((key, str(r.get(key) or 'unknown')) not in seen for key in ('species', 'category', 'query_style'))
            row = sorted(candidates, key=lambda r: (-new_coverage(r), r['question_id']))[0]
            chosen.append(row)
            candidates.remove(row)
            seen.update((key, str(row.get(key) or 'unknown')) for key in ('species', 'category', 'query_style'))
        if len(chosen) != per_condition:
            raise ValueError('Insufficient answered questions for fixed repeatability sample')
        result.extend(chosen)
    return result
