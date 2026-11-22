"""Reports from preserved physical-device requests, never retrieval or judge calls."""
from __future__ import annotations
import json
import statistics
from collections import Counter,defaultdict
from pathlib import Path
from .core import MODELS,QUALITY,summary,pareto
from .analysis19a import ifr,run_stability,ratios,status,paired_performance,cold_release_reanalysis,SUSTAINED_MODELS
from .runner import read_rows
from .execution19a import OUT,write
from .report import reliability,validate_results

def safe_rate(a,b):return a/b if b else None
def samples(rows):return [s for r in rows for s in r.get('telemetry',{}).get('samples',[])]
def measured_summary(ss,key):return summary([s.get(key) for s in ss])

def hardware_summary(rows):
    return hardware_samples_summary(samples(rows))

def hardware_samples_summary(ss):
    gps=[s['gpu'] for s in ss if s.get('gpu')]
    pids=defaultdict(list);adapter_shared=defaultdict(list);gpu_process=defaultdict(list)
    for s in ss:
        for p in s.get('ollama_process_working_sets') or []:
            pids[(p['pid'],p['name'])].append(p.get('working_set_bytes'))
        for p in s.get('shared_GPU_memory') or []:adapter_shared[p['instance']].append(p['value_bytes'])
        for scope,items in (s.get('GPU_process_memory') or {}).items():
            for p in items or []:gpu_process[(scope,p['instance'])].append(p['value_bytes'])
    return dict(system_RAM_used_bytes=measured_summary(ss,'system_RAM_used_bytes'),
        dedicated_GPU_used_bytes=summary([g.get('dedicated_used_bytes') for g in gps]),
        Ollama_process_working_sets=[dict(pid=p[0],name=p[1],working_set_bytes=summary(v)) for p,v in pids.items()],
        shared_GPU_memory_by_adapter={k:summary(v) for k,v in adapter_shared.items()},
        Ollama_GPU_process_memory=[dict(kind=k[0],instance=k[1],bytes=summary(v)) for k,v in gpu_process.items()],
        GPU_board_power_watts=summary([g.get('gpu_board_power_watts') for g in gps]),
        GPU_temperature_c=summary([g.get('temperature_c') for g in gps]),
        GPU_graphics_clock_MHz=summary([g.get('graphics_clock_mhz') for g in gps]),
        GPU_utilization_percent=summary([g.get('utilization_percent') for g in gps]),
        CPU_utilization_percent=measured_summary(ss,'CPU_utilization_percent'),
        peak_is_sampled=True,sample_interval_seconds=2,
        scopes={'RAM':'whole-system used, not benchmark process','working_set':'individual Ollama processes; never summed as private memory',
            'dedicated_VRAM':'whole GPU device, includes Windows/background allocations','shared_GPU':'WDDM per-adapter RAM-backed usage, separate from dedicated VRAM',
            'GPU_process_memory':'Only recorded ollama-prefixed parent process instances; llama-server.exe runner not captured','power':'GPU board only'},
        process_memory_coverage='partial: process-name filter omitted llama-server.exe',
        runner_process_working_set_available=False,model_process_specific_RAM_peak=None,model_process_specific_VRAM_peak=None,
        power_metrics_available=any(g.get('gpu_board_power_watts') is not None for g in gps))

def citation_and_behavior(rows):
    all_den=all_num=present_den=present_num=answered_den=answered_num=0
    for r in rows:
        e=r['result']['required_evidence_citation']
        all_den+=e['required_chunk_count_all_questions'];all_num+=e['strict_cited_required_chunk_count']
        present_den+=e['required_chunk_count_present'];present_num+=e.get('strict_cited_required_chunk_count_present',0)
        if r['status']=='answered' and e['all_required_evidence_present']:
            answered_den+=e['required_chunk_count_present'];answered_num+=e.get('strict_cited_required_chunk_count_present_and_answered',0)
    behavior={k:summary([r['behavior'].get(k) for r in rows]) for k in ('normalized_answer_similarity','citation_set_jaccard')}
    behavior.update({k:safe_rate(sum(r['behavior'].get(k) is True for r in rows),len(rows)) for k in ('status_agreement','schema_agreement','citation_set_exact')})
    numeric=[dict(question_id=r['question_id'],repetition=r['repetition'],
        **r['result']['calculation_numeric_evaluation']) for r in rows if r['result'].get('calculation_numeric_evaluation') is not None]
    return dict(required_evidence_citation_recall={'A_all_questions':dict(numerator=all_num,denominator=all_den,rate=safe_rate(all_num,all_den)),
        'B_evidence_present':dict(numerator=present_num,denominator=present_den,rate=safe_rate(present_num,present_den)),
        'C_evidence_present_answered':dict(numerator=answered_num,denominator=answered_den,rate=safe_rate(answered_num,answered_den))},
        Silver_token_F1=summary([(r['result'].get('silver_reference_similarity') or {}).get('f1') for r in rows]),
        calculation_numeric_results=numeric,behavior=behavior,
        reference_generator='Gemma 2 9B',reference_alignment_bias_possible=True,human_validation_available=False,
        interpretation='Behavior preservation against frozen Phase 17 outputs, not human correctness')

