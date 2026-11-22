"""Evaluation-only Phase 19B gates and metric contracts; no production imports."""
from __future__ import annotations

import copy
import datetime as dt
import math
import time
from contextlib import contextmanager
from typing import Any

MODELS = ('gemma2:9b', 'qwen2.5-coder:7b')
CONDITIONS = ('R0_edge_retrieval_only', 'F1_edge_fullrag_gemma', 'F2_edge_fullrag_qwen')
STAGES = ('bm25_ms', 'dense_query_embedding_ms', 'dense_search_ms', 'rrf_ms',
          'reranker_ms', 'context_assembly_ms')


def utc_now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def schedule():
    orders = ((0, 1, 2), (2, 0, 1), (1, 2, 0))
    return [{'repetition': r, 'condition': CONDITIONS[i]} for r, order in enumerate(orders, 1) for i in order]


def runtime_gate(probe):
    """CUDA is mandatory. A failure never authorizes a CPU/model fallback."""
    return bool(probe.get('torch_import') and probe.get('cuda_available') and
                probe.get('model_loaded') and probe.get('single_pair_finite') and
                probe.get('ten_query_count') == 10 and probe.get('pairs_scored') == 500 and
                probe.get('all_scores_finite') and probe.get('candidate_ids_preserved'))


def compare_top5(expected, actual):
    if len(expected) != 5:
        raise ValueError('Frozen reference must contain exactly five retrieval chunks')
    return {'match': list(expected) == list(actual), 'expected': list(expected), 'actual': list(actual)}


def reproduction_gate(expected_by_id, actual_by_id):
    if set(expected_by_id) != set(actual_by_id):
        return {'retrieval_reproducibility_pass': False, 'reason': 'question_ID_mismatch'}
    diffs = [{'question_id': qid, **compare_top5(ids, actual_by_id[qid])}
             for qid, ids in expected_by_id.items() if ids != actual_by_id[qid]]
    return {'retrieval_reproducibility_pass': len(expected_by_id) == 60 and not diffs,
            'questions_checked': len(expected_by_id), 'mismatch_count': len(diffs), 'differences': diffs}


def frozen_context_check(expected, actual):
    fields = ('context_id', 'chunk_id', 'document_id', 'page', 'text')
    if len(expected) != 5 or len(actual) != 5:
        return False
    return all(all(e.get(k) == a.get(k) for k in fields) for e, a in zip(expected, actual))


class StageTimers:
    def __init__(self, clock=time.perf_counter):
        self.clock, self.values = clock, {}

    @contextmanager
    def stage(self, name):
        if name not in STAGES:
            raise ValueError('Unknown retrieval stage')
        started = self.clock()
        try:
            yield
        finally:
            self.values[name] = (self.clock() - started) * 1000

    def retrieval_to_context_ms(self):
        if any(k not in self.values for k in STAGES):
            raise ValueError('Every retrieval stage must be measured')
        return sum(self.values[k] for k in STAGES)


def e2e_ttft_ms(accepted_monotonic, events):
    """First content-channel structured-answer token; native thinking is excluded."""
    for event in events:
        if event.get('content'):
            return (event['monotonic'] - accepted_monotonic) * 1000
    return None


def ifr(rows):
    """Include every formal request, including failed requests, in the denominator."""
    failed = sum(bool(r.get('final_failed')) for r in rows)
    retrieval_failed = sum(bool(r.get('retrieval_failed')) for r in rows)
    generation_failed = sum(bool(r.get('generation_failed')) for r in rows)
    return dict(n_total=len(rows), n_failed=failed, final_IFR=failed / len(rows) if rows else None,
                retrieval_IFR=retrieval_failed / len(rows) if rows else None,
                generation_IFR=generation_failed / len(rows) if rows else None)


def residency_record(node, sample):
    if node not in ('request_start', 'after_dense', 'after_reranker', 'before_generator', 'after_generator'):
        raise ValueError('Unknown residency node')
    # Observations do not justify inferred eviction, fallback or spill labels.
    return {'node': node, 'observations': copy.deepcopy(sample), 'model_eviction': None,
            'model_reload': None, 'cpu_fallback': None, 'shared_memory_spill': None}


def process_roles(processes, benchmark_pid, reranker_pid=None):
    """Identify server, actual llama-server runners and descendants explicitly."""
    selected = {}
    for p in processes:
        name = p['name'].casefold()
        roles = []
        if p['pid'] == benchmark_pid:
            roles.append('benchmark_runner')
        if p['pid'] == reranker_pid:
            roles.append('reranker_python')
        if name.startswith('ollama'):
            roles.append('ollama_server_or_launcher')
        if name in ('llama-server.exe', 'llama-server', 'ollama_llama_server.exe'):
            roles.append('ollama_model_runner')
        if roles:
            selected[p['pid']] = {**p, 'roles': roles}
    changed = True
    while changed:
        changed = False
        for p in processes:
            if p['pid'] not in selected and p.get('parent_pid') in selected:
                selected[p['pid']] = {**p, 'roles': ['descendant_of_observed_runtime']}
                changed = True
    return list(selected.values())


def sustained_gate(rows):
    expected = {(r, q) for r in range(1, 4) for q in range(60)}
    keys = {(r.get('repetition'), r.get('question_position')) for r in rows}
    return len(rows) == 180 and keys == expected and not any(r.get('OOM') or r.get('runtime_crash') for r in rows)


def hardware_status(rows, reproduction_pass, context_fits=True):
    if any(r.get('OOM') or r.get('cannot_load') or r.get('context_capacity_failure') for r in rows):
        return 'not_feasible'
    if not sustained_gate(rows) or not reproduction_pass:
        return 'benchmark_incomplete'
    if context_fits and ifr(rows)['final_IFR'] == 0 and not any(r.get('limitations') or r.get('retry_triggered') for r in rows):
        return 'deployable_on_device'
    return 'deployable_with_limitations'


def split_readiness(hardware_by_model, *, independent_judge_ready=False, human_review_complete=False,
                    qwen_quality_unresolved=True):
    feasible = any(hardware_by_model.get(m) in ('deployable_on_device', 'deployable_with_limitations') for m in MODELS)
    return {'phase20_research_integration_ready': feasible,
            'final_model_selection_ready': bool(feasible and independent_judge_ready and human_review_complete and
                                               not qwen_quality_unresolved)}


def finite_scores(scores, expected):
    return len(scores) == expected and all(math.isfinite(float(s)) for s in scores)
