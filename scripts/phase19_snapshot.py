"""Read-only freeze of all earlier artifacts and installed runtimes."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.phase18_1_snapshot import snapshot as prior_snapshot
from src.evaluation.generation.frozen import sha256_file

OUT = ROOT/'reports/evaluation/edge/phase19'


def snapshot():
    rows = prior_snapshot()
    for folder in ('reports/evaluation/validity/phase18_1','src/evaluation/human_support'):
        for p in (ROOT/folder).rglob('*'):
            if p.is_file() and '__pycache__' not in p.parts:
                s=p.stat()
                rows[p.relative_to(ROOT).as_posix()]=dict(sha256=sha256_file(p),size=s.st_size,mtime_ns=s.st_mtime_ns)
    for p in [ROOT/'docs/human_claim_citation_review_protocol.md',*(ROOT/'scripts').glob('phase18_1*.py')]:
        s=p.stat()
        rows[p.relative_to(ROOT).as_posix()]=dict(sha256=sha256_file(p),size=s.st_size,mtime_ns=s.st_mtime_ns)
    return rows


if __name__=='__main__':
    OUT.mkdir(parents=True,exist_ok=True)
    path=OUT/'protected_before.json'
    if '--verify' in sys.argv:
        before=json.loads(path.read_text(encoding='utf-8'));changed=[]
        for name,old in before.items():
            p=ROOT/name
            if not p.is_file():changed.append(name);continue
            s=p.stat();new=dict(sha256=sha256_file(p),size=s.st_size,mtime_ns=s.st_mtime_ns)
            if old!=new:changed.append(name)
        result=dict(protected_count=len(before),changed=changed,unchanged=not changed)
        (OUT/'compatibility.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
        print(json.dumps(result),flush=True)
        if changed:raise SystemExit(1)
    else:
        if path.exists():raise SystemExit('Refusing to overwrite initial protection snapshot')
        path.write_text(json.dumps(snapshot(),indent=2)+'\n',encoding='utf-8')
        print('Phase 19 protected files frozen',flush=True)
