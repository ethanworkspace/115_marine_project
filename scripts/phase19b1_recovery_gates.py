"""Exact existing CUDA runtime R0-R5 gates; never run formal Phase 19B benchmark."""
import datetime as dt
import json
import os
import sys
import traceback
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from src.evaluation.generation.frozen import read_jsonl,sha256_file
from src.evaluation.edge.recovery19b1 import compatibility,exact_model_identity
OUT=ROOT/'reports/evaluation/edge/phase19B_runtime_recovery'


def write(name,data):
    with (OUT/name).open('x',encoding='utf-8') as f:json.dump(data,f,indent=2,ensure_ascii=False);f.write('\n')


def main():
    if (OUT/'torch_preflight.json').exists():raise SystemExit('Recovery execution already preserved; do not retry')
    decision=json.loads((OUT/'remediation_decision.json').read_text(encoding='utf-8'))
    if decision['requires_policy_authorization']:raise SystemExit('Policy authorization required; no auto remediation')
    os.environ['HF_HUB_OFFLINE']='1';os.environ['TRANSFORMERS_OFFLINE']='1';os.environ['HF_HUB_DISABLE_TELEMETRY']='1'
    gates={};stage='R0';started=dt.datetime.now(dt.timezone.utc).isoformat()
    names={'R0':'torch_preflight.json','R1':'cuda_preflight.json','R2':'reranker_model_preflight.json',
           'R3':'single_pair_validation.json','R4':'ten_query_validation.json','R5':'ten_query_compatibility.json'}
    try:
        import torch
        gates['R0']=dict(passed=True,torch_version=torch.__version__,CUDA_build=torch.version.cuda,runtime_path=torch.__file__,
            executable=sys.executable,Python=sys.version,started_at=started,environment_rebuilt=False)
        write(names['R0'],gates['R0']);stage='R1'
        available=torch.cuda.is_available()
        gates['R1']=dict(passed=available,CUDA_available=available,GPU_name=torch.cuda.get_device_name(0) if available else None,
                        CPU_fallback=False)
        write(names['R1'],gates['R1'])
        if not available:raise RuntimeError('blocked_cuda_runtime')
        stage='R2'
        model=json.loads((ROOT/'reports/evaluation/reranker_runtime/model_metadata.json').read_text())
        hashes={name:sha256_file(Path(model['snapshot_location'])/name) for name in model['files']}
        if not exact_model_identity(model,hashes):raise RuntimeError('Exact reranker identity changed')
        from src.evaluation.reranker_runtime import CrossEncoderRuntime
        runtime=CrossEncoderRuntime(model['snapshot_location'],device='cuda:0',max_length=512,batch_size=4)
        gates['R2']=dict(passed=True,model_id=model['model_id'],revision=model['revision'],artifact_hashes=hashes,
            device=runtime.device,dtype=runtime.load_info.dtype,max_length=runtime.max_length,batch_size=runtime.batch_size,
            model_load_seconds=runtime.load_info.model_load_seconds)
        write(names['R2'],gates['R2']);stage='R3'
        pools={}
        for row in read_jsonl(ROOT/'reports/evaluation/reranker_runtime/e3_rrf_top50_candidates.jsonl'):
            pools.setdefault(row['question_id'],[]).append(row)
        pools={qid:sorted(rows,key=lambda r:int(r['rank'])) for qid,rows in pools.items()}
        single=json.loads((ROOT/'reports/evaluation/reranker_runtime/one_pair_smoke.json').read_text())
        candidates={r['chunk_id']:r for r in pools[single['question_id']]}
        pair=[candidates[cid] for cid in single['chunk_ids']]
        if len(pair)!=2:raise RuntimeError('Frozen single-pair fixture does not contain exactly two candidates')
        scores=runtime.score_pairs(pair[0]['question'],[r['text'] for r in pair])
        import math
        good=len(scores)==2 and all(math.isfinite(s) for s in scores)
        gates['R3']=dict(passed=good,question_id=single['question_id'],chunk_ids=single['chunk_ids'],scores=scores,
            finite=good,candidate_identity_preserved=len(scores)==len(pair),NaN_count=sum(math.isnan(s) for s in scores),
            Inf_count=sum(math.isinf(s) for s in scores))
        write(names['R3'],gates['R3'])
        if not good:raise RuntimeError('Single-pair validation failed')
        stage='R4'
        mini=json.loads((ROOT/'reports/evaluation/reranker_runtime/mini_batch_smoke.json').read_text())
        reference={}
        for row in read_jsonl(ROOT/'reports/evaluation/experiments/E4_grounded_rrf_reranker_v1/reranker_traces.jsonl'):
            reference.setdefault(row['question_id'],[]).append(row)
        actual=[];comparisons=[]
        with (OUT/'ten_query_scores.jsonl').open('x',encoding='utf-8') as stream:
            for qid in mini['question_ids']:
                ranked=runtime.rerank(pools[qid][0]['question'],pools[qid])
                cmp=compatibility(reference[qid],ranked);comparisons.append(dict(question_id=qid,**cmp))
                if len(ranked)!=50 or not cmp['all_scores_finite'] or not cmp['candidate_identity_preserved']:
                    raise RuntimeError('10-query scoring identity or finite-score validation failed')
                for row in ranked:stream.write(json.dumps(row,ensure_ascii=False)+'\n')
                actual.extend(ranked)
        gates['R4']=dict(passed=True,question_ids=mini['question_ids'],queries=10,pairs_scored=len(actual),
            scores_source='ten_query_scores.jsonl',candidate_identity_preserved=True,all_scores_finite=True)
        write(names['R4'],gates['R4']);stage='R5'
        passed=all(c['passed'] for c in comparisons)
        gates['R5']=dict(passed=passed,question_count=len(comparisons),comparisons=comparisons,
            ordering_mismatch_count=sum(not c['ordering_equal'] for c in comparisons),
            max_score_difference=max(c['max_score_difference'] for c in comparisons),
            score_exact=all(c['score_exact'] for c in comparisons),
            reference='Frozen E4 reranker traces for original Phase14.1 10-query subset',
            settings_changed=False)
        write(names['R5'],gates['R5'])
        if not passed:raise RuntimeError('reranker_runtime_compatibility_failed')
    except Exception as exc:
        failure=dict(passed=False,status='failed',failed_gate=stage,error=str(exc),error_type=type(exc).__name__,
                     winerror=getattr(exc,'winerror',None),traceback=traceback.format_exc())
        gates.setdefault(stage,failure)
        if not (OUT/names[stage]).exists():write(names[stage],failure)
    for gate,name in names.items():
        if not (OUT/name).exists():write(name,dict(passed=False,status='not_reached',prior_failed_gate=stage))
    write('R0_R5_execution.json',dict(gates=gates,all_passed=all(gates.get(k,{}).get('passed') for k in names),
        failed_gate=None if all(gates.get(k,{}).get('passed') for k in names) else stage,
        started_at=started,finished_at=dt.datetime.now(dt.timezone.utc).isoformat(),runtime_r2_created=False,
        original_runtime_used=True,no_CPU_fallback=True,no_model_substitution=True,formal_queries_executed=0))
    print(json.dumps({'gates':{k:v.get('passed') for k,v in gates.items()},'last_gate':stage},ensure_ascii=False),flush=True)


if __name__=='__main__':main()
