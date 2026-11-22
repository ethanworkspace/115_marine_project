"""Ollama and telemetry adapters. Never called until an explicit target gate passes."""
from __future__ import annotations

import ctypes
import json
import os
import platform
import subprocess
import threading
import time
from pathlib import Path

import requests

from .core import OPTIONS, target_gate, token_metrics, digest, TTFT_DEFINITION


class TargetBlocked(RuntimeError):
    pass


def require_target(target, node=None):
    gate=target_gate(target)
    if not gate['edge_execution_ready']:
        raise TargetBlocked('edge_execution_ready=false: '+', '.join(gate['errors']))
    if target['execution_node']!=(node or platform.node()):
        raise TargetBlocked('Execution node differs from explicitly named target; no research-host substitution')
    return gate


class OllamaEdge:
    def __init__(self,target,session=None):
        require_target(target)
        self.target=target;self.session=session or requests.Session()
        self.endpoint=target['runtime']['endpoint'].rstrip('/')

    def get(self,path):
        r=self.session.get(self.endpoint+path,timeout=10);r.raise_for_status();return r.json()

    def preflight(self,models):
        version=self.get('/api/version').get('version')
        if version!=self.target['runtime']['version']:
            raise TargetBlocked('Target runtime version differs from declared manifest')
        local={r['name']:r for r in self.get('/api/tags').get('models',[])}
        actual={}
        from .core import validate_model_identity
        for name,expected in models.items():
            m=local.get(name)
            if m is None:raise TargetBlocked('blocked_runtime: specified model not already present: '+name)
            r=self.session.post(self.endpoint+'/api/show',json={'model':name},timeout=20)
            r.raise_for_status();show=r.json();info=show.get('model_info',{});arch=info.get('general.architecture','')
            row=dict(name=name,digest=m.get('digest'),quantization=show.get('details',{}).get('quantization_level'),
                parameter_count=info.get('general.parameter_count'),native_context_length=info.get(arch+'.context_length'),
                artifact_size_bytes=m.get('size'),runtime_version=version,capabilities=show.get('capabilities',[]))
            validate_model_identity(expected,row);actual[name]=row
        return actual

    def unload(self,model):
        r=self.session.post(self.endpoint+'/api/generate',json={'model':model,'keep_alive':0},timeout=120)
        r.raise_for_status()
        deadline=time.monotonic()+30
        while time.monotonic()<deadline:
            active=self.get('/api/ps').get('models',[])
            if not any(r.get('name',r.get('model'))==model for r in active):
                return dict(unloaded=True,verification='model absent from Ollama /api/ps',resident_models=active)
            time.sleep(.25)
        return dict(unloaded=False,verification='model still resident; cold repetition is not independent')

    def allocations(self):
        return self.get('/api/ps')

    def generation(self,*,model,system_prompt,user_prompt,schema,thinking_capable=False,log_path=None):
        body=dict(model=model,stream=True,format=schema,keep_alive='30m',
            messages=[{'role':'system','content':system_prompt},{'role':'user','content':user_prompt}],options=dict(OPTIONS))
        start=time.perf_counter();parts=[];thinking=[];events=[];done={};error=None;ttft=None;any_token=None
        log=Path(log_path) if log_path else None
        offset=log.stat().st_size if log and log.is_file() else None
        try:
            with self.session.post(self.endpoint+'/api/chat',json=body,stream=True,timeout=900) as response:
                response.raise_for_status();response.encoding='utf-8'
                for line in response.iter_lines(decode_unicode=True):
                    if not line:continue
                    events.append(line)
                    try:e=json.loads(line)
                    except json.JSONDecodeError as exc:
                        error='stream_event_json_error: '+str(exc);continue
                    m=e.get('message') or {};content=m.get('content') or '';thought=m.get('thinking') or ''
                    elapsed=time.perf_counter()-start
                    if content or thought:
                        if any_token is None:any_token=elapsed
                    if content:
                        if ttft is None:ttft=elapsed
                        parts.append(content)
                    if thought:thinking.append(thought)
                    if e.get('error'):error=str(e['error'])
                    if e.get('done'):done=e
        except Exception as exc:error=type(exc).__name__+': '+str(exc)
        latency=time.perf_counter()-start;raw=''.join(parts);inline='<think>' in raw or '</think>' in raw
        if inline:ttft=None # No honest final-token timing from an undifferentiated reasoning/content channel.
        if not error and not done:error='stream_interrupted: final done event missing'
        parsed=None;parse_error=None
        try:
            parsed=json.loads(raw)
            if not isinstance(parsed,dict):parse_error='response_json_not_object';parsed=None
        except json.JSONDecodeError as exc:parse_error=type(exc).__name__+': '+str(exc)
        warnings=[];log_available=offset is not None
        if log_available:
            try:
                with log.open('rb') as f:
                    f.seek(offset);lines=f.read().decode('utf-8',errors='replace').splitlines()
                warnings=[x for x in lines if 'truncat' in x.casefold() and any(t in x.casefold() for t in ('prompt','input'))]
            except OSError:log_available=False
        prompt=done.get('prompt_eval_count');margin=8192-1024-prompt if prompt is not None else None
        budget=dict(prompt_tokens=prompt,context_length=8192,max_output_tokens=1024,remaining_context_margin=margin,
            input_truncated=True if warnings else False if log_available and margin is not None and margin>=0 else None,
            runtime_truncation_warnings=warnings,runtime_log_available=log_available,
            context_capacity_failure=bool(warnings) or margin is not None and margin<0,
            detection='Runtime prompt count/margin and input-warning log. Missing log remains unknown, not zero truncation.')
        if budget['context_capacity_failure']:error='context_capacity_failure: frozen context cannot be shortened'
        tokens=token_metrics(done,thinking_capable=thinking_capable,thinking_observed=bool(thinking),inline_reasoning=inline)
        return dict(raw_output=raw,raw_output_sha256=digest(raw),parsed=parsed,parse_error=parse_error,execution_error=error,
            latency_seconds=latency,ttft_seconds=ttft,ttft_final_answer_seconds=ttft,ttft_any_token_seconds=any_token,
            ttft_definition=TTFT_DEFINITION,prompt_tokens=prompt,completion_tokens=done.get('eval_count'),
            tokens_per_second=tokens['runtime_tps'],load_duration_ns=done.get('load_duration'),done_reason=done.get('done_reason'),
            raw_stream_events=events,raw_thinking=''.join(thinking),raw_thinking_sha256=digest(''.join(thinking)),
            final_event=done,request_sha256=digest(json.dumps(body,ensure_ascii=False,sort_keys=True)),
            token_metrics=tokens,context_window_budget=budget,inline_reasoning_channel_ambiguous=inline)


