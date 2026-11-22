"""Serial model-cold, three warm rounds, and two fixed 30-minute workloads."""
from __future__ import annotations
import json
import threading
import time
from pathlib import Path
import requests
from .core import MODELS,OPTIONS,WARMUP,schedule,behavior_preservation
from .inputs import ROOT,BUNDLE,load_bundle,load_target
from .runtime import OllamaEdge,require_target,TargetBlocked
from .runner import execute_protocol,append_jsonl,ReadyProbe,read_rows
from .hardware19a import Sensors
from .analysis19a import SUSTAINED_MODELS,SUSTAINED_SECONDS

OUT=ROOT/'reports/evaluation/edge/phase19A'

def write(path,row):
    temp=path.with_suffix(path.suffix+'.tmp');temp.write_text(json.dumps(row,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    # Windows readers can briefly hold a destination handle without FILE_SHARE_DELETE.
    # This retries only report-file replacement, never a model request or answer selection.
    for attempt in range(100):
        try:temp.replace(path);return
        except PermissionError:
            if attempt==99:raise
            time.sleep(.1)

class LowLatencySession(requests.Session):
    """Read streaming lines without the default 512-byte client buffering delay."""
    def post(self,*args,**kwargs):
        response=super().post(*args,**kwargs)
        if kwargs.get('stream'):
            original=response.iter_lines
            response.iter_lines=lambda **kw:original(chunk_size=1,**kw)
        return response

class ObservedOllama(OllamaEdge):
    def generation(self,**kwargs):
        value=super().generation(**kwargs)
        self.last_captures.append(value)
        return value

class Collector:
    def __init__(self):
        self.sensor=Sensors();self.records=[];self.lock=threading.Lock();self.stop=threading.Event()
        self.thread=threading.Thread(target=self.loop,daemon=True)
    def loop(self):
        while not self.stop.is_set():
            sample=self.sensor.sample()
            with self.lock:self.records.append(sample)
            append_jsonl(OUT/'sensor_samples.jsonl',sample)
            self.stop.wait(2)
    def start(self):self.thread.start()
    def between(self,start,end):
        with self.lock:return [r for r in self.records if start<=r['timestamp']<=end]
    def latest(self):
        with self.lock:return self.records[-1] if self.records else None
    def finish(self):
        self.stop.set();self.thread.join(timeout=10);self.sensor.close()

def thermal_start(collector,*,wait=time.sleep,clock=time.monotonic):
    start=clock();idle_since=None;samples=[]
    while True:
        r=collector.latest();now=clock();gpu=(r or {}).get('gpu') or {}
        util=gpu.get('utilization_percent');temperature=gpu.get('temperature_c')
        if util is not None and util<5:
            if idle_since is None:idle_since=now
        else:idle_since=None
        samples.append(dict(elapsed=now-start,utilization_percent=util,temperature_c=temperature))
        idle=idle_since is not None and now-idle_since>=60
        if idle and temperature is not None and temperature<=45:break
        if now-start>=300:break
        wait(2)
    return dict(wait_seconds=now-start,continuous_idle_60_seconds=idle,
        thermal_baseline_not_reached=temperature is None or temperature>45,
        utilization_baseline_not_reached=not idle,actual_temperature_c=temperature,samples=samples,
        no_power_plan_or_security_change=True)

def placement(adapter,model,collector):
    allocations=adapter.allocations();active=next((r for r in allocations.get('models',[]) if r.get('name',r.get('model'))==model),None)
    return dict(model=model,runtime_model_status=active,runtime_allocations=allocations,sensor=collector.latest(),
        CPU_allocation_bytes=None,GPU_allocation_bytes=(active or {}).get('size_vram'),
        GPU_offload_layers=None,CPU_threads=None,batch_size=None,
        allocation_note='size_vram is Ollama reported allocation, not physical device-wide memory. CPU bytes/layers unknown unless runtime log explicitly exposes them.')

def unloaded_gpu_check(unload,sample,idle_gpu_bytes):
    gpu=(sample or {}).get('gpu') or {}
    pd=(sample or {}).get('GPU_process_memory') or {}
    process=pd.get('dedicated_process')
    if process is not None:
        released=all(v['value_bytes']<=16*1024**2 for v in process)
        method='Ollama absent from /api/ps and Ollama process WDDM dedicated usage <=16 MiB per instance'
    else:
        current=gpu.get('dedicated_used_bytes')
        released=current is not None and idle_gpu_bytes is not None and current<=idle_gpu_bytes+64*1024**2
        method='Ollama absent from /api/ps plus device memory returned within 64 MiB of initial background; proxy with background-memory limitation'
    return dict(verified=bool(unload['unloaded'] and released),GPU_model_allocation_released=released,
        verification_method=method,sample=sample,OS_filesystem_cache_cleared=False)

def execute(*,resume=False):
    manifest=json.loads((OUT/'experiment_manifest.json').read_text(encoding='utf-8'))
    target=load_target();require_target(target)
    if json.loads((OUT/'target_device_manifest.json').read_text(encoding='utf-8'))['target']!=target:raise TargetBlocked('Target changed after freeze')
    rows,bundle=load_bundle()
    if bundle!=manifest['input_bundle']:raise TargetBlocked('Bundle changed after freeze')
    if not resume and any((OUT/n).exists() and (OUT/n).stat().st_size for n in ('attempts.jsonl','cold_starts.jsonl','warm_runs.jsonl','sustained_requests.jsonl')):
        raise TargetBlocked('Existing physical run records: refusing restart, best-run selection, or mixed experiment')
    models={m:json.loads((OUT/'model_manifests'/(m.replace(':','_')+'.json')).read_text(encoding='utf-8')) for m in MODELS}
    adapter=ObservedOllama(target,session=LowLatencySession());adapter.last_captures=[];adapter.preflight(models)
    residents=adapter.allocations().get('models',[])
    if any(r.get('name',r.get('model')) not in MODELS for r in residents):raise TargetBlocked('Unrelated resident workload; refusing to change it')
    prior_warm=read_rows(OUT/'warm_runs.jsonl') if resume else []
    prior_cold=read_rows(OUT/'cold_starts.jsonl') if resume else []
    if resume:
        from .report import validate_results
        validate_results(prior_warm,prior_cold,bundle['question_ids'])
        if len(prior_cold)!=12 or not all(c['independent_cold_start_verified'] for c in prior_cold) or (OUT/'sustained_requests.jsonl').exists():
            raise TargetBlocked('Resume is limited to an already frozen cold-complete, warm-prefix journal; no arbitrary restart')
        write(OUT/'execution_resume.json',dict(reason='Windows report replacement share-lock, no inference failure',
            preserved_warm_requests=len(prior_warm),preserved_cold_requests=12,timestamp=time.time(),
            completed_outputs_never_reexecuted=True,original_interruption_preserved=True,measurement_gap_is_limitation=True))
    collector=Collector();collector.start();time.sleep(3)
    idle=collector.latest();idle_gpu_bytes=(idle.get('gpu') or {}).get('dedicated_used_bytes')
    if not resume:write(OUT/'execution_start.json',dict(timestamp=time.time(),initial_idle=idle,OPTIONS=OPTIONS))
    prompt=(BUNDLE/'generation_v2.txt').read_text(encoding='utf-8').strip()
    schema=json.loads((BUNDLE/'generation_output_v2.schema.json').read_text(encoding='utf-8'))
    references={(r['model'],r['question_id']):r for r in read_rows(BUNDLE/'phase17_behavior_references.jsonl')}
    def unload_all():
        for r in adapter.allocations().get('models',[]):
            name=r.get('name',r.get('model'))
            if name not in MODELS:raise TargetBlocked('Unrelated workload appeared during run')
            adapter.unload(name)
    def progress(stage,model,rep,count):
        write(OUT/'execution_progress.json',dict(stage=stage,model=model,repetition=rep,completed_in_block=count,timestamp=time.time()))
        print(f'{stage} {model} run={rep} completed={count}',flush=True)
    def request(item,model,stage,rep):
        begin=time.monotonic();pre=adapter.allocations()
        adapter.last_captures=[]
        result=execute_protocol(item['question'],item['contexts'],models[model],adapter,OUT,stage,rep,prompt,schema)
        end=time.monotonic()
        result.update(context_band=item['subset_row']['context_band'],query_style=item['question']['query_style'],
            context_sha256=item['subset_row']['context_sha256'],context_ids=[c['context_id'] for c in item['contexts']],
            context_chunk_ids=[c['chunk_id'] for c in item['contexts']],
            sensor_start_monotonic=begin,sensor_end_monotonic=end,
            telemetry={'samples':collector.between(begin,end),'interval_seconds':2,'peak_is_sampled_not_absolute':True},
            runtime_allocations=pre,warm_residency_verified=any(r.get('name',r.get('model'))==model for r in pre.get('models',[])),
            behavior=behavior_preservation(references[(model,item['question']['question_id'])],result['result']))
        # Retain runtime prompt/evaluation timings per attempt without altering the old execution protocol.
        captured=adapter.last_captures
        last=captured[-1]['final_event'];result['runtime_times']={k:last.get(k) for k in ('prompt_eval_duration','eval_duration','total_duration','load_duration')}
        result['first_pass_json_valid']=captured[0]['parsed'] is not None and captured[0]['parse_error'] is None
        result['final_json_valid']=captured[-1]['parsed'] is not None and captured[-1]['parse_error'] is None
        result['attempt_request_sha256']=[c['request_sha256'] for c in captured]
        append_jsonl(OUT/'per_request_metrics.jsonl',result)
        return result
    try:
        if not resume:unload_all()
        for model in (() if resume else MODELS):
            for rep in (1,2,3):
                unload=adapter.unload(model);time.sleep(3)
                check=unloaded_gpu_check(unload,collector.latest(),idle_gpu_bytes)
                if not check['verified']:
                    append_jsonl(OUT/'cold_starts.jsonl',dict(model=model,stage='cold',repetition=rep,status='unload_unverified',independent_cold_start_verified=False,verification=check))
                    raise TargetBlocked('Cannot verify model-cold GPU allocation release: '+model)
                probe=ReadyProbe(adapter,model);probe.thread.start()
                result=request(rows[0],model,'cold',rep)
                result.update(independent_cold_start_verified=True,cold_verification=check,ready_probe=probe.finish(),placement_after=placement(adapter,model,collector))
                append_jsonl(OUT/'cold_starts.jsonl',result);progress('cold',model,rep,1)
            adapter.unload(model)
        for block in schedule():
            model=block['model'];rep=block['repetition']
            prior=[r for r in prior_warm if r['model']==model and r['repetition']==rep]
            if len(prior)==60:continue
            if prior:
                active=adapter.allocations().get('models',[])
                if not any(a.get('name',a.get('model'))==model and a.get('digest')==models[model]['digest'] for a in active):
                    raise TargetBlocked('Cannot preserve warm residency across report-file interruption')
                append_jsonl(OUT/'measurement_gaps.jsonl',dict(model=model,repetition=rep,after_question_count=len(prior),
                    last_completed_timestamp=prior[-1]['sensor_end_monotonic'],resume_timestamp=time.monotonic(),model_remained_resident=True))
            else:
                unload_all();start_condition=thermal_start(collector)
                append_jsonl(OUT/'thermal_start_conditions.jsonl',dict(model=model,repetition=rep,**start_condition))
                from ..generation.runner_v2 import format_v2_user_prompt
                warm=adapter.generation(model=model,system_prompt=prompt,user_prompt=format_v2_user_prompt(WARMUP,WARMUP['contexts']),schema=schema,
                    thinking_capable='thinking' in models[model]['capabilities'],log_path=target['runtime'].get('log_path'))
                append_jsonl(OUT/'warmup_outputs.jsonl',dict(model=model,repetition=rep,stage='warmup',raw=warm,excluded_from_formal_metrics=True))
                append_jsonl(OUT/'model_placement.jsonl',dict(stage='warm',repetition=rep,**placement(adapter,model,collector)))
            for i,item in enumerate(rows[len(prior):],len(prior)+1):
                result=request(item,model,'warm',rep);append_jsonl(OUT/'warm_runs.jsonl',result);progress('warm',model,rep,i)
        for model in SUSTAINED_MODELS:
            unload_all();start_condition=thermal_start(collector)
            append_jsonl(OUT/'thermal_start_conditions.jsonl',dict(model=model,repetition='sustained',**start_condition))
            from ..generation.runner_v2 import format_v2_user_prompt
            warm=adapter.generation(model=model,system_prompt=prompt,user_prompt=format_v2_user_prompt(WARMUP,WARMUP['contexts']),schema=schema,
                thinking_capable='thinking' in models[model]['capabilities'],log_path=target['runtime'].get('log_path'))
            append_jsonl(OUT/'warmup_outputs.jsonl',dict(model=model,stage='sustained_warmup',raw=warm,excluded_from_formal_metrics=True))
            begin=time.monotonic();i=0
            while time.monotonic()-begin<SUSTAINED_SECONDS:
                item=rows[i%60];result=request(item,model,'sustained',i+1)
                result.update(sustained_start_monotonic=begin,elapsed_start_seconds=result['sensor_start_monotonic']-begin,
                    interval_index=min(5,int((result['sensor_start_monotonic']-begin)//300)))
                append_jsonl(OUT/'sustained_requests.jsonl',result);i+=1;progress('sustained',model,1,i)
            append_jsonl(OUT/'sustained_completion.jsonl',dict(model=model,configured_seconds=1800,actual_seconds=time.monotonic()-begin,
                requests=i,complete=True,last_request_may_finish_after_30_minutes=True))
        unload_all();write(OUT/'execution_complete.json',dict(status='complete',timestamp=time.time(),formal_requests=720,cold_requests=12))
        if resume:write(OUT/'execution_recovery_completed.json',dict(original_interruption_resolved=True,timestamp=time.time(),measurement_gap_preserved=True))
    except Exception as exc:
        error=dict(error=type(exc).__name__+': '+str(exc),timestamp=time.time(),benchmark_incomplete=True)
        if (OUT/'execution_interruption.json').exists():append_jsonl(OUT/'additional_interruptions.jsonl',error)
        else:write(OUT/'execution_interruption.json',error)
        raise
    finally:
        collector.finish();write(OUT/'sensor_limitations.json',dict(errors=collector.sensor.errors,
            PDH_errors=collector.sensor.pdh.errors if collector.sensor.pdh else ['PDH unavailable']))
