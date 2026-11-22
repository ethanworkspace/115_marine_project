"""Read-only placement/process GPU supplement; never changes model residency."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from src.evaluation.edge.hardware19a import GpuMemoryCounters
from src.evaluation.edge.telemetry19b import windows_process_tree
from src.evaluation.edge.runner import append_jsonl
OUT=ROOT/'reports/evaluation/edge/phase19B_exec_r2'
CLI=Path('C:/Users/ethan/AppData/Local/Programs/Ollama/ollama.exe')

def main():
    if (OUT/'placement_observations.jsonl').exists():raise SystemExit('Observer evidence exists; refuse overwrite')
    start=json.loads((OUT/'execution_start.json').read_text(encoding='utf-8'));pid=start['pid']
    pre=json.loads((OUT/'fresh_preflight.json').read_text(encoding='utf-8'));reranker=pre['worker']['pid']
    pdh=GpuMemoryCounters()
    try:
        while not (OUT/'execution_complete.json').exists():
            tree=windows_process_tree(pid,reranker);pids={p['pid'] for p in tree['processes']}
            data=pdh.sample()
            counters={k:[v for v in data.get(k) or [] if any(v['instance'].startswith('pid_'+str(p)+'_') for p in pids)]
                if data.get(k) is not None else None for k in ('dedicated_process','shared_process')}
            p=subprocess.run([str(CLI),'ps'],capture_output=True,encoding='utf-8',errors='replace',timeout=30)
            append_jsonl(OUT/'placement_observations.jsonl',dict(timestamp=time.monotonic(),wall_timestamp=time.time(),
                ollama_ps_stdout=p.stdout,ollama_ps_stderr=p.stderr,exit_code=p.returncode,
                process_tree=tree,process_GPU_memory=counters,adapter_shared=data.get('shared_adapter'),
                measurement_scope='WDDM process/adapter instances; shared usage is RAM-backed, never dedicated VRAM',
                sampling_seconds=5,read_only=True,no_keep_alive_or_offload_changes=True))
            time.sleep(5)
    finally:pdh.close()

if __name__=='__main__':main()
