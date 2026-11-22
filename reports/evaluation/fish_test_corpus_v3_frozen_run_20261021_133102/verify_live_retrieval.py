from pathlib import Path
import sys,json,gc,time
W=Path(__file__).resolve().parent;R=W.parents[2];sys.path.insert(0,str(W));sys.stdout.reconfigure(encoding='utf-8')
from frozen_runner import FrozenRag,unload,write,sha,requests,OLLAMA
from rag_v3_runtime import RagV3Runtime
for x in requests.get(OLLAMA+'/api/ps').json().get('models',[]):unload(x['name'])
rt=RagV3Runtime(load_reranker=True);f=FrozenRag();q=f.retrieval['FT-milkfish-Q04'];start=time.perf_counter();r=rt.retrieve(q['question'],q['species'],q['category'])
a=[c['chunk_id'] for c in r['top5']];b=[c['chunk_id'] for c in q['top5']]
write('live_retrieval_validation.json',{'status':'PASS' if a==b else 'FAIL','method':'Fresh actual BM25 + BGE-M3 embedding + RRF60 + local BGE Reranker; no corpus rebuild','question_id':q['question_id'],'new_top5_ids':a,'frozen_top5_ids':b,'actual_retrieval':r,'wall_seconds':time.perf_counter()-start,'frozen_context_not_modified':True})
path=rt.pipe.RERANKER_PATH;files=[p for p in path.iterdir() if p.is_file()]
write('reranker_file_identity.json',{'snapshot':str(path),'files':[{'filename':p.name,'sha256':sha(p),'bytes':p.stat().st_size} for p in files]})
unload('bge-m3:latest');del rt;gc.collect()
import torch
torch.cuda.empty_cache();print('Live retrieval',a==b,flush=True)
