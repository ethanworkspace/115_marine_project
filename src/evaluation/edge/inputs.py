"""Create immutable portable copies from frozen records, never re-run retrieval."""
from __future__ import annotations

import json
import os
from pathlib import Path

from .core import MODELS, QUALITY, OPTIONS, validate_subset, target_gate
from ..generation.frozen import sha256_file, read_jsonl, validate_frozen_inputs
from ..generation.contexts import build_e4_top5_contexts

ROOT=Path(__file__).resolve().parents[3]
OUT=ROOT/'reports/evaluation/edge/phase19'
BUNDLE=ROOT/'data/evaluation/edge/phase19_inputs_v1'
SUBSET=ROOT/'reports/evaluation/validity/phase18/edge_benchmark_subset_v1.jsonl'
TARGET=ROOT/'configs/edge_target_device.yaml'


def load_target(path=TARGET):
    p=Path(path)
    if not p.exists():return None
    text=p.read_text(encoding='utf-8')
    try:return json.loads(text)
    except json.JSONDecodeError:
        try:
            import yaml
        except ImportError as exc:
            raise ValueError('Use JSON-compatible YAML 1.2 as in project configs, or the existing .venv-ragas YAML reader; no automatic installation') from exc
        value=yaml.safe_load(text)
        if not isinstance(value,dict):raise ValueError('Target YAML must be an object')
        return value


def validate_target_schema(target, root=ROOT):
    from jsonschema import Draft202012Validator
    schema=json.loads((root/'schemas/edge_target_device.schema.json').read_text(encoding='utf-8'))
    errors=sorted(Draft202012Validator(schema).iter_errors(target),key=lambda e:str(e.path))
    return [str(e.message) for e in errors]


