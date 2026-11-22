"""Resumable isolated ingestion. Never writes a historical or Production index."""
from __future__ import annotations
import argparse
import csv
import datetime
import hashlib
import html
from html.parser import HTMLParser
import io
import json
from pathlib import Path
import re
import shutil
import sqlite3
import sys
from collections import Counter

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from src.unified_rag_v4.common import clean,digest,dump,sha_file,species,tokens,embed,verify_embedding_model,EMBED_MODEL,EMBED_DIGEST
from src.unified_rag_v4.extraction import WindowsOCR,create_archive_schema,extract_pdf,add_element
from src.unified_rag_v4.segmentation import segment_document

POINTER=json.loads((ROOT/'research_staging/unified_rag_build_pointer.json').read_text(encoding='utf-8'))
WORK=Path(POINTER['workspace']);REPORT=Path(POINTER['report_directory'])
CFG=json.loads((WORK/'build_config.json').read_text(encoding='utf-8'))
DB=WORK/CFG.get('database_filename','marine_unified_v4.sqlite3')

def db():
    frozen=WORK/'release_frozen.json'
    if frozen.exists():
        release=json.loads(frozen.read_text(encoding='utf-8'))
        if Path(release['database']).resolve()==DB.resolve():
            raise RuntimeError('This released database is immutable. Create a versioned successor workspace before rebuilding.')
    if not DB.exists():
        src=sqlite3.connect(Path(CFG['source_frozen_database']).as_uri()+'?mode=ro',uri=True)
        target=sqlite3.connect(DB);src.backup(target);src.close();target.close()
    con=sqlite3.connect(DB);con.row_factory=sqlite3.Row;con.execute('PRAGMA foreign_keys=ON');create_archive_schema(con);return con

def baseline(label):
    p=ROOT/'reports/evaluation/final_model_selection/phase20/protected_inputs_before.json'
    j=json.loads(p.read_text(encoding='utf-8-sig'))
    rows=j if isinstance(j,list) else j.get('files',j.get('protected_files',j.get('entries',[])))
    if not isinstance(rows,list):
        rows=[{'path':k,**v} if isinstance(v,dict) else {'path':k,'sha256':v} for k,v in rows.items()]
    checks=[]
    for row in rows:
        target=Path(row['path']);target=target if target.is_absolute() else ROOT/target
        expected=row.get('sha256',row.get('checksum',row.get('expected_sha256')))
        try: actual=sha_file(target);status='UNCHANGED' if actual==expected else 'CHANGED'
        except Exception as e: actual=None;status=repr(e)
        checks.append({'path':str(target),'expected':expected,'actual':actual,'status':status})
    production=sha_file(ROOT/'rag_store.sqlite3')
    summary={'checked_at':datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).isoformat(),'count':len(checks),'unchanged':sum(x['status']=='UNCHANGED' for x in checks),'production_sqlite_sha256':production,'production_matches':production==CFG['baseline_sqlite_sha256'],'entries':checks}
    dump(REPORT/('protected_'+label+'.json'),summary)
    if summary['count']!=636 or summary['unchanged']!=636 or not summary['production_matches']: raise RuntimeError('Protected baseline mismatch; stopped')
    return summary

