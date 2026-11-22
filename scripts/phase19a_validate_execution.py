"""Validate all request/attempt identities without any model or retrieval calls."""
import json,sys
from collections import Counter,defaultdict
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from src.evaluation.edge.execution19a import OUT,write
from src.evaluation.edge.inputs import BUNDLE,load_bundle
from src.evaluation.edge.core import MODELS,digest
from src.evaluation.edge.runner import read_rows

def main():
    rows,bundle=load_bundle();expected={r['question']['question_id']:r for r in rows}
    warm=read_rows(OUT/'warm_runs.jsonl');failures=[];seen=Counter()
    for r in read_rows(OUT/'per_request_metrics.jsonl'):
        item=expected.get(r['question_id'])
        if item is None:failures.append('unknown question');continue
        if r['context_sha256']!=item['subset_row']['context_sha256'] or r['context_ids']!=[c['context_id'] for c in item['contexts']] or r['context_chunk_ids']!=[c['chunk_id'] for c in item['contexts']]:
            failures.append('context mismatch '+r['question_id'])
        if len(set(r['attempt_request_sha256']))!=1:failures.append('retry input changed '+r['question_id'])
    count=0;raw_fail=0;attempt_keys=defaultdict(list)
    for line in (OUT/'attempts.jsonl').open(encoding='utf-8'):
        if not line.strip():continue
        r=json.loads(line);count+=1
        raw_fail+=digest(r['raw_output'])!=r['raw_output_sha256'] or r['captured_runtime']['raw_output_sha256']!=r['raw_output_sha256']
        key=(r['stage'],r['model'],r['repetition'],r['question_id']);attempt_keys[key].append(r)
    for key,attempts in attempt_keys.items():
        if [r['attempt_number'] for r in attempts] not in ([1],[1,2]):failures.append('invalid attempt sequence '+str(key))
        if len(attempts)==2 and attempts[0]['attempt_valid']:failures.append('retry on success '+str(key))
    for model in MODELS:
        for rep in (1,2,3):
            ids=[r['question_id'] for r in warm if r['model']==model and r['repetition']==rep]
            if ids!=bundle['question_ids']:failures.append('incomplete/changed warm order '+model+' '+str(rep))
    for p in read_rows(OUT/'model_placement.jsonl'):
        active=p.get('runtime_model_status') or {}
        expected_model=json.loads((OUT/'model_manifests'/(p['model'].replace(':','_')+'.json')).read_text(encoding='utf-8'))
        if active.get('digest')!=expected_model['digest'] or active.get('context_length')!=8192:
            failures.append('resident model identity/context length mismatch '+p['model'])
    result=dict(passed=not failures and not raw_fail,formal_requests=len(warm),expected_formal_requests=720,
        preserved_attempt_count=count,raw_SHA_mismatches=raw_fail,raw_preservation_rate=(count-raw_fail)/count if count else None,
        context_mismatch_or_protocol_failures=failures,no_retrieval_execution=True,no_Judge_execution=True)
    starts=read_rows(OUT/'thermal_start_conditions.jsonl')
    result['start_condition_protocol_deviations']=[{k:t.get(k) for k in ('model','repetition','wait_seconds','continuous_idle_60_seconds','actual_temperature_c')}
        for t in starts if t.get('utilization_baseline_not_reached')]
    result['data_integrity_passed']=result['passed']
    result['environment_start_protocol_complete']=not result['start_condition_protocol_deviations']
    write(OUT/'execution_validation.json',result);print(json.dumps(result))
    if not result['passed']:raise SystemExit(1)
if __name__=='__main__':main()
