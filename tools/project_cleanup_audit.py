"""Conservative local cleanup: exact failed downloads and regenerable code caches.

Never deletes original documents, database/index files, evaluation results,
environments, model caches or inaccessible paths. Every deletion has a receipt.
"""
import argparse, collections, datetime, hashlib, json, os, stat, zipfile, sqlite3
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
TZ=datetime.timezone(datetime.timedelta(hours=8))
SKIP={'.git','site-packages','node_modules','vendor','test_env','frontend_env','runtime_env','github_checkout','github_main_checkout'}
CODE_ROOTS={'src','tests','scripts','tools','config','configs','prompts','schemas'}

def sha(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--apply',action='store_true');parser.add_argument('--output',required=True)
    args=parser.parse_args();out=Path(args.output).resolve();assert out.is_relative_to(ROOT)
    out.mkdir(parents=True,exist_ok=True)
    frozen=json.loads((ROOT/'reports/evaluation/final_model_selection/phase20/protected_inputs_before.json').read_text(encoding='utf-8'))
    protected={(ROOT/r['path']).resolve() for r in frozen['files']}
    errors=[]; inventory=collections.Counter();exts=collections.Counter();candidate=[];review=[]
    def walk_error(error):errors.append({'path':error.filename,'error':type(error).__name__})
    for base,dirs,files in os.walk(ROOT,topdown=True,onerror=walk_error,followlinks=False):
        parent=Path(base);rel=parent.relative_to(ROOT)
        dirs[:]=[d for d in dirs if d not in SKIP and not d.startswith('.venv') and not (parent/d).is_symlink()
                 and not ((parent/d).resolve()==out) and not ((parent/d).stat().st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)]
        in_code=(not rel.parts or rel.parts[0] in CODE_ROOTS)
        in_cache='__pycache__' in rel.parts or '.pytest_cache' in rel.parts or (rel.parts and rel.parts[0].startswith('pytest-cache-files-'))
        for name in files:
            path=parent/name
            try:
                if path.is_symlink() or path.stat().st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT:continue
                size=path.stat().st_size
            except OSError as exc:errors.append({'path':str(path),'error':type(exc).__name__});continue
            inventory[rel.parts[0] if rel.parts else '[root]']+=1;exts[path.suffix.lower()]+=1
            if in_code and in_cache and (name.endswith(('.pyc','.pyo')) or '.pytest_cache' in rel.parts or (rel.parts and rel.parts[0].startswith('pytest-cache-files-'))):
                if path.resolve() not in protected:candidate.append({'path':str(path.relative_to(ROOT)),'bytes':size,'reason':'REGENERABLE_CODE_OR_PYTEST_CACHE','sha256':sha(path)})
            elif any(x in name.lower() for x in ('.incomplete','.partial','.crdownload','.part.')) or name.endswith(('.part','.download')):
                review.append({'path':str(path.relative_to(ROOT)),'bytes':size,'status':'REQUIRES_REVIEW_NOT_AUTOMATICALLY_DELETED'})
    known=json.loads((ROOT/'reports/evaluation/unified_rag_v6_20261121_160441/incomplete_downloads.json').read_text(encoding='utf-8'))
    active=json.loads((ROOT/'research_staging/unified_rag_active.json').read_text(encoding='utf-8-sig'))
    with sqlite3.connect(Path(active['database']).as_uri()+'?mode=ro',uri=True) as con:
        active_document_hashes={r[0] for r in con.execute('SELECT sha256 FROM documents')}
    for item in known:
        assert item['not_ingested_as_legal_content'] and item['status']=='INVALID_OR_TRUNCATED_DOWNLOAD'
        assert item['sha256'] not in active_document_hashes
        original=Path(item['path']).resolve()
        duplicate=ROOT/'my_data/RAG來源資料總庫/99_待補件_下載失敗'/original.name
        for path in (original,duplicate.resolve()):
            if not path.exists():continue
            assert (path.is_relative_to(ROOT/'research_staging/official_downloads') or path.is_relative_to(ROOT/'my_data/RAG來源資料總庫/99_待補件_下載失敗')) and path not in protected
            assert sha(path)==item['sha256'] and path.stat().st_size==item['bytes']
            assert not zipfile.is_zipfile(path)
            candidate.append({'path':str(path.relative_to(ROOT)),'bytes':item['bytes'],'sha256':item['sha256'],
                              'reason':'CONFIRMED_TRUNCATED_ZIP_NOT_INGESTED','reference':'reports/evaluation/unified_rag_v6_20261121_160441/incomplete_downloads.json'})
    candidates={r['path']:r for r in candidate}
    plan={'at':datetime.datetime.now(TZ).isoformat(),'policy':'Only proven failed downloads and regenerable source-code caches; preserve all data/results/environments.',
          'frozen_manifest_entries':len(protected),'deletion_requested':args.apply,'candidates':list(candidates.values()),
          'review_only':review,'inventory_file_counts_excluding_environments':dict(inventory),'extension_counts':dict(exts),'inaccessible_paths':errors}
    (out/'cleanup_plan.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2),encoding='utf-8')
    deleted=[];failed=[]
    if args.apply:
        for item in candidates.values():
            path=(ROOT/item['path']).resolve()
            assert path.is_relative_to(ROOT) and path not in protected and path.is_file() and not path.is_symlink()
            try:
                assert path.stat().st_size==item['bytes'] and sha(path)==item['sha256'],'Changed after inventory'
                path.unlink();deleted.append(item)
            except (OSError,AssertionError) as exc:failed.append({'path':item['path'],'error':type(exc).__name__})
        # Only remove empty cache directories whose exact paths were inventoried.
        parents={ROOT/r['path'] for r in deleted}
        dirs={p.parent for p in parents}
        for d in sorted(dirs,key=lambda p:len(p.parts),reverse=True):
            if d.is_relative_to(ROOT) and ('__pycache__' in d.parts or '.pytest_cache' in d.parts or any(p.startswith('pytest-cache-files-') for p in d.parts)):
                try:d.rmdir()
                except OSError:pass
    receipt={'at':datetime.datetime.now(TZ).isoformat(),'applied':args.apply,'deleted_files':len(deleted),
             'released_bytes':sum(r['bytes'] for r in deleted),'deleted':deleted,'failed':failed,
             'excluded_protected_files':len(protected),'inaccessible_paths_left_unchanged':errors,
             'original_data_results_models_and_environments_preserved':True}
    (out/'cleanup_receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in receipt.items() if k not in ('deleted','inaccessible_paths_left_unchanged')},ensure_ascii=False))

if __name__=='__main__':main()
