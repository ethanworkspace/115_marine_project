"""Build a hash-bound inventory; filename matches never establish a license."""
import hashlib
import json
import re
import sqlite3
from collections import defaultdict
from pathlib import Path
import fitz

ROOT = Path(__file__).resolve().parents[1]
WORK = Path(json.loads((ROOT/'research_staging/unified_rag_build_pointer.json').read_text(encoding='utf-8'))['workspace'])
def sha(p):
    with p.open('rb') as f: return hashlib.file_digest(f, 'sha256').hexdigest()
approval = json.loads((ROOT/'reports/evaluation/fish_test_phase_v_20261018_224918/source_approval_manifest_v1.json').read_text(encoding='utf-8-sig'))['records']
paths = {p.resolve() for p in (ROOT/'my_data').rglob('*') if p.is_file()}
paths.update((ROOT/r['original_path']).resolve() for r in approval if (ROOT/r['original_path']).is_file())
config=json.loads((WORK/'build_config.json').read_text(encoding='utf-8'))
c=sqlite3.connect(Path(config['source_frozen_database']).as_uri()+'?mode=ro',uri=True)
c.row_factory=sqlite3.Row
old=[dict(x) for x in c.execute('SELECT * FROM sources')];c.close()
paths.update(Path(s['source_file']) for s in old if Path(s['source_file']).is_file())
by_hash=defaultdict(list)
for p in sorted(paths): by_hash[sha(p)].append(p)
oldmap={s['source_sha256']:s for s in old}
converted={r['source']:r['pdf'] for r in json.loads((WORK/'word_conversion_results.json').read_text(encoding='utf-8')) if r.get('status')=='CONVERTED_READ_ONLY'}
rows=[]
for checksum,aliases in by_hash.items():
    p=aliases[0]
    original_pdf=next((x for x in aliases if x.suffix.lower()=='.pdf'),None)
    parse_path=original_pdf or Path(converted[str(p)]) if str(p) in converted else original_pdf or p
    rec={'document_id':'DOC-'+checksum[:20], 'sha256':checksum, 'paths':[str(x) for x in aliases], 'primary_path':str(p), 'parse_path':str(parse_path), 'suffix':p.suffix.lower(), 'my_data':any('my_data' in x.parts for x in aliases), 'owner_decision':'APPROVED_RESEARCH_PROCESSING', 'publisher':None,'version':None,'license_scope':'UNVERIFIED_FULLTEXT_BASIS','metadata':{},'publication_excerpt':'','rights_statements':[]}
    try:
        if parse_path.suffix.lower()=='.pdf':
            with fitz.open(parse_path) as doc:
                rec['page_count']=len(doc);rec['metadata']=doc.metadata
                indices=sorted(set(range(min(4,len(doc)))) | set(range(max(0,len(doc)-4),len(doc))))
                sample='\n'.join(doc[i].get_text() for i in indices)
                rec['publication_excerpt']=sample[:5000]
                rec['rights_statements']=[sample[max(0,m.start()-100):m.end()+160] for m in re.finditer('版權|著作權|不得重製|不得重制|書面同意|非經|授權|開放授權|Creative Commons|copyright|all rights reserved',sample,re.I)]
                rec['first_page']=doc[0].get_text()[:1000] if len(doc) else ''
        elif p.suffix.lower()=='.html':
            rec['publication_excerpt']=p.read_text(encoding='utf-8-sig',errors='replace')[:4000]
    except Exception as exc: rec['inspection_error']=repr(exc)
    if checksum in oldmap:
        rec['existing_source']=oldmap[checksum]['source_id']
        rec['existing_scope']=oldmap[checksum]['processing_scope']
    rows.append(rec)
(WORK/'source_inventory.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'unique_files':len(rows),'file_paths':sum(len(x['paths']) for x in rows),'my_data_unique_files':sum(x['my_data'] for x in rows),'sources':[{'id':x['document_id'],'name':Path(x['primary_path']).name,'pages':x.get('page_count'),'rights':x['rights_statements'][:2],'first_page':x.get('first_page','')[:170]} for x in rows]},ensure_ascii=False))
