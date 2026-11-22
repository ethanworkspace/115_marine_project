from __future__ import annotations
import hashlib, json, os, sys, time
from pathlib import Path
from collections import Counter
import numpy as np
from dataclasses import asdict

ROOT=Path.cwd(); sys.path.append(str(ROOT/'.venv/Lib/site-packages')); import requests; RUN=ROOT/'reports/evaluation/fish_test_phase_t_20261017_174751'; S=ROOT/'reports/evaluation/fish_test_phase_s_integrated_20261017_173906'; RAG=S/'rag_v2'
SNAP=ROOT/'.venv-reranker/hf-cache/hub/models--BAAI--bge-reranker-v2-m3/snapshots/953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e'
DB=S/'corpus/phase_s_integrated_kb_v1.sqlite3'
EXPECTED_FILES={'config.json':'13dcd6c31d9fec9d1d8e158702072f62d7fa7d312a64b9fe057bec9a08cfe41a','model.safetensors':'d9e3e081faff1eefb84019509b2f5558fd74c1a05a2c7db22f74174fcedb5286','sentencepiece.bpe.model':'cfc8146abe2a0488e9e2a0c56de7952f7c11ab059eca145a0a727afce0db2865','special_tokens_map.json':'8c785abebea9ae3257b61681b4e6fd8365ceafde980c21970d001e834cf10835','tokenizer.json':'69564b696052886ed0ac63fa393e928384e0f8caada38c1f4864a9bfbf379c15','tokenizer_config.json':'7e4c1cc848840aeccdd763458c18dd525eb0f795c992e00ebe9c28554e7db2d4'}
EXPECTED_MODELS={'M1':('deepseek-r1:7b','755ced02ce7befdb13b7ca74e1e4d08cddba4986afdb63a480f2c93d3140383f'),'M2':('qwen2.5-coder:7b','dae161e27b0e90dd1856c8bb3209201fd6736d8eb66298e75ed87571486f4364'),'M3':('hf.co/bartowski/DeepSeek-R1-Distill-Llama-8B-GGUF:Q4_K_M','aab87d0e8a585cc6260d3a448e3f66ff2057d1cd6975c834151deeb1eae94b42'),'M4':('gemma2:9b','ff02c3702f322b9e075e9568332d96c0a7028002f1a5a056e0a6784320a4db0b'),'BGE-M3':('bge-m3:latest','7907646426070047a77226ac3e684fbbe8410524f7b4a74d02837e43f2146bab')}

def sha(p):
 h=hashlib.sha256();
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
 return h.hexdigest()
def readj(p): return json.loads(p.read_text(encoding='utf-8-sig'))
def readjl(p): return [json.loads(l) for l in p.read_text(encoding='utf-8-sig').splitlines() if l.strip()]
def writej(p,x): p.write_text(json.dumps(x,ensure_ascii=False,indent=2),encoding='utf-8')
def writejl(p,rows): p.write_text(''.join(json.dumps(x,ensure_ascii=False,separators=(',',':'))+'\n' for x in rows),encoding='utf-8')

# Reconcile the Phase S snapshot without changing it.
old_manifest=readj(S/'knowledge_base_build_manifest.json')
chunks_path=ROOT/old_manifest['chunk_file']; vector_path=ROOT/old_manifest['vector_file']; db_path=ROOT/old_manifest['database_file']
index_integrity={'chunk_file':str(chunks_path.relative_to(ROOT)),'chunk_sha256':sha(chunks_path),'expected_chunk_sha256':old_manifest['chunk_file_sha256'],'chunk_match':sha(chunks_path)==old_manifest['chunk_file_sha256'],'vector_file':str(vector_path.relative_to(ROOT)),'vector_sha256':sha(vector_path),'expected_vector_sha256':old_manifest['vector_file_sha256'],'vector_match':sha(vector_path)==old_manifest['vector_file_sha256'],'database_file':str(db_path.relative_to(ROOT)),'database_sha256':sha(db_path),'expected_database_sha256':old_manifest['database_sha256'],'database_match':sha(db_path)==old_manifest['database_sha256'],'chunk_count':sum(1 for l in chunks_path.open(encoding='utf-8-sig') if l.strip()),'candidate_corpus_version':old_manifest['corpus_version'],'formal_corpus_v3':False}

