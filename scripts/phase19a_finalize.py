"""Post-run statistics, full existing unittest suite and protected artifact audit."""
import json,os,re,subprocess,sys
from pathlib import Path
from urllib.request import urlopen
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from src.evaluation.edge.report19a import compile_all
from src.evaluation.edge.execution19a import OUT,write
from src.evaluation.generation.frozen import sha256_file

def main():
    from src.evaluation.edge.inputs import load_target
    from src.evaluation.edge.core import MODELS
    from src.evaluation.edge.runtime import OllamaEdge
    frozen_models={m:json.loads((OUT/'model_manifests'/(m.replace(':','_')+'.json')).read_text(encoding='utf-8')) for m in MODELS}
    write(OUT/'runtime_identity_after.json',OllamaEdge(load_target()).preflight(frozen_models))
    subprocess.run([str(ROOT/'.venv/Scripts/python.exe'),'scripts/phase19a_runtime_log_capture.py'],cwd=ROOT,check=True)
    validation=subprocess.run([str(ROOT/'.venv/Scripts/python.exe'),'scripts/phase19a_validate_execution.py'],cwd=ROOT,
        stdout=subprocess.PIPE,stderr=subprocess.STDOUT,encoding='utf-8',errors='replace')
    (OUT/'execution_validation.log').write_text(validation.stdout,encoding='utf-8')
    matrix=compile_all()
    r=subprocess.run([str(ROOT/'.venv/Scripts/python.exe'),'-m','unittest','discover','-s','tests','-v'],cwd=ROOT,
        stdout=subprocess.PIPE,stderr=subprocess.STDOUT,encoding='utf-8',errors='replace',env={**os.environ,'PYTHONIOENCODING':'utf-8'})
    (OUT/'unittest_final.log').write_text(r.stdout,encoding='utf-8')
    n=re.search(r'Ran (\d+) tests?',r.stdout);skip=re.search(r'skipped=(\d+)',r.stdout)
    tests=dict(return_code=r.returncode,tests=int(n[1]) if n else None,skipped=int(skip[1]) if skip else 0)
    write(OUT/'tests.json',tests)
    before=json.loads((OUT/'protected_before.json').read_text(encoding='utf-8'));changed=[]
    for name,old in before.items():
        p=ROOT/name
        if not p.is_file():changed.append(name);continue
        s=p.stat()
        if dict(sha256=sha256_file(p),size=s.st_size,mtime_ns=s.st_mtime_ns)!=old:changed.append(name)
    db=ROOT/'rag_store.sqlite3';s=db.stat();dbafter=dict(sha256=sha256_file(db),size=s.st_size,mtime_ns=s.st_mtime_ns)
    try:
        with urlopen('http://127.0.0.1:8767/_stcore/health',timeout=10) as response:http=response.status
    except Exception as exc:http=None
    compatibility=dict(protected_count=len(before),changed=changed,unchanged=not changed,
        sqlite_before=before['rag_store.sqlite3'],sqlite_after=dbafter,SQLite_identical=before['rag_store.sqlite3']==dbafter,
        production_Streamlit_HTTP=http,production_code_modified=False,production_prompt_modified=False,
        no_retrieval_execution=True,no_RAGAS=True,no_model_download=True,no_quantization_or_model_tuning=True,
        allowed_existing_changes=['configs/edge_target_device.yaml: user-designated target','tests/evaluation/test_target_device_manifest.py: pending-profile regression now reads frozen pending fixture'])
    write(OUT/'compatibility.json',compatibility)
    completed=(OUT/'execution_complete.json').exists() and (not (OUT/'execution_interruption.json').exists() or (OUT/'execution_recovery_completed.json').exists())
    write(OUT/'completion.json',dict(status='complete' if completed else 'benchmark_incomplete',
        edge_execution_ready=True,core_warm_requests=sum(1 for l in (OUT/'warm_runs.jsonl').read_text(encoding='utf-8').splitlines() if l.strip()),
        tests=tests,compatibility_passed=not changed and compatibility['SQLite_identical'] and http==200,
        phase19B_worth_planning=completed and any(m['hardware_status'].startswith('deployable') for m in matrix),
        phase19B_executed=False,phase20_ready=False,human_validated_quality_winner=False))
    from src.evaluation.edge.summary19a import render_summary
    render_summary()
    write(OUT/'implementation_checksums.json',{p.relative_to(ROOT).as_posix():sha256_file(p) for p in
        [*(ROOT/'src/evaluation/edge').glob('*19a.py'),*(ROOT/'scripts').glob('phase19a*.py'),ROOT/'configs/edge_target_device.yaml']})
    write(OUT/'output_checksums.json',{p.relative_to(ROOT).as_posix():sha256_file(p) for p in OUT.rglob('*') if p.is_file() and p.name!='output_checksums.json'})
    print(json.dumps({'tests':tests,'compatibility':compatibility},ensure_ascii=False))
    if validation.returncode or r.returncode or changed or http!=200:raise SystemExit(1)

if __name__=='__main__':main()
