"""Only the authorized 60-question E4 reproduction gate, not a timing benchmark."""
import datetime as dt
import json
import os
import sys
from array import array
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from src.evaluation.generation.frozen import validate_frozen_inputs,read_jsonl,sha256_file
from src.evaluation.edge.recovery19b1 import resume_gate
from src.evaluation.edge.core19b import compare_top5
OUT=ROOT/'reports/evaluation/edge/phase19B_runtime_recovery'


def write(name,data):
    with (OUT/name).open('x',encoding='utf-8') as f:json.dump(data,f,indent=2,ensure_ascii=False);f.write('\n')


def main():
    if (OUT/'e4_60_reproduction.json').exists():raise SystemExit('Reproduction evidence already exists; refuse retry')
    prior=json.loads((OUT/'R0_R5_execution.json').read_text(encoding='utf-8'))
    if not prior['all_passed']:raise SystemExit('R0-R5 must all pass before any new retrieval')
    os.environ['HF_HUB_OFFLINE']='1';os.environ['TRANSFORMERS_OFFLINE']='1';os.environ['HF_HUB_DISABLE_TELEMETRY']='1'
    started=dt.datetime.now(dt.timezone.utc).isoformat();results=[];failure=None
    try:
        from src.evaluation.grounded_baselines import load_dense_index,OllamaEmbeddingRuntime
        from src.evaluation.retrievers.bm25 import EvaluationBM25
        from src.evaluation.rrf import fuse_ranked_lists
        from src.evaluation.silver import _eligible_corpus
        from src.evaluation.reranker_runtime import CrossEncoderRuntime
        frozen=validate_frozen_inputs(ROOT)
        rows=read_jsonl(ROOT/'data/evaluation/edge/phase19_inputs_v1/inputs.jsonl')
        subset=read_jsonl(ROOT/'reports/evaluation/validity/phase18/edge_benchmark_subset_v1.jsonl')
        if [r['question']['question_id'] for r in rows]!=[r['question_id'] for r in subset]:
            raise RuntimeError('Frozen subset order mismatch')
        corpus=_eligible_corpus(frozen['corpus'])
        if len(corpus)!=2224:raise RuntimeError('Expected 2224 canonical retrieval chunks')
        bm25=EvaluationBM25(corpus,corpus_sha256=frozen['hashes']['evaluation_corpus_v2_sha256'])
        dense,index=load_dense_index(ROOT,{'corpus':corpus,'questions':frozen['questions'],
            'hashes':{'evaluation_corpus_v2':frozen['hashes']['evaluation_corpus_v2_sha256']}})
        embed=OllamaEmbeddingRuntime();embed.dimension=1024
        tags=embed._request('api/tags')['models']
        tag=next((t for t in tags if t['name']==index['model']['model_name']),None)
        if not tag or tag['digest']!=index['model']['model_digest']:
            raise RuntimeError('Pinned BGE-M3 runtime identity changed')
        if embed._request('api/version').get('version')!='0.35.0':raise RuntimeError('Ollama runtime version changed')
        meta=json.loads((ROOT/'reports/evaluation/reranker_runtime/model_metadata.json').read_text())
        for name,record in meta['files'].items():
            if sha256_file(Path(meta['snapshot_location'])/name)!=record['sha256']:raise RuntimeError('Model artifact checksum changed')
        reranker=CrossEncoderRuntime(meta['snapshot_location'],device='cuda:0',max_length=512,batch_size=4)
        old_candidates={}
        for r in read_jsonl(ROOT/'reports/evaluation/experiments/E3_grounded_rrf_v1/candidate_traces.jsonl'):
            old_candidates.setdefault((r['question_id'],r['retriever_type']),[]).append(r)
        old_rrf={}
        for r in read_jsonl(ROOT/'reports/evaluation/reranker_runtime/e3_rrf_top50_candidates.jsonl'):
            old_rrf.setdefault(r['question_id'],[]).append(r)
        with (OUT/'e4_reproduction_traces.jsonl').open('x',encoding='utf-8') as trace:
            for row in rows:
                question=row['question'];qid=question['question_id'];query=question['question']
                bm_hits=bm25.retrieve(query,top_k=50)
                current_vector=embed.embed_texts([query],batch_size=32)[0]
                current_vector=array('f',current_vector).tolist() # exact baseline serialization precision
                saved_vector=dense.query_vectors[query]
                dense_hits=dense.rank_vector(current_vector)[:50]
                fused=fuse_ranked_lists(bm_hits,dense_hits,frozen['corpus_by_id'],k=60,top_n=50)
                candidates=[dict(chunk_id=r['chunk_id'],document_id=r['document_id'],page=r['page'],
                    rank=r['final_rank'],rrf_rank=r['final_rank'],rrf_score=r['rrf_score'],
                    bm25_rank=r['bm25_rank'],dense_rank=r['dense_rank'],text=frozen['corpus_by_id'][r['chunk_id']]['text']) for r in fused]
                ranked=reranker.rerank(query,candidates)
                expected=[c['chunk_id'] for c in row['contexts']]
                actual=[r['chunk_id'] for r in ranked[:5]]
                cmp=compare_top5(expected,actual)
                intermediate={}
                for name,hits in [('bm25',bm_hits),('dense',dense_hits)]:
                    refs=sorted(old_candidates.get((qid,name),[]),key=lambda r:int(r['rank']))[:50]
                    intermediate[name+'_top50_equal']=[r['chunk_id'] for r in refs]==[h.chunk_id for h in hits] if refs else None
                reference_rrf=sorted(old_rrf.get(qid,[]),key=lambda r:int(r['rank']))
                intermediate['RRF_top50_equal']=[r['chunk_id'] for r in reference_rrf]==[r['chunk_id'] for r in candidates]
                record=dict(question_id=qid,**cmp,**intermediate,
                    query_embedding_max_delta=max(abs(a-b) for a,b in zip(current_vector,saved_vector)),
                    reranker_candidates=len(ranked),context_text_provenance_match=all(
                        c['document_id']==frozen['corpus_by_id'][c['chunk_id']]['document_id'] and
                        c['text']==frozen['corpus_by_id'][c['chunk_id']]['text'] for c in row['contexts']))
                results.append(record)
                trace.write(json.dumps(dict(**record,bm25_chunk_ids=[h.chunk_id for h in bm_hits],
                    dense_chunk_ids=[h.chunk_id for h in dense_hits],RRF_chunk_ids=[r['chunk_id'] for r in candidates],
                    reranked=[{k:r.get(k) for k in ('chunk_id','reranker_score','reranker_rank','rrf_rank','rrf_score')} for r in ranked]),ensure_ascii=False)+'\n')
                trace.flush()
                print(json.dumps({'checked':len(results),'question_id':qid,'top5_equal':cmp['match']},ensure_ascii=False),flush=True)
                if not cmp['match']:
                    raise RuntimeError('E4 final Top-5 mismatch; stop without tuning')
    except Exception as exc:
        import traceback
        failure=dict(error=str(exc),error_type=type(exc).__name__,winerror=getattr(exc,'winerror',None),traceback=traceback.format_exc())
    passed=len(results)==60 and all(r['match'] and r['context_text_provenance_match'] for r in results) and failure is None
    write('e4_60_reproduction.json',dict(passed=passed,retrieval_reproducibility_pass=passed,
        questions_expected=60,questions_checked=len(results),matched=sum(r['match'] for r in results),
        mismatch_count=sum(not r['match'] for r in results),results=results,failure=failure,
        fresh_Dense_query_embeddings=True,uses_saved_corpus_vectors=True,uses_saved_query_vectors_for_ranking=False,
        benchmark_queries_executed=0,started_at=started,finished_at=dt.datetime.now(dt.timezone.utc).isoformat()))
    print(json.dumps({'retrieval_reproducibility_pass':passed,'checked':len(results),'failure':failure},ensure_ascii=False),flush=True)


if __name__=='__main__':main()