def policy(rec):
    text=rec.get('publication_excerpt','');name=Path(rec['primary_path']).name
    if rec.get('existing_source') in ('MOA-TFRI-OPEN-114846','MOA-ANIMAL-DRUG-OPEN-7274','MOA-EEL-STOCKING-OPEN-41845','DGBAS-79395-2020'):
        return {'status':'EXISTING_ADMITTED_STRUCTURED_RECORD_SCOPE','eligible':False,'url':None,'license_url':'https://data.gov.tw/license','publisher':'已核實提供機關，詳既有Source Registry','scope':rec['existing_scope'],'evidence':['Existing separately verified Owner Admission, dataset resource identity and OGL v1 scope retained','Native records are stored and the previously eligible record representations are reused; this is not a new unscoped fulltext admission'],'general_scope':False}
    special=bool(re.search(r'非經.{0,12}同意.{0,20}不得.{0,15}(重製|數位化|轉載)|不得重製|all rights reserved',text,re.S|re.I))
    # A chapter cannot shed the explicit restriction of its identified parent book.
    if '技術手冊17' in name or '技術手冊15' in name or 'tfrin_technical_manual_17' in name or '生物安全手冊' in text[:900]: special=True
    official=[]
    manifest=WORK/'upstream/download_manifest.json'
    if manifest.exists(): official=json.loads(manifest.read_text(encoding='utf-8'))
    for p in (WORK/'upstream').glob('*.pdf'):
        if sha_file(p)==rec['sha256']:
            url=next((x.get('url') for x in official if x.get('file')==str(p)),None)
            # Exact known resources, including files acquired in the first request.
            if not url and p.name=='tfrin_eel_parasites.pdf': url='https://www.tfrin.gov.tw/redirect_files.php?file_name=PLAkufpcOgoZRKZ9OwWGEqualG6pqTSq1sCzn6PFKbkjMbC2pX&id=13349'
            if url and not special and (WORK/'upstream/tfrin_website_license.html').exists():
                return {'status':'OGL_V1_EXACT_OFFICIAL_RESOURCE_EXCEPTION_SCREENED','eligible':True,'url':url,'license_url':'https://www.tfrin.gov.tw/ws.php?id=523','publisher':'農業部水產試驗所','scope':'Historical source text; no current medication authorization, diagnostic certainty or unqualified cross-species inference. Figure credits and OCR remain separately screened.','evidence':['Exact upstream file SHA-256 equals local original','Publisher website OGL v1 declaration, special-consent exception retained','No specific reuse prohibition found in this exact document'],'general_scope':False}
    if not special and ('法規名稱：' in text or ('行政院公報' in text and ('農委會' in text or '行政院農業委員會' in text)) or ('修正條文對照表' in text and ('本標準' in text or '本規則' in text))):
        return {'status':'STATUTORY_TEXT_ART9_HISTORICAL_SNAPSHOT','eligible':True,'url':None,'license_url':'https://law.moj.gov.tw/LawClass/LawAll.aspx?pcode=J0070017','publisher':'原件所載主管機關；現行版本未另核實','scope':'Statutory/public-document wording only. This archived revision is not certified current. No drug permission, dose or withdrawal inference.','evidence':['Original body identifies statutory or official-public-document wording','Copyright Act article 9 scope; not a blanket license for added illustrations or third-party expression'],'general_scope':True}
    return {'status':'EXPLICIT_RESTRICTION_FULLTEXT_QUARANTINED' if special else 'FULLTEXT_USAGE_BASIS_UNVERIFIED','eligible':False,'url':None,'license_url':None,'publisher':None,'scope':'Local source review/archive only. No fulltext FTS, dense answer retrieval or generator context. Existing admitted limited fact representations remain separate.','evidence':rec.get('rights_statements',[])[:4],'general_scope':False}

class TextHTML(HTMLParser):
    def __init__(self): super().__init__();self.parts=[];self.skip=0
    def handle_starttag(self,tag,attrs):
        if tag in ('script','style'): self.skip+=1
        elif tag in ('p','br','div','tr','li','h1','h2','h3'): self.parts.append('\n')
    def handle_endtag(self,tag):
        if tag in ('script','style'): self.skip=max(0,self.skip-1)
    def handle_data(self,data):
        if not self.skip: self.parts.append(data)

