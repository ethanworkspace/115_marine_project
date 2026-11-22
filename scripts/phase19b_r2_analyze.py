"""Consolidate immutable request journals; partial blocks never become primary."""
from __future__ import annotations
import collections
import itertools
import json
import math
import os
import re
import statistics
import subprocess
import sys
from pathlib import Path
from urllib.request import urlopen
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from src.evaluation.edge.exec19b_r2 import primary_rows,valid_block,request_summary,latency_comparison,cv
from src.evaluation.edge.core import summary
from src.evaluation.generation.frozen import sha256_file
OUT=ROOT/'reports/evaluation/edge/phase19B_exec_r2'

def read(name,default=None):
    p=OUT/name
    return json.loads(p.read_text(encoding='utf-8')) if p.exists() else default
def rows(name):
    p=OUT/name;return [json.loads(l) for l in p.read_text(encoding='utf-8').splitlines()] if p.exists() else []
def write(name,value):
    with (OUT/name).open('x',encoding='utf-8') as f:json.dump(value,f,ensure_ascii=False,indent=2);f.write('\n')

def gen_metrics(rs):
    gs=[r['generation'] for r in rs if 'generation' in r];outs=[r['result'] for r in gs]
    count=len(gs);cit=sum(r.get('citation_count',0) for r in outs)
    strict=sum(r.get('strict_citation_count',0) for r in outs)
    def ratio(n,d):return n/d if d else None
    def recall(suffix):
        numerator_suffix='' if suffix=='_all_questions' else suffix
        n=sum((r.get('required_evidence_citation') or {}).get('strict_cited_required_chunk_count'+numerator_suffix,0) for r in outs)
        d=sum((r.get('required_evidence_citation') or {}).get('required_chunk_count'+suffix,0) for r in outs)
        return dict(numerator=n,denominator=d,rate=ratio(n,d))
    return dict(n_total=count,n_formal_requests=len(rs),n_generation_not_executed=len(rs)-count,
        first_pass_JSON_valid=ratio(sum(r.get('first_pass_JSON_valid',False) for r in rs),count),
        first_pass_schema_valid=ratio(sum(g['first_pass_schema_valid'] for g in gs),count),
        final_schema_valid=ratio(sum(g['final_schema_valid'] for g in gs),count),
        citation_parse_rate=ratio(sum(g['final_citation_parse'] for g in gs),count),
        strict_citation_validity=dict(numerator=strict,denominator=cit,rate=ratio(strict,cit)),
        required_citation_recall={'all':recall('_all_questions'),'evidence_present':recall('_present'),
            'present_and_answered':recall('_present_and_answered')},
        retry_trigger_count=sum(g['retry_triggered'] for g in gs),retry_success_count=sum(g['retry_success'] for g in gs),
        retry_failure_count=sum(g['retry_triggered'] and not g['retry_success'] for g in gs),
        statuses=dict(collections.Counter(g['status'] for g in gs)),
        input_truncation_count=sum(g.get('context_budget',{}).get('input_truncated') is True for g in gs),
        input_truncation_unknown=sum(g.get('context_budget',{}).get('input_truncated') is None for g in gs),
        context_capacity_failure_count=sum(g.get('context_budget',{}).get('context_capacity_failure',False) for g in gs),
        completion_truncation_count=sum(g.get('completion_truncation',False) for g in gs),
        unknown_context_id=sum(r.get('citation_error_taxonomy',{}).get('unknown_context_id',0) for r in outs),
        Silver_token_F1=summary([(r.get('silver_reference_similarity') or {}).get('f1') for r in outs],count),
        calculation=[{'question_id':r['question_id'],'numeric':r['calculation_numeric_evaluation']} for r in outs if r.get('calculation_numeric_evaluation') is not None],
        runtime_TPS=summary([g.get('tokens',{}).get('runtime_tps') for g in gs],count))

