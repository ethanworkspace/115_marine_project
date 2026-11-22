"""Carry forward already admitted native-field datasets without inventing SOPs."""
import json
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tools'))
from build_unified_rag_v4 import db,WORK,REPORT
from src.unified_rag_v4.common import digest,dump
old=json.loads((ROOT/'reports/evaluation/fish_test_phase_v_20261018_224918/source_admission_final.json').read_text(encoding='utf-8'))['previously_admitted_from_phase_u']
con=db();summary=[]
for source in old:
    sid=source['source_id']
    if con.execute('SELECT 1 FROM sources WHERE source_id=?',(sid,)).fetchone(): continue
    doc=con.execute('SELECT * FROM documents WHERE sha256=?',(source['source_sha256'],)).fetchone()
    if not doc or not source.get('license_scope_verified_for_this_dataset'): continue
    role='CONTEXT_ONLY_NATIVE_STATISTICS' if sid.startswith(('FA-STOCKING','WRA-')) else 'NAME_CODE_LOOKUP_ONLY' if 'SPECIES-CODE' in sid else 'STATISTICAL_NATIVE_FIELDS_ONLY'
    row={'source_id':sid,'dataset_id':source.get('official_dataset_url','').rstrip('/').rsplit('/',1)[-1] or 'NATIVE_SNAPSHOT','title':source.get('source_title',sid),'publisher':source.get('publisher','原提供機關，詳歷史核驗紀錄'),'dataset_url':source.get('official_dataset_url') or 'LOCAL_PUBLISHED_ORIGINAL','resource_url':source.get('resource_url') or 'LOCAL_PUBLISHED_ORIGINAL','source_sha256':source['source_sha256'],'file_size_bytes':Path(source['local_file']).stat().st_size,'source_file':str(ROOT/source['local_file']),'license':source.get('license','政府資料開放授權條款第1版'),'license_url':source.get('license_url','https://data.gov.tw/license'),'attribution':source.get('attribution_text',source.get('publisher',sid)),'owner_admission_status':'EXISTING_APPROVED_SCOPE_LIMITED_NO_NEW_OWNER_DECISION','license_scope_status':'PRIOR_NATIVE_RESOURCE_LICENSE_SCOPE_VERIFIED','identity_status':'EXACT_PRIOR_ADMISSION_SHA_MATCH','version_status':source.get('publication_version','IMMUTABLE_SNAPSHOT_NOT_CERTIFIED_CURRENT'),'applicability_status':role,'completeness_status':'DATASET_COMPLETENESS_UNKNOWN_FOR_9999_RECORD_RESPONSE' if 'PRODUCTION' in sid else 'NATIVE_SNAPSHOT_RECORDS_PARSED','processing_scope':source['approved_usage_scope'],'source_cluster_id':'SC-DGBAS-79395' if sid.startswith('DGBAS') else sid,'metadata_json':json.dumps(source,ensure_ascii=False)}
    cols=list(row);con.execute('INSERT INTO sources('+','.join(cols)+') VALUES('+','.join('?' for _ in cols)+')',[row[k] for k in cols])
    rec=json.loads(doc['metadata_json']);rec['prior_admission_source']=source;rec['usage_policy']['status']='PRIOR_APPROVED_NATIVE_FIELDS_SCOPE_ONLY';rec['usage_policy']['scope']=source['approved_usage_scope'];rec['usage_policy']['eligible']=False
    con.execute('UPDATE documents SET rights_status=?,metadata_json=? WHERE document_id=?',('PRIOR_APPROVED_NATIVE_FIELDS_SCOPE_ONLY',json.dumps(rec,ensure_ascii=False),doc['document_id']))
    raw=list(con.execute('SELECT * FROM structured_records WHERE document_id=? ORDER BY record_index',(doc['document_id'],)))
    added=0;seen=set()
    for record in raw:
        obj=json.loads(record['record_json']);checksum=record['record_sha256'];rid=sid+'-ROW-'+str(record['record_index']);locator=json.dumps({'document_id':doc['document_id'],'native_record_ordinal':record['record_index'],'field_locator':record['field_locator']},ensure_ascii=False)
        eligible=role!='CONTEXT_ONLY_NATIVE_STATISTICS'
        con.execute('INSERT OR IGNORE INTO source_records VALUES(?,?,?,?,?,?,?,?)',(rid,sid,locator,checksum,'RETRIEVAL_ELIGIBLE' if eligible else 'CONTEXT_ONLY',source['approved_usage_scope'],record['record_json'],checksum if checksum in seen else None))
        if checksum in seen: continue
        seen.add(checksum)
        # Render native names and values literally; no calendar conversion,
        # fabricated statistical year, dose, diagnosis, or species inference.
        text='\n'.join(str(k)+'：'+str(v) for k,v in obj.items())
        cid='NATIVE-'+digest([sid,checksum])[:24]
        vals={'chunk_id':cid,'source_id':sid,'source_record_id':rid,'source_sha256':source['source_sha256'],'source_version':row['version_status'],'locator':locator,'text':text,'content_sha256':digest(text.encode()),'source_quote':text,'raw_field_pointer':record['field_locator'],'quote_start':0,'quote_end':len(text),'species_scope':'[]','scientific_scope':None,'taxonomy_level':role,'category_scope':'Fact/native fields only','source_cluster_id':row['source_cluster_id'],'processing_scope':source['approved_usage_scope'],'source_path':row['source_file'],'source_page':None,'retrieval_status':'RETRIEVAL_ELIGIBLE' if eligible else 'CONTEXT_ONLY','retrieval_eligible':int(eligible),'human_gold':0,'formal_admission':1,'embedding':None,'embedding_model':None,'embedding_digest':None,'embedding_dimension':None,'transform_rule':'EXACT_NATIVE_FIELD_RENDERING_NO_UNSUPPORTED_INFERENCE','restrictions_json':json.dumps({'scope_kind':role,'native_record':obj,'dataset_limitations':source.get('limitations',[]),'no_husbandry_inference':True,'no_medication_inference':True},ensure_ascii=False)}
        fields=list(vals);con.execute('INSERT OR IGNORE INTO chunks('+','.join(fields)+') VALUES('+','.join('?' for _ in fields)+')',[vals[k] for k in fields]);added+=1
    summary.append({'source_id':sid,'role':role,'raw_records':len(raw),'distinct_records':len(seen),'duplicate_records':len(raw)-len(seen),'chunks':added,'eligible':role!='CONTEXT_ONLY_NATIVE_STATISTICS'})
    con.commit()
con.close();dump(REPORT/'prior_native_admission_integration.json',summary);print(json.dumps(summary,ensure_ascii=False))