def freeze_write(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():
        if path.read_bytes()!=data:raise ValueError('Immutable input differs: '+str(path))
        return
    with path.open('xb') as f:f.write(data)


def encode_jsonl(rows):
    return ''.join(json.dumps(r,ensure_ascii=False,sort_keys=True)+'\n' for r in rows).encode('utf-8')


def artifact_record(frozen, cache_root=None):
    show=frozen['model_show'];info=show['model_info'];arch=info['general.architecture']
    native=info[arch+'.context_length']
    record=dict(name=frozen['name'],tag=frozen['tag'],digest=frozen['digest'],
        parameter_size=frozen['parameter_size'],parameter_count=info['general.parameter_count'],
        quantization=frozen['quantization'],native_context_length=native,experimental_context_length=8192,
        runtime=frozen['runtime'],capabilities=show.get('capabilities',[]),
        availability_on_target='unknown_target_not_selected',quality_status=QUALITY[frozen['name']],
        artifact_size_bytes=None,artifact_size_scope='sum of config and layers in exact Ollama manifest',
        judge_conflict=frozen['judge_conflict'],reference_alignment_bias_possible=True,
        generation_options=OPTIONS,source='Frozen Phase 17 generator manifest, no download')
    cache=Path(cache_root or os.environ.get('OLLAMA_MODELS') or Path.home()/'.ollama/models')
    name,tag=frozen['name'].split(':',1)
    p=cache/'manifests/registry.ollama.ai/library'/name/tag
    if p.is_file():
        if sha256_file(p)!=frozen['digest']:raise ValueError('Existing local artifact manifest differs: '+name)
        m=json.loads(p.read_text(encoding='utf-8'))
        record.update(artifact_size_bytes=sum(x['size'] for x in [m.get('config',{}),*m.get('layers',[])] if isinstance(x.get('size'),int)),
            research_host_cache_manifest_sha256=sha256_file(p),research_host_cache_manifest=str(p),
            artifact_layers=[{k:x.get(k) for k in ('digest','size','mediaType')} for x in m.get('layers',[])],
            availability_provenance='Read-only existing research-host manifest, not target-device availability')
    else:record['artifact_size_unavailable_reason']='Existing research-host Ollama manifest not found; target not selected'
    return record


def prepare_bundle():
    phase18=json.loads((ROOT/'reports/evaluation/validity/phase18/experiment_manifest.json').read_text(encoding='utf-8'))
    key=SUBSET.name
    expected=phase18['sample_sha256'][key]
    if sha256_file(SUBSET)!=expected:raise ValueError('Phase 18 edge subset checksum changed')
    frozen=validate_frozen_inputs(ROOT)
    qs={q['question_id']:q for q in frozen['questions']}
    subset=read_jsonl(SUBSET)
    contexts={r['question_id']:build_e4_top5_contexts(qs[r['question_id']],frozen['e4_trace_by_question'][r['question_id']],
        frozen['corpus_by_id']) for r in subset}
    validate_subset(subset,qs,contexts,phase18['edge_context_character_cuts'])
    common=json.loads((ROOT/'reports/evaluation/generation_models/phase17/generator_comparison_manifest.json').read_text(encoding='utf-8'))
    for rel,field in [('prompts/generation_v2.txt','prompt_sha256'),('schemas/generation_output_v2.schema.json','schema_sha256')]:
        if sha256_file(ROOT/rel)!=common[field]:raise ValueError('Frozen generation contract changed: '+rel)
    models={m['name']:artifact_record(m) for m in common['generators']}
    if set(models)!=set(MODELS) or common['generation_options']!=OPTIONS:
        raise ValueError('Frozen generator roster/config differs')
    rows=[dict(subset_row=r,question=qs[r['question_id']],contexts=contexts[r['question_id']]) for r in subset]
    selected={r['question_id'] for r in subset}
    baseline=[]
    for r in read_jsonl(ROOT/'reports/evaluation/generation_models/phase17/per_question_metrics.jsonl'):
        if r['condition']=='e4_top5' and r['question_id'] in selected:
            d=r['deterministic_generation']
            baseline.append(dict(model=r['generator'],question_id=r['question_id'],status=r['status'],answer=r['answer'],
                citations=d.get('citations',[]),schema_valid=d.get('schema_valid'),quality_reference_source='Phase 17 frozen answer',
                historical_latency_not_imported=True))
    if len(baseline)!=240 or len({(r['model'],r['question_id']) for r in baseline})!=240:
        raise ValueError('Frozen Phase 17 behavior references incomplete')
    freeze_write(BUNDLE/'inputs.jsonl',encode_jsonl(rows))
    freeze_write(BUNDLE/'phase17_behavior_references.jsonl',encode_jsonl(baseline))
    freeze_write(BUNDLE/'edge_subset_v1.jsonl',SUBSET.read_bytes())
    freeze_write(BUNDLE/'generation_v2.txt',(ROOT/'prompts/generation_v2.txt').read_bytes())
    freeze_write(BUNDLE/'generation_output_v2.schema.json',(ROOT/'schemas/generation_output_v2.schema.json').read_bytes())
    bundle_manifest=dict(benchmark_type='silver',generation_source='corpus_grounded_ai',frozen_question_count=60,
        reference_generator='Gemma 2 9B',reference_alignment_bias_possible=True,
        source_subset_sha256=expected,parent_frozen_hashes=frozen['hashes'],
        files={p.name:sha256_file(p) for p in BUNDLE.iterdir() if p.is_file() and p.name!='bundle_manifest.json'},
        question_ids=[r['question_id'] for r in subset],context_sha256_by_question={r['question_id']:r['context_sha256'] for r in subset},
        copy_policy='Immutable copies for physical-device transfer; results never overwrite source artifacts')
    freeze_write(BUNDLE/'bundle_manifest.json',(json.dumps(bundle_manifest,ensure_ascii=False,indent=2)+'\n').encode('utf-8'))
    return rows,models,bundle_manifest


def load_bundle(folder=BUNDLE):
    folder=Path(folder);m=json.loads((folder/'bundle_manifest.json').read_text(encoding='utf-8'))
    for name,expected in m['files'].items():
        if Path(name).name!=name or sha256_file(folder/name)!=expected:
            raise ValueError('Portable frozen input checksum mismatch: '+name)
    rows=read_jsonl(folder/'inputs.jsonl')
    if [r['question']['question_id'] for r in rows]!=m['question_ids']:
        raise ValueError('Frozen question order differs')
    return rows,m