def request_stats(rows):
    return dict(n=len(rows),ttft_any=summary([r.get('ttft_any_token_seconds') for r in rows]),
        ttft=summary([r.get('ttft_final_answer_seconds') for r in rows]),
        TPS=summary([r.get('tokens',{}).get('runtime_tps') for r in rows]),
        visible_TPS=summary([r.get('tokens',{}).get('visible_answer_tps') for r in rows]),
        latency=summary([r.get('retry_inclusive_latency_seconds') for r in rows]),
        request_latency=summary([r.get('total_request_latency_seconds') for r in rows]),
        prompt_eval_seconds=summary([r.get('runtime_times',{}).get('prompt_eval_duration',0)/1e9 if r.get('runtime_times',{}).get('prompt_eval_duration') is not None else None for r in rows]),
        generation_seconds=summary([r.get('runtime_times',{}).get('eval_duration',0)/1e9 if r.get('runtime_times',{}).get('eval_duration') is not None else None for r in rows]),
        IFR=ifr(rows),reliability=reliability(rows,len(rows)),hardware=hardware_summary(rows))

def telemetry_interval(telemetry,begin,index):
    """Half-open time windows; long requests never shift sensor samples to their start bucket."""
    if begin is None:return []
    lo=begin+index*300;hi=lo+300
    return [s for s in telemetry if isinstance(s.get('timestamp'),(int,float)) and lo<=s['timestamp']<hi]

def sustained_report(rows,completions,telemetry=None):
    result={}
    for model in MODELS:
        if model not in SUSTAINED_MODELS:
            result[model]=dict(executed=False,reason='Predeclared low-priority diagnostic candidate excluded from sustained workload');continue
        rs=[r for r in rows if r['model']==model];intervals=[]
        begin=rs[0]['sustained_start_monotonic'] if rs else None
        measured=telemetry if telemetry is not None else list({s['timestamp']:s for s in samples(rs)}.values())
        for i in range(6):
            sub=[r for r in rs if r['interval_index']==i]
            stats=request_stats(sub);window=telemetry_interval(measured,begin,i)
            stats['hardware']=hardware_samples_summary(window)
            intervals.append(dict(index=i,start_seconds=i*300,end_seconds=(i+1)*300,
                sensor_sample_count=len(window),request_assignment='request start time',
                telemetry_assignment='sensor timestamp in half-open interval',**stats))
        first=intervals[0];last=intervals[-1]
        def delta(k,path='median'):
            a=first[k][path];b=last[k][path];return b-a if a is not None and b is not None else None
        def ratio(k):
            a=first[k]['median'];b=last[k]['median'];return b/a if a and b is not None else None
        completion=next((c for c in completions if c['model']==model),None)
        hs=[i['hardware'] for i in intervals]
        def memory_change(k):
            a=hs[0][k]['median'];b=hs[-1][k]['median'];return b-a if a is not None and b is not None else None
        duration=completion['actual_seconds'] if completion else 1800
        model_samples=[s for s in measured if begin is not None and begin<=s.get('timestamp',-1)<begin+duration]
        gpu=[s['gpu'] for s in model_samples if s.get('gpu')]
        whole=request_stats(rs);whole['hardware']=hardware_samples_summary(model_samples)
        result[model]=dict(executed=bool(rs),completion=completion,intervals=intervals,
            overall=whole,sensor_sample_count=len(model_samples),
            start_temperature_C=gpu[0].get('temperature_c') if gpu else None,
            end_temperature_C=gpu[-1].get('temperature_c') if gpu else None,
            peak_temperature_C=whole['hardware']['GPU_temperature_c']['max'],
            thermal_throttling_flag=None,
            graphics_clock_start_MHz=gpu[0].get('graphics_clock_mhz') if gpu else None,
            graphics_clock_end_MHz=gpu[-1].get('graphics_clock_mhz') if gpu else None,
            TTFT_median_drift_seconds=delta('ttft'),latency_median_drift_seconds=delta('latency'),TPS_last_first_ratio=ratio('TPS'),
            TPS_last_first_percent_change=(ratio('TPS')-1)*100 if ratio('TPS') is not None else None,
            RAM_median_growth_bytes=memory_change('system_RAM_used_bytes'),VRAM_median_growth_bytes=memory_change('dedicated_GPU_used_bytes'),
            GPU_temperature_median_drift_C=memory_change('GPU_temperature_c'),
            interpretation='Requests grouped by start time; sensors grouped by actual timestamp. Last request may finish past 1800 seconds, included in overall but not the six fixed sensor windows. Intervals differ in question mix; descriptive drift, not causal throttling or memory-leak proof.')
    return result

