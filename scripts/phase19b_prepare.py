"""Read-only artifact gate; freeze new Phase 19B manifests before inference."""
import json
import platform
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.evaluation.generation.frozen import sha256_file, validate_frozen_inputs
from src.evaluation.edge.inputs import load_bundle, BUNDLE, load_target
from src.evaluation.edge.runtime import OllamaEdge
from src.evaluation.edge.core import OPTIONS
from src.evaluation.edge.core19b import MODELS, CONDITIONS, schedule, utc_now

OUT = ROOT / 'reports/evaluation/edge/phase19B'


def write(name, value):
    path = OUT / name
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


def stat(path):
    s = path.stat()
    return dict(sha256=sha256_file(path), size=s.st_size, mtime_ns=s.st_mtime_ns)


def main():
    if (OUT / 'protected_before.json').exists():
        raise SystemExit('Refusing to overwrite Phase 19B initial protection snapshot')
    a = ROOT / 'reports/evaluation/edge/phase19A'
    old = json.loads((a / 'protected_before.json').read_text(encoding='utf-8'))
    allowed = {'configs/edge_target_device.yaml', 'tests/evaluation/test_target_device_manifest.py'}
    mismatches = [name for name, rec in old.items() if name not in allowed and
                  (not (ROOT / name).is_file() or stat(ROOT / name) != rec)]
    expected = dict(old)
    for name in allowed:
        expected[name] = stat(ROOT / name)
    # Freeze all Phase 19/19A source, report and portable data files, including final logs.
    folders = ('reports/evaluation/edge/phase19A', 'reports/evaluation/edge/phase19',
               'data/evaluation/edge/phase19_inputs_v1', 'src/evaluation/edge')
    for folder in folders:
        for p in (ROOT / folder).rglob('*'):
            if p.is_file() and '__pycache__' not in p.parts and not p.name.endswith('19b.py'):
                expected[p.relative_to(ROOT).as_posix()] = stat(p)
    for p in [*(ROOT / 'scripts').glob('phase19a*.py'), ROOT / 'docs/phase19A_local_edge_protocol.md']:
        expected[p.relative_to(ROOT).as_posix()] = stat(p)
    write('protected_before.json', expected)
    if mismatches:
        write('protected_input_validation.json', {'status': 'failed', 'mismatches': mismatches})
        raise SystemExit('Protected artifact mismatch; no runtime execution')
    frozen = validate_frozen_inputs(ROOT)
    rows, bundle = load_bundle()
    if bundle['parent_frozen_hashes'] != frozen['hashes']:
        raise ValueError('Frozen Phase 19 parent checksum mismatch')
    a_manifest = json.loads((a / 'experiment_manifest.json').read_text(encoding='utf-8'))
    if a_manifest['question_ids'] != bundle['question_ids'] or a_manifest['generation_options'] != OPTIONS:
        raise ValueError('Phase 19A subset or common generation settings mismatch')
    e4 = frozen['e4_manifest']
    relationships = {
        'E1_manifest_sha256': 'reports/evaluation/experiments/E1_grounded_bm25_v1/experiment_manifest.json',
        'E2_manifest_sha256': 'reports/evaluation/experiments/E2_grounded_dense_v1/experiment_manifest.json',
        'E3_manifest_sha256': 'reports/evaluation/experiments/E3_grounded_rrf_v1/experiment_manifest.json',
        'E2_dense_index_manifest_sha256': 'data/evaluation/indexes/E2_grounded_bge_m3_v1/index_manifest.json'}
    for key, name in relationships.items():
        if sha256_file(ROOT / name) != e4[key]:
            raise ValueError('Frozen E4 ancestor differs: ' + key)
    index_dir = ROOT / 'data/evaluation/indexes/E2_grounded_bge_m3_v1'
    index = json.loads((index_dir / 'index_manifest.json').read_text(encoding='utf-8'))
    for filename, key in [('chunks.jsonl', 'chunks_sha256'), ('vectors.f32', 'vectors_sha256'),
                          ('query_vectors.f32', 'query_vectors_sha256'), ('queries.jsonl', 'query_map_sha256')]:
        if sha256_file(index_dir / filename) != index[key]:
            raise ValueError('Dense index artifact differs: ' + filename)
    meta = json.loads((ROOT / 'reports/evaluation/reranker_runtime/model_metadata.json').read_text(encoding='utf-8'))
    snapshot = Path(meta['snapshot_location'])
    for name, record in e4['reranker']['files'].items():
        if sha256_file(snapshot / name) != record['sha256']:
            raise ValueError('Reranker artifact differs: ' + name)
    target = load_target()
    if target['device_name'] != 'marine-edge-workstation-01' or target['execution_node'] != platform.node():
        raise ValueError('Target physical machine identity mismatch')
    models = {m: json.loads((a / 'model_manifests' / (m.replace(':', '_') + '.json')).read_text(encoding='utf-8')) for m in MODELS}
    adapter = OllamaEdge(target)
    actual = adapter.preflight(models)
    import requests
    tags = requests.get('http://127.0.0.1:11434/api/tags', timeout=10).json()['models']
    dense_tag = next((t for t in tags if t['name'] == index['model']['model_name']), None)
    if dense_tag is None or dense_tag['digest'] != index['model']['model_digest']:
        raise ValueError('Existing BGE-M3 model artifact unavailable or changed; no download')
    write('protected_input_validation.json', dict(status='passed', protected_files=len(expected),
        frozen_hashes=frozen['hashes'], dense_index=index, reranker_identity=e4['reranker'],
        question_count=len(rows), context_count=sum(len(r['contexts']) for r in rows)))
    write('experiment_manifest.json', dict(experiment_id='phase19B_full_edge_rag_v1',
        timestamp=utc_now(), status='awaiting_reranker_preflight', target_device=target['device_name'],
        benchmark_scope='full_rag', conditions=CONDITIONS, models=MODELS,
        question_ids=bundle['question_ids'], context_sha256_by_question=bundle['context_sha256_by_question'],
        frozen_hashes=frozen['hashes'], ancestor_hashes={k: e4[k] for k in relationships},
        BM25={'k1':1.5,'b':0.75,'tokenizer':'frozen evaluation tokenizer'}, Dense=index['model'],
        RRF=e4['RRF_config'], candidate_depth=e4['candidate_depth'], reranker=e4['reranker'],
        generation_options=OPTIONS, generation_protocol='v2.2', maximum_attempts=2,
        prompt_sha256=sha256_file(BUNDLE/'generation_v2.txt'),
        schema_sha256=sha256_file(BUNDLE/'generation_output_v2.schema.json'),
        run_order=schedule(), cold_runs_per_condition=3, warm_requests_per_condition=180,
        formal_query_count=540, sustained_seconds_per_generator=1800,
        sustained_gate='Three formal runs completed without OOM/runtime crash',
        residency_policy='Existing frozen runtime defaults; no manual residency optimization',
        retrieval_retry_count=0, reranker_retry_count=0,
        environment_start={'GPU_utilization_less_than_percent':5,'GPU_temperature_at_most_C':45,'maximum_wait_seconds':300},
        acceptance_thresholds_defined=False, quality_status={'gemma2:9b':'conditional_candidate','qwen2.5-coder:7b':'evaluation_unresolved'},
        no_RAGAS=True,no_model_download=True,no_production_migration=True))
    write('target_device_manifest.json', target)
    for model in MODELS:
        write('model_manifests/'+model.replace(':','_')+'.json', {**models[model], 'preflight_identity': actual[model]})
    print(json.dumps({'protected_input_validation':'passed','protected_count':len(expected),'reranker_snapshot':str(snapshot),'next':'CUDA preflight'}), flush=True)


if __name__ == '__main__':
    main()
