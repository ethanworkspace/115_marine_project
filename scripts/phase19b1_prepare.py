"""Immutable recovery revision: preserve previous phases and entire failed environment."""
import datetime as dt
import importlib.metadata
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from src.evaluation.generation.frozen import sha256_file

OUT=ROOT/'reports/evaluation/edge/phase19B_runtime_recovery'


def record(path):
    s=path.stat()
    return dict(sha256=sha256_file(path),size=s.st_size,mtime_ns=s.st_mtime_ns)


def write(name,obj):
    p=OUT/name;p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('x',encoding='utf-8') as f:json.dump(obj,f,indent=2,ensure_ascii=False);f.write('\n')


def main():
    if (OUT/'protected_before.json').exists():raise SystemExit('Refuse to overwrite recovery snapshot')
    prior=json.loads((ROOT/'reports/evaluation/edge/phase19B/protected_before.json').read_text(encoding='utf-8'))
    changed=[name for name,old in prior.items() if not (ROOT/name).is_file() or record(ROOT/name)!=old]
    if changed:raise SystemExit('Earlier protected input mismatch: '+str(changed[:5]))
    # Include even pyc/cache files: -B and PYTHONDONTWRITEBYTECODE protect the failed environment.
    envfiles={p.relative_to(ROOT).as_posix():record(p) for p in (ROOT/'.venv-reranker').rglob('*') if p.is_file()}
    before={**prior,**envfiles}
    for folder in ('reports/evaluation/edge/phase19B',):
        for p in (ROOT/folder).rglob('*'):
            if p.is_file():before[p.relative_to(ROOT).as_posix()]=record(p)
    for p in [*(ROOT/'scripts').glob('phase19b_*.py'),*(ROOT/'src/evaluation/edge').glob('*19b.py'),
              ROOT/'docs/phase19B_full_edge_protocol.md']:
        before[p.relative_to(ROOT).as_posix()]=record(p)
    write('protected_before.json',before)
    write('failed_runtime_files_before.json',envfiles)
    write('experiment_manifest.json',dict(experiment_id='phase19B_1_windows_reranker_runtime_recovery_v1',
        timestamp=dt.datetime.now(dt.timezone.utc).isoformat(),scope='read-only application-control forensics; conditional recovery gates',
        failed_environment=str(ROOT/'.venv-reranker'),minimal_reproductions_allowed=1,
        frozen_model='BAAI/bge-reranker-v2-m3',revision='953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e',
        frozen_config=dict(device='cuda:0',dtype='float32',max_length=512,batch_size=4),
        security_policy_changes_allowed=False,allow_rule_allowed=False,Zone_Identifier_removal_allowed=False,
        original_runtime_mutation_allowed=False,CPU_fallback_allowed=False,random_package_trial_allowed=False,
        new_runtime_requires_forensic_justification=True,automatic_full_benchmark_allowed=False,
        current_E4_manifest_sha256=sha256_file(ROOT/'reports/evaluation/experiments/E4_grounded_rrf_reranker_v1/experiment_manifest.json'),
        protected_count=len(before),failed_runtime_file_count=len(envfiles)))
    python=ROOT/'.venv-reranker/Scripts/python.exe'
    env={**os.environ,'PYTHONIOENCODING':'utf-8','PYTHONDONTWRITEBYTECODE':'1','PIP_DISABLE_PIP_VERSION_CHECK':'1'}
    r=subprocess.run([str(python),'-B','-m','pip','freeze','--all','--disable-pip-version-check'],
        cwd=ROOT,env=env,capture_output=True)
    (OUT/'failed_runtime_pip_freeze.txt').write_bytes(r.stdout)
    (OUT/'failed_runtime_pip_freeze.stderr.txt').write_bytes(r.stderr)
    (OUT/'runtime_pyvenv.cfg.snapshot').write_bytes((ROOT/'.venv-reranker/pyvenv.cfg').read_bytes())
    code="import sys,os,platform,importlib.metadata as m,json; names=['PATH','PYTHONHOME','PYTHONPATH','VIRTUAL_ENV','CUDA_PATH','CUDA_VISIBLE_DEVICES','HF_HOME','HF_HUB_CACHE','TRANSFORMERS_CACHE','HF_HUB_OFFLINE','TRANSFORMERS_OFFLINE']; rows=[{'name':d.metadata['Name'],'version':d.version,'metadata_path':str(d._path),'requires':d.requires} for d in m.distributions()]; print(json.dumps({'python':platform.python_version(),'executable':sys.executable,'base_prefix':sys.base_prefix,'base_executable':sys._base_executable,'OS':platform.platform(),'packages':rows,'environment_variables':{k:os.environ.get(k) for k in names}},ensure_ascii=False))"
    m=subprocess.run([str(python),'-B','-c',code],cwd=ROOT,env=env,capture_output=True)
    (OUT/'package_metadata.raw.json').write_bytes(m.stdout)
    write('failed_runtime_manifest.json',dict(environment_path=str(ROOT/'.venv-reranker'),python_path=str(python),
        python_executable=record(python),pyvenv_cfg=record(ROOT/'.venv-reranker/pyvenv.cfg'),
        pip_freeze_exit_code=r.returncode,pip_freeze_sha256=sha256_file(OUT/'failed_runtime_pip_freeze.txt'),
        package_metadata_exit_code=m.returncode,package_metadata_sha256=sha256_file(OUT/'package_metadata.raw.json'),
        file_count=len(envfiles),full_checksums_file='failed_runtime_files_before.json'))
    print(json.dumps({'protected_count':len(before),'failed_runtime_files':len(envfiles),'metadata_exit':m.returncode,'freeze_exit':r.returncode}),flush=True)


if __name__=='__main__':main()
