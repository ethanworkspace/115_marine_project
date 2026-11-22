"""Capture read-only Phase 16 compatibility inputs before installing evaluators."""
import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'reports/evaluation/ragas'


def snapshot():
    paths = set()
    for directory in ('data/shadow', 'data/evaluation', 'reports/evaluation/experiments',
                      'reports/evaluation/generation', 'prompts', 'schemas'):
        base = ROOT / directory
        paths.update(p for p in base.rglob('*') if p.is_file())
    for name in ('rag_store.sqlite3', 'app.py', 'chat.py', 'rag_core.py', 'requirements.txt'):
        p = ROOT / name
        if p.exists():
            paths.add(p)
    for name in ('.venv', '.venv-reranker'):
        base = ROOT / name
        # Hash every installed file to verify the old environments remain untouched.
        paths.update(p for p in base.rglob('*') if p.is_file() and '__pycache__' not in p.parts)
    rows = {}
    for p in sorted(paths):
        digest = hashlib.sha256()
        with p.open('rb') as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(block)
        s = p.stat()
        rows[p.relative_to(ROOT).as_posix()] = dict(sha256=digest.hexdigest(), size=s.st_size, mtime_ns=s.st_mtime_ns)
    return rows


if __name__ == '__main__':
    import sys
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / 'protected_before.json'
    if '--verify' in sys.argv:
        before = json.loads(path.read_text(encoding='utf-8'))
        current = snapshot()
        changed = [name for name, value in before.items() if current.get(name) != value]
        result = dict(protected_file_count=len(before), changed=changed, unchanged=not changed,
                      sqlite=current.get('rag_store.sqlite3'))
        (OUT / 'compatibility.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
        print(json.dumps(result))
        if changed:
            raise SystemExit(1)
    else:
        if path.exists():
            raise SystemExit('Refusing to overwrite the original compatibility snapshot')
        path.write_text(json.dumps(snapshot(), indent=2) + '\n', encoding='utf-8')
        print('Protected artifacts and existing environments frozen')
