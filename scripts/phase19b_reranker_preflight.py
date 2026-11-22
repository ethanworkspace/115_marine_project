"""Run only the mandatory CUDA reranker gate in the existing isolated runtime."""
import json
import os
import platform
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.evaluation.edge.core19b import finite_scores, runtime_gate, utc_now
from src.evaluation.generation.frozen import read_jsonl, sha256_file

OUT = ROOT / 'reports/evaluation/edge/phase19B'


def main():
    if (OUT / 'runtime_preflight.json').exists():
        raise SystemExit('Preflight evidence is immutable; refusing another execution')
    gate = json.loads((OUT/'protected_input_validation.json').read_text(encoding='utf-8'))
    if gate['status'] != 'passed':
        raise SystemExit('Input gate did not pass')
    os.environ['HF_HUB_OFFLINE'] = '1'
    os.environ['TRANSFORMERS_OFFLINE'] = '1'
    os.environ['HF_HUB_DISABLE_TELEMETRY'] = '1'
    result = dict(timestamp=utc_now(), executable=sys.executable, Python=platform.python_version(),
        torch_import=False, cuda_available=False, model_loaded=False, single_pair_finite=False,
        ten_query_count=0, pairs_scored=0, all_scores_finite=False, candidate_ids_preserved=False,
        device_requested='cuda:0', CPU_fallback_allowed=False, alternate_model_allowed=False,
        reranker=gate['reranker_identity'], failed_step=None, runtime_ready=False,
        technical_retry_count=0, Generator_executions=0)
    step = 'torch_import'
    started = time.perf_counter()
    try:
        import torch
        result.update(torch_import=True, torch_version=torch.__version__, CUDA_version=torch.version.cuda)
        step = 'CUDA_availability'
        result['cuda_available'] = torch.cuda.is_available()
        if not result['cuda_available']:
            raise RuntimeError('Mandatory CUDA runtime unavailable; CPU fallback prohibited')
        result['GPU_name'] = torch.cuda.get_device_name(0)
        meta = json.loads((ROOT/'reports/evaluation/reranker_runtime/model_metadata.json').read_text(encoding='utf-8'))
        step = 'model_load'
        from src.evaluation.reranker_runtime import CrossEncoderRuntime
        cfg = gate['reranker_identity']
        runtime = CrossEncoderRuntime(meta['snapshot_location'],device=cfg['device'],
            max_length=cfg['max_sequence_length'],batch_size=cfg['batch_size'])
        result['model_loaded'] = True
        result['model_load_seconds'] = runtime.load_info.model_load_seconds
        bundle = read_jsonl(ROOT/'data/evaluation/edge/phase19_inputs_v1/inputs.jsonl')
        candidates = read_jsonl(ROOT/'reports/evaluation/reranker_runtime/e3_rrf_top50_candidates.jsonl')
        pools = {}
        for candidate in candidates:
            pools.setdefault(candidate['question_id'], []).append(candidate)
        pools = {qid: sorted(rows, key=lambda r: int(r['rank'])) for qid, rows in pools.items()}
        result['preflight_source'] = 'Frozen E3 Top-50 candidate pool; no ranking labels used for scoring'
        sample = []
        step = 'single_pair_inference'
        first = bundle[0]['question']
        passages = pools[first['question_id']]
        if not isinstance(passages, list) or len(passages) != 50:
            raise ValueError('Frozen candidate pool format is not a 50-candidate query row')
        text = passages[0]['text']
        scores = runtime.score_pairs(first['question'], [text])
        result['single_pair_finite'] = finite_scores(scores, 1)
        result['single_pair_scores'] = scores
        if not result['single_pair_finite']:
            raise RuntimeError('Single pair score failed')
        step = 'ten_query_inference'
        for row in bundle[:10]:
            q = row['question']; passages = pools[q['question_id']]
            if not isinstance(passages, list) or len(passages) != 50:
                raise ValueError('Expected exactly 50 frozen RRF candidates')
            ranked = runtime.rerank(q['question'], passages)
            valid = finite_scores([r['reranker_score'] for r in ranked], 50)
            identity = {r['chunk_id'] for r in ranked} == {r['chunk_id'] for r in passages}
            if not valid or not identity:
                raise RuntimeError('Nonfinite scores or candidate loss')
            sample.append(dict(question_id=q['question_id'], pairs=ranked))
            result['ten_query_count'] += 1
            result['pairs_scored'] += 50
        result.update(all_scores_finite=True, candidate_ids_preserved=True)
        with (OUT/'preflight_scores.jsonl').open('x',encoding='utf-8') as stream:
            for row in sample:
                stream.write(json.dumps(row,ensure_ascii=False)+'\n')
    except Exception as exc:
        result.update(failed_step=step, error_type=type(exc).__name__, error=str(exc),
            winerror=getattr(exc,'winerror',None), traceback=traceback.format_exc())
    result['elapsed_seconds'] = time.perf_counter()-started
    result['runtime_ready'] = runtime_gate(result)
    result['phase19B_status'] = 'preflight_passed' if result['runtime_ready'] else 'blocked_reranker_runtime'
    with (OUT/'runtime_preflight.json').open('x',encoding='utf-8') as stream:
        json.dump(result,stream,ensure_ascii=False,indent=2);stream.write('\n')
    print(json.dumps({k:result.get(k) for k in ('phase19B_status','failed_step','error','winerror','pairs_scored','runtime_ready')},ensure_ascii=False),flush=True)


if __name__ == '__main__':
    main()
