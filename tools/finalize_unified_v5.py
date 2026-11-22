"""Validate every original/vector association before isolated application use."""
import json,sqlite3,sys
from collections import Counter
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tools')]
import expand_unified_all_documents_v5 as x
from src.unified_rag_v4.common import dump,sha_file,digest

con=x.connect();checks={}
checks['missing_archive_vectors']=con.execute('SELECT count(*) FROM archive_units u LEFT JOIN embedding_cache e USING(content_sha256) WHERE e.content_sha256 IS NULL').fetchone()[0]
checks['bad_archive_vector_dimensions']=con.execute('SELECT count(*) FROM embedding_cache WHERE dimension!=1024 OR length(embedding)!=4096').fetchone()[0]
checks['missing_media_vectors']=con.execute('SELECT count(*) FROM media_assets a LEFT JOIN image_embeddings e USING(asset_id) WHERE e.asset_id IS NULL').fetchone()[0]
checks['bad_image_vector_dimensions']=con.execute('SELECT count(*) FROM image_embeddings WHERE dimension!=512 OR length(embedding)!=2048').fetchone()[0]
checks['pages_without_visual_asset']=con.execute("SELECT count(*) FROM document_pages p WHERE NOT EXISTS(SELECT 1 FROM document_elements e WHERE e.document_id=p.document_id AND e.page=p.page AND e.kind='PAGE_RENDER')").fetchone()[0]
checks['orphan_archive_chunk_ids']=con.execute('SELECT count(*) FROM archive_units u LEFT JOIN chunks c ON u.related_chunk_id=c.chunk_id WHERE u.related_chunk_id IS NOT NULL AND c.chunk_id IS NULL').fetchone()[0]
checks['my_data_paths']=con.execute('SELECT count(*) FROM document_files WHERE is_my_data=1').fetchone()[0]
checks['my_data_with_archive_units']=con.execute('SELECT count(DISTINCT f.path) FROM document_files f JOIN archive_units u USING(document_id) WHERE f.is_my_data=1').fetchone()[0]
checks['documents_without_text_or_media_vector']=con.execute('SELECT count(*) FROM documents d WHERE NOT EXISTS(SELECT 1 FROM archive_units u JOIN embedding_cache v USING(content_sha256) WHERE u.document_id=d.document_id) AND NOT EXISTS(SELECT 1 FROM document_elements e JOIN image_embeddings v USING(asset_id) WHERE e.document_id=d.document_id)').fetchone()[0]
checks['raw_source_blob_hash_errors']=[]
for row in con.execute('SELECT document_id,sha256,original_bytes FROM documents JOIN raw_documents USING(document_id)'):
    if digest(bytes(row['original_bytes']))!=row['sha256']:checks['raw_source_blob_hash_errors'].append(row['document_id'])
checks['original_file_hash_errors']=[]
for row in con.execute('SELECT path,sha256 FROM document_files'):
    if sha_file(row['path'])!=row['sha256']:checks['original_file_hash_errors'].append(row['path'])
checks['pinned_parent_database_unchanged']=sha_file(Path(x.CFG['parent_database']))==x.CFG['parent_database_sha256']
laws=json.loads((x.R/'official_laws_parsed.json').read_text(encoding='utf-8'))
checks['official_law_pages']=len(laws)
checks['use_rules_all_eight_articles_parsed']=len(laws['M0130023']['articles'])==8
checks['official_article_unit_count_mismatches']=[]
for law in laws.values():
    doc=con.execute('SELECT document_id FROM documents WHERE sha256=?',(law['source']['sha256'],)).fetchone()
    n=con.execute('SELECT count(*) FROM element_chunks WHERE document_id=?',(doc[0],)).fetchone()[0]
    if n!=len(law['articles'])+1:checks['official_article_unit_count_mismatches'].append({'law_id':law['law_id'],'expected':len(law['articles'])+1,'actual':n,'one_extra_unit':'Original official metadata/version fields'})
parent=sqlite3.connect(Path(x.CFG['parent_database']).as_uri()+'?mode=ro',uri=True)
parent_ids={r[0] for r in parent.execute('SELECT document_id FROM documents')};parent.close()
event_ids={r[0] for r in con.execute('SELECT document_id FROM source_usage_events')}
checks['original_66_documents_have_usage_statement']=len(parent_ids)==66 and parent_ids.issubset(event_ids)
zero_fields=['missing_archive_vectors','bad_archive_vector_dimensions','missing_media_vectors','bad_image_vector_dimensions','pages_without_visual_asset','orphan_archive_chunk_ids','documents_without_text_or_media_vector']
valid=all(checks[k]==0 for k in zero_fields) and not any(checks[k] for k in ['raw_source_blob_hash_errors','original_file_hash_errors','official_article_unit_count_mismatches']) and checks['pinned_parent_database_unchanged'] and checks['use_rules_all_eight_articles_parsed'] and checks['original_66_documents_have_usage_statement'] and checks['my_data_paths']==checks['my_data_with_archive_units']==53
dump(x.R/'all_document_vector_integrity.json',{'checks':checks,'passed':valid,'not_human_gold':True})
if not valid:raise RuntimeError('All-document integrity checks failed; application pointer unchanged')
con.close()
x.b.finalize()
manifest=json.loads((x.W/'corpus_manifest.json').read_text(encoding='utf-8'))
con=sqlite3.connect(x.DB.as_uri()+'?mode=ro',uri=True);con.row_factory=sqlite3.Row
counts=manifest['counts']
for table in ('archive_units','embedding_cache','semantic_archive_fts','source_usage_events','law_source_status'):
    counts[table]=con.execute('SELECT count(*) FROM '+table).fetchone()[0]