def compile_all():
    manifest=json.loads((OUT/'experiment_manifest.json').read_text(encoding='utf-8'))
    rows=read_rows(OUT/'warm_runs.jsonl');cold=read_rows(OUT/'cold_starts.jsonl')
    validate_results(rows,cold,manifest['question_ids'])
    ttft={};tps={};lat={};mem={};power={};thermal={};fail={};rel={};ctx={};stability={};behavior={};matrix=[]
    interrupted=(OUT/'execution_interruption.json').exists() and not (OUT/'execution_recovery_completed.json').exists()
    placements_all=read_rows(OUT/'model_placement.jsonl')
    thermal_starts=read_rows(OUT/'thermal_start_conditions.jsonl')
    initial_idle=json.loads((OUT/'execution_start.json').read_text(encoding='utf-8')).get('initial_idle') if (OUT/'execution_start.json').exists() else None
    adapters=json.loads((OUT/'dxgi_adapter_identity.json').read_text(encoding='utf-8')).get('adapters',[]) if (OUT/'dxgi_adapter_identity.json').exists() else []
    for model in MODELS:
        rs=[r for r in rows if r['model']==model];cs=[r for r in cold if r['model']==model]
        stats=request_stats(rs);hs=stats['hardware'];ttft[model]={'any':stats['ttft_any'],'final_answer':stats['ttft'],
            'first_attempt_final_answer':summary([r.get('first_request_ttft_seconds') for r in rs]),
            'retry_inclusive_final_answer':summary([r.get('retry_inclusive_ttft_final_answer_seconds') for r in rs]),
            'semantics':'final_answer is the final attempt content-channel TTFT; first-attempt and accepted-response retry-inclusive times are separately preserved'}
        tps[model]={'runtime':stats['TPS'],'visible_answer':stats['visible_TPS'],
            'semantics':dict(Counter(r.get('tokens',{}).get('runtime_tps_semantics') for r in rs)),
            'reasoning_token_separation_available':bool(rs) and all(r.get('tokens',{}).get('reasoning_token_separation_available') for r in rs),
            'mixed_token_semantics_not_a_speed_winner':True}
        lat[model]={k:stats[k] for k in ('latency','request_latency','prompt_eval_seconds','generation_seconds')}
        mem[model]={k:hs[k] for k in ('system_RAM_used_bytes','dedicated_GPU_used_bytes','Ollama_process_working_sets','shared_GPU_memory_by_adapter','Ollama_GPU_process_memory','scopes',
            'process_memory_coverage','runner_process_working_set_available','model_process_specific_RAM_peak','model_process_specific_VRAM_peak')}
        mem[model].update(initial_whole_workstation_idle_sample=initial_idle,
            model_loaded_samples=[p.get('sensor') for p in placements_all if p['model']==model],
            model_loaded_sample_limitation='Last native sample after warm-up, at most one polling interval old; timestamp retained, never relabeled as a process peak')
        mem[model]['shared_GPU_adapter_identity']={instance:next((a for a in adapters if instance.startswith(a['LUID_instance_prefix'])),None)
            for instance in hs['shared_GPU_memory_by_adapter']}
        mem[model]['shared_GPU_capacity_scope']='DXGI shared system capacity is RAM-backed, not additional dedicated VRAM; Basic Render Driver kept separate'
        power[model]={'GPU_board_power_watts':hs['GPU_board_power_watts'],'available':hs['power_metrics_available'],'whole_system_power_available':False,'energy_per_request_joules':None}
        thermal[model]={'GPU_temperature_c':hs['GPU_temperature_c'],'clock_throttling_measured':None,'thermal_throttling_flag':None}
        thermal[model].update(start_conditions=[t for t in thermal_starts if t['model']==model],
            thermal_baseline_not_reached_count=sum(t.get('thermal_baseline_not_reached',False) for t in thermal_starts if t['model']==model),
            idle_utilization_baseline_not_reached_count=sum(t.get('utilization_baseline_not_reached',False) for t in thermal_starts if t['model']==model))
        fail[model]=ifr(rs,180);rel[model]=reliability(rs,180)
        rel[model].update(first_pass_JSON_valid_rate=safe_rate(sum(r.get('first_pass_json_valid') is True for r in rs),180),
            final_JSON_valid_rate=safe_rate(sum(r.get('final_json_valid') is True for r in rs),180),
            unknown_context_ID_count=sum(r['result'].get('citation_error_taxonomy',{}).get('unknown_context_id',0) for r in rs))
        ctx[model]={}
        for band in ('short','medium','long'):
            sub=[r for r in rs if r['context_band']==band]
            ctx[model][band]=request_stats(sub)
            ctx[model][band]['IFR']=ifr(sub,{'short':60,'medium':63,'long':57}[band])
        sem={r.get('tokens',{}).get('runtime_tps_semantics') for r in rs}
        ctx[model]['long_short_ratios']=ratios(ctx[model],len(sem)==1 and None not in sem)
        stability[model]=run_stability(rs);behavior[model]=citation_and_behavior(rs)
        limitations=['Runner-specific RAM/VRAM unavailable: llama-server.exe was outside the recorded process-name filter; whole-device measurements retained']
        if any(t.get('utilization_baseline_not_reached') for t in thermal_starts if t['model']==model):
            limitations.append('Continuous <5% GPU idle requirement not achieved within the 300-second bounded wait; explicit start-condition protocol deviation, no threshold change')
        if any(g['model']==model for g in read_rows(OUT/'measurement_gaps.jsonl')):limitations.append('Warm run resumed after report-file share-lock interruption; retained resident model and all outputs, with explicit idle measurement gap')
        if any(r.get('context_budget',{}).get('input_truncated') is None for r in rs):limitations.append('input truncation detection incomplete')
        if any(r.get('completion_truncation') for r in rs):limitations.append('completion truncation observed')
        placements=read_rows(OUT/'model_placement.jsonl')
        alloc=[p['runtime_model_status'] for p in placements if p['model']==model and p.get('runtime_model_status')]
        if any(a.get('size_vram',0)<a.get('size',0) for a in alloc):limitations.append('Ollama reported GPU allocation smaller than total allocation; partial CPU placement possible; consult runtime log')
        if any(r['retry_triggered'] for r in rs):limitations.append('technical retry required')
        hw=status(rs,cs,limitations,external_interrupt=interrupted)
        matrix.append(dict(model=model,quality_status=QUALITY[model],hardware_status=hw,
            TTFT_final_answer_median=stats['ttft']['median'],TTFT_any_median=stats['ttft_any']['median'],runtime_TPS_median=stats['TPS']['median'],
            visible_answer_TPS_median=stats['visible_TPS']['median'],latency_median=stats['latency']['median'],p95_latency=stats['latency']['p95'],
            RAM_sampled_peak_bytes=hs['system_RAM_used_bytes']['max'],dedicated_VRAM_sampled_peak_bytes=hs['dedicated_GPU_used_bytes']['max'],
            shared_GPU_sampled_peak_bytes=max((s['max'] for instance,s in hs['shared_GPU_memory_by_adapter'].items()
                if any(a['name']=='NVIDIA GeForce RTX 4060' and instance.startswith(a['LUID_instance_prefix']) for a in adapters)),default=None),
            GPU_board_power_mean_watts=hs['GPU_board_power_watts']['mean'],GPU_temperature_peak_C=hs['GPU_temperature_c']['max'],
            final_IFR=fail[model]['final_IFR'],schema_reliability=rel[model]['final_schema_validity'],
            behavior_preservation=behavior[model]['behavior'],limitations=limitations,quality_status_unchanged=True,
            human_validated=False,judge_conflict=model=='qwen2.5-coder:7b',reference_alignment_bias_possible=True,weighted_score=None))
    outputs={'ttft.json':ttft,'throughput.json':tps,'latency.json':lat,'memory.json':mem,'gpu_power.json':power,'thermal.json':thermal,
        'ifr.json':fail,'reliability.json':rel,'context_length_analysis.json':ctx,'run_stability.json':stability,
        'behavior_preservation.json':behavior,'model_deployment_matrix.json':matrix,
        'model_placement.json':read_rows(OUT/'model_placement.jsonl'),
        'cold_gpu_release_audit.json':cold_release_reanalysis(cold,((initial_idle or {}).get('gpu') or {}).get('dedicated_used_bytes')),
        'sustained_load.json':sustained_report(read_rows(OUT/'sustained_requests.jsonl'),read_rows(OUT/'sustained_completion.jsonl'),read_rows(OUT/'sensor_samples.jsonl')),
        'paired_performance.json':paired_performance(rows),
        'pareto_analysis.json':{'performance_only':pareto(matrix,{'TTFT_final_answer_median':'min','p95_latency':'min','RAM_sampled_peak_bytes':'min','dedicated_VRAM_sampled_peak_bytes':'min','final_IFR':'min','schema_reliability':'max'}),
            'comparable_content_TPS_subset':pareto([m for m in matrix if m['model'] in ('gemma2:9b','qwen2.5-coder:7b')],
                {'TTFT_final_answer_median':'min','p95_latency':'min','visible_answer_TPS_median':'max','RAM_sampled_peak_bytes':'min','dedicated_VRAM_sampled_peak_bytes':'min','final_IFR':'min'}),
            'quality_status_preserved':QUALITY,'runtime_TPS_cross_model_dominance_disabled':'Reasoning/content token semantics differ; visible TPS missing on DeepSeek',
            'GPU_power_axis_disabled':'power.draw unavailable','quality_winner':None,'human_validation_missing':True}}
    outputs['cold_start_summary.json']={m:{'repetitions':len([r for r in cold if r['model']==m]),
        'model_load_seconds':summary([r.get('runtime_load_duration_ns',0)/1e9 if r.get('runtime_load_duration_ns') is not None else None for r in cold if r['model']==m]),
        **request_stats([r for r in cold if r['model']==m and r.get('result')])} for m in MODELS}
    outputs['environment_limitations.json']=dict(target_class='local edge inference workstation, not embedded board or Jetson',
        GPU_power_unavailable=True,whole_system_power_unavailable=True,model_cold_not_OS_boot=True,
        memory_scopes_explicit=True,shared_memory_not_dedicated=True,thermal_throttling_not_directly_measured=True,
        process_memory_coverage='partial: llama-server.exe runner missing; parent readings not total model process memory',
        localized_capture_encoding_issue='Original localized OS edition/power-plan labels contain decode replacement characters; OS version/build and power-plan GUID preserved. Raw capture not rewritten.',
        no_final_quality_winner=True,no_RAGAS=True,no_retrieval_execution=True,full_RAG_latency_not_measured=True,
        start_condition_deviations=[{k:t.get(k) for k in ('model','repetition','wait_seconds','actual_temperature_c','continuous_idle_60_seconds')}
            for t in thermal_starts if t.get('utilization_baseline_not_reached')],
        windows_reranker_policy_limitation='Frozen E4 contexts reused; no c10_cuda.dll or reranker execution in Phase 19A')
    for name,data in outputs.items():write(OUT/name,data)
    lines=['# Phase 19A — Local Edge Workstation Generator Benchmark','',
        'Generator-only descriptive feasibility. No embedded-device claim, no full-RAG latency, no human-validated quality winner.','',
        '| Model | Warm requests | Hardware status | Quality status | TTFT median (s) | Latency p95 (s) | IFR |',
        '|---|---:|---|---|---:|---:|---:|']
    for r in matrix:
        lines.append(f"| {r['model']} | {fail[r['model']]['n_total']}/180 | {r['hardware_status']} | {r['quality_status']} | {r['TTFT_final_answer_median']} | {r['p95_latency']} | {r['final_IFR']} |")
    lines+=['','GPU board power is unavailable; no estimates. RAM/VRAM are whole-device sampled measurements with per-process details retained.',
        'Shared GPU memory is RAM-backed WDDM usage, separate from dedicated VRAM. Native thinking tokens are excluded from final-answer TTFT; DeepSeek visible-answer TPS remains null when separation is unavailable.',
        'Performance comparisons aggregate each fixed question across three runs; no weighted score or quality-status promotion.',
        'Phase 19B can be considered only as a separate full-RAG target benchmark; Phase 20 is not established by generator performance alone.','']
    (OUT/'phase19A_summary.md').write_text('\n'.join(lines),encoding='utf-8')
    return matrix
