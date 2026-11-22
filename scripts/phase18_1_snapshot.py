"""Read-only protection of all earlier research, runtimes and production files."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.phase18_snapshot import snapshot as prior_snapshot
from src.evaluation.generation.frozen import sha256_file

OUT = ROOT / 'reports/evaluation/validity/phase18_1'


def snapshot():
    rows = prior_snapshot()
    for folder in ('reports/evaluation/validity/phase18', 'src/evaluation/validity'):
        for p in (ROOT / folder).rglob('*'):
            if p.is_file() and '__pycache__' not in p.parts:
                s = p.stat()
                rows[p.relative_to(ROOT).as_posix()] = dict(
                    sha256=sha256_file(p), size=s.st_size, mtime_ns=s.st_mtime_ns)
    paths = [ROOT / 'docs/edge_benchmark_protocol.md']
    paths += [p for p in (ROOT / 'scripts').glob('phase18*.py')
              if not p.name.startswith('phase18_1')]
    for p in paths:
        s = p.stat()
        rows[p.relative_to(ROOT).as_posix()] = dict(
            sha256=sha256_file(p), size=s.st_size, mtime_ns=s.st_mtime_ns)
    return rows


if __name__ == '__main__':
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / 'protected_before.json'
    if '--verify' in sys.argv:
        before = json.loads(path.read_text(encoding='utf-8'))
        changed = []
        for name, previous in before.items():
            p = ROOT / name
            if not p.is_file():
                changed.append(name)
                continue
            s = p.stat()
            current = dict(sha256=sha256_file(p), size=s.st_size, mtime_ns=s.st_mtime_ns)
            if current != previous:
                changed.append(name)
        result = dict(protected_count=len(before), changed=changed, unchanged=not changed)
        (OUT / 'compatibility.json').write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
        print(json.dumps(result), flush=True)
        if changed:
            raise SystemExit(1)
    else:
        if path.exists():
            raise SystemExit('Refusing to overwrite protection snapshot')
        expected = json.loads((ROOT / 'reports/evaluation/validity/phase18/output_checksums.json').read_text())
        mismatches = [n for n, h in expected.items() if sha256_file(ROOT / n) != h]
        if mismatches:
            raise SystemExit('Phase 18 checksum mismatch: '+str(mismatches))
        path.write_text(json.dumps(snapshot(), indent=2)+'\n', encoding='utf-8')
        print('Earlier artifacts and runtimes frozen', flush=True)