def archive():
    if not (REPORT/'protected_before.json').exists(): baseline('before')
    con=db();inventory=json.loads((WORK/'source_inventory.json').read_text(encoding='utf-8'));ocr=WindowsOCR(ROOT,WORK)
    dump(REPORT/'ocr_runtime.json',ocr.info)
    try:
        for rec in inventory:
            did=rec['document_id'];existing=con.execute('SELECT parse_status FROM documents WHERE document_id=?',(did,)).fetchone()
            if existing and existing[0]=='PARSED': continue
            p=Path(rec['primary_path']);checksum=sha_file(p)
            if checksum!=rec['sha256']: raise ValueError('Source changed during build: '+str(p))
            dest=WORK/'snapshots'/(checksum+p.suffix.lower())
            if not dest.exists(): shutil.copyfile(p,dest)
            rights=policy(rec);rec['usage_policy']=rights
            rec['native_record_version']='LOCAL_IMMUTABLE_SHA256_SNAPSHOT; ORIGINAL_RELEASE_VERSION_NOT_UNIFORMLY_VERIFIED'
            con.execute('INSERT OR REPLACE INTO documents VALUES(?,?,?,?,?,?,?,?,?,?)',(did,checksum,p.stem,p.suffix,rights['publisher'],rec['native_record_version'],rights['status'],rec['owner_decision'],'PROCESSING',json.dumps(rec,ensure_ascii=False)))
            for alias in rec['paths']: con.execute('INSERT OR REPLACE INTO document_files VALUES(?,?,?,?)',(alias,did,checksum,int('my_data' in Path(alias).parts)))
            con.execute('INSERT OR IGNORE INTO raw_documents VALUES(?,?)',(did,p.read_bytes()));con.commit()
            print(json.dumps({'stage':'EXTRACT','file':p.name,'policy':rights['status']},ensure_ascii=False),flush=True)
            try:
                parse=Path(rec['parse_path'])
                if parse.suffix.lower()=='.pdf': result=extract_pdf(con,rec,WORK,ocr)
                elif p.suffix.lower()=='.html':
                    obj=TextHTML();obj.feed(p.read_text(encoding='utf-8-sig',errors='replace'));txt=clean(''.join(obj.parts));add_element(con,did,None,'HTML_TEXT',txt,metadata={'parser':'HTMLParser_SKIP_SCRIPT_STYLE'});result={'pages':0,'issues':[]}
                else:
                    # Structured official records already have their scoped retrieval
                    # representations in the pinned parent, not a new unscoped index.
                    result={'pages':0,'issues':[],'status':'STRUCTURED_RAW_SNAPSHOT_PRESERVED_WITH_EXISTING_RECORD_INDEX'}
                    if p.suffix.lower()=='.json':
                        raw=json.loads(p.read_text(encoding='utf-8-sig'))
                        records=raw if isinstance(raw,list) else [raw]
                        result['record_count']=len(records)
                rec['extraction_result']=result
                con.execute("UPDATE documents SET parse_status='PARSED',metadata_json=? WHERE document_id=?",(json.dumps(rec,ensure_ascii=False),did));con.commit()
            except Exception as exc:
                rec['extraction_error']=repr(exc);con.execute("UPDATE documents SET parse_status='EXTRACTION_ERROR',metadata_json=? WHERE document_id=?",(json.dumps(rec,ensure_ascii=False),did));con.commit()
                print(json.dumps({'stage':'EXTRACT_ERROR','file':p.name,'error':repr(exc)},ensure_ascii=False),flush=True)
    finally: ocr.close();con.close()

def register_source(con,rec):
    pol=rec['usage_policy'];sid='MYDATA-'+rec['sha256'][:16]
    version=rec['native_record_version'];source=next(iter(rec['paths']))
    row={'source_id':sid,'dataset_id':'LOCAL_DOCUMENT','title':Path(source).stem,'publisher':pol['publisher'] or 'UNVERIFIED','dataset_url':pol['url'] or 'LOCAL_PUBLISHED_ORIGINAL','resource_url':pol['url'] or 'LOCAL_PUBLISHED_ORIGINAL','source_sha256':rec['sha256'],'file_size_bytes':Path(source).stat().st_size,'source_file':str(WORK/'snapshots'/(rec['sha256']+Path(source).suffix.lower())),'license':pol['status'],'license_url':pol['license_url'] or 'UNVERIFIED','attribution':(pol['publisher'] or '原件發布者待核')+'；'+Path(source).stem+'；原始文件SHA-256 '+rec['sha256'],'owner_admission_status':'APPROVED_RESEARCH_PROCESSING_EXISTING_OWNER_DECISIONS_PRESERVED','license_scope_status':pol['status'],'identity_status':'LOCAL_SHA_VERIFIED_AND_EXACT_OFFICIAL_RESOURCE' if pol['url'] else 'LOCAL_ORIGINAL_SHA_VERIFIED','version_status':version,'applicability_status':'ELEMENT_AND_SECTION_SCOPED_NOT_FILENAME_INFERENCE','completeness_status':'EXTRACTION_QUALITY_RECORDED_PER_PAGE_TABLE_AND_IMAGE','processing_scope':pol['scope'],'source_cluster_id':rec['document_id'],'metadata_json':json.dumps(rec,ensure_ascii=False)}
    columns=list(row);con.execute('INSERT OR REPLACE INTO sources('+','.join(columns)+') VALUES('+','.join('?'*len(columns))+')',[row[k] for k in columns]);return row

