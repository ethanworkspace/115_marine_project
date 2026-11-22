"""Use printed front-matter subjects, never filenames, for missing source scope."""
import json,re,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tools')]
import expand_unified_all_documents_v5 as x
from src.unified_rag_v4.common import species,tokens,dump,FISH

con=x.connect();out=[]
for doc in con.execute('SELECT * FROM documents').fetchall():
    if con.execute('SELECT 1 FROM law_source_status WHERE document_id=?',(doc['document_id'],)).fetchone():continue
    meta=json.loads(doc['metadata_json']);subjects=[]
    pages=con.execute('SELECT page,cleaned_text FROM document_pages WHERE document_id=? AND page<=6 ORDER BY page',(doc['document_id'],)).fetchall()
    for page in pages:
        for line in page['cleaned_text'].splitlines():
            line=line.strip()
            if len(line)>100 or not any(term in line for term in ('養殖','培育','養成','生物安全')):continue
            found=species(line)
            if found:subjects.append({'physical_page':page['page'],'exact_source_line':line,'species':found})
    canonical={s for row in subjects for s in row['species'] if s in FISH}
    scope=list(dict.fromkeys(s for row in subjects for s in row['species'])) if len(canonical)==1 else []
    draft=any('文字初稿' in page['cleaned_text'] for page in pages)
    if subjects:meta['printed_subject_evidence']=subjects
    if draft:meta['document_variant']='EXPLICIT_PRINTED_DRAFT_NOT_DEFAULT_ANSWER_SOURCE'
    con.execute('UPDATE documents SET metadata_json=? WHERE document_id=?',(json.dumps(meta,ensure_ascii=False),doc['document_id']))
    changed=[]
    for row in con.execute('SELECT * FROM chunks WHERE source_sha256=?',(doc['sha256'],)).fetchall():
        restrictions=json.loads(row['restrictions_json']);old=row['retrieval_eligible'];eligible=old
        if draft:
            eligible=0;restrictions['source_draft_warning']=True
        elif scope and restrictions.get('scope_kind')=='SPECIES_SCOPE_UNKNOWN':
            restrictions['scope_kind']='SPECIES_EXPLICIT';restrictions['printed_subject_evidence']=subjects
            quality=restrictions.get('quality');eligible=int(quality not in ('OVERSIZE_UNIT_REVIEW','TABLE_MULTIROW_HEADER_REQUIRES_REVIEW','OCR_ONLY_REQUIRES_REVIEW') and not restrictions.get('historical_treatment_quarantined') and not restrictions.get('third_party_credit') and len(row['text'])>=20)
            con.execute('UPDATE chunks SET species_scope=?,taxonomy_level=? WHERE chunk_id=?',(json.dumps(scope,ensure_ascii=False),'SPECIES_EXPLICIT',row['chunk_id']))
        con.execute('UPDATE chunks SET retrieval_eligible=?,retrieval_status=?,restrictions_json=? WHERE chunk_id=?',(eligible,'RETRIEVAL_ELIGIBLE' if eligible else 'CONTEXT_ONLY',json.dumps(restrictions,ensure_ascii=False),row['chunk_id']))
        if eligible!=old:changed.append({'chunk_id':row['chunk_id'],'previous':old,'current':eligible})
    if subjects or draft:out.append({'document_id':doc['document_id'],'printed_subject_evidence':subjects,'inheritance_only_if_one_canonical_subject':scope,'explicit_draft':draft,'changed_chunks':changed,'not_answer_support_verification':True})
    con.commit()
con.execute('DELETE FROM unified_fts')
for row in con.execute('SELECT chunk_id,text FROM chunks WHERE retrieval_eligible=1').fetchall():con.execute('INSERT INTO unified_fts VALUES(?,?)',(row['chunk_id'],tokens(row['text'])))
con.execute('INSERT OR REPLACE INTO answer_eligibility SELECT chunk_id,retrieval_eligible,? FROM chunks',('QUALITY_SPECIES_AND_SOURCE_VERSION_GATE; archive discovery is separate',))
con.commit();con.close();dump(x.R/'printed_source_scope_refinement.json',out)
print(json.dumps({'sources_with_printed_subject_or_draft':len(out),'answer_eligibility_changes':sum(len(r['changed_chunks']) for r in out)}))
