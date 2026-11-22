"""Three cold starts and rotating three-pass warm runs on the explicitly named target."""
from __future__ import annotations

import json
import platform
import threading
import time
from pathlib import Path

from .core import MODELS, OPTIONS, WARMUP, schedule, MAX_ATTEMPTS, behavior_preservation
from .inputs import load_target, load_bundle, validate_target_schema, BUNDLE, OUT, freeze_write
from .runtime import require_target, OllamaEdge, Telemetry, TargetBlocked


def append_jsonl(path,row):
    import os
    with path.open('a',encoding='utf-8',newline='\n') as f:
        f.write(json.dumps(row,ensure_ascii=False,sort_keys=True)+'\n');f.flush();os.fsync(f.fileno())


class ReadyProbe:
    """Readiness observed by polling, with explicit upper-bound timing semantics."""
    def __init__(self,adapter,model):
        self.adapter=adapter;self.model=model;self.start_time=time.perf_counter();self.seconds=None
        self.stop=threading.Event();self.errors=[];self.thread=threading.Thread(target=self.run,daemon=True)

    def run(self):
        while not self.stop.is_set():
            try:
                if any(r.get('name',r.get('model'))==self.model for r in self.adapter.allocations().get('models',[])):
                    self.seconds=time.perf_counter()-self.start_time;return
            except Exception as exc:self.errors.append(str(exc))
            self.stop.wait(.25)

    def finish(self):
        self.stop.set();self.thread.join(timeout=11)
        return dict(first_ready_observed_seconds=self.seconds,poll_interval_seconds=.25,
                    semantics='first /api/ps resident observation; upper bound, not exact internal load completion',errors=self.errors)


def execute_protocol(question,contexts,model,adapter,folder,stage,repetition,prompt,schema,*,call_hook=None):
    """Reuse the frozen parser/evaluator and retry decision without semantic repair."""
    from ..generation.runner_v2 import _run_one_v2
    from ..generation.retry_v21 import build_attempt_record, should_retry
    attempts=[];captured=[];start=time.perf_counter()
    for number in range(1,MAX_ATTEMPTS+1):
        capture={}
        def call(**kw):
            fn=call_hook or adapter.generation
            value=fn(model=model['name'],system_prompt=kw['system_prompt'],user_prompt=kw['user_prompt'],schema=schema,
                thinking_capable='thinking' in model.get('capabilities',[]),
                log_path=adapter.target.get('runtime',{}).get('log_path'))
            capture.update(value);return value
        result,raw=_run_one_v2(question,contexts,condition='G1',model=model['name'],base_url=adapter.endpoint,
            prompt=prompt,corpus_ids={c['chunk_id'] for c in contexts},call_fn=call)
        attempt=build_attempt_record(question_id=question['question_id'],attempt_number=number,result=result,raw=raw)
        attempt.update(model=model['name'],stage=stage,repetition=repetition,captured_runtime=capture)
        append_jsonl(folder/'attempts.jsonl',attempt);attempts.append(attempt);captured.append(capture)
        check={**result,'execution_error':capture.get('execution_error')}
        if not should_retry(check,attempt_number=number):break
    final=attempts[-1]['result'];first=attempts[0]
    success=attempts[-1]['attempt_valid']
    final_ttft=captured[-1].get('ttft_final_answer_seconds')
    before=sum(a['generation_latency_seconds'] for a in attempts[:-1])
    technical_failures=[]
    for a,c in zip(attempts,captured):
        text=str(c.get('execution_error') or '').casefold()
        failures=[]
        if any(t in text for t in ('out of memory','cuda oom','allocation failed')):failures.append('OOM')
        if 'timeout' in text or 'timed out' in text:failures.append('timeout')
        if any(t in text for t in ('connectionerror','connection refused','runtime crash')):failures.append('runtime_crash_or_unavailable')
        if 'load' in text and any(t in text for t in ('failed','error')):failures.append('model_load_failure')
        if c.get('context_window_budget',{}).get('context_capacity_failure'):failures.append('context_capacity_failure')
        if c.get('context_window_budget',{}).get('input_truncated') is True:failures.append('input_truncation')
        if c.get('done_reason')=='length':failures.append('completion_truncation')
        if not a['schema_status']:failures.append('schema_failure')
        if text and not failures:failures.append('unknown_technical_failure')
        technical_failures.extend(dict(attempt_number=a['attempt_number'],category=f) for f in failures)
    return dict(model=model['name'],stage=stage,repetition=repetition,question_id=question['question_id'],
        attempt_count=len(attempts),first_pass_schema_valid=first['schema_status'],final_schema_valid=attempts[-1]['schema_status'],
        retry_triggered=len(attempts)>1,retry_success=len(attempts)>1 and success,
        retry_inclusive_latency_seconds=time.perf_counter()-start,
        total_request_latency_seconds=sum(a['generation_latency_seconds'] for a in attempts),
        generation_latency_seconds=captured[-1]['latency_seconds'],
        ttft_final_answer_seconds=final_ttft,
        retry_inclusive_ttft_final_answer_seconds=before+final_ttft if success and final_ttft is not None else None,
        first_request_ttft_seconds=captured[0].get('ttft_final_answer_seconds'),
        ttft_any_token_seconds=captured[-1].get('ttft_any_token_seconds'),
        runtime_load_duration_ns=captured[0].get('load_duration_ns'),
        tokens=captured[-1].get('token_metrics',{}),
        context_budget=captured[-1].get('context_window_budget',{}),
        completion_truncation=any(c.get('done_reason')=='length' for c in captured),
        first_pass_citation_parse=first['citation_parse_status'],
        final_citation_parse=attempts[-1]['citation_parse_status'],
        technical_failures=technical_failures,result=final,status=final['status'],raw_attempts_preserved=True)