def add_segment_chunk(con,source,rec,seg):
    els=[dict(con.execute('SELECT * FROM document_elements WHERE element_id=?',(eid,)).fetchone()) for eid in seg['elements']]
    context='\n'.join([seg.get('section',''),seg['text']])
    fish=species(context)
    # Document scope is only inherited from an explicit original first-page
    # subject, never the operating-system filename.
    evidence=rec.get('first_page','')
    document_fish=species(evidence)
    pol=rec['usage_policy']
    if not fish and len([f for f in document_fish if f in ('虱目魚','吳郭魚','石斑魚','鱸魚','烏魚','鰻魚')])==1: fish=document_fish
    scope='GENERAL_REGULATION' if pol['general_scope'] else 'SPECIES_EXPLICIT' if fish else 'SPECIES_SCOPE_UNKNOWN'
    if not fish and '養殖淡' in evidence[:500] and ('魚類疾病防治' in evidence[:500]):
        scope='GENERAL_FRESHWATER_AQUACULTURE'
    if pol['general_scope']: fish=[]
    # Third-party credits are not covered merely by a publisher's site license.
    third_party=seg['kind']=='IMAGE_OCR_CAPTION' and bool(re.search(r'取自|轉載|圖片來源|照片提供|courtesy|©',seg['text'],re.I))
    historical_treatment=not pol['general_scope'] and bool(re.search(r'孔雀綠|硝基呋喃|三氯松|美舒添|馬速展|抗生素|藥浴|投藥|給藥|處方|停藥期|休藥期',seg['text']))
    good=pol['eligible'] and scope!='SPECIES_SCOPE_UNKNOWN' and not third_party and not historical_treatment and seg['quality'] not in ('OVERSIZE_UNIT_REVIEW','TABLE_MERGED_OR_MISSING_CELLS_REVIEW','TABLE_MULTIROW_HEADER_REQUIRES_REVIEW','OCR_ONLY_REQUIRES_REVIEW') and len(seg['text'])>=20
    rid=seg['segment_id'];cid='V4-'+digest([source['source_id'],rid])[:24]
    loc={'document_id':rec['document_id'],'physical_pages':[seg['page_start'],seg['page_end']],'elements':[{'element_id':e['element_id'],'page':e['page'],'bbox':json.loads(e['bbox_json']),'text_offset':[0,len(e['text'])]} for e in els],'table_row_range':seg.get('row_range')}
    record={'source_record_id':rid,'source_id':source['source_id'],'source_record_locator':json.dumps(loc,ensure_ascii=False),'source_record_sha256':digest(seg['text'].encode()),'eligibility_status':'RETRIEVAL_ELIGIBLE' if good else 'CONTEXT_ONLY','eligibility_reason':scope+'; '+seg['quality'],'original_record_json':json.dumps({'original_elements':els,'usage_policy':pol,'scope_evidence':{'paragraph_species':species(context),'original_first_page_subject':evidence[:500],'scope_kind':scope},'kind':seg['kind']},ensure_ascii=False),'duplicate_group_id':None}
    con.execute('INSERT OR REPLACE INTO source_records VALUES(?,?,?,?,?,?,?,?)',tuple(record.values()))
    text=seg['text'];row={'chunk_id':cid,'source_id':source['source_id'],'source_record_id':rid,'source_sha256':rec['sha256'],'source_version':source['version_status'],'locator':record['source_record_locator'],'text':text,'content_sha256':digest(text.encode()),'source_quote':text,'raw_field_pointer':'document_elements:'+','.join(seg['elements']),'quote_start':0,'quote_end':len(text),'species_scope':json.dumps(fish,ensure_ascii=False),'scientific_scope':None,'taxonomy_level':scope,'category_scope':json.dumps(['Law'] if pol['general_scope'] else ['Aquaculture source text; exact applicability retained']),'source_cluster_id':source['source_cluster_id'],'processing_scope':pol['scope'],'source_path':source['source_file'],'source_page':seg['page_start'],'retrieval_status':'RETRIEVAL_ELIGIBLE' if good else 'CONTEXT_ONLY','retrieval_eligible':int(good),'human_gold':0,'formal_admission':1,'embedding':None,'embedding_model':None,'embedding_digest':None,'embedding_dimension':None,'transform_rule':seg['method'],'restrictions_json':json.dumps({'scope_kind':scope,'kind':seg['kind'],'quality':seg['quality'],'no_current_medication_inference':True,'no_unqualified_cross_species_inference':True,'historical_treatment_quarantined':historical_treatment,'third_party_credit':third_party,'asset_ids':list({e['asset_id'] for e in els if e['asset_id']})},ensure_ascii=False)}
    columns=list(row);con.execute('INSERT OR REPLACE INTO chunks('+','.join(columns)+') VALUES('+','.join('?'*len(columns))+')',[row[k] for k in columns]);con.execute('UPDATE element_chunks SET chunk_id=? WHERE segment_id=?',(cid,rid))

