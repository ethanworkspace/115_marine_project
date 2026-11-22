from __future__ import annotations
import hashlib, json, re, shutil, sqlite3, time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pymupdf
import requests

ROOT=Path.cwd(); OUT=ROOT/'reports/evaluation/fish_test_phase_u_20261018_195823'
INITIAL=OUT/'corpus_v3'; FINAL=OUT/'corpus_v3_final'
MATRIX=ROOT/'reports/evaluation/fish_test_phase_u_20261018_171024/source_admission_approval_matrix.jsonl'
OWNERS=OUT/'source_owner_decision_update_57.jsonl'
REGISTRY=OUT/'source_admission_registry_v3.jsonl'
AUDIT=OUT/'source_rights_version_scope_audit_57.jsonl'
LEGAL=ROOT/'my_data/my_data/動物用藥品管理法.pdf'
LEGAL_ID='MOA-FL014718-ACT'; LEGAL_RECORD='SRC-9427ecc0ecf6'
LEGAL_SHA='f90b9274bdc57bc4c99d1a988872ec3e4783efb6355de9fd7ab4929eace27c67'
OFFICIAL='https://law.moa.gov.tw/LawContent.aspx?id=FL014718'
COPYRIGHT='https://law.moj.gov.tw/LawClass/LawAll.aspx?PCode=J0070017'
OLLAMA='http://127.0.0.1:11434'; BGE='bge-m3:latest'; BGE_DIGEST='7907646426070047a77226ac3e684fbbe8410524f7b4a74d02837e43f2146bab'

def sha_bytes(b): return hashlib.sha256(b).hexdigest()
def sha_file(p): return sha_bytes(Path(p).read_bytes())
def readj(p): return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def readjl(p): return [json.loads(x) for x in Path(p).read_text(encoding='utf-8-sig').splitlines() if x.strip()]
def writej(p,x): Path(p).write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def writejl(p,xs): Path(p).write_text(''.join(json.dumps(x,ensure_ascii=False,separators=(',',':'))+'\n' for x in xs),encoding='utf-8')

if not LEGAL.is_file() or sha_file(LEGAL)!=LEGAL_SHA: raise RuntimeError('Local statutory file missing or checksum mismatch')
matrix=readjl(MATRIX); owners=readjl(OWNERS)
assert len(matrix)==57 and len(owners)==57 and all(x['owner_decision']=='APPROVED' for x in owners)
record=next(x for x in matrix if x['source_record_id']==LEGAL_RECORD)
owner=next(x for x in owners if x['source_record_id']==LEGAL_RECORD)
if owner['owner_decision']!='APPROVED' or record.get('url')!=OFFICIAL: raise RuntimeError('Owner decision or official link mismatch for statute')

# Verify source metadata and its precise statutory scope locally.
doc=pymupdf.open(LEGAL); page_texts=[p.get_text() for p in doc]
full='\n\f\n'.join(page_texts)
if '動物用藥品管理法' not in page_texts[0] or '105 年 11 月 09 日' not in page_texts[0]: raise RuntimeError('Local statute title/revision date not verified')
starts=list(re.finditer(r'(?m)^\s*第\s*(\d+(?:-\d+)?)\s*條\s*$',full))
if len(starts)!=65 or len({m.group(1) for m in starts})!=65: raise RuntimeError(f'Unexpected article parse count: {len(starts)}')
page_starts=[]; pos=0
for i,t in enumerate(page_texts): page_starts.append((pos,i+1)); pos += len(t)+3
def page_at(offset):
    p=1
    for start,pno in page_starts:
        if start<=offset: p=pno
        else: break
    return p
