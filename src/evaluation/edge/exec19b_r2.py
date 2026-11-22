"""Revision-two continuity and reporting contracts. Evaluation only."""
from __future__ import annotations
import statistics
from .core import summary


def valid_block(block, question_ids):
    return bool(block.get('completed') and block.get('runtime_valid') and
                block.get('question_ids') == list(question_ids) and
                block.get('relevant_policy_blocks', 0) == 0)


def primary_rows(rows, blocks, question_ids):
    accepted = {b['run_id'] for b in blocks if valid_block(b, question_ids)}
    return [r for r in rows if r['run_id'] in accepted and r.get('stage') == 'formal']


def restart_plan(previous_run_id, preflight_pass):
    return dict(allowed=bool(preflight_pass), previous_run_id=previous_run_id,
                start_question_position=0 if preflight_pass else None,
                new_run_id_required=True, partial_primary_data_reused=False)


def residency_changes(before, after, seen, generator_load_ms=None):
    def models(value):
        return {m.get('name', m.get('model')): m for m in value.get('models', [])}
    a, b = models(before), models(after)
    loaded = sorted(set(b) - set(a)); removed = sorted(set(a) - set(b))
    return dict(model_load=loaded, model_reload=[m for m in loaded if m in seen],
        model_eviction=removed, eviction_semantics='Previously observed model absent from later /api/ps; internal cause unknown',
        GPU_offload_change=[m for m in set(a) & set(b) if a[m].get('size_vram') != b[m].get('size_vram')],
        CPU_fallback=None, shared_memory_spill=None,
        generator_runtime_load_duration_ms=generator_load_ms)


def latency_comparison(current, historical):
    return dict(current=current, historical=historical,
        difference_ms=current['median'] - historical['median'] if current.get('median') is not None and historical.get('median') is not None else None,
        interpretation='Cross-phase descriptive comparison; difference is not exclusively retrieval overhead')


def request_summary(rows):
    fields=('bm25_ms','dense_embedding_ms','dense_search_ms','rrf_ms','reranker_ms',
            'context_assembly_ms','retrieval_to_context_ms','generator_load_reload_ms',
            'generator_ttft_any_ms','generator_ttft_final_ms','generation_completion_ms',
            'e2e_ttft_final_ms','e2e_total_latency_ms')
    failed=sum(bool(r.get('final_failed')) for r in rows)
    return dict(n_total=len(rows), final_failed=failed, final_IFR=failed/len(rows) if rows else None,
        retrieval_IFR=sum(bool(r.get('retrieval_failed')) for r in rows)/len(rows) if rows else None,
        generation_IFR=sum(bool(r.get('generation_failed')) for r in rows)/len(rows) if rows else None,
        metrics={k:summary([r.get(k) for r in rows], len(rows)) for k in fields})


def cv(values):
    values=[v for v in values if v is not None]
    return statistics.pstdev(values)/statistics.fmean(values) if len(values)>1 and statistics.fmean(values) else None
