"""Run isolated CUDA integration tests after all performance measurement ends."""
from __future__ import annotations
import contextlib
import io
import json
import os
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'reports/evaluation/edge/phase19B_exec_r2'
sys.path.insert(0,str(ROOT))
os.environ['HF_HUB_OFFLINE']='1'
os.environ['TRANSFORMERS_OFFLINE']='1'
os.environ['HF_HUB_DISABLE_TELEMETRY']='1'
os.environ['PYTHONDONTWRITEBYTECODE']='1'

def main():
    if not (OUT/'execution_complete.json').exists():
        raise SystemExit('Do not perturb the active performance benchmark')
    log=io.StringIO()
    metadata=dict(CPU_fallback=False,execution_environment='.venv-reranker',
        performed_after_performance_measurement=True)
    try:
        with contextlib.redirect_stdout(log),contextlib.redirect_stderr(log):
            import torch
            metadata.update(torch=torch.__version__,CUDA=torch.cuda.is_available(),CUDA_build=torch.version.cuda)
            if not metadata['CUDA']:
                raise RuntimeError('CUDA unavailable: CPU fallback is forbidden')
            metadata['GPU']=torch.cuda.get_device_name(0)
            if metadata['torch']!='2.14.1+cu130' or metadata['GPU']!='NVIDIA GeForce RTX 4060':
                raise RuntimeError('Pinned runtime/device identity mismatch')
            suite=unittest.TestSuite()
            for filename in ('test_reranker_model_load.py','test_reranker_score_finite.py',
                'test_reranker_candidate_identity.py','test_reranker_batch.py',
                'test_reranker_determinism.py','test_reranker_truncation.py'):
                suite.addTests(unittest.defaultTestLoader.discover(str(ROOT/'tests/evaluation/reranker'),pattern=filename))
            result=unittest.TextTestRunner(stream=log,verbosity=2).run(suite)
            metadata.update(tests=result.testsRun,skipped=len(result.skipped),failures=len(result.failures),
                errors=len(result.errors),passed=result.wasSuccessful())
    except Exception as exc:
        metadata.update(passed=False,error=str(exc))
        log.write(str(exc))
    with (OUT/'isolated_runtime_tests.log').open('x',encoding='utf-8') as f:
        f.write(log.getvalue())
    with (OUT/'isolated_runtime_tests.json').open('x',encoding='utf-8') as f:
        json.dump(metadata,f,ensure_ascii=False,indent=2)
    print(json.dumps(metadata,ensure_ascii=True),flush=True)
    if not metadata['passed']:raise SystemExit(1)

if __name__=='__main__':main()