def index():
    verify_embedding_model();con=db()
    for dbrow in list(con.execute("SELECT * FROM documents WHERE parse_status='PARSED'")):
        rec=json.loads(dbrow['metadata_json']);did=rec['document_id'];pol=rec['usage_policy']
        if con.execute('SELECT 1 FROM element_chunks WHERE document_id=? LIMIT 1',(did,)).fetchone(): continue
        print(json.dumps({'stage':'SEGMENT','file':Path(rec['primary_path']).name,'semantic':pol['eligible']},ensure_ascii=False),flush=True)
        segments=segment_document(con,did,semantic=pol['eligible'])
        if pol['eligible']:
            source=register_source(con,rec)
            for seg in segments: add_segment_chunk(con,source,rec,seg)
        con.commit()
    rows=list(con.execute('SELECT chunk_id,text FROM chunks WHERE retrieval_eligible=1 AND embedding IS NULL'))
    for start in range(0,len(rows),24):
        batch=rows[start:start+24];vectors=embed([r['text'] for r in batch])
        for row,vec in zip(batch,vectors): con.execute('UPDATE chunks SET embedding=?,embedding_model=?,embedding_digest=?,embedding_dimension=1024 WHERE chunk_id=?',(vec.tobytes(),EMBED_MODEL,EMBED_DIGEST,row['chunk_id']))
        con.commit();print(json.dumps({'stage':'BGE_EMBED','completed':start+len(batch),'total':len(rows)}),flush=True)
    con.execute('CREATE VIRTUAL TABLE IF NOT EXISTS unified_fts USING fts5(chunk_id UNINDEXED, tokens, tokenize="unicode61")')
    # Remove only the unused copied FTS table inside this new database. The
    # historical database is always opened read-only and is never changed.
    con.execute('DROP TABLE IF EXISTS chunks_fts')
    con.execute('DELETE FROM unified_fts')
    for row in con.execute('SELECT chunk_id,text FROM chunks WHERE retrieval_eligible=1 ORDER BY chunk_id').fetchall(): con.execute('INSERT INTO unified_fts(chunk_id,tokens) VALUES(?,?)',(row['chunk_id'],tokens(row['text'])))
    con.commit();con.close()