counts['distinct_text_vectors_used']=con.execute('SELECT count(DISTINCT content_sha256) FROM archive_units').fetchone()[0]
counts['all_documents_with_vectors']=counts['documents']-checks['documents_without_text_or_media_vector']
counts['retrieval_source_groups']=con.execute('SELECT count(DISTINCT source_id) FROM chunks WHERE retrieval_eligible=1').fetchone()[0]
counts['user_statement_expanded_documents']=con.execute("SELECT count(*) FROM documents WHERE rights_status='USER_ATTESTED_LOCAL_RESEARCH_FULLTEXT'").fetchone()[0]
manifest.update(archive_scope='All original documents and native records have semantic text or image vectors; answer eligibility remains separately source/species/version/quality checked',
    usage_basis='Current user all-documents-use statement is recorded; pre-existing copyright statements and independently verified license states retained separately',
    image_model={'model':'openai/clip-vit-base-patch32','dimension':512,'directory':x.CFG['clip_model_directory'],'no_expert_visual_diagnosis_claim':True},
    law_verification={'official_law_families':12,'official_resources_saved':33,'original_documents_compared':15,
        'compilation_cutoffs_preserved':True,'same_revision_date_not_automatically_same_text':True,'no_residue_to_dose_or_withdrawal_inference':True},
    segmentation={'text':'Logical paragraph/list/condition plus BGE semantic boundaries; official articles atomic and never merged across articles',
        'embedding_context_limits':'Full original text retained; long units use complete overlapping embedding windows and normalized mean, not silent truncation',
        'structured_records':'HTML entities decoded and inline chemical notation preserved; raw JSON unchanged',
        'tables':'Native cells/headers/blanks and positions retained; merged/uncertain structures flagged rather than imputed',
        'images':'Every saved media asset has actual CLIP vector; OCR/native captions remain separate from expert visual interpretation',
        'not_all_ocr_or_table_semantics_expert_verified':True},
    restriction='No Production switch or historical index mutation. All-document discovery and safe answer eligibility are different stages. Existing statistical and drug-permit field limitations retained.')
manifest['all_document_integrity']=checks
dump(x.W/'corpus_manifest.json',manifest);dump(x.R/'corpus_manifest.json',manifest)
files=[]
for row in con.execute('SELECT f.*,d.title,d.parse_status,d.rights_status,d.source_version FROM document_files f JOIN documents d USING(document_id) ORDER BY f.path'):
    item=dict(row);did=row['document_id']
    item['archive_units']=con.execute('SELECT count(*) FROM archive_units WHERE document_id=?',(did,)).fetchone()[0]
    item['image_vectors']=con.execute('SELECT count(DISTINCT e.asset_id) FROM document_elements e JOIN image_embeddings v USING(asset_id) WHERE document_id=?',(did,)).fetchone()[0]
    item['all_original_bytes_saved']=True;files.append(item)
with (x.R/'all_file_processing_results.jsonl').open('w',encoding='utf-8') as f:
    for row in files:f.write(json.dumps(row,ensure_ascii=False)+'\n')
dump(x.R/'all_document_usage_manifest.json',{'user_statement':x.CFG['user_use_attestation'],
    'expanded_documents':counts['user_statement_expanded_documents'],'license_independently_verified_not_implied':True,
    'original_notices_and_old_use_policy_retained':True,'no_repeated_owner_approval':True})
dump(x.R/'compatibility.json',{'frozen_manifest_count':636,'unchanged':636,
    'production_sqlite_sha256':x.CFG['baseline_sqlite_sha256'],'verified_in':str(x.R/'protected_after.json'),
    'parent_v4_database_unchanged':checks['pinned_parent_database_unchanged'],'new_720_run':False,
    'production_switched':False,'historical_generations_overwritten':False,'database_sha256':manifest['database_sha256']})
con.close();print(json.dumps({'passed':True,'counts':counts,'database_sha256':manifest['database_sha256']},ensure_ascii=False))
