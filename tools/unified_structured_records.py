"""Preserve every native JSON/CSV/XML record, independently of answer eligibility."""
import csv
import io
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tools'))
from build_unified_rag_v4 import db,REPORT
from src.unified_rag_v4.common import digest,dump
con=db()
con.execute('CREATE TABLE IF NOT EXISTS structured_records(document_id TEXT NOT NULL,record_index INTEGER NOT NULL,field_locator TEXT NOT NULL,record_json TEXT NOT NULL,record_sha256 TEXT NOT NULL,PRIMARY KEY(document_id,record_index))')
summary=[]
for row in con.execute('SELECT * FROM documents').fetchall():
    rec=json.loads(row['metadata_json']);p=Path(rec['primary_path']);kind=p.suffix.lower()
    if kind not in ('.json','.csv','.xml'): continue
    try:
        raw=p.read_bytes();encoding='utf-8-sig'
        if kind=='.json':
            parsed=json.loads(raw.decode(encoding));records=parsed if isinstance(parsed,list) else [parsed];locators=['/'+str(i) for i in range(len(records))]
        elif kind=='.csv':
            try: text=raw.decode(encoding)
            except UnicodeDecodeError: encoding='cp950';text=raw.decode(encoding)
            reader=csv.DictReader(io.StringIO(text));records=list(reader);locators=['CSV_DATA_ROW_'+str(i+2) for i in range(len(records))]
        else:
            tree=ET.fromstring(raw)
            groups=[el for el in tree.iter() if len(el)>=2 and all(not len(c) for c in el)]
            records=[{c.tag:c.text for c in el} for el in groups];locators=[tree.tag+'//'+el.tag+'['+str(i+1)+']' for i,el in enumerate(groups)]
        for i,(record,loc) in enumerate(zip(records,locators)):
            con.execute('INSERT OR REPLACE INTO structured_records VALUES(?,?,?,?,?)',(rec['document_id'],i,loc,json.dumps(record,ensure_ascii=False),digest(record)))
        fields=sorted({str(k) for r in records if isinstance(r,dict) for k in r})
        missing={f:sum(r.get(f) in ('',None) for r in records if isinstance(r,dict)) for f in fields}
        hashes=[digest(r) for r in records]
        summary.append({'document_id':rec['document_id'],'file':p.name,'encoding':encoding,'records':len(records),'fields':fields,'empty_or_missing_fields':missing,'exact_duplicate_records':len(hashes)-len(set(hashes)),'indexed_answer_eligibility_is_separate':True})
    except Exception as exc: summary.append({'document_id':rec['document_id'],'file':p.name,'error':repr(exc)})
con.commit();con.close();dump(REPORT/'structured_record_integrity.json',summary);print(json.dumps(summary,ensure_ascii=False))
