"""Record explicit publication/revision strings; never infer current legal effect."""
import json
import re
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tools'))
from build_unified_rag_v4 import db,REPORT
from src.unified_rag_v4.common import dump
con=db();out=[]
for r in con.execute('SELECT * FROM documents').fetchall():
    rec=json.loads(r['metadata_json']);text=rec.get('publication_excerpt','');version=None;quote=None
    m=re.search(r'(?:修正日期|公布日期|發布日期)[：:\s]*([^\n]{4,65})',text)
    if m:
        quote=m.group(0);version='原件記載：'+quote+'；僅為該原件版本，現行效力未另核實'
    else:
        m=re.search(r'水產試驗所特刊\s*第\s*\d+\s*號\s*[：:]\s*\d+\s*[-－–]\s*\d+\s*[,，]\s*(\d{4})',text)
        if m: quote=m.group(0);version='原件出版標頭：'+quote+'；歷史文獻，非現行病例或用藥許可'
    if version:
        rec['source_version_evidence']={'exact_source_string':quote,'version_claim':'EXPLICIT_IN_ORIGINAL_NOT_CURRENTNESS_CERTIFICATION'}
        rec['native_record_version']=version
        con.execute('UPDATE documents SET source_version=?,metadata_json=? WHERE document_id=?',(version,json.dumps(rec,ensure_ascii=False),r['document_id']))
        con.execute("UPDATE sources SET version_status=? WHERE source_sha256=? AND source_id LIKE 'MYDATA-%'",(version,r['sha256']))
        con.execute("UPDATE chunks SET source_version=? WHERE source_sha256=? AND source_id LIKE 'MYDATA-%'",(version,r['sha256']))
        out.append({'document_id':r['document_id'],'version':version,'evidence':quote})
con.commit();con.close();dump(REPORT/'source_version_evidence.json',out);print(json.dumps({'explicit_versions_recorded':len(out)}))
