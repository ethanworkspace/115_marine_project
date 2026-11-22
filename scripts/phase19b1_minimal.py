"""Only one minimal import reproduction; preserve raw bytes and timestamps."""
import datetime as dt
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from src.evaluation.generation.frozen import sha256_file
OUT=ROOT/'reports/evaluation/edge/phase19B_runtime_recovery'


def main():
    if (OUT/'minimal_failure.json').exists():raise SystemExit('Minimal reproduction already preserved; do not repeat')
    if not (OUT/'protected_before.json').is_file():raise SystemExit('Preservation snapshot missing')
    cmd=[str(ROOT/'.venv-reranker/Scripts/python.exe'),'-B','-c','import torch']
    env={**os.environ,'PYTHONIOENCODING':'utf-8','PYTHONDONTWRITEBYTECODE':'1'}
    before=dt.datetime.now(dt.timezone.utc).isoformat()
    r=subprocess.run(cmd,cwd=ROOT,env=env,capture_output=True,timeout=120)
    after=dt.datetime.now(dt.timezone.utc).isoformat()
    (OUT/'minimal_stdout.bin').write_bytes(r.stdout);(OUT/'minimal_stderr.bin').write_bytes(r.stderr)
    data=dict(command=cmd,started_at=before,ended_at=after,exit_code=r.returncode,
        stdout=r.stdout.decode('utf-8',errors='replace'),stderr=r.stderr.decode('utf-8',errors='replace'),
        stdout_sha256=sha256_file(OUT/'minimal_stdout.bin'),stderr_sha256=sha256_file(OUT/'minimal_stderr.bin'),
        model_load_attempted=False,CUDA_check_attempted=False,technical_retry_count=0)
    with (OUT/'minimal_failure.json').open('x',encoding='utf-8') as f:json.dump(data,f,ensure_ascii=False,indent=2);f.write('\n')
    print(json.dumps({'exit_code':r.returncode,'started_at':before,'ended_at':after,'stderr':data['stderr']},ensure_ascii=False),flush=True)


if __name__=='__main__':main()
