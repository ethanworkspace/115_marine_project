"""All-original local research ingestion with provenance and separate answer gates."""
from __future__ import annotations
import argparse,hashlib,json,re,shutil,sqlite3,sys,time
from pathlib import Path
import numpy as np
import requests
from bs4 import BeautifulSoup
import html
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tools')]
import build_unified_rag_v4 as b
from src.unified_rag_v4 import segmentation
from src.unified_rag_v4.common import clean,digest,dump,embed,sha_file,species,EMBED_MODEL,EMBED_DIGEST,tokens
P=json.loads((ROOT/'research_staging/unified_rag_v5_build_pointer.json').read_text(encoding='utf-8'))
W=Path(P['workspace']);R=Path(P['report_directory']);CFG=json.loads((W/'build_config.json').read_text(encoding='utf-8'))
b.WORK=W;b.REPORT=R;b.CFG=CFG;b.DB=W/CFG['database_filename'];DB=b.DB
LAW_DOCS={
 'DOC-81c5219064ec1c90a033':'M0130003','DOC-f90b9274bdc57bc4c99d':'M0130015',
 'DOC-b93e25715f931fd3342b':'M0130015','DOC-b13b9492322d7c0de2e1':'M0130023',
 'DOC-182d92546b8f1fa64d9d':'J0110001','DOC-1c1ee3f85abf19691285':'O0040001',
 'DOC-05420f084eed4b041f7e':'M0050001','DOC-b7358af17acdb68ad3c2':'O0060020',
 'DOC-3e3137456f8eeeaad471':'M0050070','DOC-43c831286633387fd28c':'M0050070',
 'DOC-373c2c4e6d4dd92835f1':'M0090019','DOC-42719d2f1f6781e1bcb4':'D0060013',
 'DOC-bcea01ea1ff5cfe77930':'L0040026','DOC-f6ace09c19557fc3fa90':'GL002203',
 'DOC-ac197eb08e591a1df8e0':'GL002203'}

def connect():
    con=b.db()
    con.executescript('''
    CREATE TABLE IF NOT EXISTS embedding_cache(content_sha256 TEXT PRIMARY KEY,embedding BLOB NOT NULL,dimension INTEGER NOT NULL,model TEXT NOT NULL,digest TEXT NOT NULL,method TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS archive_units(unit_id TEXT PRIMARY KEY,document_id TEXT,source_id TEXT,kind TEXT,locator TEXT NOT NULL,text TEXT NOT NULL,content_sha256 TEXT NOT NULL,related_chunk_id TEXT);
    CREATE TABLE IF NOT EXISTS source_usage_events(document_id TEXT PRIMARY KEY,user_statement_json TEXT NOT NULL,previous_rights_status TEXT NOT NULL,original_notices_json TEXT NOT NULL,third_party_license_verified INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS answer_eligibility(chunk_id TEXT PRIMARY KEY,eligible INTEGER NOT NULL,reason TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS image_embedding_methods(asset_id TEXT PRIMARY KEY,method_json TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS all_documents_checkpoint(document_id TEXT PRIMARY KEY,status TEXT NOT NULL);
    ''')
    con.execute('INSERT OR IGNORE INTO embedding_cache SELECT content_sha256,embedding,1024,embedding_model,embedding_digest,? FROM chunks WHERE embedding IS NOT NULL AND embedding_dimension=1024 AND embedding_digest=?',('REUSED_PINNED_PARENT_VECTOR',EMBED_DIGEST))
    con.execute('INSERT OR IGNORE INTO answer_eligibility SELECT chunk_id,retrieval_eligible,? FROM chunks',('PINNED_PARENT_USAGE_AND_CONTENT_GATE_RETAINED',));con.commit()
    return con

