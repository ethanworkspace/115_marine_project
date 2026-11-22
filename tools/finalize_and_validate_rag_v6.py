"""Freeze only the completed successor; preserve all old databases and inputs."""
from __future__ import annotations
import ast,collections,html,json,sqlite3,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tools')]
import complete_and_catalog_rag_v6 as build
from src.unified_rag_v4.common import tokens


def main():
    w,r,cfg=build.paths();c=build.connect();checks={}
    checks['sqlite_integrity']=c.execute('PRAGMA integrity_check').fetchone()[0]
    checks['foreign_key_errors']=[list(x) for x in c.execute('PRAGMA foreign_key_check')]
    checks['missing_text_vectors']=c.execute('SELECT count(*) FROM archive_units u LEFT JOIN embedding_cache e USING(content_sha256) WHERE e.content_sha256 IS NULL').fetchone()[0]
    checks['bad_text_dimensions']=c.execute('SELECT count(*) FROM embedding_cache WHERE dimension!=1024 OR length(embedding)!=4096').fetchone()[0]
    checks['missing_image_vectors']=c.execute('SELECT count(*) FROM media_assets a LEFT JOIN image_embeddings e USING(asset_id) WHERE e.asset_id IS NULL').fetchone()[0]
    checks['bad_image_dimensions']=c.execute('SELECT count(*) FROM image_embeddings WHERE dimension!=512 OR length(embedding)!=2048').fetchone()[0]
    checks['legacy_files_without_vector']=c.execute('SELECT count(*) FROM media_files f LEFT JOIN image_embeddings v USING(asset_id) WHERE v.asset_id IS NULL').fetchone()[0]
    checks['legacy_files_without_source']=c.execute("SELECT count(*) FROM media_files WHERE document_id IS NULL OR page IS NULL OR mapping_status!='ORIGINAL_FILENAME_IDENTITY_AND_PAGE_RANGE'").fetchone()[0]
    checks['legacy_file_asset_sha_mismatches']=c.execute('SELECT count(*) FROM media_files f JOIN media_assets a USING(asset_id) WHERE f.sha256!=a.sha256').fetchone()[0]
    # UNINDEXED identifiers in FTS virtual tables cannot support a normal SQL
    # left-join lookup. Materialize once, avoiding a quadratic scan.
    archive_ids={x[0] for x in c.execute('SELECT unit_id FROM archive_units')}
    archive_fts_ids={x[0] for x in c.execute('SELECT unit_id FROM semantic_archive_fts')}
    eligible_ids={x[0] for x in c.execute('SELECT chunk_id FROM chunks WHERE retrieval_eligible=1')}
    answer_fts_ids={x[0] for x in c.execute('SELECT chunk_id FROM unified_fts')}
    checks['archive_fts_missing']=len(archive_ids-archive_fts_ids)
    checks['eligible_fts_missing']=len(eligible_ids-answer_fts_ids)
    checks['fts_contains_ineligible']=len(answer_fts_ids-eligible_ids)
    build.emit({'stage':'vector_and_fts_integrity_checked'})
    checks['tables_without_native_cells']=sum('cells' not in json.loads(x[0]) for x in c.execute("SELECT metadata_json FROM document_elements WHERE kind='TABLE'"))
    checks['media_catalog_missing_paths']=sum(not Path(x[0]).is_file() for x in c.execute('SELECT path FROM media_assets'))
    checks['original_file_hash_errors']=[]
    for row in c.execute('SELECT path,sha256 FROM document_files'):
        if not Path(row['path']).is_file() or build.sha(row['path'])!=row['sha256']:checks['original_file_hash_errors'].append(row['path'])
    checks['source_registry_missing_paths']=[row['source_id'] for row in c.execute('SELECT source_id,source_file FROM sources') if not row['source_file'] or not Path(row['source_file']).is_file()]
    checks['parent_v5_unchanged']=build.sha(cfg['parent_database'])==cfg['parent_database_sha256']
    checks['documents_without_vector']=c.execute('SELECT count(*) FROM documents d WHERE NOT EXISTS(SELECT 1 FROM archive_units u JOIN embedding_cache v USING(content_sha256) WHERE u.document_id=d.document_id) AND NOT EXISTS(SELECT 1 FROM document_elements e JOIN image_embeddings v USING(asset_id) WHERE e.document_id=d.document_id)').fetchone()[0]
    zero=[k for k in checks if k not in ('sqlite_integrity','parent_v5_unchanged')]
    passed=checks['sqlite_integrity']=='ok' and checks['parent_v5_unchanged'] and all(not checks[k] for k in zero)
    build.dump(r/'all_document_media_integrity.json',{'checks':checks,'passed':passed,'media_file_hashes_checked_during_copy':True,'not_professional_content_accuracy':True})
    if not passed:raise RuntimeError('New source/media integrity failed; website pointer is unchanged: '+json.dumps(checks,ensure_ascii=False))
    counts={t:c.execute('SELECT count(*) FROM '+t).fetchone()[0] for t in ('documents','document_files','document_pages','document_elements','element_chunks','media_assets','image_embeddings','sources','source_records','chunks','archive_units','semantic_archive_fts','embedding_cache','media_files','catalog_documents','catalog_assets')}
    counts.update(retrieval_eligible=c.execute('SELECT count(*) FROM chunks WHERE retrieval_eligible=1').fetchone()[0],context_only=c.execute('SELECT count(*) FROM chunks WHERE retrieval_eligible=0').fetchone()[0],distinct_text_vectors_used=c.execute('SELECT count(DISTINCT content_sha256) FROM archive_units').fetchone()[0],my_data_paths=c.execute('SELECT count(*) FROM document_files WHERE is_my_data=1').fetchone()[0],all_documents_with_vectors=counts['documents'],semantic_boundary_decisions=c.execute('SELECT count(*) FROM semantic_boundaries WHERE cosine IS NOT NULL').fetchone()[0])
    counts['element_kinds']=dict(c.execute('SELECT kind,count(*) FROM document_elements GROUP BY kind'))
    counts['ocr_status']=dict(c.execute('SELECT ocr_status,count(*) FROM media_assets GROUP BY ocr_status'))
    parent=build.read(Path(cfg['parent_database']).parent/'corpus_manifest.json')
    manifest={**parent,**cfg,'database':str(w/cfg['database_filename']),'counts':counts,'source_catalog_directory':cfg['source_catalog_directory'],'all_document_integrity':checks,'legacy_media_complete':True,'no_expert_visual_or_table_accuracy_claim':True,'parent_corpus_version':parent['version'],'segmentation':parent['segmentation'],'not_a_new_720_evaluation':True}
    for section in ('document_rights_status','parse_status','segmentation_quality'):
        table,col=('documents','rights_status') if section=='document_rights_status' else ('documents','parse_status') if section=='parse_status' else ('element_chunks','quality_status')
        counts[section]=dict(c.execute('SELECT '+col+',count(*) FROM '+table+' GROUP BY '+col))
    sources=[dict(x) for x in c.execute('SELECT * FROM sources')]
    build.dump(w/'source_registry.json',sources);build.dump(r/'source_registry.json',sources)
    build.dump(r/'processing_method.json',{'existing_text_units':'Preserved source paragraph/list/condition and BGE semantic-boundary segments; law articles remain atomic; no rewording of source data','recovered_images':'Every original media file bound to exact source document name and checked physical page; raw bytes and hashes retained; no bounding box guessed','image_ocr':'Actual Windows Traditional Chinese OCR, source-bound punctuation/paragraph units, quality flags retained; not expert interpretation','table_export':'Native cells, blank/null distinctions, headers, footnote candidates, bbox and page preserved in JSON; CSV is a view, not authoritative reconstruction','long_embeddings':'Full-text overlapping windows; original source retained; no silent truncation','no_fish_or_numeric_guessing':True,'image_vectors':'Actual pinned CLIP 512d vectors; similarity does not qualify professional evidence','text_vectors':'Actual pinned BGE-M3 1024d vectors','old_indexes_unchanged':True})
    c.close();manifest['database_sha256']=build.sha(w/cfg['database_filename'])
    build.dump(w/'corpus_manifest.json',manifest);build.dump(r/'corpus_manifest.json',manifest)
    x=build.hook();x.b.baseline('after')
    protected=build.read(r/'protected_after.json')
    build.dump(r/'compatibility.json',{'checked_at':build.now(),'frozen_manifest_count':protected['count'],'unchanged':protected['unchanged'],'production_sqlite_sha256':protected['production_sqlite_sha256'],'parent_v5_unchanged':checks['parent_v5_unchanged'],'current_database_sha256':manifest['database_sha256'],'production_switched':False,'old_720_results_modified':False,'new_720_run':False,'originals_moved_or_deleted':False})
    build.dump(w/'release_frozen.json',{'version':cfg['version'],'database':manifest['database'],'database_sha256':manifest['database_sha256'],'released_at':build.now(),'versioned_successor_required_for_changes':True})
    for p in (ROOT/'src/unified_rag_v6').glob('*.py'):ast.parse(p.read_text(encoding='utf-8'))
    build.emit({'passed':True,'counts':counts,'database_sha256':manifest['database_sha256'],'frozen_unchanged':protected['unchanged']})


if __name__=='__main__':main()