# Fresh local model identity check via Ollama API; no model generation occurs here.
ollama='http://127.0.0.1:11434'; tags=requests.get(ollama+'/api/tags',timeout=8).json().get('models',[]); tag_by_name={m.get('name'):m for m in tags}; model_checks=[]
for mid,(name,want) in EXPECTED_MODELS.items():
 rec=tag_by_name.get(name); got=(rec or {}).get('digest','').removeprefix('sha256:'); info={}
 if rec:
  try: info=requests.post(ollama+'/api/show',json={'model':name},timeout=30).json()
  except Exception as e: info={'show_error':str(e)}
 details=(rec or {}).get('details',{})
 model_checks.append({'model_id':mid,'tag':name,'available':bool(rec),'expected_digest':want,'actual_digest':got or None,'digest_match':got==want,'family':details.get('family'),'parameter_size':details.get('parameter_size'),'quantization_level':details.get('quantization_level'),'show_model_info':{k:v for k,v in (info.get('model_info') or {}).items() if 'architecture' in k or k.endswith('.block_count') or k.endswith('.embedding_length')},'checked_via':'local Ollama /api/tags and /api/show'})
writej(RUN/'model_identity_recheck.json',{'checked_at':time.strftime('%Y-%m-%dT%H:%M:%S%z'),'models':model_checks,'all_five_runtime_identities_match':all(x['digest_match'] for x in model_checks),'generator_calls':0})

# Verify exact pinned reranker artifacts, local only.
files={}
for name,want in EXPECTED_FILES.items():
 p=SNAP/name; got=sha(p) if p.is_file() else None
 files[name]={'exists':p.is_file(),'size_bytes':p.stat().st_size if p.is_file() else None,'sha256':got,'expected_sha256':want,'matches':got==want}
config=readj(SNAP/'config.json') if (SNAP/'config.json').is_file() else {}
rerank_report={'model_id':'BAAI/bge-reranker-v2-m3','required_revision':SNAP.name,'expected_revision':'953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e','snapshot_path':str(SNAP),'revision_matches':SNAP.name=='953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e','config_architecture':config.get('model_type'),'config_architectures':config.get('architectures'),'tokenizer_files_and_weight_hashes':files,'all_required_hashes_match':all(x['matches'] for x in files.values()),'local_files_only':True,'network_download_attempted':False,'source_of_previous_false_missing_status':'Phase S preflight searched default Hugging Face cache but omitted project-local .venv-reranker/hf-cache'}
if not rerank_report['all_required_hashes_match'] or config.get('model_type')!='xlm-roberta':
 rerank_report.update({'runtime_load_status':'blocked','status':'fail'}); writej(RUN/'reranker_runtime_validation.json',rerank_report); raise SystemExit('Pinned reranker artifact validation failed')

# Load source and query vectors before initializing the GPU reranker.
sys.path.insert(0,str(RAG)); import phase_s_rag as rag
chunks=rag.load_chunks(DB); by_id={c['chunk_id']:c for c in chunks}
questions=readjl(ROOT/'reports/evaluation/fish_test_run_20261012_152244/fish_test_questions_normalized.jsonl')
if len(questions)!=180: raise RuntimeError(f'Expected 180 question rows, found {len(questions)}')
profiles=[rag.requirement_profile(q) for q in questions]
queries=[f"{p['target_species'] or ''} {q.get('question_text','')}" for q,p in zip(questions,profiles)]
query_vectors=[]
for i in range(0,len(queries),24):
 response=requests.post(ollama+'/api/embed',json={'model':'bge-m3:latest','input':queries[i:i+24],'keep_alive':'0s'},timeout=180); response.raise_for_status()
 batch=np.asarray(response.json()['embeddings'],dtype=np.float32)
 if batch.shape!=(len(queries[i:i+24]),1024): raise RuntimeError(f'BGE output shape invalid: {batch.shape}')
 norms=np.linalg.norm(batch,axis=1,keepdims=True)
 if np.any(norms==0) or not np.isfinite(batch).all(): raise RuntimeError('Invalid BGE query embeddings')
 query_vectors.extend(batch/norms)
query_vectors=np.asarray(query_vectors,dtype=np.float32)

# Load once and freshly rerank all eligible RRF candidates. No answer/rubric enters query.
sys.path.insert(0,str(ROOT)); from src.evaluation.reranker_runtime import CrossEncoderRuntime
started=time.perf_counter(); model=CrossEncoderRuntime(SNAP,device='cuda',max_length=512,batch_size=4)
rerank_report.update({'runtime_load_status':'loaded','load_info':asdict(model.load_info),'load_seconds_wall':time.perf_counter()-started,'one_pair_score':model.score_pairs(queries[0],[chunks[0]['content']])[0],'status':'pass'})
writej(RUN/'reranker_runtime_validation.json',rerank_report)

