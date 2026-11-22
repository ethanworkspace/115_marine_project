"""Supplemental read-only sampling including the llama-server worker process."""
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.evaluation.generation_models.runner import OUT, MODELS, model_dir
from src.evaluation.ragas_eval.runtime import ENDPOINT, append_jsonl
import requests

while True:
    if all((model_dir(n) / 'per_question.jsonl').exists() and sum(1 for _ in (model_dir(n) / 'per_question.jsonl').open(encoding='utf-8')) >= 338 for n in MODELS[1:]):
        break
    sample = {'timestamp': time.time(), 'sampling_scope': 'Ollama plus llama-server process-family working-set sum; device-wide VRAM'}
    try:
        command = "@(Get-Process | Where-Object { $_.ProcessName -match 'llama|ollama' } | Select-Object Id,ProcessName,WorkingSet64,PrivateMemorySize64) | ConvertTo-Json -Compress"
        result = subprocess.check_output(['powershell', '-NoProfile', '-Command', command], text=True, timeout=10)
        processes = json.loads(result)
        if isinstance(processes, dict): processes = [processes]
        gpu = subprocess.check_output(['nvidia-smi', '--query-gpu=memory.used', '--format=csv,noheader,nounits'], text=True, timeout=10)
        sample.update(processes=processes, working_set_bytes=sum(p['WorkingSet64'] for p in processes),
                      device_vram_used_mib=int(gpu.strip().splitlines()[0]), allocation=requests.get(ENDPOINT + '/api/ps', timeout=10).json())
    except Exception as exc:
        sample['error'] = type(exc).__name__ + ': ' + str(exc)
    append_jsonl(OUT / 'supplemental_memory_samples.jsonl', sample)
    time.sleep(5)