articles=[]
for i,m in enumerate(starts):
    end=starts[i+1].start() if i+1<len(starts) else len(full)
    txt=full[m.start():end].strip()
    txt=re.sub(r'(?m)^\s*\d{1,2}\s*$', '', txt).strip()
    article=m.group(1)
    p0,p1=page_at(m.start()),page_at(end-1)
    locator=f'Article {article}; PDF page {p0}'+(f'-{p1}' if p1!=p0 else '')
    cid='u3-law-'+hashlib.sha256(f'{LEGAL_SHA}|article|{article}'.encode()).hexdigest()[:24]
    articles.append({
        'chunk_id':cid,'source_id':LEGAL_ID,'source_title':'動物用藥品管理法','source_url':OFFICIAL,
        'resource_url':OFFICIAL,'source_sha256':LEGAL_SHA,
        'source_version':'consolidated law; latest amendment shown on official MOA page: 2016-11-09; local PDF metadata modified 2025-01-22; verified 2026-10-18',
        'publisher':'農業部（官方主管法規共用系統）；local PDF author metadata: 全國法規資料庫',
        'license':'Statutory text only; Taiwan Copyright Act Art. 9(1)(1) excludes laws from copyright subject matter',
        'attribution':'農業部主管法規共用系統，動物用藥品管理法（修正日期：民國105年11月9日）',
        'species_scope':'General aquaculture animal-drug law; does not establish product-specific approval, dose, withdrawal period, or species permission without the applicable current rule/annex/product label.',
        'category_scope':['Medication / Law'],'period':'current consolidation as of access date; latest amendment date 2016-11-09',
        'record_locator':locator,'page':p0,'locator':f'Article {article}','chunk_role':'retrieval','retrieval_eligible':True,
        'eligibility_note':'Use only statutory text for general legal requirements. Specific drug use requires the current applicable annex/product registration; excluded here.',
        'source_cluster_id':'MOA-ANIMAL-DRUG-LEGISLATION','corpus_version':'research_corpus_v3_phase_u_20261018_final',
        'content_sha256':sha_bytes(txt.encode('utf-8')),'text':txt,'raw_fields':{'article':article,'source_local_path':str(LEGAL.relative_to(ROOT)).replace('\\','/')}
    })

approval={
  'admission_id':'ADMISSION-MOA-FL014718-ACT-20261018','source_record_id':LEGAL_RECORD,'source_id':LEGAL_ID,
  'owner_decision':'APPROVED','owner_decision_reference':'explicit user instruction 2026-10-18; source-matrix record '+LEGAL_RECORD,
  'source_identity':'verified','publisher':'Ministry of Agriculture, Taiwan; legal system page title and official source corroborated; local PDF metadata author is National Laws and Regulations Database',
  'official_url':OFFICIAL,'local_file':str(LEGAL.relative_to(ROOT)).replace('\\','/'),'source_sha256':LEGAL_SHA,
  'file_format':'PDF 1.7; 12 pages; searchable text; 65 article identifiers including inserted articles',
  'source_version':'Official page shows promulgation 1971-08-16 and last amendment 2016-11-09; local PDF page 1 matches title and amendment date; local PDF metadata modified 2025-01-22',
  'attribution':'農業部主管法規共用系統，動物用藥品管理法（修正日期：民國105年11月9日）',
  'usage_basis':{'type':'law_not_copyrightable','reference':'Taiwan Copyright Act Article 9(1)(1), official National Laws and Regulations Database','url':COPYRIGHT,'scope':'statutory text only; no site interface, commentary, images, editorial material, or linked annexes'},
  'approved_processing_scope':'Extract and index the plain statutory text by article for isolated local research RAG; attribute the official MOA law page.',
  'allowed_categories':['Medication / Law'],'excluded_categories':['Water Quality','Disease','Climate / Cold','Calculation','species-specific husbandry'],
  'prohibited_inferences':['specific product approval','specific fish species permission','drug dose','withdrawal period','current annex content'],
  'species_scope':'General legal scope; no species-specific drug use authorization inferred',
  'admission_execution_status':'admitted_scope_limited','corpus_inclusion_status':'retrieval_eligible_statutory_articles_only',
  'verification_evidence':{'local_title_revision_match':True,'official_current_page_revision':'2016-11-09','local_checksum_match':True,'article_count':len(articles),'exact_locator_type':'PDF page + article'},
  'caveat':'The linked Aquatic Animal Drug Use Standards Annex I has a 2025-01-08 update on the official site; the local 2019 PDF is stale and is excluded. This admission does not cover that annex.'
}
writej(OUT/'animal_drug_management_act_admission_record.json',approval)
writejl(OUT/'animal_drug_management_act_article_chunks.jsonl',articles)