def image_vectors():
    import numpy as np
    import torch
    from PIL import Image
    from transformers import CLIPModel,CLIPProcessor
    con=db();folder=WORK/'models/clip-vit-base-patch32'
    model=CLIPModel.from_pretrained(folder,local_files_only=True).eval();processor=CLIPProcessor.from_pretrained(folder,local_files_only=True)
    revision=json.loads((folder/'revision.json').read_text())['revision']
    # A visual vector is not an aquatic diagnosis or a text-grounded fact.
    rows=list(con.execute('SELECT DISTINCT a.asset_id,a.path, d.rights_status FROM media_assets a JOIN document_elements e ON a.asset_id=e.asset_id JOIN documents d ON d.document_id=e.document_id WHERE e.kind="IMAGE" AND a.width>=70 AND a.height>=35 AND d.rights_status="OGL_V1_EXACT_OFFICIAL_RESOURCE_EXCEPTION_SCREENED" AND a.asset_id NOT IN(SELECT asset_id FROM image_embeddings)'))
    credited={r['asset_id'] for r in con.execute('SELECT asset_id,metadata_json FROM document_elements WHERE kind="IMAGE"') if re.search(r'取自|轉載|圖片來源|照片提供|courtesy|©',json.loads(r['metadata_json']).get('caption',''),re.I)}
    rows=[r for r in rows if r['asset_id'] not in credited]
    for start in range(0,len(rows),12):
        batch=rows[start:start+12];images=[Image.open(r['path']).convert('RGB') for r in batch]
        with torch.inference_mode():
            inputs=processor(images=images,return_tensors='pt');features=model.get_image_features(**inputs)
            if hasattr(features,'pooler_output'): features=features.pooler_output
            vectors=features.float().detach().numpy();vectors/=np.maximum(np.linalg.norm(vectors,axis=1,keepdims=True),1e-12)
        for row,vector in zip(batch,vectors): con.execute('INSERT OR REPLACE INTO image_embeddings VALUES(?,?,?,?,?,?)',(row['asset_id'],vector.astype(np.float32).tobytes(),len(vector),'openai/clip-vit-base-patch32',revision,1))
        for im in images: im.close()
        con.commit();print(json.dumps({'stage':'CLIP_IMAGE_EMBED','completed':start+len(batch),'total':len(rows)}),flush=True)
    con.close()

