"""Target gating, frozen identity and comparable measurement semantics."""
from __future__ import annotations

import hashlib
import json
import math
import statistics
from collections import Counter
from copy import deepcopy

MODELS = ('gemma2:9b', 'qwen2.5-coder:7b', 'deepseek-r1:8b', 'deepseek-r1:7b')
QUALITY = {'gemma2:9b':'conditional_candidate', 'qwen2.5-coder:7b':'evaluation_unresolved',
           'deepseek-r1:8b':'low_priority', 'deepseek-r1:7b':'low_priority'}
OPTIONS = dict(temperature=0, top_p=1.0, seed=15015, num_predict=1024, num_ctx=8192)
REPETITIONS = 3
COLD_REPETITIONS = 3
MAX_ATTEMPTS = 2
TTFT_DEFINITION = 'request sent -> first non-empty final-output message.content token; structured JSON channel, excluding message.thinking'
WARMUP = {'question_id':'edge_fixed_warmup_v1', 'question':'提供的 Evidence 說明了什麼？',
          'contexts':[{'context_id':'C1','chunk_id':'warmup_only','document_id':'warmup_only','page':1,
                       'text':'這是一筆固定的執行環境暖機資料。'}]}


def digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def json_hash(data):
    return digest(json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(',',':')))


def _known(value):
    return isinstance(value,str) and value.strip().casefold() not in ('','unknown','unavailable','pending','tbd')


def target_gate(target):
    """A pending template never identifies the research host as the edge target."""
    errors=[]
    if not isinstance(target,dict):
        return dict(edge_execution_ready=False,errors=['target_device_missing'],acceptance_thresholds_defined=False)
    if target.get('target_device_confirmed') is not True:errors.append('target_device_not_confirmed')
    for name in ('device_name','device_id','execution_node'):
        if not _known(target.get(name)):errors.append(name+'_missing')
    for name,key in (('CPU','name'),('OS','name'),('OS','version'),('runtime','name'),('runtime','version'),('storage','device')):
        if not _known((target.get(name) or {}).get(key)):errors.append(name+'.'+key+'_missing')
    ram=(target.get('RAM') or {}).get('bytes')
    if not isinstance(ram,int) or isinstance(ram,bool) or ram<=0:errors.append('RAM.bytes_missing')
    for accel in ('GPU','NPU'):
        info=target.get(accel) or {}
        if not isinstance(info.get('available'),bool):errors.append(accel+'.availability_unknown')
        if info.get('available') and not _known(info.get('name')):errors.append(accel+'.name_missing')
    if (target.get('GPU') or {}).get('available'):
        sizes=[(target.get(k) or {}).get('bytes') for k in ('VRAM','unified_memory')]
        if not any(isinstance(n,int) and not isinstance(n,bool) and n>0 for n in sizes):
            errors.append('accelerator_memory_missing')
    if target.get('deployment_mode') not in ('generator_only','full_rag'):errors.append('deployment_mode_invalid')
    for sensor in ('power_measurement','thermal_measurement'):
        info=target.get(sensor) or {}
        if not isinstance(info.get('available'),bool):errors.append(sensor+'.availability_missing')
        if info.get('available') and not (_known(info.get('sensor')) and _known(info.get('scope'))):
            errors.append(sensor+'.identity_or_scope_missing')
    runtime=target.get('runtime') or {}
    if runtime.get('name') and runtime['name'].casefold()!='ollama':
        errors.append('runtime_adapter_not_supported; no silent alternative invocation')
    if runtime.get('endpoint') and not runtime['endpoint'].startswith(('http://127.0.0.1:','http://localhost:')):
        errors.append('runtime_endpoint_must_be_local_to_attested_device')
    if not _known(runtime.get('endpoint')):errors.append('runtime.endpoint_missing')
    thresholds=target.get('acceptance_thresholds')
    defined=isinstance(thresholds,dict) and bool(thresholds)
    if defined:
        if not _known(thresholds.get('predefined_source')) or not _known(thresholds.get('defined_before_experiment')):
            errors.append('acceptance_threshold_provenance_missing')
        for k,v in thresholds.items():
            if k in ('predefined_source','defined_before_experiment'):continue
            if not isinstance(v,(int,float)) or isinstance(v,bool) or not math.isfinite(v) or v<=0:
                errors.append('acceptance_threshold_invalid:'+k)
    return dict(edge_execution_ready=not errors,errors=errors,
                acceptance_thresholds_defined=defined,
                benchmark_mode='predeclared_thresholds' if defined else 'descriptive_feasibility',
                deployment_mode=target.get('deployment_mode','generator_only'))


