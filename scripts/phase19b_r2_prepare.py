"""Freeze a new execution revision without changing earlier outputs or runtimes."""
import json, os, platform, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from src.evaluation.generation.frozen import sha256_file, validate_frozen_inputs
from src.evaluation.edge.inputs import load_bundle, load_target, BUNDLE
from src.evaluation.edge.runtime import OllamaEdge
from src.evaluation.edge.core import OPTIONS
from src.evaluation.edge.core19b import MODELS,schedule,utc_now
OUT=ROOT/'reports/evaluation/edge/phase19B_exec_r2'

def record(p):
    s=p.stat();return dict(sha256=sha256_file(p),size=s.st_size,mtime_ns=s.st_mtime_ns)

def write(name,obj):
    p=OUT/name;p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('x',encoding='utf-8') as f:json.dump(obj,f,ensure_ascii=False,indent=2);f.write('\n')

def main():
    if OUT.exists():raise SystemExit('Execution revision directory exists; refuse overwrite')
    recovery=ROOT/'reports/evaluation/edge/phase19B_runtime_recovery'
    ready=json.loads((recovery/'phase19b_resume_status.json').read_text())
    if not ready['phase19b_runtime_ready']:raise SystemExit('Recovery not ready')
    prior=json.loads((recovery/'protected_before.json').read_text())
    changed=[n for n,v in prior.items() if not (ROOT/n).is_file() or record(ROOT/n)!=v]
    if changed:raise SystemExit('Protected mismatch: '+str(changed[:8]))
    before=dict(prior)
    for folder in (recovery,ROOT/'reports/evaluation/edge/phase19B'):
        for p in folder.rglob('*'):
            if p.is_file():before[p.relative_to(ROOT).as_posix()]=record(p)
    for p in [*(ROOT/'scripts').glob('phase19b1*'),ROOT/'src/evaluation/edge/recovery19b1.py']:
        before[p.relative_to(ROOT).as_posix()]=record(p)
    rows,bundle=load_bundle();frozen=validate_frozen_inputs(ROOT)
    if bundle['parent_frozen_hashes']!=frozen['hashes']:raise ValueError('Frozen parents differ')
    target=load_target()
    if target['device_name']!='marine-edge-workstation-01' or target['execution_node']!=platform.node():raise ValueError('Target identity differs')
    models={m:json.loads((ROOT/'reports/evaluation/edge/phase19A/model_manifests'/(m.replace(':','_')+'.json')).read_text()) for m in MODELS}
    actual=OllamaEdge(target).preflight(models)
    e4=frozen['e4_manifest'];index_dir=ROOT/'data/evaluation/indexes/E2_grounded_bge_m3_v1'
    index=json.loads((index_dir/'index_manifest.json').read_text())
    for file,key in [('chunks.jsonl','chunks_sha256'),('vectors.f32','vectors_sha256'),('query_vectors.f32','query_vectors_sha256'),('queries.jsonl','query_map_sha256')]:
        if sha256_file(index_dir/file)!=index[key]:raise ValueError('Dense artifact mismatch '+file)
    from src.evaluation.grounded_baselines import OllamaEmbeddingRuntime
    er=OllamaEmbeddingRuntime();tags=er._request('api/tags')['models']
    t=next((t for t in tags if t['name']==index['model']['model_name']),None)
    if not t or t['digest']!=index['model']['model_digest']:raise ValueError('BGE-M3 digest mismatch')
    meta=json.loads((ROOT/'reports/evaluation/reranker_runtime/model_metadata.json').read_text())
    for name,v in e4['reranker']['files'].items():
        if sha256_file(Path(meta['snapshot_location'])/name)!=v['sha256']:raise ValueError('Reranker mismatch '+name)
    # Actual local model layers are hashed, not just display names or tags.
    for m,model in models.items():
        mp=Path(model['research_host_cache_manifest'])
        if sha256_file(mp)!=model['digest']:raise ValueError('Generator manifest mismatch '+m)
        raw=json.loads(mp.read_text());base=mp.parents[4]
        for layer in [raw['config'],*raw['layers']]:
            blob=base/'blobs'/layer['digest'].replace(':','-')
            if sha256_file(blob)!=layer['digest'].split(':')[1]:raise ValueError('Generator blob mismatch '+m)
            before[str(blob)]=record(blob)
    write('protected_before.json',before)
    write('input_validation.json',dict(passed=True,questions=len(rows),contexts=sum(len(r['contexts']) for r in rows),
        frozen_hashes=frozen['hashes'],bundle=bundle,index_manifest=index,models=actual,reranker=e4['reranker']))
    write('experiment_manifest.json',dict(experiment_execution_id='phase19B_exec_r2',timestamp=utc_now(),
        references={'initial_blocked':'reports/evaluation/edge/phase19B','recovery':'reports/evaluation/edge/phase19B_runtime_recovery'},
        scope='full_edge_rag',target=target,models=models,question_ids=bundle['question_ids'],
        context_checksums=bundle['context_sha256_by_question'],generation_options=OPTIONS,protocol='v2.2',
        prompt_sha256=sha256_file(BUNDLE/'generation_v2.txt'),schema_sha256=sha256_file(BUNDLE/'generation_output_v2.schema.json'),
        protected_count=len(before),runtime='.venv-reranker',reranker=e4['reranker'],Dense=index['model'],
        BM25={'k1':1.5,'b':.75,'tokenizer':'frozen evaluation tokenizer'},RRF=e4['RRF_config'],
        schedule=schedule(),primary_target=540,requests_per_block=60,maximum_generation_attempts=2,
        maximum_runtime_block_restarts=1,restart_from_question_position=0,
        runtime_continuity='Invalid partial blocks diagnostic only; never splice resumed requests into primary blocks',
        residency='Ollama server defaults: no request keep_alive override, no manual unload/offload optimization',
        stage_latency_units='ms',telemetry_sampling_seconds=2,checkpoint_overhead_included_in_e2e=True,
        environment_start_max_seconds=300,sustained_seconds=1800,sustained_interval_seconds=300,
        quality_status={'gemma2:9b':'conditional_candidate','qwen2.5-coder:7b':'evaluation_unresolved'},
        acceptance_thresholds_defined=False,policy_allow_reason='unknown',permanent_policy_fix_claimed=False,
        no_RAGAS=True,no_download=True,no_security_policy_changes=True))
    print(json.dumps({'input_validation':'passed','protected_count':len(before),'question_count':len(rows),'context_count':300}),flush=True)

if __name__=='__main__':main()
