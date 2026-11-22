"""Descriptive reports with explicit unmeasured values and separate quality/hardware status."""
from __future__ import annotations

import json
import subprocess
from collections import Counter
from datetime import datetime, timezone

from .core import MODELS, OPTIONS, QUALITY, TTFT_DEFINITION, WARMUP, schedule, summary, deployment_row, pareto, hardware_status
from .inputs import ROOT, OUT, BUNDLE, TARGET, prepare_bundle, load_target, validate_target_schema, freeze_write
from .runner import read_rows
from .core import target_gate
from ..generation.frozen import sha256_file


def write_json(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


def reliability(rows, expected=180):
    n=len(rows)
    ratio=lambda count: count/expected if n and expected else None
    first=sum(r['first_pass_schema_valid'] for r in rows)
    final=sum(r['final_schema_valid'] for r in rows)
    retry=sum(r['retry_triggered'] for r in rows)
    cites=sum(r['result']['citation_count'] for r in rows)
    valid=sum(r['result']['strict_citation_count'] for r in rows)
    return dict(n_expected=expected,n_executed=n,n_missing=expected-n,
        first_pass_schema_validity=ratio(first),final_schema_validity=ratio(final),
        first_pass_valid_count=first,final_valid_count=final,
        citation_parse_rate=ratio(sum(r['final_citation_parse'] for r in rows)),
        strict_citation_validity=valid/cites if cites else None,
        citation_denominator=cites,retry_trigger=retry,retry_success=sum(r['retry_success'] for r in rows),
        generation_error=sum(r['status']=='generation_error' for r in rows),
        answered=sum(r['status']=='answered' for r in rows),abstained=sum(r['status']=='insufficient_evidence' for r in rows),
        input_truncation=sum(r.get('context_budget',{}).get('input_truncated') is True for r in rows),
        input_truncation_unknown=sum(r.get('context_budget',{}).get('input_truncated') is None for r in rows),
        completion_truncation=sum(r.get('completion_truncation',False) for r in rows),
        technical_failure_attempt_counts=dict(Counter(f['category'] for r in rows for f in r.get('technical_failures',[]))),
        status='not_executed' if not n else 'complete' if n==expected else 'benchmark_incomplete',
        failed_and_missing_not_removed_from_reliability_denominator=True)


def validate_results(rows,cold,question_ids):
    allowed=set(question_ids)
    seen=set()
    for r in rows:
        key=(r['model'],r['repetition'],r['question_id'])
        if r['stage']!='warm' or r['model'] not in MODELS or r['repetition'] not in (1,2,3) or r['question_id'] not in allowed or key in seen:
            raise ValueError('Invalid or duplicate warm benchmark record')
        seen.add(key)
    for model in MODELS:
        for repetition in (1,2,3):
            ids=[r['question_id'] for r in rows if r['model']==model and r['repetition']==repetition]
            if ids!=question_ids[:len(ids)]:raise ValueError('Frozen warm question order changed')
    cold_keys=[(r['model'],r['repetition']) for r in cold]
    if len(cold_keys)!=len(set(cold_keys)) or any(r['stage']!='cold' for r in cold):
        raise ValueError('Cold/warm records mixed or duplicated')


def compile_reports(manifest,rows,cold):
    validate_results(rows,cold,manifest['question_ids'])
    models={m:[r for r in rows if r['model']==m] for m in MODELS}
    latency={};ttft={};throughput={};contexts={};reliable={};behavior={};matrix=[];memory={};power={};thermal={}
    for m,rs in models.items():
        # Reloaded/crashed requests are not presented as genuine warm latency; denominator remains visible.
        warm=[r for r in rs if r.get('warm_residency_verified') is True]
        latency[m]={key:summary([r.get(key) for r in warm],180) for key in
            ('generation_latency_seconds','total_request_latency_seconds','retry_inclusive_latency_seconds')}
        ttft[m]={key:summary([r.get(key) for r in warm],180) for key in
            ('ttft_final_answer_seconds','ttft_any_token_seconds','retry_inclusive_ttft_final_answer_seconds')}
        throughput[m]=dict(runtime=summary([r.get('tokens',{}).get('runtime_tps') for r in warm],180),
            visible_answer=summary([r.get('tokens',{}).get('visible_answer_tps') for r in warm],180),
            reasoning_token_separation_available=bool(warm) and all(r.get('tokens',{}).get('reasoning_token_separation_available') for r in warm),
            runtime_tps_semantics=dict(Counter(r.get('tokens',{}).get('runtime_tps_semantics','unknown') for r in warm)),
            token_semantics_comparability_not_assumed=True)
        reliable[m]=reliability(rs)
        contexts[m]={}
        for band in ('short','medium','long'):
            subset=[r for r in warm if r['context_band']==band]
            count={'short':60,'medium':63,'long':57}[band]
            contexts[m][band]=dict(ttft=summary([r.get('ttft_final_answer_seconds') for r in subset],count),
                runtime_tps=summary([r.get('tokens',{}).get('runtime_tps') for r in subset],count),
                latency=summary([r.get('retry_inclusive_latency_seconds') for r in subset],count),
                reliability=reliability([r for r in rs if r['context_band']==band],count),
                interpretation='Descriptive; missing target/results prevents context-effect inference' if not subset else 'Descriptive fixed subset, no population claim')
            contexts[m][band]['memory_sampled_peak']={kind:summary([
                max((v['value_bytes'] for s in r.get('telemetry',{}).get('samples',[]) for v in s.get('memory',[])
                     if v['kind']==kind and v['scope']=='whole_device'),default=None) for r in subset],count)
                for kind in ('RAM','VRAM')}
        behavior[m]=dict(n_compared=len(rs),
            normalized_answer_similarity=summary([r.get('behavior',{}).get('normalized_answer_similarity') for r in rs],180),
            status_agreement=summary([int(r['behavior']['status_agreement']) for r in rs],180),
            citation_set_agreement=summary([int(r['behavior']['citation_set_exact']) for r in rs],180),
            citation_set_jaccard=summary([r['behavior']['citation_set_jaccard'] for r in rs],180),
            schema_agreement=summary([int(r['behavior']['schema_agreement']) for r in rs],180),
            silver_token_f1=summary([(r['result'].get('silver_reference_similarity') or {}).get('f1') for r in rs],180),
            required_citation_recall=summary([r['result']['required_evidence_citation']['strict_recall_all_questions'] for r in rs],180),
            calculation_numeric=[dict(question_id=r['question_id'],repetition=r['repetition'],result=r['result']['calculation_numeric_evaluation'])
                for r in rs if r['result'].get('calculation_numeric_evaluation')],
            reference_alignment_bias_possible=True,reference_generator='Gemma 2 9B',human_validated=False)
        samples=[s for r in rs for s in r.get('telemetry',{}).get('samples',[])]
        mem=[v for s in samples for v in s.get('memory',[])]
        baselines=[x for r in rs for phase in ('loaded_idle',) for x in r.get(phase,{}).get('memory',[])]
        cold_idle=[x for r in cold if r['model']==m for x in r.get('idle',{}).get('memory',[])]
        memory[m]=dict(measurements_available=bool(mem),sampled_peak_only=True,scopes={},
            no_RAM_plus_unified_memory_double_count=True,process_specific_peak_RAM=None,process_specific_peak_VRAM=None)
        for kind in ('RAM','VRAM','unified_memory'):
            for scope in ('whole_device','process_family','process_specific','unified_pool'):
                vals=[x['value_bytes'] for x in mem if x['kind']==kind and x['scope']==scope]
                if vals:
                    memory[m]['scopes'][kind+'_'+scope]=dict(inference=summary(vals),
                        idle=summary([x['value_bytes'] for x in cold_idle if x['kind']==kind and x['scope']==scope]),
                        model_loaded=summary([x['value_bytes'] for x in baselines if x['kind']==kind and x['scope']==scope]))
        powers=[s['power_watts'] for s in samples if s.get('power_watts') is not None]
        temps=[s['temperature_c'] for s in samples if s.get('temperature_c') is not None]
        from .runtime import energy_from_samples
        power[m]=dict(power_metrics_available=bool(powers),inference_watts=summary(powers),
            scopes=sorted({s['power_scope'] for s in samples if s.get('power_scope')}),
            idle_watts=summary([r['idle'].get('power_watts') for r in cold if r['model']==m and r.get('idle')]),
            model_loaded_idle_watts=summary([r.get('loaded_idle',{}).get('power_watts') for r in rs]),
            measured_sample_integral_joules=summary([energy_from_samples(r.get('telemetry',{}).get('samples',[])) for r in rs]),
            energy_window='sample timestamps around execution protocol; includes observer overhead, no unmeasured extrapolation')
        thermal[m]=dict(thermal_metrics_available=bool(temps),inference_temperature_c=summary(temps),
            start_temperature_c=temps[0] if temps else None,end_temperature_c=temps[-1] if temps else None,
            thermal_throttling=None,clock_reduction=None)
        cr=[r for r in cold if r['model']==m]
        complete_cold=len(cr)==3 and all(r['independent_cold_start_verified'] for r in cr)
        status=hardware_status(completed=len(rs),required=180,cold_verified=complete_cold,
            failure_count=reliable[m]['generation_error'],input_audited=reliable[m]['input_truncation_unknown']==0 and reliable[m]['input_truncation']==0,
            limitations=bool(rs) and (any(not r.get('warm_residency_verified') for r in rs) or reliable[m]['completion_truncation']>0))
        scopes=memory[m]['scopes']
        ram=(scopes.get('RAM_whole_device') or {}).get('inference',{}).get('max')
        vram=(scopes.get('VRAM_whole_device') or {}).get('inference',{}).get('max')
        matrix.append(deployment_row(m,status,dict(schema_reliability=reliable[m]['final_schema_validity'],
            TTFT=ttft[m]['ttft_final_answer_seconds']['mean'],TPS=throughput[m]['runtime']['mean'],
            visible_answer_TPS=throughput[m]['visible_answer']['mean'],
            p95_latency=latency[m]['retry_inclusive_latency_seconds']['p95'],RAM=ram,VRAM=vram,unified_memory=None,
            memory_scope='whole_device_sampled' if ram is not None else None,power=power[m]['inference_watts']['mean'],
            thermal=thermal[m]['inference_temperature_c']['max'],
            limitations=['actual target not specified; no benchmark performed'] if not rs else
                ['Human validation absent; Qwen quality unresolved; measurement gaps remain explicit'])))
    return dict(latency=latency,ttft=dict(definition=TTFT_DEFINITION,by_model=ttft),throughput=throughput,
        context_length_analysis=contexts,reliability=reliable,behavior_preservation=behavior,
        memory=memory,power=power,thermal=thermal,
        model_deployment_matrix=dict(benchmark_scope='generator_only',rows=matrix,composite_score=None),
        pareto_analysis=pareto(matrix,{'TTFT':'min','p95_latency':'min','RAM':'min'},('memory_scope',)),
        cold_start=dict(n_measured=len(cold),expected_total=12,records=cold,
            warm_metrics_separate=True,OS_cache_purged=False),
        sustained_load=dict(required=False,executed=False,duration_seconds=None,
            reason='Frozen Phase 18 protocol specifies no sustained-load test duration; not invented after results'))


def prepare():
    OUT.mkdir(parents=True,exist_ok=True)
    rows,models,bundle=prepare_bundle()
    target=load_target();schema_errors=validate_target_schema(target) if target else ['target missing']
    gate=target_gate(target)
    gate['target_profile_schema_valid']=not schema_errors
    gate['schema_errors']=schema_errors
    gate['edge_execution_ready']=gate['edge_execution_ready'] and not schema_errors
    target_manifest=dict(target_device=target,target_profile_sha256=sha256_file(TARGET) if TARGET.is_file() else None,
        gate=gate,actual_device_designated=bool(target and target.get('target_device_confirmed')),
        research_host_used_as_automatic_target=False)
    write_json(OUT/'target_device_manifest.json',target_manifest)
    for m in MODELS:
        freeze_write(OUT/'model_manifests'/(m.replace(':','_')+'.json'),
            (json.dumps(models[m],ensure_ascii=False,indent=2)+'\n').encode('utf-8'))
    manifest=dict(phase='19A',benchmark_scope='generator_only',requested_deployment_mode=(target or {}).get('deployment_mode','generator_only'),
        status='prepared_not_executed' if gate['edge_execution_ready'] else 'blocked_target_device',
        edge_execution_ready=gate['edge_execution_ready'],target_device_manifest_sha256=sha256_file(OUT/'target_device_manifest.json'),
        target_profile_sha256=target_manifest['target_profile_sha256'],acceptance_thresholds_defined=gate['acceptance_thresholds_defined'],
        acceptance_thresholds=(target or {}).get('acceptance_thresholds'),benchmark_mode=gate['benchmark_mode'],
        models=list(MODELS),model_manifest_sha256={m:sha256_file(OUT/'model_manifests'/(m.replace(':','_')+'.json')) for m in MODELS},
        input_bundle_sha256=sha256_file(BUNDLE/'bundle_manifest.json'),source_subset_sha256=bundle['source_subset_sha256'],
        parent_frozen_hashes=bundle['parent_frozen_hashes'],question_ids=bundle['question_ids'],question_count=60,
        query_styles=dict(Counter(r['subset_row']['query_style'] for r in rows)),
        context_bands=dict(Counter(r['subset_row']['context_band'] for r in rows)),
        generation_options=OPTIONS,prompt_version='generation_v2',schema_version='generation_output_v2',
        generation_protocol='v2.2',maximum_attempts=2,technical_retry_only=True,
        cold_repetitions_per_model=3,warm_full_runs_per_model=3,expected_warm_questions_per_model=180,
        expected_total_warm_questions=720,warmup=WARMUP,warmup_excluded=True,block_schedule=schedule(),
        question_order='exact Phase 18 frozen order for every model and repetition',parallel_requests=False,
        ttft_definition=TTFT_DEFINITION,reasoning_token_separation_not_assumed=True,
        telemetry_sample_interval_seconds=1.0,memory_scope='explicit per sample; no process/device/unified mixing',
        sustained_load=dict(required=False,duration_seconds=None,source='No fixed duration in frozen Phase 18 protocol'),
        quality_status=QUALITY,human_reviewed_outputs=0,human_reviewed_claims=0,
        independent_judge_available=False,Qwen_judge_conflict=True,
        reference_generator='Gemma 2 9B',reference_alignment_bias_possible=True,
        no_judge_execution=True,no_model_download=True,no_quantization_change=True,
        runtime_preflight_executed=False,hardware_benchmark_executed=False,
        all_models_same_prompt_context_schema=True,full_RAG_latency_measured=False,
        git_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip())
    freeze_write(OUT/'experiment_manifest.json',(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n').encode('utf-8'))
    write_json(OUT/'input_validation.json',dict(input_bundle_valid=True,questions=60,context_records=300,
        model_artifact_manifests_validated=4,question_order_preserved=True,context_checksum_validation=True,
        source_subset_sha256=bundle['source_subset_sha256'],query_styles=manifest['query_styles'],context_bands=manifest['context_bands'],
        prompt_unchanged=True,schema_unchanged=True,generation_calls=0,retrieval_calls=0))
    reports=compile_reports(manifest,[],[])
    for name,value in reports.items():write_json(OUT/(name+'.json'),value)
    for filename in ('warm_runs.jsonl','attempts.jsonl','cold_runs.jsonl','warmup_outputs.jsonl'):
        freeze_write(OUT/filename,b'')
    limitations=dict(edge_execution_ready=gate['edge_execution_ready'],blocking_reasons=gate['errors'],
        target_hardware_unknown=True,actual_benchmark_executed=False,
        acceptance_thresholds_defined=False,descriptive_feasibility_only=True,
        Windows_reranker_limitation='Known c10_cuda.dll / WinError 4551; E4 not rerun, frozen contexts used; existing E4 metrics not invalidated',
        memory_sampling='Sampled whole-device memory where available; no process peak invented; unified pool remains null without adapter',
        sensors='No target sensors queried; power/thermal unknown. GPU board power is not whole-device power.',
        tokenizer='No inferred visible/reasoning token counts; null when runtime does not expose them',
        cold_start='Verify model absence from /api/ps; OS cache remains explicit, no false independent start',
        hardware_adapters_unvalidated_on_actual_device=True,human_validation_missing=True,
        no_primary_quality_winner=True,phase19B_not_executed=True,phase20_production_migration_not_authorized=True)
    write_json(OUT/'environment_limitations.json',limitations)
    text='''# Phase 19A — Actual Edge Device Feasibility tooling

## Execution status

**blocked_target_device — no actual hardware benchmark performed.**
The target profile is a pending template, not a designation of the RTX 4060 research host.
`edge_execution_ready = false`; `acceptance_thresholds_defined = false`.
Deployment scope is generator_only. These reports contain no full-RAG latency.

## Frozen inputs and execution plan

60 questions preserved from Phase 18: Direct/Paraphrase/Contextual 20/20/20,
short/medium/long 20/21/19. All 300 E4 Top-5 context records, order and checksums validated.
Four original model digests and quantizations retained; no model download or variant.
Native context 8192/32768/131072 as individually recorded; experimental num_ctx stays 8192.
Same generation_v2 prompt, original schema, protocol v2.2, temperature 0, top_p 1,
seed 15015, output budget 1024, maximum two technical attempts.

Each model has three independent-unload-verified cold starts and three complete warm
60-question runs planned. Rotating model blocks keep frozen question order.
Warm-up is fixed and excluded. Failures and missing questions retain their denominators.
The frozen Phase 18 protocol prescribes no sustained-load duration; no new timed test added.

## Measurements

All cold/warm TTFT, TPS, latency, RAM/VRAM/unified memory, power, thermal,
runtime reliability and behavior-preservation measurements are currently **null / not executed**.
Historical RTX 4060 results are not copied into target-device measurements.
Final-output content TTFT and any-token TTFT are separate. Mixed reasoning/content
throughput cannot be silently compared as visible-answer throughput.
Memory scope stays explicit; power integrates observed sensor samples only.

## Quality and hardware are separate

Gemma: conditional_candidate. Qwen: evaluation_unresolved. DeepSeek 8B/7B: low_priority.
All four hardware_status values are benchmark_incomplete. No performance result promotes quality.
Human-reviewed outputs/claims remain 0/0. Qwen judge conflict and Gemma reference bias remain.
There is no human-validated best model, composite score, Pareto winner or final quality winner.

## Next gate

Provide an explicitly selected physical target, hardware/memory/OS/runtime/storage,
sensor capabilities and execution-node identity in configs/edge_target_device.yaml.
The file is JSON-compatible YAML 1.2, as used by other project configurations.
Do not invent acceptance thresholds after results. With none, use descriptive feasibility.
Use immutable copies in data/evaluation/edge/phase19_inputs_v1 with bundle SHA verification.
Only an explicit execute invocation on the named device can run the gated adapter.
Actual device adapters and sensors still require runtime preflight; synthetic tests do not prove device feasibility.
Phase 19B requires completed 19A and an explicit full_rag scope; no automatic execution.
Phase 20 final system integration lacks actual device evidence and is not started.
'''
    (OUT/'phase19_summary.md').write_text(text,encoding='utf-8')
    return manifest