# Preserve the six-file source build, then build a final isolated Corpus v3 including only verified statute text.
if not (OUT/'corpus_v3_initial_snapshot').exists(): shutil.copytree(INITIAL,OUT/'corpus_v3_initial_snapshot')
FINAL.mkdir(parents=True,exist_ok=True)
old_manifest=readj(INITIAL/'corpus_v3_manifest.json')
old_chunks=readjl(INITIAL/'corpus_chunks_v3.jsonl')
new_chunks=old_chunks+articles
chunks_path=FINAL/'corpus_chunks_v3_final.jsonl'
chunks_path.write_text(''.join(json.dumps(x,ensure_ascii=False,separators=(',',':'))+'\n' for x in new_chunks),encoding='utf-8')
db_path=FINAL/'corpus_v3_final.sqlite3'; shutil.copy2(INITIAL/'corpus_v3.sqlite3',db_path)
with sqlite3.connect(db_path) as con:
    con.execute('PRAGMA foreign_keys=ON')
    con.execute('INSERT INTO sources VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',(
      LEGAL_ID,'動物用藥品管理法','農業部',str(LEGAL.relative_to(ROOT)).replace('\\','/'),LEGAL_SHA,OFFICIAL,OFFICIAL,
      'statutory text; Taiwan Copyright Act Art. 9(1)(1)','Attribution to Ministry of Agriculture official law page',approval['source_version'],
      approval['approved_processing_scope'],1))
    for c in articles:
        meta={k:v for k,v in c.items() if k not in {'text','raw_fields'}}; meta['raw_fields']=c['raw_fields']
        con.execute('INSERT INTO chunks VALUES (?,?,?,?,?,?,?,?,?,?)',(
          c['chunk_id'],LEGAL_ID,LEGAL_SHA,c['source_version'],c['record_locator'],c['content_sha256'],c['text'],
          json.dumps(meta,ensure_ascii=False,separators=(',',':')),1,'statute_article'))
    token_re=re.compile(r'[a-z0-9]+(?:[./_%+\-][a-z0-9]+)*|[\u3400-\u9fff]+',re.I)
    def tok(text):
        out=[]
        for m in token_re.finditer(text.casefold()):
            t=m.group(0)
            out.extend([t] if re.fullmatch(r'[\u3400-\u9fff]+',t) and len(t)==1 else ([t[i:i+2] for i in range(len(t)-1)] if re.fullmatch(r'[\u3400-\u9fff]+',t) else [t]))
        return ' '.join(out)
    con.executemany('INSERT INTO chunks_fts(chunk_id,token_text) VALUES (?,?)',[(c['chunk_id'],tok(c['text'])) for c in articles])
    con.commit()

source_registry=readjl(REGISTRY)
if not any(x.get('source_id')==LEGAL_ID for x in source_registry):
    source_registry.append({
      'source_record_id':LEGAL_RECORD,'source_id':LEGAL_ID,'source_title':'動物用藥品管理法','publisher':'農業部','official_dataset_url':OFFICIAL,
      'resource_url':OFFICIAL,'local_file':str(LEGAL.relative_to(ROOT)).replace('\\','/'),'source_sha256':LEGAL_SHA,
      'license':'Taiwan Copyright Act Article 9(1)(1), statutory text only','license_url':COPYRIGHT,'attribution_required':True,
      'attribution_text':approval['attribution'],'publication_version':approval['source_version'],'source_version_status':'verified_for_statutory_body_only',
      'approved_usage_scope':approval['approved_processing_scope'],'prohibited_usage_scope':approval['prohibited_inferences'],
      'category_scope':['Medication / Law'],'species_scope':approval['species_scope'],'source_cluster_id':'MOA-ANIMAL-DRUG-LEGISLATION',
      'retrieval_default':True,'owner_decision':'APPROVED','source_admission_status':'admitted_scope_limited',
      'admission_execution_status':'admitted_scope_limited','corpus_v3_inclusion_status':'retrieval_eligible_statutory_articles_only',
      'existing_admission':False,'limitations':[approval['caveat']]
    })
writejl(OUT/'source_admission_registry_v3_final.jsonl',source_registry)

# Add the final source-specific result to the 57-record rights/version review without rewriting the original historical audit.
audits=readjl(AUDIT)
for row in audits:
    if row.get('source_record_id')==LEGAL_RECORD:
        row.update({'rights_status':'verified_statutory_text_only_under_copyright_act_art9','source_version':'official MOA current page last amendment 2016-11-09; local PDF title/date match; local file checksum verified','publisher':'Ministry of Agriculture official laws system; local PDF author field: National Laws and Regulations Database','species_scope_status':'general law only; no product/species-specific permission inferred','admission_execution_status':'admitted_scope_limited','corpus_v3_inclusion_status':'statutory articles only','blocker_reason':'No blocker for statutory text. Linked 2025 aquatic-drug annex is a separate source and remains excluded because local 2019 PDF is stale.'})
writejl(OUT/'source_rights_version_scope_audit_57_final.jsonl',audits)

# Append deterministic embeddings for the new statutory article chunks.
tags=requests.get(f'{OLLAMA}/api/tags',timeout=8).json().get('models',[])
match=next((m for m in tags if m.get('name')==BGE),None)
if not match or match.get('digest','').removeprefix('sha256:')!=BGE_DIGEST: raise RuntimeError('BGE model digest changed')
info=requests.post(f'{OLLAMA}/api/show',json={'model':BGE},timeout=30).json()
if info.get('model_info',{}).get('bert.embedding_length')!=1024: raise RuntimeError('BGE embedding dimension mismatch')
new_vectors=[]
for start in range(0,len(articles),24):
    texts=[x['text'] for x in articles[start:start+24]]
    r=requests.post(f'{OLLAMA}/api/embed',json={'model':BGE,'input':texts,'truncate':False,'keep_alive':'30m'},timeout=300); r.raise_for_status()
    a=np.asarray(r.json()['embeddings'],dtype=np.float32)
    if a.shape!=(len(texts),1024) or not np.isfinite(a).all(): raise RuntimeError('New article embeddings failed schema/dimension validation')
    norms=np.linalg.norm(a,axis=1,keepdims=True)
    if np.any(norms<=0): raise RuntimeError('Zero norm article embedding')
    new_vectors.append(a/norms)
