from pathlib import Path
import sys,json,sqlite3,collections,subprocess,datetime,requests
W=Path(__file__).resolve().parent;R=W.parents[2];sys.path.insert(0,str(W))
from bootstrap_run import sha,write,jl
from frozen_runner import FrozenRag
rt=FrozenRag();con=sqlite3.connect(f"file:{W/'corpus/marine_hybrid_rag_corpus_v3.sqlite3'}?mode=ro",uri=True);con.row_factory=sqlite3.Row
sources=[]
for s in con.execute('select * from sources'):
 s=dict(s);p=Path(s['source_file']);s['actual_sha256']=sha(p) if p.is_file() else None;s['raw_file_reverified']=s['actual_sha256']==s['source_sha256'];sources.append(s)
assert all(s['raw_file_reverified'] for s in sources)
write('frozen_source_manifest.json',{'sources':sources,'fulltext_rights_expansion':False,'new_owner_approval_requested':False})
write('hardware_and_runtime.json',{'at':datetime.datetime.now().astimezone().isoformat(),'nvidia_smi':subprocess.run(['nvidia-smi','--query-gpu=name,memory.total,driver_version,uuid','--format=csv,noheader'],capture_output=True,text=True).stdout,'ollama_version':requests.get('http://127.0.0.1:11434/api/version').json(),'model_weights_full_byte_digest_recomputed':False,'model_identity_method':'Actual Ollama content digest plus /api/show metadata; M3 general.architecture=llama','measurement':'system-level sampled RAM and dedicated GPU memory; not process-exclusive'})
parent=R/'reports/evaluation/fish_test_corpus_v3_integration_20261021_003519/retrieval_results_v3_180.jsonl'
if parent.is_file():
 old=jl(parent);om={r['question_id']:r for r in old};diff=[]
 for r in rt.rows:
  o=om[r['question_id']];a=o.get('top5',o.get('reranked_top5',[]));b=r['top5']
  diff.append({'question_id':r['question_id'],'prior_count':len(a),'current_count':len(b),'prior_chunk_ids':[c['chunk_id'] for c in a],'current_chunk_ids':[c['chunk_id'] for c in b],'same_context_ids':[c['chunk_id'] for c in a]==[c['chunk_id'] for c in b],'prior_corpus_sha256':o.get('corpus_sha256'),'current_corpus_sha256':r['corpus_sha256'],'prior_query':o.get('question',o.get('question_text')),'current_query':r['question'],'prior_retrieval_config':o.get('retrieval_config'),'current_retrieval_config':r['retrieval_config']})
 (W/'retrieval_version_comparison_180.jsonl').write_text(''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in diff),encoding='utf-8')
 write('retrieval_version_difference.json',{'prior_path':str(parent),'prior_sha256':sha(parent),'current_sha256':sha(W/'frozen_corpus_and_contexts_180.jsonl'),'prior_context_questions':sum(bool(r.get('top5',r.get('reranked_top5',[]))) for r in old),'prior_full_top5':sum(len(r.get('top5',r.get('reranked_top5',[])))==5 for r in old),'same_chunk_id_lists':sum(x['same_context_ids'] for x in diff),'counts_declined':sum(x['current_count']<x['prior_count'] for x in diff),'counts_increased':sum(x['current_count']>x['prior_count'] for x in diff),'interpretation':'Versioned system evolution with documented scope corrections, finite source cards and record dedupe; not controlled A/B or evidence of retriever regression by itself'})
write('frozen_prompt_catalog.json',{'prompt_files':[{'question_id':r['question_id'],'prompt_sha256':__import__('hashlib').sha256(rt.payload(r,'M1')[0]['prompt'].encode()).hexdigest(),'prompt_characters':len(rt.payload(r,'M1')[0]['prompt']),'context_digest':r['context_digest']} for r in rt.rows],'reference_answers_sent_to_generator':False,'question_requirements_evidence_state_sent':True})
g=subprocess.run(['git','status','--porcelain=v1'],cwd=R,capture_output=True,text=True,encoding='utf-8',errors='replace');(W/'test_logs/git_status_before.txt').write_text(g.stdout+g.stderr,encoding='utf-8')
print('Source identities reverified',len(sources),flush=True)
