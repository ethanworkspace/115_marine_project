import sys, traceback, json
from pathlib import Path
from dataclasses import asdict
root=Path.cwd(); sys.path.insert(0,str(root))
from src.evaluation.reranker_runtime import CrossEncoderRuntime
p=root/'.venv-reranker/hf-cache/hub/models--BAAI--bge-reranker-v2-m3/snapshots/953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e'
try:
 m=CrossEncoderRuntime(p,device='cuda',max_length=512,batch_size=4)
 print('LOAD',json.dumps(asdict(m.load_info)))
 print('SCORES',m.score_pairs('魚種養殖管理問題',['這是關於魚種養殖管理的相關段落。','這是氣象 API 文件。']))
 rows=[{'chunk_id':'smoke-a','text':'魚種養殖管理相關段落','rank':2},{'chunk_id':'smoke-b','text':'氣象 API 文件','rank':1}]
 print('RERANK',m.rerank('魚種養殖管理問題',rows))
except Exception:
 traceback.print_exc()
 raise
