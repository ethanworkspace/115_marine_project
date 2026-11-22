"""Predeclared performance definitions; no quality promotion or composite score."""
from __future__ import annotations
import itertools
import statistics
from .core import MODELS, QUALITY, summary, schedule

SUSTAINED_MODELS=('gemma2:9b','qwen2.5-coder:7b')
SUSTAINED_SECONDS=1800
INTERVAL_SECONDS=300

def cold_release_reanalysis(cold,initial_gpu_bytes):
    """Audit preserved unload observations with the existing device-background proxy.

    Parent-process zeros alone cannot establish llama-server.exe allocation release.
    Original measurements remain intact; the proxy is separately identified.
    """
    rows=[]
    for r in cold:
        check=r.get('cold_verification') or {};sample=check.get('sample') or {}
        used=(sample.get('gpu') or {}).get('dedicated_used_bytes')
        absent=(r.get('runtime_allocations') or {}).get('models')==[]
        delta=used-initial_gpu_bytes if used is not None and initial_gpu_bytes is not None else None
        proxy=absent and delta is not None and delta<=64*1024**2
        rows.append(dict(model=r['model'],repetition=r['repetition'],Ollama_PS_empty=absent,
            original_verified=check.get('verified'),original_method=check.get('verification_method'),
            initial_device_background_bytes=initial_gpu_bytes,observed_device_memory_bytes=used,
            difference_from_background_bytes=delta,device_memory_proxy_supports_release=proxy,
            runner_specific_memory_available=False,original_record_modified=False))
    return dict(records=rows,all_device_proxies_pass=bool(rows) and all(r['device_memory_proxy_supports_release'] for r in rows),
        proxy_tolerance_bytes=64*1024**2,tolerance_source='Existing pre-execution unloaded_gpu_check fallback; not a performance acceptance threshold',
        limitation='Parent-only PDH readings are incomplete; PS absence and near-background device memory support model unload indirectly. OS filesystem cache retained.')

def ifr(rows,expected=None):
    total=len(rows);failed=sum(r['status']=='generation_error' or not r['final_schema_valid'] for r in rows)
    return dict(n_total=total,n_expected=expected,n_missing=(expected-total) if expected is not None else None,
        final_failed=failed,final_IFR=failed/total if total else None,
        first_pass_failed=sum(not r['first_pass_schema_valid'] for r in rows),
        first_pass_failure_rate=sum(not r['first_pass_schema_valid'] for r in rows)/total if total else None,
        retry_count=sum(r['retry_triggered'] for r in rows),retry_success=sum(r['retry_success'] for r in rows),
        retry_success_rate=sum(r['retry_success'] for r in rows)/sum(r['retry_triggered'] for r in rows) if any(r['retry_triggered'] for r in rows) else None,
        denominator='all executed formal requests, including failures; missing scheduled requests separately counted')

def cv(values):
    return statistics.pstdev(values)/statistics.fmean(values) if len(values)>1 and statistics.fmean(values)!=0 else None

def run_stability(rows):
    runs=[]
    for rep in (1,2,3):
        rs=[r for r in rows if r['repetition']==rep]
        runs.append(dict(repetition=rep,n=len(rs),IFR=ifr(rs,60),
            ttft=summary([r.get('ttft_final_answer_seconds') for r in rs]),
            TPS=summary([r.get('tokens',{}).get('runtime_tps') for r in rs]),
            latency=summary([r['retry_inclusive_latency_seconds'] for r in rs])))
    def med(k):return [r[k]['median'] for r in runs if r[k]['median'] is not None]
    return dict(runs=runs,TTFT_run_median_CV=cv(med('ttft')),TPS_run_median_CV=cv(med('TPS')),
        latency_run_median_CV=cv(med('latency')),CV_definition='population SD / mean of three run medians')

def ratios(groups,comparable):
    def ratio(key):
        a=groups['long'][key]['median'];b=groups['short'][key]['median']
        return a/b if a is not None and b else None
    return dict(long_short_median_TTFT_ratio=ratio('ttft'),long_short_median_latency_ratio=ratio('latency'),
        long_short_median_TPS_ratio=ratio('TPS') if comparable else None,TPS_semantics_comparable=comparable)

def status(rows,cold,limitations,external_interrupt=False):
    severe={f['category'] for r in rows for f in r.get('technical_failures',[])}
    if external_interrupt:return 'benchmark_incomplete'
    if severe & {'OOM','model_load_failure','context_capacity_failure'}:return 'not_feasible'
    if len(rows)!=180 or len(cold)!=3 or not all(c.get('independent_cold_start_verified') for c in cold):return 'benchmark_incomplete'
    if ifr(rows)['final_IFR'] or severe & {'runtime_crash_or_unavailable'}:return 'deployable_with_limitations'
    if any(r['retry_triggered'] for r in rows) or limitations:return 'deployable_with_limitations'
    return 'deployable_on_device'

def paired_performance(rows,iterations=10000,seed=19019):
    import numpy as np
    results={};rng=np.random.default_rng(seed)
    for a,b in itertools.combinations(MODELS,2):
        per={}
        for key in ('ttft_final_answer_seconds','retry_inclusive_latency_seconds'):
            maps=[]
            for model in (a,b):
                grouped={}
                for r in rows:
                    if r['model']==model and r.get(key) is not None:grouped.setdefault(r['question_id'],[]).append(r[key])
                maps.append({qid:statistics.median(v) for qid,v in grouped.items() if len(v)==3})
            ids=sorted(set(maps[0])&set(maps[1]));d=np.array([maps[1][q]-maps[0][q] for q in ids])
            if len(d):
                samples=d[rng.integers(0,len(d),size=(iterations,len(d)))].mean(axis=1)
                per[key]=dict(n_paired=len(ids),question_ids=ids,difference='second - first',mean_difference=float(d.mean()),CI95=list(map(float,np.quantile(samples,[.025,.975]))))
            else:per[key]=dict(n_paired=0,mean_difference=None,CI95=None)
        results[a+' vs '+b]=per
    return dict(iterations=iterations,seed=seed,per_question_aggregation='median of exactly 3 warm repetitions',
        comparison=results,interpretation='Performance only, no quality winner; invalid/missing measurements not silently imputed')