def validate_model_identity(expected, actual):
    for key in ('name','digest','quantization','parameter_count','native_context_length'):
        if expected.get(key) is None or actual.get(key)!=expected[key]:
            raise ValueError('Model artifact mismatch: '+key)
    if len(expected['digest'])!=64:
        raise ValueError('Full artifact digest required')
    return True


def validate_subset(subset, questions, contexts, cuts):
    if len(subset)!=60 or len({r['question_id'] for r in subset})!=60:
        raise ValueError('Frozen edge subset must be exactly 60 unique IDs')
    if Counter(r['query_style'] for r in subset)!=Counter(direct=20,paraphrase=20,contextual=20):
        raise ValueError('Frozen style distribution differs')
    if Counter(r['context_band'] for r in subset)!=Counter(short=20,medium=21,long=19):
        raise ValueError('Frozen context-band distribution differs')
    for r in subset:
        qid=r['question_id'];q=questions.get(qid);cs=contexts.get(qid)
        if q is None or cs is None or q['question']!=r['question'] or q['query_style']!=r['query_style']:
            raise ValueError('Frozen question differs: '+qid)
        texts=[c['text'] for c in cs]
        if digest(json.dumps(texts,ensure_ascii=False))!=r['context_sha256']:
            raise ValueError('Frozen E4 context checksum differs: '+qid)
        if len(cs)!=5 or [c['context_id'] for c in cs]!=['C1','C2','C3','C4','C5']:
            raise ValueError('Exactly five frozen contexts required')
        for c,p in zip(cs,r['context_provenance'],strict=True):
            if any(c.get(k)!=p[k] for k in ('context_id','chunk_id','document_id','page','rank')):
                raise ValueError('Frozen context order/provenance differs')
            if digest(c['text'])!=p['content_checksum']:
                raise ValueError('Frozen chunk text differs')
        n=sum(map(len,texts));band='short' if n<=cuts[0] else 'medium' if n<=cuts[1] else 'long'
        if r['context_characters']!=n or r['context_band']!=band:
            raise ValueError('Frozen length band differs')
    return True


def schedule(models=MODELS):
    """Rotating whole-model blocks; every block keeps the original 60-question order."""
    return [dict(repetition=i+1,model=m,block=j+1) for i in range(REPETITIONS)
            for j,m in enumerate(models[i:]+models[:i])]


def summary(values, expected_count=None):
    data=sorted(float(v) for v in values if isinstance(v,(float,int)) and not isinstance(v,bool) and math.isfinite(v))
    p=.95*(len(data)-1) if data else None
    p95=(data[math.floor(p)]+(data[math.ceil(p)]-data[math.floor(p)])*(p-math.floor(p))) if data else None
    return dict(n_measured=len(data),n_expected=expected_count,n_missing=(expected_count-len(data)) if expected_count is not None else None,
        mean=statistics.fmean(data) if data else None,median=statistics.median(data) if data else None,
        p95=p95,max=max(data) if data else None,min=min(data) if data else None)


def token_metrics(done, *, thinking_capable, thinking_observed, inline_reasoning=False):
    count=done.get('eval_count');duration=done.get('eval_duration')
    reasoning=done.get('thinking_eval_count');visible=done.get('content_eval_count')
    if visible is None and reasoning is not None and count is not None:visible=count-reasoning
    separation=visible is not None and reasoning is not None
    if not thinking_capable and not thinking_observed and not inline_reasoning:
        visible=count;reasoning=0;separation=count is not None
    runtime_tps=count/(duration/1e9) if count is not None and duration and duration>0 else None
    visible_duration=done.get('content_eval_duration')
    if not thinking_capable and not thinking_observed and not inline_reasoning:visible_duration=duration
    return dict(runtime_eval_count=count,visible_output_token_count=visible,reasoning_token_count=reasoning,
        reasoning_token_separation_available=separation,runtime_tps=runtime_tps,
        visible_answer_tps=visible/(visible_duration/1e9) if visible is not None and visible_duration and visible_duration>0 else None,
        runtime_tps_semantics='mixed_or_unknown_thinking_and_content' if not separation else 'content_only' if reasoning==0 else 'thinking_plus_content',
        visible_answer_tps_semantics='visible content tokens / separately measured content decoding duration; null if unavailable')


