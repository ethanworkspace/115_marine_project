"""Preserve all earlier artifacts and installed runtimes without writing to them."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.phase16_snapshot import snapshot as prior_snapshot
from src.evaluation.generation.frozen import sha256_file

OUT = ROOT / 'reports/evaluation/generation_models/phase17'


def snapshot():
    rows = prior_snapshot()
    for folder in ('reports/evaluation/ragas', 'src/evaluation/generation', 'src/evaluation/ragas_eval', '.venv-ragas', 'config'):
        for p in (ROOT / folder).rglob('*'):
            if p.is_file() and '__pycache__' not in p.parts:
                s = p.stat()
                rows[p.relative_to(ROOT).as_posix()] = dict(sha256=sha256_file(p), size=s.st_size, mtime_ns=s.st_mtime_ns)
    return rows


if __name__ == '__main__':
    OUT.mkdir(parents=True, exist_ok=True)
    p = OUT / 'protected_before.json'
    if '--verify' in sys.argv:
        before = json.loads(p.read_text(encoding='utf-8'))
        after = snapshot()
        changed = [k for k in before if before[k] != after.get(k)]
        result = dict(protected_count=len(before), unchanged=not changed, changed=changed, sqlite=after.get('rag_store.sqlite3'))
        (OUT / 'compatibility.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
        print(json.dumps(result))
        if changed:
            raise SystemExit(1)
    else:
        if p.exists():
            raise SystemExit('Refusing to overwrite original snapshot')
        p.write_text(json.dumps(snapshot(), indent=2) + '\n', encoding='utf-8')
        print('Phase 17 protected inputs and runtimes frozen', flush=True)