def main():
    if not (OUT/'execution_complete.json').exists():raise SystemExit('Execution still running; reports not finalized')
    manifest=read('experiment_manifest.json');ids=manifest['question_ids'];bs=rows('formal_blocks.jsonl')
    write('analysis_manifest.json',dict(analysis_code_sha256=sha256_file(Path(__file__)),
        statistics='Finite observed values; arithmetic mean, median, linearly interpolated p95, min/max; missing values never imputed',
        run_CV='Population standard deviation / mean of three valid run medians',
        invalid_blocks='All rows remain diagnostic; only complete valid blocks contribute primary metrics',
        hardware_quality_separate=True,weighted_composite_score=False,
        deployment_scope='full_rag',target_identity_source='Frozen Phase 19A target YAML, hardware identity reused; this execution has full-RAG scope',
        evaluation_only=True,RAGAS_rerun=False))
    from src.evaluation.edge.core import digest,OPTIONS
    from src.evaluation.generation.runner_v2 import format_v2_user_prompt
    bundle=ROOT/'data/evaluation/edge/phase19_inputs_v1'
    questions={r['question']['question_id']:r['question'] for r in read_jsonl_path(bundle/'inputs.jsonl')}
    ctx={(r['run_id'],r['question_id']):r['top5'] for r in rows('retrieval_results.jsonl')}
    schema=json.loads((bundle/'generation_output_v2.schema.json').read_text(encoding='utf-8'))
    prompt=(bundle/'generation_v2.txt').read_text(encoding='utf-8').strip();request_audit=[]
    for attempt in rows('attempts.jsonl'):
        key=(attempt['stage'],attempt['question_id']);contexts=ctx[key]
        body=dict(model=attempt['model'],stream=True,format=schema,keep_alive='30m',
            messages=[{'role':'system','content':prompt},{'role':'user','content':format_v2_user_prompt(questions[key[1]],contexts)}],options=OPTIONS)
        declared=digest(json.dumps(body,ensure_ascii=False,sort_keys=True));body.pop('keep_alive')
        request_audit.append(dict(run_id=key[0],question_id=key[1],attempt_number=attempt['attempt_number'],
            captured_pre_session_hash=attempt['captured_runtime']['request_sha256'],
            pre_session_reconstruction_matches=declared==attempt['captured_runtime']['request_sha256'],
            actual_transmitted_body_sha256=digest(json.dumps(body,ensure_ascii=False,sort_keys=True)),
            residency_override_transmitted=False))
    write('request_payload_hash_audit.json',dict(attempts=request_audit,
        all_pre_session_reconstructions_match=all(r['pre_session_reconstruction_matches'] for r in request_audit),
        semantics='Original adapter hash records pre-session body with legacy keep_alive; new session deterministically omits keep_alive to use server defaults. Actual body hashes derived separately; original attempts never edited'))
    native={r['point']:r for r in rows('code_integrity_native_monitor_v2.jsonl') if not r['point'].startswith('live_')}
    # Authoritative native read-only capture supplements preserved PowerShell module errors.
    for b in bs:
        cap=native.get('formal_block_end_'+b['run_id'])
        b['native_event_capture']=cap
        b['runtime_valid']=bool(b['runtime_valid'] and cap and cap['status']=='collected' and not cap.get('capped') and cap['relevant_execution_block_count']==0)
        b['primary_metrics_valid']=valid_block(b,ids)
    all_rows=rows('stage_metrics.jsonl');primary=primary_rows(all_rows,bs,ids)
    sensors=rows('sensor_samples.jsonl')
    by={c:[r for r in primary if r['condition']==c] for c in ('R0_edge_retrieval_only','F1_edge_fullrag_gemma','F2_edge_fullrag_qwen')}
    valid=sum(b['primary_metrics_valid'] for b in bs);invalid=len(bs)-valid
    write('runtime_continuity_validation.json',dict(blocks=bs,valid_formal_blocks=valid,invalid_formal_blocks=invalid,
        primary_requests=len(primary),diagnostic_formal_requests=sum(r['stage']=='formal' for r in all_rows)-len(primary),
        no_partial_run_splicing=True,authoritative_capture='code_integrity_native_monitor_v2.jsonl'))
    reports={}
    for cond,file in zip(by,('R0_retrieval.json','F1_gemma_fullrag.json','F2_qwen_fullrag.json')):
        rs=by[cond];reports[cond]=dict(**request_summary(rs),n_target=180,
            generation=gen_metrics(rs) if cond!='R0_edge_retrieval_only' else None,
            IFR_denominator='Every executed request within complete valid primary blocks; invalid-block requests retained separately')
        if cond=='R0_edge_retrieval_only':
            reports[cond]['generation_IFR']=None
            reports[cond]['generation_scope']='not_applicable: retrieval-only condition'
        reports[cond]['failure_counts']={key:sum(bool(r.get(key)) for r in rs) for key in
            ('OOM','runtime_crash','context_capacity_failure','retrieval_failed','generation_failed','runtime_failure')}
        reports[cond]['timing_accounting']=dict(
            non_stage_residual_ms=summary([r['e2e_total_latency_ms']-r.get('retrieval_to_context_ms',0)-
                r.get('generation_completion_ms',0) for r in rs]),
            interpretation='Measured end-to-end includes synchronous telemetry, provenance checks and output validation. Residual is not removed from reported latency')
        write(file,reports[cond])
    write('ifr.json',dict(primary={c:{k:reports[c][k] for k in ('n_total','n_target','final_failed','final_IFR','retrieval_IFR','generation_IFR')} for c in by},
        all_executed_diagnostic=request_summary([r for r in all_rows if r['stage']=='formal'])))
    write('retrieval_drift.json',dict(primary_drift_count=sum(r['retrieval_drift'] for r in primary),
        all_executed_drift_count=sum(r['retrieval_drift'] for r in all_rows),
        drift_requests=[{'run_id':r['run_id'],'question_id':r['question_id']} for r in all_rows if r['retrieval_drift']]))
    context={};stability={}
    for c,rs in by.items():
        context[c]={band:request_summary([r for r in rs if r['context_band']==band]) for band in ('short','medium','long')}
        run_reports=[]
        for b in [b for b in bs if b['condition']==c]:
            rrs=[r for r in all_rows if r['run_id']==b['run_id']]
            ss=[s for s in sensors if rrs and rrs[0]['telemetry_start_monotonic']<=s['timestamp']<=rrs[-1]['telemetry_end_monotonic']]
            drift={}
            if ss:
                ar=ss[0].get('system_RAM_used_bytes');zr=ss[-1].get('system_RAM_used_bytes')
                drift['system_RAM_used_bytes_end_minus_start']=zr-ar if zr is not None and ar is not None else None
                a=(ss[0].get('gpu') or {}).get('dedicated_used_bytes');z=(ss[-1].get('gpu') or {}).get('dedicated_used_bytes')
                drift['dedicated_GPU_used_bytes_end_minus_start']=z-a if z is not None and a is not None else None
                drift['interpretation']='Whole-system/device drift; not a proved process memory leak'
            run_reports.append(dict(run_id=b['run_id'],primary_metrics_valid=b['primary_metrics_valid'],summary=request_summary(rrs),
                memory_drift=drift,
                reload_count=sum(len(e['model_reload']) for r in rrs for e in r['residency_events']),
                eviction_count=sum(len(e['model_eviction']) for r in rrs for e in r['residency_events'])))
        good=[r['summary']['metrics'] for r in run_reports if r['primary_metrics_valid']]
        stability[c]=dict(runs=run_reports,CV_of_run_medians={k:cv([r[k]['median'] for r in good]) for k in
            ('retrieval_to_context_ms','e2e_ttft_final_ms','e2e_total_latency_ms')},memory_drift_report='memory.json')
    write('run_stability.json',stability)
    sensors=rows('sensor_samples.jsonl');checkpoints=rows('residency_trace.jsonl')
    index_manifest=json.loads((ROOT/'data/evaluation/indexes/E2_grounded_bge_m3_v1/index_manifest.json').read_text(encoding='utf-8'))
    expected_digests={model:value['digest'] for model,value in manifest['models'].items()}
    expected_digests['bge-m3:latest']=index_manifest['model']['model_digest']
    identity_observations=[]
    for checkpoint in checkpoints:
        for model in checkpoint['loaded_ollama_models'].get('models',[]):
            name=model.get('name',model.get('model'))
            if name in expected_digests:
                identity_observations.append(dict(run_id=checkpoint['run_id'],question_id=checkpoint['question_id'],
                    node=checkpoint['node'],model=name,digest=model.get('digest'),expected=expected_digests[name],
                    matches=model.get('digest')==expected_digests[name]))
    write('runtime_model_identity.json',dict(observations=identity_observations,
        mismatch_count=sum(not r['matches'] for r in identity_observations),
        models_observed=dict(collections.Counter(r['model'] for r in identity_observations)),
        semantics='Actual loaded /api/ps artifact digests; complements frozen file checksums'))
    intervals={c:[(r['telemetry_start_monotonic'],r['telemetry_end_monotonic']) for r in rs] for c,rs in by.items()}
    def subset_samples(c):return [s for s in sensors if any(a<=s['timestamp']<=b for a,b in intervals[c])]
    def shared(s):
        values=s.get('shared_GPU_memory')
        return sum(x['value_bytes'] for x in values) if values is not None else None
    def mem_summary(samples):
        return dict(system_RAM_used_bytes=summary([s.get('system_RAM_used_bytes') for s in samples]),
            dedicated_VRAM_whole_device_bytes=summary([(s.get('gpu') or {}).get('dedicated_used_bytes') for s in samples]),
            shared_GPU_RAM_backed_adapter_bytes=summary([shared(s) for s in samples]),
            GPU_board_power_watts=summary([(s.get('gpu') or {}).get('gpu_board_power_watts') for s in samples]),
            GPU_temperature_C=summary([(s.get('gpu') or {}).get('temperature_c') for s in samples]),
            sampled_peak_only=True,shared_scope='Sum of observed WDDM adapter instances; per-adapter raw counters preserved; not dedicated VRAM or a claimed RTX-only process total')
    mem={c:mem_summary(subset_samples(c)) for c in by}
    for c,rs in by.items():
        for band in ('short','medium','long'):
            rr=[r for r in rs if r['context_band']==band]
            context[c][band]['distinct_questions']=len({r['question_id'] for r in rr})
            samples=[s for s in sensors if any(r['telemetry_start_monotonic']<=s['timestamp']<=r['telemetry_end_monotonic'] for r in rr)]
            context[c][band]['memory']=mem_summary(samples)
        context[c]['long_short_ratios']={k:
            context[c]['long']['metrics'][k]['median']/context[c]['short']['metrics'][k]['median']
            if context[c]['long']['metrics'][k]['median'] is not None and context[c]['short']['metrics'][k]['median'] else None
            for k in ('e2e_ttft_final_ms','e2e_total_latency_ms','retrieval_to_context_ms')}
    write('context_length_analysis.json',context)
    family={}
    for c in by:
        selected=[s for s in checkpoints if s['condition']==c and s['stage']=='formal' and s['run_id'] in {b['run_id'] for b in bs if b['primary_metrics_valid']}]
        processes=[p for s in selected for p in s['process_tree']['processes']]
        family[c]={role:dict(working_set_bytes=summary([p['working_set_bytes'] for p in processes if role in p['roles']]),
            private_commit_bytes=summary([p['private_commit_bytes'] for p in processes if role in p['roles']])) for role in
            ('benchmark_runner','reranker_python','ollama_server_or_launcher','ollama_model_runner','descendant_of_observed_runtime')}
    placement=rows('placement_observations.jsonl');processor={}
    process_gpu={}
    for c in by:
        selected=[s for s in placement if any(a<=s['timestamp']<=b for a,b in intervals[c])]
        raw=[];splits=collections.defaultdict(collections.Counter)
        for s in selected:
            for line in s.get('ollama_ps_stdout','').splitlines()[1:]:
                m=re.match(r'^(\S+)\s+\S+\s+[\d.]+\s+\S+\s+(.+?)\s+(\d+)\s+.+$',line)
                if m:splits[m[1]][m[2].strip()]+=1
        processor[c]={m:dict(v) for m,v in splits.items()}
        for s in selected:
            for kind,values in s.get('process_GPU_memory',{}).items():
                for value in values or []:raw.append(dict(timestamp=s['timestamp'],kind=kind,**value))
        process_gpu[c]=dict(observations=raw,semantics='Measured WDDM counters for identified benchmark/reranker/Ollama process tree; per-adapter instance, shared is RAM-backed',
            available=bool(raw))
    write('process_memory.json',dict(by_condition=family,semantics='Per-process working set and private commit; not summed as physical RAM or VRAM'))
    write('process_gpu_memory.json',process_gpu)
    write('processor_split.json',dict(by_condition=processor,source='Read-only existing Ollama CLI ps',
        interpretation='Observed processor allocation. Mixed CPU/GPU is partial offload; it does not prove a complete CPU fallback'))
    write('gpu_memory.json',dict(by_condition=mem,per_process_VRAM_complete=None,
        limitation='Whole-device NVIDIA dedicated memory is reliable; existing sensor process counters cover only part of Ollama family and are not treated as complete process GPU allocation'))
    write('memory.json',mem)
    unique_events={e.get('record_id',e.get('raw_event_xml')):e for r in native.values() for e in r.get('events',[])}
    write('code_integrity_summary.json',dict(captures=[{k:v for k,v in r.items() if k!='events'} for r in native.values()],
        new_event_count=len(unique_events),capture_event_count_sum=sum(r['count'] for r in native.values()),
        event_ids=dict(collections.Counter(str(e.get('event_id')) for e in unique_events.values())),
        deduplication='Named lifecycle windows only, unique Windows event record IDs; overlapping live windows excluded',
        relevant_execution_block_count=sum(r['relevant_execution_block_count'] for r in native.values()),
        primary_monitor='Windows native wevtutil (read only)',original_failed_captures_preserved=True))
    residency={}
    for c,rs in by.items():
        es=[e for r in rs for e in r['residency_events']]
        residency[c]=dict(observed_model_loads=dict(collections.Counter(m for e in es for m in e['model_load'])),
            observed_reloads=dict(collections.Counter(m for e in es for m in e['model_reload'])),
            observed_model_disappearances=dict(collections.Counter(m for e in es for m in e['model_eviction'])),
            offload_changes=dict(collections.Counter(m for e in es for m in e['GPU_offload_change'])),
            CPU_fallback=None,observed_processor_split=processor.get(c,{}),shared_memory_spill=None,
            GPU_allocations=[{'run_id':s['run_id'],'question_id':s['question_id'],'node':s['node'],
                'models':[{k:m.get(k) for k in ('name','digest','size','size_vram','context_length')} for m in s['loaded_ollama_models'].get('models',[])]}
                for s in checkpoints if s['condition']==c and s['stage']=='formal'],
            causality='Observed /api/ps transitions only; allocation changes do not independently prove CPU fallback or shared-memory spill')
    write('residency_summary.json',residency)
    behavior={}
    for c,rs in by.items():
        if c=='R0_edge_retrieval_only':continue
        behavior[c]={phase:{k:summary([r['behavior_'+phase].get(k) for r in rs]) if k in ('normalized_answer_similarity','citation_set_jaccard') else
            {'agreement_count':sum(r['behavior_'+phase].get(k,False) for r in rs),'denominator':len(rs),'rate':sum(r['behavior_'+phase].get(k,False) for r in rs)/len(rs) if rs else None}
            for k in ('status_agreement','schema_agreement','citation_set_exact','citation_set_jaccard','normalized_answer_similarity')}
            for phase in ('phase17','phase19A')}
    write('behavior_preservation.json',behavior)
    write('behavior_reference_manifest.json',dict(Phase17='Frozen bundled e4_top5 outputs for the same model/question IDs',
        Phase19A='Frozen formal warm repetition 1 for the same model/question IDs, fixed before execution; no best-output selection',
        methods=['status agreement','schema agreement','citation set exact/Jaccard','normalized answer similarity'],
        RAGAS_rerun=False,raw_exact_match_required=False))
    historical=read_jsonl_path(ROOT/'reports/evaluation/edge/phase19A/warm_runs.jsonl')
    historical_memory=json.loads((ROOT/'reports/evaluation/edge/phase19A/memory.json').read_text(encoding='utf-8'))
    historical_placement=json.loads((ROOT/'reports/evaluation/edge/phase19A/model_placement.json').read_text(encoding='utf-8'))
    comparisons={}
    for c,model in [('F1_edge_fullrag_gemma','gemma2:9b'),('F2_edge_fullrag_qwen','qwen2.5-coder:7b')]:
        hs=[r for r in historical if r['model']==model]
        comparisons[model]=dict(
            TTFT_final=latency_comparison(reports[c]['metrics']['e2e_ttft_final_ms'],summary([r.get('retry_inclusive_ttft_final_answer_seconds',0)*1000 for r in hs])),
            generation_component=latency_comparison(reports[c]['metrics']['generation_completion_ms'],summary([r['retry_inclusive_latency_seconds']*1000 for r in hs])),
            total_latency=latency_comparison(reports[c]['metrics']['e2e_total_latency_ms'],summary([r['retry_inclusive_latency_seconds']*1000 for r in hs])),
            Phase19B_memory=mem[c],Phase19A_memory_report='reports/evaluation/edge/phase19A/memory.json',
            RAM_comparison=dict(current=mem[c]['system_RAM_used_bytes'],historical=historical_memory[model]['system_RAM_used_bytes'],scope='Whole-system used RAM; background/host cache not controlled across phases'),
            dedicated_VRAM_comparison=dict(current=mem[c]['dedicated_VRAM_whole_device_bytes'],historical=historical_memory[model]['dedicated_GPU_used_bytes'],scope='Whole GPU device; includes background allocations'),
            shared_GPU_comparison=dict(current=mem[c]['shared_GPU_RAM_backed_adapter_bytes'],historical_by_adapter=historical_memory[model]['shared_GPU_memory_by_adapter'],scope='WDDM RAM-backed shared usage, separate from dedicated VRAM'),
            current_schema_valid=reports[c]['generation']['final_schema_valid'],historical_schema_valid=sum(r['final_schema_valid'] for r in hs)/len(hs),
            historical_model_placement=[{k:r.get(k) for k in ('repetition','GPU_allocation_bytes','runtime_allocations','allocation_note')}
                for r in historical_placement if r['model']==model and r.get('stage')=='warm'],
            current_generator_size_vram_bytes=summary([m.get('size_vram') for s in checkpoints if s['condition']==c
                and s['stage']=='formal' and s['node']=='after_generator' for m in s['loaded_ollama_models'].get('models',[])
                if m.get('name',m.get('model'))==model]),
            residency_diagnostics=residency[c],interpretation='Cross-phase descriptive. Residency/reloads, context cache and host load may contribute; difference is not exclusively retrieval')
    write('phase19A_vs_19B.json',comparisons)
    sustained=rows('sustained_requests.jsonl')
    for model,label in [('gemma2:9b','gemma'),('qwen2.5-coder:7b','qwen')]:
        execution=read('sustained_'+label+'_execution.json',{'completed':False,'reason':'not reached'})
        rs=[r for r in sustained if r.get('model')==model]
        result=dict(execution=execution,overall=request_summary(rs),intervals=[])
        for i in range(6):
            subset=[r for r in rs if r['interval_index']==i]
            ss=[s for s in sensors if any(r['telemetry_start_monotonic']<=s['timestamp']<=r['telemetry_end_monotonic'] for r in subset)]
            ci=[r for r in rows('code_integrity_native_monitor_v2.jsonl') if r['point']==('sustained_'+model.replace(':','_')+'_interval_'+str(i+1))]
            result['intervals'].append(dict(interval=i+1,start_seconds=i*300,end_seconds=(i+1)*300,
                metrics=request_summary(subset),memory=mem_summary(ss),
                new_Code_Integrity_event_count=sum(r['count'] for r in ci) if ci else None,
                relevant_Code_Integrity_block_count=sum(r['relevant_execution_block_count'] for r in ci) if ci else None,
                runtime_TPS=summary([r['generation']['tokens'].get('runtime_tps') for r in subset if 'generation' in r]),
                reloads=sum(len(e['model_reload']) for r in subset for e in r['residency_events']),
                evictions=sum(len(e['model_eviction']) for r in subset for e in r['residency_events'])))
        if result['intervals']:
            a,z=result['intervals'][0],result['intervals'][-1]
            am=a['runtime_TPS']['median'];zm=z['runtime_TPS']['median']
            def difference(key,section):
                av=a[section][key]['median'];zv=z[section][key]['median']
                return zv-av if av is not None and zv is not None else None
            result['drift']=dict(TPS_last_first_median_ratio=zm/am if am and zm is not None else None,
                latency_last_first_median_difference_ms=z['metrics']['metrics']['e2e_total_latency_ms']['median']-a['metrics']['metrics']['e2e_total_latency_ms']['median'] if z['metrics']['metrics']['e2e_total_latency_ms']['median'] is not None and a['metrics']['metrics']['e2e_total_latency_ms']['median'] is not None else None,
                temperature_last_first_median_difference_C=difference('GPU_temperature_C','memory'),
                system_RAM_last_first_median_difference_bytes=difference('system_RAM_used_bytes','memory'),
                interpretation='Descriptive interval drift with varying frozen questions; no strict causal attribution')
        write('sustained_'+label+'.json',result)
    limitations=['Historical application-control block confirmed; current allow reason unknown, no permanent fix claimed',
        'PowerShell Diagnostics module did not load; native read-only wevtutil supplements each original capture window',
        'Initial native +00:00 filter failed positive control; immutable diagnostics retained, authoritative capture uses validated UTC-Z v2',
        'Sampled memory/power peaks; not absolute peaks',
        'Shared GPU memory is RAM-backed WDDM adapter usage, never dedicated VRAM',
        'CPU fallback and cause of memory spill unknown without sufficient runtime evidence',
        'No product latency thresholds; descriptive feasibility',
        'Human citation review incomplete and Qwen judge conflict unresolved']
    baselines=rows('environment_baselines.jsonl')
    write('environment_limitations.json',dict(limitations=limitations,
        environment_start_protocol=dict(blocks_observed=len(baselines),
            completed=sum(r['environment_start_protocol_complete'] for r in baselines),
            not_reached=sum(not r['environment_start_protocol_complete'] for r in baselines),
            maximum_wait_seconds=300,continuation_without_environment_cherry_picking=True),
        code_integrity_native_capture_complete=all(
        ('formal_block_end_'+b['run_id']) in native and native['formal_block_end_'+b['run_id']]['status']=='collected' for b in bs),
        initial_startup_UTF8_error_preserved='startup_attempt_1.json',security_settings_changed=False))
    matrix=[]
    for c,model in [('F1_edge_fullrag_gemma','gemma2:9b'),('F2_edge_fullrag_qwen','qwen2.5-coder:7b')]:
        rs=by[c];capacity=any(r.get('context_capacity_failure') for r in rs)
        oom=any(r['OOM'] for r in rs);crash=any(r['runtime_crash'] for r in rs)
        if len(rs)!=180:status='benchmark_incomplete'
        elif oom or capacity:status='not_feasible'
        elif any('CPU/GPU' in split or '100% CPU' in split for split in processor.get(c,{}).get(model,{})):status='deployable_with_limitations'
        elif reports[c]['final_IFR']==0 and not crash and not any(r['retrieval_drift'] for r in rs):status='deployable_on_device'
        else:status='deployable_with_limitations'
        matrix.append(dict(model=model,quality_status=manifest['quality_status'][model],hardware_status=status,
            full_benchmark_technical_feasibility=bool(len(rs)==180 and reports[c]['final_IFR']==0 and
                not oom and not crash and not capacity and not any(r['retrieval_drift'] for r in rs)
                and identity_observations and all(r['matches'] for r in identity_observations)),
            metrics=reports[c],memory=mem[c],residency=residency[c],no_product_threshold_pass_claim=True,
            quality_status_changed=False,human_validated=False,CPU_fallback=None))
    write('deployment_matrix.json',matrix)
    research=any(r['full_benchmark_technical_feasibility'] for r in matrix)
    write('phase20_readiness.json',dict(phase20_research_integration_ready=research,final_model_selection_ready=False,
        independent_judge_ready=False,human_citation_support_review_complete=False,Qwen_quality_status='evaluation_unresolved'))
    test=subprocess.run([str(ROOT/'.venv/Scripts/python.exe'),'-B','-m','unittest','discover','-s','tests','-v'],
        cwd=ROOT,capture_output=True,encoding='utf-8',errors='replace',env={**os.environ,'PYTHONIOENCODING':'utf-8','PYTHONDONTWRITEBYTECODE':'1'})
    log=test.stdout+test.stderr;(OUT/'unittest_final.log').write_text(log,encoding='utf-8')
    n=re.search(r'Ran (\d+) tests?',log);skip=re.search(r'skipped=(\d+)',log)
    isolated=read('isolated_runtime_tests.json',{})
    write('tests.json',dict(return_code=test.returncode,tests=int(n[1]) if n else None,skipped=int(skip[1]) if skip else 0,
        isolated_CUDA_integration_tests=isolated,
        all_unique_tests_executed=bool(test.returncode==0 and isolated.get('passed') and isolated.get('skipped',1)==0
            and isolated.get('tests')==(int(skip[1]) if skip else 0))))
    before=read('protected_before.json');changed=[]
    for name,old in before.items():
        p=ROOT/name
        if not p.is_file():changed.append(name);continue
        s=p.stat()
        if dict(sha256=sha256_file(p),size=s.st_size,mtime_ns=s.st_mtime_ns)!=old:changed.append(name)
    original_env={p.relative_to(ROOT).as_posix() for p in (ROOT/'.venv-reranker').rglob('*') if p.is_file()}
    original_expected={n for n in before if n.startswith('.venv-reranker/')}
    environment_membership={}
    for environment in ('.venv','.venv-reranker','.venv-ragas'):
        expected={n for n in before if n.startswith(environment+'/')}
        if expected:
            actual={p.relative_to(ROOT).as_posix() for p in (ROOT/environment).rglob('*') if p.is_file()}
            environment_membership[environment]=dict(added=sorted(actual-expected),removed=sorted(expected-actual))
    http=None
    try:
        with urlopen('http://127.0.0.1:8767/_stcore/health',timeout=10) as res:http=res.status
    except Exception:pass
    write('compatibility.json',dict(protected_count=len(before),changed=changed,unchanged=not changed,
        original_reranker_files_added=sorted(original_env-original_expected),original_reranker_files_removed=sorted(original_expected-original_env),
        virtual_environment_membership=environment_membership,
        production_Streamlit_HTTP=http,SQLite_unchanged='rag_store.sqlite3' not in changed,
        no_policy_changes=True,no_virtual_environment_changes=not any(n.startswith('.venv') for n in changed)
            and not any(v['added'] or v['removed'] for v in environment_membership.values())))
    small={c:{'n':reports[c]['n_total'],'IFR':reports[c]['final_IFR'],'latency_ms':reports[c]['metrics']['e2e_total_latency_ms'],
        'TTFT_ms':reports[c]['metrics']['e2e_ttft_final_ms']} for c in by}
    def number(v):return f'{v:.2f}' if isinstance(v,(int,float)) else '未取得'
    summary_text=f'''# Phase 19B Execution Revision 2

Experiment：`phase19B_exec_r2`。marine-edge-workstation-01；Windows 11 build 26300／RTX 4060 8 GiB／32 GiB RAM／Ollama 0.35.0。

本報告是實際 Full Edge RAG feasibility/performance；Benchmark 為 AI-generated Corpus-Grounded Silver，沒有人工驗證的品質優勝模型。

## Gates 與 runtime continuity

Fresh torch／CUDA／指定 reranker model／single-query gate 已保存於 `fresh_preflight.json`。
E4 60-question reproduction：{read('e4_reproduction.json',{}).get('matched',0)}/60。
完整有效 formal blocks：{valid}；無效 blocks：{invalid}；主要 requests：{len(primary)}/540。
無效或部分 block 的 requests 保留 diagnostic，未拼接至其他 primary run。

## Full-RAG performance

所有 latency 以下均為毫秒，包含目前機器上的 telemetry/checkpoint overhead。

| Condition | n | TTFT mean / median / p95 | Total latency mean / median / p95 | Final IFR |
|---|---:|---|---|---:|
'''
    for c in by:
        tt=reports[c]['metrics']['e2e_ttft_final_ms'];lat=reports[c]['metrics']['e2e_total_latency_ms']
        summary_text+=f"| {c} | {reports[c]['n_total']} | {' / '.join(number(tt[k]) for k in ('mean','median','p95'))} | {' / '.join(number(lat[k]) for k in ('mean','median','p95'))} | {number(reports[c]['final_IFR'])} |\n"
    summary_text+='\n## R0 stage latency\n\n| Stage | Mean | Median | p95 | Max |\n|---|---:|---:|---:|---:|\n'
    for key in ('bm25_ms','dense_embedding_ms','dense_search_ms','rrf_ms','reranker_ms','context_assembly_ms','retrieval_to_context_ms'):
        x=reports['R0_edge_retrieval_only']['metrics'][key]
        summary_text+=f"| {key} | {' | '.join(number(x[k]) for k in ('mean','median','p95','max'))} |\n"
    summary_text+='\n## Hardware 與 quality status\n\n| Model | Hardware | Quality |\n|---|---|---|\n'
    for r in matrix:summary_text+=f"| {r['model']} | {r['hardware_status']} | {r['quality_status']} |\n"
    summary_text+='\n## Generator 與各階段\n\n| Condition | Stage | Mean / median / p95 (ms) |\n|---|---|---|\n'
    for c in ('F1_edge_fullrag_gemma','F2_edge_fullrag_qwen'):
        for key in ('retrieval_to_context_ms','generator_load_reload_ms','generator_ttft_any_ms',
                    'generator_ttft_final_ms','generation_completion_ms'):
            x=reports[c]['metrics'][key]
            summary_text+=f"| {c} | {key} | {' / '.join(number(x[k]) for k in ('mean','median','p95'))} |\n"
    summary_text+='\n## Context length 與 three-run stability\n\n| Condition | Context | Distinct questions | Median TTFT / latency (ms) | IFR |\n|---|---|---:|---|---:|\n'
    for c in by:
        for band in ('short','medium','long'):
            x=context[c][band];m=x['metrics']
            summary_text+=f"| {c} | {band} | {x['distinct_questions']} | {number(m['e2e_ttft_final_ms']['median'])} / {number(m['e2e_total_latency_ms']['median'])} | {number(x['final_IFR'])} |\n"
    summary_text+='\nCV 以下為三個有效 run median 的變異係數。\n\n'
    for c in by:summary_text+=f"- {c}: {json.dumps(stability[c]['CV_of_run_medians'],ensure_ascii=False)}\n"
    summary_text+='\n## Memory、placement 與 residency\n\nRAM 為 whole-system used；dedicated VRAM 為 whole-device；shared GPU 為 RAM-backed WDDM adapter usage。以下為取樣 peak，非絕對 peak。\n\n| Condition | RAM / dedicated / shared sampled peak (GiB) | GPU peak temperature |\n|---|---|---|\n'
    for c in by:
        mm=mem[c]
        peaks=[mm[k]['max']/2**30 if mm[k]['max'] is not None else None for k in
            ('system_RAM_used_bytes','dedicated_VRAM_whole_device_bytes','shared_GPU_RAM_backed_adapter_bytes')]
        summary_text+=f"| {c} | {' / '.join(number(v) for v in peaks)} | {number(mm['GPU_temperature_C']['max'])} |\n"
    summary_text+='\n- Processor allocation：`processor_split.json`；CPU fallback／shared-memory spill 原因不足以直接判定時保留 null。\n'
    summary_text+='- Process working-set／private-commit 與 WDDM process GPU counters 另存，不與 whole-device physical memory 相加。\n'
    summary_text+='- GPU board power 無可靠讀值時保留 null；不估算 whole-system power。\n'
    summary_text+='\n## Sustained Full RAG 與 reliability\n\n'
    for label in ('gemma','qwen'):
        ss=read('sustained_'+label+'.json');e=ss['execution'];q=ss['overall']
        summary_text+=f"- {label}: completed={e.get('completed')}, configured=1800 sec, elapsed={number(e.get('elapsed_seconds'))} sec, requests={q['n_total']}, final IFR={number(q['final_IFR'])}。六個 5-minute intervals 與 drift 保存在 sustained report。\n"
    for c in ('F1_edge_fullrag_gemma','F2_edge_fullrag_qwen'):
        g=reports[c]['generation']
        summary_text+=f"- {c}: first-pass schema={number(g['first_pass_schema_valid'])}, final schema={number(g['final_schema_valid'])}, citation parse={number(g['citation_parse_rate'])}, strict citation validity={number(g['strict_citation_validity']['rate'])}, retries={g['retry_trigger_count']}, recovered={g['retry_success_count']}。\n"
    summary_text+='\n## Cross-phase overhead 與 behavior preservation\n\n'
    for model,comp in comparisons.items():
        summary_text+=f"- {model}: median TTFT difference={number(comp['TTFT_final']['difference_ms'])} ms；median total latency difference={number(comp['total_latency']['difference_ms'])} ms。這是 cross-phase descriptive，不能全歸因於 Retrieval。\n"
    summary_text+='- Status／schema／citation-set／normalized answer similarity 分別與 Phase 17、19A 比較，見 `behavior_preservation.json`；未重跑 RAGAS。\n'
    summary_text+=f"\nCode Integrity lifecycle windows 共 {len(unique_events)} 個新 event records；相關 reranker execution blocks={sum(r['relevant_execution_block_count'] for r in native.values())}。實際允許執行的原因 unknown，沒有永久修復宣稱。\n"
    summary_text+=f'\n`phase20_research_integration_ready={str(research).lower()}`；`final_model_selection_ready=false`。\n'
    summary_text+='\n## Compatibility 與 tests\n\n'
    summary_text+=f"Tests：{int(n[1]) if n else 'unknown'}，skipped={int(skip[1]) if skip else 0}，return code={test.returncode}。Protected files={len(before)}，changed={len(changed)}；Production HTTP={http}。\n"
    summary_text+='\n## 解讀限制\n\n'+ '\n'.join('- '+l for l in limitations)+'\n'
    summary_text+='\n## 下一步\n\nTechnical feasibility 支持時可規劃 Phase 20 research integration；final model selection 仍須補足 Independent Judge／human citation-support review。未進行 production migration、RAGAS rerun 或 tuning。\n'
    (OUT/'phase19B_exec_r2_summary.md').write_text(summary_text,encoding='utf-8')
    write('output_checksums.json',{p.relative_to(ROOT).as_posix():sha256_file(p) for p in OUT.rglob('*') if p.is_file() and p.name!='output_checksums.json'})
    print(json.dumps({'conditions':small,'valid_blocks':valid,'invalid_blocks':invalid,'protected_changed':changed,
        'HTTP':http,'tests_return_code':test.returncode,'research_ready':research},ensure_ascii=True),flush=True)
    if test.returncode or changed:raise SystemExit(1)

def read_jsonl_path(p):return [json.loads(l) for l in p.read_text(encoding='utf-8').splitlines()]
if __name__=='__main__':main()