def execute(*,target_path=None,bundle_path=BUNDLE,output_root=OUT/'runs',adapter_factory=OllamaEdge):
    """Guard runs before constructing a transport or touching any model residency."""
    target=load_target(target_path) if target_path else load_target()
    errors=validate_target_schema(target) if target is not None else ['missing target']
    if errors:raise TargetBlocked('Target manifest schema error: '+str(errors))
    require_target(target)
    rows,bundle=load_bundle(bundle_path)
    models={m:json.loads((OUT/'model_manifests'/(m.replace(':','_')+'.json')).read_text(encoding='utf-8')) for m in MODELS}
    adapter=adapter_factory(target);actual=adapter.preflight(models)
    from .core import json_hash
    run_id='edge_'+json_hash(dict(target=target,bundle=bundle,models=models))[:20]
    folder=Path(output_root)/run_id
    if folder.exists():
        raise TargetBlocked('Refusing to mix, restart or select results in an existing physical-device experiment; inspect its incomplete manifest')
    folder.mkdir(parents=True)
    manifest=dict(experiment_id=run_id,target=target,target_gate_passed=True,models=actual,
        source_bundle=bundle,generation_options=OPTIONS,maximum_attempts=2,
        benchmark_scope='generator_only',requested_deployment_mode=target['deployment_mode'],
        warm_full_runs_per_model=3,cold_repetitions_per_model=3,question_order=bundle['question_ids'],question_ids=bundle['question_ids'],
        block_schedule=schedule(),runtime_settings_declared=target['runtime_settings'],
        runtime_settings_applied='Frozen OPTIONS only; thread/batch/offload defaults observed, never per-model tuning',
        sustained_load_required=False,sustained_load_reason='Frozen Phase 18 protocol does not prescribe a sustained-load duration',
        execution_environment={'node':platform.node(),'OS':platform.platform(),'python':platform.python_version(),
            'CPU_identifier':platform.processor(),'accelerator_runtime_version':None,
            'accelerator_runtime_version_reason':'Ollama does not expose a CUDA/ROCm version through its model API; no invented version',
            'CPU_threads_observed':None,'batch_size_observed':None,
            'GPU_offload_observation':'Per-request /api/ps size/size_vram retained; not a guessed per-layer count'},
        human_validation_available=False,primary_quality_winner_selected=False)
    freeze_write(folder/'experiment_manifest.json',(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n').encode('utf-8'))
    prompt=(Path(bundle_path)/'generation_v2.txt').read_text(encoding='utf-8').strip()
    schema=json.loads((Path(bundle_path)/'generation_output_v2.schema.json').read_text(encoding='utf-8'))
    loaded=adapter.allocations().get('models',[])
    if any(r.get('name',r.get('model')) not in MODELS for r in loaded):
        raise TargetBlocked('Unrelated resident models on target; no automatic unload of another workload')
    for name in MODELS:
        for resident in adapter.allocations().get('models',[]):
            resident_name=resident.get('name',resident.get('model'))
            if resident_name in MODELS:adapter.unload(resident_name)
        for repetition in range(1,4):
            unload=adapter.unload(name)
            cold=dict(model=name,stage='cold',repetition=repetition,unload=unload,
                independent_cold_start_verified=unload['unloaded'],OS_page_cache_cleared=False,
                limitation='Unloaded model process state; OS disk cache is not forcibly purged')
            if not unload['unloaded']:
                cold['status']='unload_unverified';append_jsonl(folder/'cold_runs.jsonl',cold);continue
            idle=Telemetry(target,phase='idle').sample();sampler=Telemetry(target);sampler.start()
            probe=ReadyProbe(adapter,name);probe.thread.start()
            first=rows[0]
            result=execute_protocol(first['question'],first['contexts'],models[name],adapter,folder,'cold',repetition,prompt,schema)
            cold.update(result,ready_probe=probe.finish(),idle=idle,telemetry=sampler.finish())
            append_jsonl(folder/'cold_runs.jsonl',cold)
        adapter.unload(name)
    references={(r['model'],r['question_id']):r for r in read_rows(Path(bundle_path)/'phase17_behavior_references.jsonl')}
    for block in schedule():
        name=block['model'];repetition=block['repetition']
        # Each whole-model block applies the same load/warm-up rule; no query reordering.
        for resident in adapter.allocations().get('models',[]):
            if resident.get('name',resident.get('model')) in MODELS:
                adapter.unload(resident.get('name',resident.get('model')))
        from ..generation.runner_v2 import format_v2_user_prompt
        warm=adapter.generation(model=name,system_prompt=prompt,user_prompt=format_v2_user_prompt(WARMUP,WARMUP['contexts']),
            schema=schema,thinking_capable='thinking' in models[name]['capabilities'])
        append_jsonl(folder/'warmup_outputs.jsonl',dict(model=name,repetition=repetition,stage='warmup',raw=warm,excluded_from_formal_metrics=True))
        loaded_idle=Telemetry(target,phase='model_loaded').sample()
        for item in rows:
            q=item['question'];sampler=Telemetry(target);sampler.start()
            allocations=adapter.allocations()
            result=execute_protocol(q,item['contexts'],models[name],adapter,folder,'warm',repetition,prompt,schema)
            result.update(context_band=item['subset_row']['context_band'],query_style=q['query_style'],
                context_sha256=item['subset_row']['context_sha256'],context_ids=[c['context_id'] for c in item['contexts']],
                context_chunk_ids=[c['chunk_id'] for c in item['contexts']],
                loaded_idle=loaded_idle,telemetry=sampler.finish(),runtime_allocations=allocations,
                warm_residency_verified=any(r.get('name',r.get('model'))==name for r in allocations.get('models',[])),
                behavior=behavior_preservation(references[(name,q['question_id'])],result['result']))
            append_jsonl(folder/'warm_runs.jsonl',result)
            print(f"{run_id} {name} run {repetition}/3 {q['question_id']} {result['status']}",flush=True)
    return folder


def read_rows(path):
    if not path.exists():return []
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]
