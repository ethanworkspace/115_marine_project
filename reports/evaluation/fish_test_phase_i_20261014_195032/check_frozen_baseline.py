import datetime as dt, hashlib, json, pathlib, os
ROOT=pathlib.Path.cwd(); OUT=ROOT/'reports/evaluation/fish_test_phase_i_20261014_195032'
manifest=json.loads((ROOT/'reports/evaluation/fish_test_phase_a_20261012/protected_files_manifest.json').read_text(encoding='utf-8-sig'))
rows=manifest['historical_636_recheck']['entries']
results=[]
for row in rows:
 p=ROOT/row['path']; rec={'path':row['path'],'expected_sha256':row['expected_sha256'],'exists':p.is_file()}
 if p.is_file():
  h=hashlib.sha256()
  with p.open('rb') as f:
   for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
  current=h.hexdigest(); rec.update({'current_sha256':current,'size_bytes':p.stat().st_size,'status':'unchanged' if current==row['expected_sha256'] else 'mismatch'})
 else: rec.update({'current_sha256':None,'status':'missing_or_unreadable'})
 results.append(rec)
db=ROOT/'rag_store.sqlite3'; h=hashlib.sha256(db.read_bytes()).hexdigest() if db.is_file() else None
summary={'checked_at':dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).isoformat(),
 'manifest_source':'reports/evaluation/fish_test_phase_a_20261012/protected_files_manifest.json#historical_636_recheck',
 'expected_entries':len(rows),'unchanged':sum(r['status']=='unchanged' for r in results),
 'mismatched':sum(r['status']=='mismatch' for r in results),'missing_or_unreadable':sum(r['status']=='missing_or_unreadable' for r in results),
 'all_636_unchanged':len(rows)==636 and all(r['status']=='unchanged' for r in results),
 'sqlite_sha256':h,'sqlite_expected_sha256':'d7d06d4d2a57d0a57d05bcb6131ffb24aefb226c6bd36349dbc5118d33b11087',
 'sqlite_matches_expected':h=='d7d06d4d2a57d0a57d05bcb6131ffb24aefb226c6bd36349dbc5118d33b11087',
 'mutations_to_protected_paths':0,'original_generations_reexecuted':False,'cleanup_deletion_or_archive':False,
 'full_repository_pytest_run':False,'notes':'Independent SHA-256 recomputation at Phase I end; Phase I outputs are outside the 636-entry historical set.'}
(OUT/'frozen_baseline_636_recheck.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False,separators=(',',':'))+'\n' for r in results),encoding='utf-8')
(OUT/'frozen_baseline_compatibility.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({k:summary[k] for k in ('expected_entries','unchanged','mismatched','missing_or_unreadable','all_636_unchanged','sqlite_sha256','sqlite_matches_expected')},ensure_ascii=False))