def finalize():
    con=db();checks={}
    for r in con.execute('SELECT document_id,metadata_json FROM documents').fetchall():
        rec=json.loads(r['metadata_json'])
        if rec.get('existing_source') in ('MOA-TFRI-OPEN-114846','MOA-ANIMAL-DRUG-OPEN-7274','MOA-EEL-STOCKING-OPEN-41845','DGBAS-79395-2020'):
            rec['usage_policy']=policy(rec)
            con.execute('UPDATE documents SET rights_status=?,metadata_json=? WHERE document_id=?',(rec['usage_policy']['status'],json.dumps(rec,ensure_ascii=False),r['document_id']))
    checks['sqlite_integrity']=con.execute('PRAGMA integrity_check').fetchone()[0]
    checks['foreign_key_errors']=[list(r) for r in con.execute('PRAGMA foreign_key_check')]
    checks['missing_eligible_embedding']=con.execute('SELECT count(*) FROM chunks WHERE retrieval_eligible=1 AND (embedding IS NULL OR embedding_dimension!=1024 OR length(embedding)!=4096)').fetchone()[0]
    eligible_ids={r[0] for r in con.execute('SELECT chunk_id FROM chunks WHERE retrieval_eligible=1')}
    fts_rows=[r[0] for r in con.execute('SELECT chunk_id FROM unified_fts')]
    fts_ids=set(fts_rows)
    checks['fts_missing']=len(eligible_ids-fts_ids)
    checks['fts_ineligible']=len(fts_ids-eligible_ids)
    checks['fts_duplicate_ids']=len(fts_rows)-len(fts_ids)
    checks['source_hash_errors']=[]
    for row in con.execute('SELECT document_id,sha256,original_bytes FROM documents JOIN raw_documents USING(document_id)'):
        if digest(bytes(row['original_bytes']))!=row['sha256']: checks['source_hash_errors'].append(row['document_id'])
    counts={k:con.execute('SELECT count(*) FROM '+k).fetchone()[0] for k in ['documents','document_files','document_pages','document_elements','element_chunks','media_assets','image_embeddings','sources','chunks','source_records','unified_fts']}
    counts['retrieval_eligible']=con.execute('SELECT count(*) FROM chunks WHERE retrieval_eligible=1').fetchone()[0]
    counts['context_only']=con.execute('SELECT count(*) FROM chunks WHERE retrieval_eligible=0').fetchone()[0]
    counts['my_data_paths']=con.execute('SELECT count(*) FROM document_files WHERE is_my_data=1').fetchone()[0]
    counts['document_rights_status']=dict(con.execute('SELECT rights_status,count(*) FROM documents GROUP BY rights_status'))
    counts['parse_status']=dict(con.execute('SELECT parse_status,count(*) FROM documents GROUP BY parse_status'))
    counts['element_kinds']=dict(con.execute('SELECT kind,count(*) FROM document_elements GROUP BY kind'))
    counts['ocr_status']=dict(con.execute('SELECT ocr_status,count(*) FROM media_assets GROUP BY ocr_status'))
    counts['segmentation_quality']=dict(con.execute('SELECT quality_status,count(*) FROM element_chunks GROUP BY quality_status'))
    counts['semantic_boundary_decisions']=con.execute('SELECT count(*) FROM semantic_boundaries WHERE cosine IS NOT NULL').fetchone()[0]
    counts['my_data_with_elements']=con.execute('SELECT count(DISTINCT f.path) FROM document_files f JOIN document_elements e USING(document_id) WHERE f.is_my_data=1').fetchone()[0]
    counts['structured_records']=con.execute('SELECT count(*) FROM structured_records').fetchone()[0]
    source_rows=[dict(r) for r in con.execute('SELECT * FROM sources')]
    dump(WORK/'source_registry.json',{'sources':source_rows})
    doc_rows=[{k:v for k,v in dict(r).items() if k!='metadata_json'} for r in con.execute('SELECT * FROM documents')]
    dump(REPORT/'document_processing_status.json',doc_rows)
    dump(REPORT/'integrity_validation.json',checks)
    con.commit();con.close()
    manifest={**CFG,'database':str(DB),'database_sha256':sha_file(DB),'counts':counts,'segmentation':{'native_text':'section/layout plus BGE-M3 paragraph cosine boundaries; threshold 0.62; max target 1100 chars without chopping indivisible sentences','tables':'atomic original cells, row groups with header and nearby footnote candidates; ambiguous merged cells not retrieval eligible','images':'original image bytes, source page/bbox, Windows zh-Hant-TW OCR, local CLIP 512-d visual embeddings for scope-eligible images','not_all_chunks_expert_semantically_verified':True},'restriction':'All originals are catalogued. Fulltext retrieval and image vectors are allowed only for verified usage scopes; restricted documents remain archive-only. No model weights or Production index changed.','validation':checks}
    dump(WORK/'corpus_manifest.json',manifest);dump(REPORT/'corpus_manifest.json',manifest)
    if checks['sqlite_integrity']!='ok' or checks['foreign_key_errors'] or any(checks[k] for k in ['missing_eligible_embedding','fts_missing','fts_ineligible','fts_duplicate_ids','source_hash_errors']): raise RuntimeError('Index integrity validation failed')
    baseline('after');dump(WORK/'build_complete.json',{'version':CFG['version'],'database':str(DB),'database_sha256':manifest['database_sha256'],'baseline_unchanged':636});print(json.dumps(manifest['counts'],ensure_ascii=False),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('stage',choices=['archive','index','images','finalize']);args=p.parse_args()
    {'archive':archive,'index':index,'images':image_vectors,'finalize':finalize}[args.stage]()