results=[]; counts=Counter(); stage_counts=Counter(); eligible_counts=[]; start_all=time.perf_counter()
for i,(q,profile,query,qvec) in enumerate(zip(questions,profiles,queries,query_vectors),1):
 stages=rag.rrf_rank(query,profile,chunks,qvec,limit=100)
 candidate_rows=[]
 for rank,s in enumerate(stages['rrf'],1):
  c=dict(by_id[s['chunk_id']]); c['text']=c['content']; c['rank']=rank; c['rrf_score']=s['score']; c['bm25_rank']=s.get('bm25_rank'); c['dense_rank']=s.get('dense_rank'); candidate_rows.append(c)
 reranked=model.rerank(query,candidate_rows) if candidate_rows else []
 top=reranked[:5]; final=[]
 for rank,c in enumerate(top,1):
  content=str(c['content']); ch=hashlib.sha256(content.encode('utf-8')).hexdigest()
  final.append({'chunk_id':c['chunk_id'],'rank':rank,'reranker_rank':c['reranker_rank'],'reranker_score':c['reranker_score'],'rrf_rank':c['rank'],'rrf_score':c['rrf_score'],'bm25_rank':c.get('bm25_rank'),'dense_rank':c.get('dense_rank'),'source_id':c['source_id'],'source_title':c['source_title'],'source_url':c['source_url'],'source_sha256':c['source_sha256'],'source_version':c.get('source_version'),'page':c.get('page'),'locator':c.get('locator'),'content_sha256':ch,'content':content,'source_kind':c['source_kind'],'species_scope':c['species_scope'],'category_scope':c['category_scope'],'retrieval_eligible':True})
  if not c.get('chunk_id') or not c.get('source_id') or not (c.get('page') is not None or c.get('locator')): raise RuntimeError(f'Untraceable final chunk {c.get("chunk_id")} for {q["question_id"]}')
 status='reranked_top5_complete' if len(final)==5 else ('no_retrieval_eligible_candidates' if not candidate_rows else 'fewer_than_five_eligible_candidates')
 row={'question_id':q['question_id'],'species':q.get('species_chinese'),'category':profile['question_category'],'question_text':q.get('question_text'),'query':query,'query_excludes_answer_and_rubric':True,'run_id':RUN.name,'corpus_version':old_manifest['corpus_version'],'corpus_manifest_sha256':sha(S/'knowledge_base_build_manifest.json'),'chunk_file_sha256':index_integrity['chunk_sha256'],'vector_file_sha256':index_integrity['vector_sha256'],'database_sha256':index_integrity['database_sha256'],'retrieval_config':{'bm25_top_k':100,'dense_top_k':100,'rrf_k':60,'reranker':'BAAI/bge-reranker-v2-m3','reranker_revision':SNAP.name,'final_top_k':5,'embedding_model':'bge-m3:latest','embedding_digest':next(x['actual_digest'] for x in model_checks if x['model_id']=='BGE-M3')},'retrieval_eligible_chunk_count':stages['eligible_chunk_count'],'scope_filtered_chunk_count':stages['scope_excluded_count'],'scope_filter_reasons':stages['scope_excluded_reasons'],'bm25_top100':stages['bm25'],'dense_top100':stages['dense'],'rrf_candidates_top100':stages['rrf'],'reranked_top5':final,'final_top5_count':len(final),'retrieval_status':status,'failure_reason':None if len(final)==5 else ('no source passed frozen scope filter' if not candidate_rows else 'fewer than five eligible candidates')}
 results.append(row); counts[status]+=1; eligible_counts.append(stages['eligible_chunk_count'])
 if i%10==0:
  writejl(RUN/'retrieval_results_v3.checkpoint.jsonl',results)
  (RUN/'retrieval_checkpoint.json').write_text(json.dumps({'completed_questions':i,'total_questions':180,'updated_at':time.strftime('%Y-%m-%dT%H:%M:%S%z')},indent=2),encoding='utf-8')
writejl(RUN/'retrieval_results_v3.jsonl',results)
retrieval_summary={'question_count':len(results),'reranker_model':'BAAI/bge-reranker-v2-m3','reranker_revision':SNAP.name,'reranker_runtime_load_status':'pass','full_reranked_top5_count':counts['reranked_top5_complete'],'partial_top5_count':counts['fewer_than_five_eligible_candidates'],'no_eligible_candidates_count':counts['no_retrieval_eligible_candidates'],'mean_retrieval_eligible_chunks':float(np.mean(eligible_counts)),'retrieval_status_counts':dict(counts),'run_seconds':time.perf_counter()-start_all,'generator_calls':0,'context_support_semantic_labels':0,'note':'Top-5 outputs are retrieval candidates; no claim of gold evidence support or benchmark eligibility is made.'}
writej(RUN/'retrieval_results_summary.json',retrieval_summary)
print(json.dumps({'reranker':'pass','model_loaded':True,'revision':SNAP.name,'query_count':len(results),'top5_complete':counts['reranked_top5_complete'],'partial':counts['fewer_than_five_eligible_candidates'],'no_candidates':counts['no_retrieval_eligible_candidates'],'mean_eligible':retrieval_summary['mean_retrieval_eligible_chunks'],'seconds':round(retrieval_summary['run_seconds'],2),'generator_calls':0},ensure_ascii=True))