def system_ram():
    """Whole-device RAM used, never labeled process-specific."""
    if os.name=='nt':
        class MemoryStatus(ctypes.Structure):
            _fields_=[('length',ctypes.c_ulong),('load',ctypes.c_ulong),
                ('total_phys',ctypes.c_ulonglong),('avail_phys',ctypes.c_ulonglong),
                ('total_page',ctypes.c_ulonglong),('avail_page',ctypes.c_ulonglong),
                ('total_virtual',ctypes.c_ulonglong),('avail_virtual',ctypes.c_ulonglong),('avail_extended',ctypes.c_ulonglong)]
        m=MemoryStatus();m.length=ctypes.sizeof(m)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)):
            raise OSError('GlobalMemoryStatusEx failed')
        return m.total_phys-m.avail_phys,'Windows GlobalMemoryStatusEx'
    p=Path('/proc/meminfo')
    if p.is_file():
        data={line.split(':',1)[0]:int(line.split(':',1)[1].split()[0])*1024 for line in p.read_text().splitlines()}
        if 'MemAvailable' not in data:raise OSError('MemAvailable unavailable; no estimated replacement')
        return data['MemTotal']-data['MemAvailable'],'Linux /proc/meminfo MemTotal-MemAvailable'
    raise OSError('Whole-device RAM sensor not implemented on this OS')