CACHE=None
def encode_complete(texts):
    """Never silently truncate. Recover explicit context-limit errors only."""
    response=requests.post('http://127.0.0.1:11434/api/embed',json={'model':EMBED_MODEL,'input':texts,'truncate':False,'keep_alive':'30m'},timeout=(15,240))
    if response.status_code==413:
        with (xlog:=W/'logs/embedding_context_limit_recovery.jsonl').open('a',encoding='utf-8') as f:
            f.write(json.dumps({'lengths':[len(t) for t in texts],'error':response.text,'action':'split batch or pool complete overlapping text windows; no content discarded'})+'\n')
        if len(texts)>1:
            half=len(texts)//2;return np.concatenate([encode_complete(texts[:half]),encode_complete(texts[half:])])
        text=texts[0]
        if len(text)<128:raise RuntimeError('Even a short embedding unit exceeded model context')
        width=max(96,len(text)//2);step=max(1,width-48)
        vec=encode_complete([text[i:i+width] for i in range(0,len(text),step)])
        value=np.mean(vec,axis=0);return np.asarray([value/max(float(np.linalg.norm(value)),1e-12)],dtype=np.float32)
    response.raise_for_status();vectors=np.asarray(response.json()['embeddings'],dtype=np.float32)
    if vectors.shape!=(len(texts),1024) or not np.isfinite(vectors).all():raise ValueError('Invalid BGE-M3 vector response')
    return vectors/np.maximum(np.linalg.norm(vectors,axis=1,keepdims=True),1e-12)

def cached_embed(texts):
    global CACHE
    if CACHE is None:
        CACHE=sqlite3.connect(W/'embedding_work_cache.sqlite3')
        CACHE.execute('CREATE TABLE IF NOT EXISTS vectors(sha TEXT PRIMARY KEY,embedding BLOB,method TEXT)')
        parent=sqlite3.connect(DB.as_uri()+'?mode=ro',uri=True)
        for sha,raw,method in parent.execute('SELECT content_sha256,embedding,method FROM embedding_cache WHERE digest=?',(EMBED_DIGEST,)):
            CACHE.execute('INSERT OR IGNORE INTO vectors VALUES(?,?,?)',(sha,raw,method))
        parent.close();CACHE.commit()
    result=[None]*len(texts);pending={}
    for i,text in enumerate(texts):
        sha=digest(text.encode());old=CACHE.execute('SELECT embedding FROM vectors WHERE sha=?',(sha,)).fetchone()
        if old:result[i]=np.frombuffer(old[0],dtype=np.float32)
        else:pending.setdefault(sha,{'text':text,'indices':[]})['indices'].append(i)
    simple=[(key,row) for key,row in pending.items() if len(row['text'])<=1700]
    for start in range(0,len(simple),16):
        batch=simple[start:start+16];vectors=encode_complete([x[1]['text'] for x in batch])
        for (sha,row),v in zip(batch,vectors):
            CACHE.execute('INSERT OR REPLACE INTO vectors VALUES(?,?,?)',(sha,v.tobytes(),'WHOLE_SEMANTIC_UNIT'))
            for i in row['indices']:result[i]=v
        CACHE.commit()
    for sha,row in pending.items():
        if len(row['text'])<=1700:continue
        text=row['text'];windows=[text[i:i+1600] for i in range(0,len(text),1500)]
        vectors=encode_complete(windows);v=np.mean(vectors,axis=0);v=(v/max(float(np.linalg.norm(v)),1e-12)).astype(np.float32)
        CACHE.execute('INSERT OR REPLACE INTO vectors VALUES(?,?,?)',(sha,v.tobytes(),'MEAN_OF_COMPLETE_OVERLAPPING_LONG_UNIT_WINDOWS; original text not cut'))
        CACHE.commit()
        for i in row['indices']:result[i]=v
    return np.asarray(result,dtype=np.float32)

def documents():
    if not (R/'protected_before.json').exists():b.baseline('before')
    con=connect();segmentation.embed=cached_embed;b.embed=cached_embed
    (W/'snapshots').mkdir(exist_ok=True)
    rows=con.execute('SELECT * FROM documents ORDER BY document_id').fetchall()
    for n,doc in enumerate(rows,1):
        rec=json.loads(doc['metadata_json']);did=doc['document_id']
        con.execute('INSERT OR IGNORE INTO source_usage_events VALUES(?,?,?,?,?)',(did,json.dumps(CFG['user_use_attestation'],ensure_ascii=False),doc['rights_status'],json.dumps(rec.get('rights_statements',[]),ensure_ascii=False),int(doc['rights_status'].startswith(('OGL_','STATUTORY_','EXISTING_ADMITTED_','PRIOR_APPROVED_')))))
        original=Path(rec['primary_path']);target=W/'snapshots'/(doc['sha256']+original.suffix.lower())
        if not target.exists():shutil.copyfile(original,target)
        checkpoint=con.execute('SELECT 1 FROM all_documents_checkpoint WHERE document_id=?',(did,)).fetchone()
        if checkpoint:
            segmented=con.execute('SELECT 1 FROM element_chunks WHERE document_id=? LIMIT 1',(did,)).fetchone()
            native=original.suffix.lower() in ('.json','.csv','.xml')
            if segmented or native:continue
            con.execute('DELETE FROM all_documents_checkpoint WHERE document_id=?',(did,));con.commit()
        if original.suffix.lower() in ('.json','.csv','.xml'):
            con.execute('INSERT INTO all_documents_checkpoint VALUES(?,?)',(did,'NATIVE_RECORD_SCOPE_RETAINED'));con.commit();continue
        previous=doc['rights_status'];pol=rec['usage_policy']
        expanded=previous in ('FULLTEXT_USAGE_BASIS_UNVERIFIED','EXPLICIT_RESTRICTION_FULLTEXT_QUARANTINED','USER_ATTESTED_LOCAL_RESEARCH_FULLTEXT')
        rec['user_use_attestation']=CFG['user_use_attestation'];rec.setdefault('original_usage_policy',pol.copy())
        if expanded:
            rec['usage_policy']={'status':'USER_ATTESTED_LOCAL_RESEARCH_FULLTEXT','eligible':True,
                'url':pol.get('url'),'license_url':pol.get('license_url'),'publisher':doc['publisher'],
                'scope':'User states all provided documents can be used for this private research RAG. Original notices retained; no claim of independently verified third-party license, current legal effect or unqualified species applicability.',
                'evidence':[CFG['user_use_attestation']['statement']], 'general_scope':did in LAW_DOCS}
            con.execute('UPDATE documents SET rights_status=?,owner_decision=?,metadata_json=? WHERE document_id=?',('USER_ATTESTED_LOCAL_RESEARCH_FULLTEXT','APPROVED_ALL_PROVIDED_DOCUMENTS_CURRENT_USER_INSTRUCTION',json.dumps(rec,ensure_ascii=False),did));con.commit()
            # Only derived rows in this new successor are regenerated.
            old=list(con.execute('SELECT segment_id,chunk_id FROM element_chunks WHERE document_id=?',(did,)))
            for seg in old:
                if seg['chunk_id']:
                    con.execute('DELETE FROM chunks WHERE chunk_id=?',(seg['chunk_id'],));con.execute('DELETE FROM source_records WHERE source_record_id=?',(seg['segment_id'],));con.execute('DELETE FROM answer_eligibility WHERE chunk_id=?',(seg['chunk_id'],))
            con.execute('DELETE FROM element_chunks WHERE document_id=?',(did,));con.execute('DELETE FROM semantic_boundaries WHERE document_id=?',(did,));con.commit()
            source=b.register_source(con,rec)
            print(json.dumps({'stage':'DOCUMENT_SEMANTIC_SPLIT','document':doc['title'],'n':n,'total':len(rows)},ensure_ascii=False),flush=True)
            units=segmentation.segment_document(con,did,semantic=True)
            for unit in units:b.add_segment_chunk(con,source,rec,unit)
        else:con.execute('UPDATE documents SET metadata_json=? WHERE document_id=?',(json.dumps(rec,ensure_ascii=False),did))
        con.execute('INSERT INTO all_documents_checkpoint VALUES(?,?)',(did,'SEMANTIC_TEXT_TABLE_IMAGE_UNITS_READY'));con.commit()
    con.close()

def archive_vectors():
    con=connect()
    con.execute('DELETE FROM archive_units WHERE related_chunk_id IS NOT NULL AND related_chunk_id NOT IN (SELECT chunk_id FROM chunks)')
    cleaning=[]
    for row in con.execute('SELECT * FROM chunks').fetchall():
        sha=digest(row['text'].encode());doc=con.execute('SELECT document_id FROM documents WHERE sha256=?',(row['source_sha256'],)).fetchone()
        con.execute('INSERT OR REPLACE INTO archive_units VALUES(?,?,?,?,?,?,?,?)',('CHUNK-'+row['chunk_id'],doc[0] if doc else None,row['source_id'],'RAG_CHUNK',row['locator'],row['text'],sha,row['chunk_id']))
    for row in con.execute('SELECT * FROM element_chunks WHERE chunk_id IS NULL').fetchall():
        text=clean(row['text'])
        if not text:continue
        con.execute('INSERT OR REPLACE INTO archive_units VALUES(?,?,?,?,?,?,?,?)',(row['segment_id'],row['document_id'],None,row['kind'],json.dumps({'pages':[row['page_start'],row['page_end']],'elements':json.loads(row['element_ids_json'])},ensure_ascii=False),text,digest(text.encode()),None))
    for row in con.execute("SELECT * FROM document_elements WHERE kind='SCAN_OCR'").fetchall():
        text=clean(row['text'])
        if text:con.execute('INSERT OR REPLACE INTO archive_units VALUES(?,?,?,?,?,?,?,?)',(row['element_id'],row['document_id'],None,'SCAN_OCR_REQUIRES_REVIEW',row['locator_json'],text,digest(text.encode()),None))
    for row in con.execute('SELECT * FROM structured_records').fetchall():
        obj=json.loads(row['record_json']);changed=[]
        def field_text(key,value):
            if value is None:return ''
            if isinstance(value,(dict,list)):return json.dumps(value,ensure_ascii=False)
            text=str(value)
            if re.search(r'</?(?:br|p|div|sup|sub|span|b|i|strong)\b',text,re.I):
                soup=BeautifulSoup(text,'html.parser')
                for tag in soup(['script','style']):tag.decompose()
                for tag in soup.find_all('br'):tag.replace_with('\n')
                result=soup.get_text()
            else:result=html.unescape(text)
            result=clean(result)
            if result!=text:changed.append(str(key))
            return result
        text='\n'.join(str(k)+'：'+field_text(k,v) for k,v in obj.items()) if isinstance(obj,dict) else field_text('',obj)
        text=clean(text)
        if text:con.execute('INSERT OR REPLACE INTO archive_units VALUES(?,?,?,?,?,?,?,?)',('RAW-'+row['document_id']+'-'+str(row['record_index']),row['document_id'],None,'ORIGINAL_STRUCTURED_RECORD',row['field_locator'],text,digest(text.encode()),None))
        if changed:cleaning.append({'document_id':row['document_id'],'record_index':row['record_index'],'original_json_unchanged':True,'normalized_fields':changed,'method':'decode HTML entities, join inline chemical notation, preserve BR line breaks; no numeric or unit inference'})
    con.commit()
    dump(R/'structured_field_cleaning_audit.json',cleaning)
    todo=list(con.execute('SELECT u.content_sha256,min(u.text) text FROM archive_units u LEFT JOIN embedding_cache e ON u.content_sha256=e.content_sha256 WHERE e.content_sha256 IS NULL GROUP BY u.content_sha256'))
    for start in range(0,len(todo),16):
        batch=todo[start:start+16];vectors=cached_embed([x['text'] for x in batch])
        for row,v in zip(batch,vectors):con.execute('INSERT OR IGNORE INTO embedding_cache VALUES(?,?,?,?,?,?)',(row['content_sha256'],v.tobytes(),1024,EMBED_MODEL,EMBED_DIGEST,'ALL_TEXT_ARCHIVE_SCOPE_AND_QUALITY_SEPARATE_FROM_ANSWER_GATE'))
        con.commit();print(json.dumps({'stage':'ALL_TEXT_VECTORS','completed':start+len(batch),'total':len(todo)}),flush=True)
    for row in con.execute('SELECT chunk_id,text FROM chunks').fetchall():
        vector=con.execute('SELECT embedding FROM embedding_cache WHERE content_sha256=?',(digest(row['text'].encode()),)).fetchone()
        if vector:con.execute('UPDATE chunks SET embedding=?,embedding_model=?,embedding_digest=?,embedding_dimension=1024 WHERE chunk_id=?',(vector[0],EMBED_MODEL,EMBED_DIGEST,row['chunk_id']))
    con.execute('CREATE VIRTUAL TABLE IF NOT EXISTS semantic_archive_fts USING fts5(unit_id UNINDEXED,tokens,tokenize="unicode61")')
    con.execute('DELETE FROM semantic_archive_fts')
    for row in con.execute('SELECT unit_id,text FROM archive_units').fetchall():con.execute('INSERT INTO semantic_archive_fts VALUES(?,?)',(row['unit_id'],tokens(row['text'])))
    con.execute('DELETE FROM unified_fts')
    for row in con.execute('SELECT chunk_id,text FROM chunks WHERE retrieval_eligible=1').fetchall():con.execute('INSERT INTO unified_fts VALUES(?,?)',(row['chunk_id'],tokens(row['text'])))
    con.commit();con.close()

def images():
    import torch
    from PIL import Image
    from transformers import CLIPModel,CLIPProcessor
    con=connect();folder=Path(CFG['clip_model_directory']);revision=json.loads((folder/'revision.json').read_text())['revision']
    device='cuda' if torch.cuda.is_available() else 'cpu'
    model=CLIPModel.from_pretrained(folder,local_files_only=True).eval().to(device);processor=CLIPProcessor.from_pretrained(folder,local_files_only=True)
    rows=list(con.execute('SELECT * FROM media_assets WHERE asset_id NOT IN(SELECT asset_id FROM image_embeddings)'))
    errors=[]
    for start in range(0,len(rows),24 if device=='cuda' else 8):
        batch=rows[start:start+(24 if device=='cuda' else 8)];valid=[];pics=[]
        for row in batch:
            try:
                im=Image.open(row['path']).convert('RGB');pics.append(im);valid.append(row)
            except Exception as exc:errors.append({'asset_id':row['asset_id'],'error':repr(exc)})
        if pics:
            with torch.inference_mode():
                inputs=processor(images=pics,return_tensors='pt').to(device);features=model.get_image_features(**inputs)
                if hasattr(features,'pooler_output'):features=features.pooler_output
                vectors=features.float().cpu().numpy();vectors/=np.maximum(np.linalg.norm(vectors,axis=1,keepdims=True),1e-12)
            for row,v in zip(valid,vectors):
                con.execute('INSERT INTO image_embeddings VALUES(?,?,?,?,?,?)',(row['asset_id'],v.astype(np.float32).tobytes(),512,'openai/clip-vit-base-patch32',revision,1))
                con.execute('INSERT OR REPLACE INTO image_embedding_methods VALUES(?,?)',(row['asset_id'],json.dumps({'device':device,'precision':'float32','scope':'ALL_USER_PROVIDED_MEDIA; not expert image interpretation or automatic diagnostic evidence'})))
        for im in pics:im.close()
        con.commit();print(json.dumps({'stage':'ALL_IMAGE_VECTORS','completed':start+len(batch),'total':len(rows),'device':device}),flush=True)
    con.close();dump(R/'image_vector_processing_errors.json',errors)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('stage',choices=['documents','vectors','images']);args=parser.parse_args()
    {'documents':documents,'vectors':archive_vectors,'images':images}[args.stage]()