old_count=old_manifest['retrieval_eligible_chunk_count']; old_vec_path=INITIAL/'dense_vectors.f32'
old_vectors=np.memmap(old_vec_path,dtype=np.float32,mode='r',shape=(old_count,1024))
all_vectors=np.vstack([np.asarray(old_vectors),*new_vectors]).astype(np.float32)
vector_path=FINAL/'dense_vectors_final.f32'; all_vectors.tofile(vector_path)
del old_vectors

db_count=sqlite3.connect(db_path).execute('select count(*) from chunks').fetchone()[0]
if db_count!=len(new_chunks): raise RuntimeError(f'SQLite count mismatch: {db_count} != {len(new_chunks)}')
eligible_count=sum(bool(c['retrieval_eligible']) for c in new_chunks)
context_count=len(new_chunks)-eligible_count
source_files=sorted(set(x['source_sha256'] for x in source_registry if x.get('corpus_v3_inclusion_status') in ('included','included_context_only','retrieval_eligible_statutory_articles_only')))
source_ids=sorted(set(x['source_id'] for x in source_registry if x.get('corpus_v3_inclusion_status') in ('included','included_context_only','retrieval_eligible_statutory_articles_only')))
manifest={**old_manifest}
manifest.update({'corpus_version':'research_corpus_v3_phase_u_20261018_final','created_at_utc':datetime.now(timezone.utc).isoformat(),
 'build_status':'BUILT_ISOLATED_LIMITED_SCOPE','formal_production_corpus':False,'source_matrix_record_count':57,'unique_source_files_by_sha256':55,
 'eligible_source_artifact_count':len(source_ids),'source_ids':source_ids,'source_sha256s':source_files,'total_chunk_count':len(new_chunks),
 'sqlite_chunk_count':db_count,'retrieval_eligible_chunk_count':eligible_count,'context_only_chunk_count':context_count,
 'chunk_jsonl_file':str(chunks_path.relative_to(ROOT)).replace('\\','/'),'chunk_jsonl_sha256':sha_file(chunks_path),
 'sqlite_path':str(db_path.relative_to(ROOT)).replace('\\','/'),'sqlite_sha256':sha_file(db_path),
 'embedding_index':{'status':'BUILT','model':BGE,'model_digest':BGE_DIGEST,'dimensions':1024,'normalization':'L2',
  'eligible_chunk_count':eligible_count,'context_only_not_embedded_count':context_count,'vector_file':str(vector_path.relative_to(ROOT)).replace('\\','/'),
  'vector_file_bytes':vector_path.stat().st_size,'vector_file_sha256':sha_file(vector_path),
  'matrix_row_order':'corpus_chunks_v3_final.jsonl filtered by retrieval_eligible; original six-source index order followed by Article-number order for MOA-FL014718-ACT',
  'matrix_order_ids_sha256':hashlib.sha256('\n'.join(c['chunk_id'] for c in new_chunks if c['retrieval_eligible']).encode()).hexdigest(),
  'model_architecture':info.get('model_info',{}).get('general.architecture'),'dimensions_verified':True},
 'reranker':{'model_id':'BAAI/bge-reranker-v2-m3','revision':'953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e','status':'loaded_and_passed_3_source_domain_smoke_tests','device':'cuda','max_sequence_length':512,'batch_size':4},
 'new_statutory_source':{'source_id':LEGAL_ID,'admitted_scope_limited':True,'article_chunks':len(articles),'scope':'general Medication / Law text only'},
 'source_admission_note':'57 Owner Decisions are approved; independent rights/version/applicability filters remain. The local 2019 Annex I PDF is excluded as stale versus the 2025-01-08 current official rule.'})
writej(FINAL/'corpus_v3_manifest.json',manifest)
print(json.dumps({'status':'BUILT_ISOLATED_LIMITED_SCOPE','article_chunks':len(articles),'total_chunks':len(new_chunks),'eligible_chunks':eligible_count,'context_only_chunks':context_count,'source_files':len(source_ids),'vector_sha256':manifest['embedding_index']['vector_file_sha256'],'sqlite_sha256':manifest['sqlite_sha256'],'legal_source_id':LEGAL_ID},ensure_ascii=True))