class Telemetry:
    def __init__(self,target,phase='inference',interval=1.0):
        self.target=target;self.phase=phase;self.interval=interval;self.samples=[];self.errors=[]
        self.stop=threading.Event();self.thread=threading.Thread(target=self._run,daemon=True)

    def sample(self):
        now=time.monotonic();r=dict(timestamp=now,phase=self.phase,memory=[],power_watts=None,temperature_c=None,
            power_scope=None,thermal_scope=None,thermal_throttling=None,clock_reduction=None)
        try:
            value,sensor=system_ram()
            r['memory'].append(dict(kind='RAM',scope='whole_device',phase=self.phase,value_bytes=value,sensor=sensor,timestamp=now))
        except Exception as exc:self.errors.append(str(exc))
        gpu=self.target.get('GPU') or {}
        if gpu.get('available') and gpu.get('device_index') is not None:
            fields=['memory.used']
            power=(self.target.get('power_measurement') or {})
            thermal=(self.target.get('thermal_measurement') or {})
            if power.get('available') and power.get('sensor')=='nvidia-smi':fields.append('power.draw')
            if thermal.get('available') and thermal.get('sensor')=='nvidia-smi':fields.append('temperature.gpu')
            try:
                text=subprocess.check_output(['nvidia-smi','-i',str(gpu['device_index']),'--query-gpu='+','.join(fields),
                    '--format=csv,noheader,nounits'],text=True,timeout=5).strip()
                cells=dict(zip(fields,[x.strip() for x in text.split(',')],strict=True))
                if self.target.get('unified_memory',{}).get('bytes'):
                    # nvidia-smi GPU used memory is not a reliable whole unified-pool measurement.
                    self.errors.append('Unified pool measurement unavailable; no RAM+VRAM sum')
                else:
                    r['memory'].append(dict(kind='VRAM',scope='whole_device',phase=self.phase,
                        value_bytes=int(float(cells['memory.used'])*1024*1024),sensor='nvidia-smi',timestamp=now))
                if 'power.draw' in cells:
                    r.update(power_watts=float(cells['power.draw']),power_scope='GPU_board')
                if 'temperature.gpu' in cells:
                    r.update(temperature_c=float(cells['temperature.gpu']),thermal_scope='GPU_sensor')
            except Exception as exc:self.errors.append(type(exc).__name__+': '+str(exc))
        self.samples.append(r);return r

    def _run(self):
        while not self.stop.is_set():
            self.sample();self.stop.wait(self.interval)

    def start(self):
        self.thread.start()

    def finish(self):
        self.stop.set();self.thread.join(timeout=6);self.sample()
        return dict(samples=self.samples,errors=self.errors,sample_interval_seconds=self.interval,
            peak_is_sampled_not_absolute=True,process_specific_RAM_available=False,
            process_specific_VRAM_available=False,power_metrics_available=any(s['power_watts'] is not None for s in self.samples),
            thermal_metrics_available=any(s['temperature_c'] is not None for s in self.samples),
            unified_memory_metrics_available=False)


def energy_from_samples(samples):
    """Integrate measured power only; no missing-sensor estimation or idle subtraction."""
    ordered=sorted(samples,key=lambda r:r['timestamp'])
    if len(ordered)<2 or any(r.get('power_watts') is None for r in ordered):return None
    if len({r.get('power_scope') for r in ordered})!=1:return None
    return sum((b['timestamp']-a['timestamp'])*(a['power_watts']+b['power_watts'])/2 for a,b in zip(ordered,ordered[1:]))