def validate_memory(sample):
    required={'kind','scope','phase','value_bytes','sensor','timestamp'}
    if not required<=set(sample) or sample['kind'] not in ('RAM','VRAM','unified_memory'):
        raise ValueError('Memory measurement identity incomplete')
    if sample['scope'] not in ('whole_device','process_family','process_specific','unified_pool'):
        raise ValueError('Unknown memory scope')
    if sample['phase'] not in ('idle','model_loaded','inference') or sample['value_bytes'] is not None and sample['value_bytes']<0:
        raise ValueError('Invalid memory phase/value')
    return True


def behavior_preservation(reference, edge):
    from ..generation.protocol_v2 import normalized_answer_similarity, jaccard
    if reference['question_id']!=edge['question_id']:raise ValueError('Behavior comparison must use same question ID')
    return dict(question_id=edge['question_id'],
        normalized_answer_similarity=normalized_answer_similarity(reference.get('answer',''),edge.get('answer','')),
        status_agreement=reference['status']==edge['status'],
        citation_set_exact=set(reference.get('citations',[]))==set(edge.get('citations',[])),
        citation_set_jaccard=jaccard(set(reference.get('citations',[])),set(edge.get('citations',[]))),
        schema_agreement=bool(reference.get('schema_valid'))==bool(edge.get('schema_valid')),
        interpretation='Behavior preservation, not exact-text correctness or human validation')


def hardware_status(*, completed, required, cold_verified, failure_count, input_audited, limitations):
    if completed!=required or not cold_verified:return 'benchmark_incomplete'
    if failure_count==required:return 'not_feasible'
    if failure_count or not input_audited or limitations:return 'deployable_with_limitations'
    return 'deployable_on_device'


def deployment_row(model, status, metrics):
    return dict(model=model,quality_status=QUALITY[model],hardware_status=status,**deepcopy(metrics),
        human_validation_available=False,judge_conflict=model=='qwen2.5-coder:7b',
        reference_generator='Gemma 2 9B',reference_alignment_bias_possible=True,
        quality_status_changed_by_speed=False,composite_score=None)


def pareto(rows, axes, required_semantics=()):
    """No weighted score; exclude missing/incomparable observations explicitly."""
    valid=[];excluded=[]
    reference=next((r for r in rows if r.get('hardware_status')!='benchmark_incomplete' and all(
        isinstance(r.get(k),(int,float)) and not isinstance(r.get(k),bool) and math.isfinite(r[k]) for k in axes)),None)
    for r in rows:
        missing=[k for k in axes if not isinstance(r.get(k),(int,float)) or isinstance(r.get(k),bool) or not math.isfinite(r[k])]
        if r.get('hardware_status')=='benchmark_incomplete' or missing:
            excluded.append(dict(model=r['model'],reason='benchmark_incomplete_or_missing_axes',missing=missing));continue
        if required_semantics and reference and any(r.get(k)!=reference.get(k) for k in required_semantics):
            excluded.append(dict(model=r['model'],reason='measurement_semantics_differ'));continue
        valid.append(r)
    def dominates(a,b):
        s={k:1 if d=='max' else -1 for k,d in axes.items()}
        return all(s[k]*a[k]>=s[k]*b[k] for k in axes) and any(s[k]*a[k]>s[k]*b[k] for k in axes)
    return dict(axes=axes,non_dominated=[r['model'] for r in valid if not any(dominates(q,r) for q in valid)],
        excluded=excluded,human_validation_available=False,composite_score=None,
        interpretation='Descriptive axis dominance only; not a final model-quality winner')
