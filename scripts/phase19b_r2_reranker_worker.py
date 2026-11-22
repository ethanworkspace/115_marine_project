"""Frozen reranker environment worker; stdlib IPC, same CrossEncoderRuntime."""
import importlib.metadata as md
import json
import os
import sys
import traceback
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
os.environ['HF_HUB_OFFLINE']='1';os.environ['TRANSFORMERS_OFFLINE']='1';os.environ['HF_HUB_DISABLE_TELEMETRY']='1'

def send(value):print(json.dumps(value,ensure_ascii=True),flush=True)

try:
    import torch
    if torch.__version__!='2.14.1+cu130' or not torch.cuda.is_available():raise RuntimeError('Exact torch/CUDA gate failed')
    if md.version('transformers')!='5.18.0' or md.version('huggingface-hub')!='1.33.0':raise RuntimeError('Pinned dependency versions differ')
    if torch.cuda.get_device_name(0)!='NVIDIA GeForce RTX 4060':raise RuntimeError('GPU identity differs')
    from src.evaluation.reranker_runtime import CrossEncoderRuntime
    meta=json.loads((ROOT/'reports/evaluation/reranker_runtime/model_metadata.json').read_text(encoding='utf-8'))
    runtime=CrossEncoderRuntime(meta['snapshot_location'],device='cuda:0',max_length=512,batch_size=4)
    send(dict(ready=True,model_loaded=True,pid=os.getpid(),torch=torch.__version__,CUDA=True,
        CUDA_build=torch.version.cuda,GPU=torch.cuda.get_device_name(0),model_load_seconds=runtime.load_info.model_load_seconds,
        runtime_path=torch.__file__,device='cuda:0',dtype='float32',max_length=512,batch_size=4))
    for line in sys.stdin:
        try:
            request=json.loads(line)
            if request['operation']=='close':break
            if request['operation']=='score':value=runtime.score_pairs(request['query'],request['texts'])
            elif request['operation']=='rerank':value=runtime.rerank(request['query'],request['candidates'])
            else:raise ValueError('Unknown operation')
            send(dict(ok=True,value=value))
        except Exception as exc:send(dict(ok=False,error=str(exc),traceback=traceback.format_exc()));break
except Exception as exc:send(dict(ready=False,error=str(exc),traceback=traceback.format_exc()));sys.exit(1)
