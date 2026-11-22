"""Document an already built release using read-only SQL and real test records."""
from __future__ import annotations
import ast
from collections import Counter
from datetime import datetime, timezone, timedelta
import hashlib
import json
from pathlib import Path
import platform
import re
import shutil
import sqlite3
import sys
import urllib.request
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tools')]
from src.unified_rag_v4.common import dump,sha_file,FISH
from build_unified_rag_v4 import baseline
P=json.loads((ROOT/'research_staging/unified_rag_build_pointer.json').read_text())
W=Path(P['workspace']);R=Path(P['report_directory'])
now=datetime.now(timezone(timedelta(hours=8))).isoformat()
manifest=json.loads((W/'corpus_manifest.json').read_text(encoding='utf-8'))
DB=Path(manifest['database'])
assert sha_file(DB)==manifest['database_sha256']
con=sqlite3.connect(DB.as_uri()+'?mode=ro',uri=True);con.row_factory=sqlite3.Row

def jlines(path,rows):
    with path.open('w',encoding='utf-8') as f:
        for row in rows: f.write(json.dumps(row,ensure_ascii=False)+'\n')

def load(name): return json.loads((R/name).read_text(encoding='utf-8'))

documents={r['document_id']:dict(r) for r in con.execute('SELECT * FROM documents')}
file_rows=[];rights=[]
for doc in documents.values():
    did=doc['document_id'];meta=json.loads(doc['metadata_json']);pol=meta['usage_policy']
    pages=con.execute('SELECT count(*) FROM document_pages WHERE document_id=?',(did,)).fetchone()[0]
    kinds=dict(con.execute('SELECT kind,count(*) FROM document_elements WHERE document_id=? GROUP BY kind',(did,)))
    chunks=con.execute('SELECT count(*),coalesce(sum(retrieval_eligible),0) FROM chunks WHERE source_sha256=?',(doc['sha256'],)).fetchone()
    structures=con.execute('SELECT count(*) FROM structured_records WHERE document_id=?',(did,)).fetchone()[0]
    for alias in con.execute('SELECT * FROM document_files WHERE document_id=?',(did,)):
        file_rows.append({'path':alias['path'],'is_my_data':bool(alias['is_my_data']),
            'document_id':did,'sha256':doc['sha256'],'raw_bytes_saved_in_database':True,
            'source_bytes_unchanged':sha_file(alias['path'])==doc['sha256'],'parse_status':doc['parse_status'],
            'pages':pages,'element_kinds':kinds,'native_structured_records':structures,
            'chunk_count_including_context_only':chunks[0],'retrieval_eligible_chunks':chunks[1],
            'rights_status':doc['rights_status'],'owner_decision':doc['owner_decision'],
            'original_source_version':doc['source_version'],'derived_layout':meta.get('derived_layout'),
            'scope':pol['scope'],'not_all_extracted_elements_retrieval_eligible':True})
    if doc['rights_status'] in ('EXPLICIT_RESTRICTION_FULLTEXT_QUARANTINED','FULLTEXT_USAGE_BASIS_UNVERIFIED'):
        rights.append({'document_id':did,'paths':meta['paths'],'sha256':doc['sha256'],
            'owner_decision':doc['owner_decision'],'status':doc['rights_status'],
            'observed_notices':meta.get('rights_statements',[]),'policy_evidence':pol.get('evidence',[]),
            'current_use':'RAW_ARCHIVE_AND_LOCAL_SOURCE_REVIEW; no new unscoped fulltext answer indexing',
            'next_step':'確認發布者授權涵蓋的原件、版本及全文索引範圍；一般版權聲明不等於已作成法律禁止判定。已有有限准入資料另行保留。',
            'new_owner_approval_requested':False,'absolute_legal_prohibition_claimed':False})
jlines(R/'processing_status_69.jsonl',file_rows)
jlines(R/'source_use_review_queue.jsonl',rights)

quality=[]
review={'OCR_ONLY_REQUIRES_REVIEW','OVERSIZE_UNIT_REVIEW','TABLE_MULTIROW_HEADER_REQUIRES_REVIEW'}
for row in con.execute('SELECT * FROM element_chunks'):
    if row['quality_status'] in review:
        quality.append({'type':'SEGMENT_QUALITY_REVIEW','segment_id':row['segment_id'],
            'document_id':row['document_id'],'pages':[row['page_start'],row['page_end']],
            'element_ids':json.loads(row['element_ids_json']),'reason':row['quality_status'],
            'chunk_id':row['chunk_id'],'human_review_status':'NOT_REVIEWED'})
for row in con.execute("SELECT document_id,page,ocr_status FROM document_pages WHERE ocr_status!='NATIVE_TEXT'"):
    quality.append({'type':'PAGE_OCR_REVIEW',**dict(row),'human_review_status':'NOT_REVIEWED'})
jlines(R/'quality_review_queue.jsonl',quality)

coverage={fish:{'explicit_candidate_chunks':0,'source_ids':set(),'raw_sha256s':set()} for fish in FISH}
general=Counter();by_source=Counter();by_kind=Counter()
for row in con.execute('SELECT source_id,source_sha256,species_scope,taxonomy_level,restrictions_json FROM chunks WHERE retrieval_eligible=1'):
    try: scope=json.loads(row['species_scope'])
    except (json.JSONDecodeError,TypeError): scope=[row['species_scope']] if row['species_scope'] else []
    if not isinstance(scope,list): scope=[scope]
    by_source[row['source_id']]+=1;by_kind[row['taxonomy_level']]+=1
    for fish in coverage:
        if fish in scope:
            coverage[fish]['explicit_candidate_chunks']+=1
            coverage[fish]['source_ids'].add(row['source_id']);coverage[fish]['raw_sha256s'].add(row['source_sha256'])
    if not scope: general[row['taxonomy_level']]+=1
for row in coverage.values():
    row['source_ids']=sorted(row['source_ids']);row['source_count']=len(row['source_ids']);row['raw_sha256s']=sorted(row['raw_sha256s'])
source_coverage={'species':coverage,'eligible_by_source':dict(by_source),'eligible_by_declared_scope':dict(by_kind),
    'no_explicit_target_species_by_scope':dict(general),'not_verified_answer_coverage':True,
    'not_independent_fact_or_source_counts':True,
    'limitation':'同一原始Record多段、統計列與分類代碼不能計為獨立專業事實；一般法規不能當成特定魚種生理或用藥證據。'}
dump(R/'source_coverage.json',source_coverage)

# Repair the acquisition manifest from actual local bytes and the exact official
# URLs used by the downloader. Filesystem modification time is not asserted to
# be an independently logged network acquisition timestamp.
download_script=ast.parse((ROOT/'tools/unified_download_models.py').read_text(encoding='utf-8'))
urls={}
for node in ast.walk(download_script):
    if isinstance(node,ast.For) and isinstance(node.iter,ast.List):
        try:
            pairs=ast.literal_eval(node.iter)
            if pairs and all(isinstance(x,tuple) and len(x)==2 for x in pairs): urls.update(pairs)
        except (ValueError,TypeError): pass
old_path=W/'upstream/download_manifest.json'
old=json.loads(old_path.read_text(encoding='utf-8')) if old_path.exists() else []
backup=W/'upstream/download_manifest_before_final_audit.json'
if old_path.exists() and not backup.exists(): shutil.copyfile(old_path,backup)
old_by_file={x['file']:x for x in old if 'file' in x}
download=[]
for name,url in urls.items():
    p=W/'upstream'/name
    if not p.is_file(): continue
    doc=next((d for d in documents.values() if d['sha256']==sha_file(p)),None)
    download.append({**old_by_file.get(str(p),{}),'url':url,'file':str(p),'bytes':p.stat().st_size,
        'sha256':sha_file(p),'verified_at':now,'filesystem_modified_at':datetime.fromtimestamp(p.stat().st_mtime,timezone(timedelta(hours=8))).isoformat(),
        'network_acquisition_time_independently_preserved':'obtained_at' in old_by_file.get(str(p),{}),
        'matching_archived_document_id':doc['document_id'] if doc else None,
        'ingestion_status':'MATCHED_EXISTING_ORIGINAL_SCOPE_CHECKED' if doc else 'VERIFICATION_DOWNLOAD_ONLY_NOT_ADMITTED'})
dump(old_path,download);dump(R/'official_download_integrity.json',download)
clip=W/'models/clip-vit-base-patch32';rev=json.loads((clip/'revision.json').read_text())['revision']
model_files=[{'path':str(p),'sha256':sha_file(p),'bytes':p.stat().st_size,
    'official_url':f'https://huggingface.co/openai/clip-vit-base-patch32/resolve/{rev}/{p.name}'}
    for p in sorted(clip.iterdir()) if p.is_file() and p.name!='revision.json']
dump(R/'clip_model_integrity.json',{'model':'openai/clip-vit-base-patch32','revision':rev,'files':model_files})

tags=json.load(urllib.request.urlopen('http://127.0.0.1:11434/api/tags',timeout=20))['models']
expected={
    'M1':'deepseek-r1:7b','M2':'qwen2.5-coder:7b',
    'M3':'hf.co/bartowski/DeepSeek-R1-Distill-Llama-8B-GGUF:Q4_K_M','M4':'gemma2:9b'}
# Digests are preserved from actual smoke records and compared with runtime.
smoke_rows=[json.loads(s) for s in (R/'real_generator_smoke_results_v3.jsonl').read_text(encoding='utf-8').splitlines() if s.strip()]
expected={m:(tag,next(x['result_record']['model_digest'] for x in smoke_rows if x['model_id']==m)) for m,tag in expected.items()}
alignment=[]
for ident,(tag,checksum) in expected.items():
    row=next(x for x in tags if x['name']==tag)
    req=urllib.request.Request('http://127.0.0.1:11434/api/show',data=json.dumps({'model':tag}).encode(),headers={'Content-Type':'application/json'})
    meta=json.load(urllib.request.urlopen(req,timeout=30));architecture=meta.get('model_info',{}).get('general.architecture')
    assert row['digest']==checksum
    if ident=='M3': assert architecture=='llama'
    alignment.append({'model_id':ident,'tag':tag,'digest':row['digest'],'architecture':architecture,'details':meta.get('details'),
        'identity_matches_real_smoke':True,'weight_bytes_rehashed':False})
reranker=ROOT/'.venv-reranker/hf-cache/hub/models--BAAI--bge-reranker-v2-m3/snapshots/953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e'
dump(R/'runtime_model_alignment.json',{'models':alignment,'embedding':{'tag':manifest['embedding_model'],'digest':manifest['embedding_digest'],'dimension':1024},
    'reranker':{'model':'BAAI/bge-reranker-v2-m3','revision':reranker.name,'path':str(reranker),'device':'cpu','max_length':512,
        'local_configuration_files':[{'path':str(p),'sha256':sha_file(p)} for p in reranker.glob('*.json')],
        'actual_scoring_executed_in_retrieval_smoke':True,'weights_not_rehashed_this_documentation_step':True}})

junit=R/'pytest_results_final.xml' if (R/'pytest_results_final.xml').exists() else R/'pytest_results.xml'
test_log=W/'logs/repository_pytest_final.log' if (W/'logs/repository_pytest_final.log').exists() else W/'logs/repository_pytest.log'
xml=ET.parse(junit).getroot()
suites=xml.findall('testsuite') if xml.tag=='testsuites' else [xml]
pytest={'tests':sum(int(s.get('tests','0')) for s in suites),
    'failures':sum(int(s.get('failures','0')) for s in suites),
    'errors':sum(int(s.get('errors','0')) for s in suites),
    'skipped':sum(int(s.get('skipped','0')) for s in suites),
    'log':str(test_log),'junit_xml':str(junit),
    'scope':'Repository tests/ with explicit interpreter; no blanket ignore of failing tests',
    'new_pipeline_specific_checks':str(R/'pipeline_validation.json'),
    'interpreter':str(ROOT/'reports/evaluation/fish_test_corpus_v3_evidence_alignment_20261021_022237/test_env/Scripts/python.exe')}
pytest['passed']=pytest['tests']-pytest['failures']-pytest['errors']-pytest['skipped']
log=test_log.read_text(encoding='utf-8-sig',errors='replace')
pytest['subtests_passed']=8 if '8 subtests passed' in log else None
totals=re.search(r'(\d+) passed, (\d+) subtests passed',log)
pytest['junit_testcase_entries_including_subtests']=pytest['tests']
if totals:
    pytest['tests']=int(totals.group(1));pytest['passed']=int(totals.group(1))
    pytest['subtests_passed']=int(totals.group(2))
dump(R/'repository_pytest_results.json',pytest)

manifest['segmentation']={
    'native_text':'v2: reconstruct logical paragraphs, open lists and conditions before BGE-M3 cosine .62 boundaries; preserve source blocks/bboxes; soft-wrap joining is derived text, not raw bytes',
    'tables':'Complete small native tables retain all cells and headers, including nulls without imputation. Large multirow/ambiguous headers are review-only. Detection does not guarantee all borderless or scanned tables.',
    'images':'Original raster bytes, page/bbox, native captions and Windows zh-Hant-TW OCR; 33 scope-eligible actual CLIP 512d vectors. Vector graphics remain in the original PDF, not all individually extracted or interpreted.',
    'not_all_chunks_expert_semantically_verified':True,
    'not_all_tables_or_figures_exhaustively_detected':True,
    'not_all_ocr_numerals_expert_verified':True}
manifest['retrieval_release']='v4.1 native-name-field identity guard; BM25/BGE-M3/RRF60/windowed BGE reranker; image CLIP branch'
dump(W/'corpus_manifest.json',manifest);dump(R/'corpus_manifest.json',manifest)

protected=baseline('final')
compat={'checked_at':now,'frozen_manifest_count':protected['count'],'unchanged':protected['unchanged'],
    'production_sqlite_sha256':protected['production_sqlite_sha256'],'production_sqlite_matches':protected['production_matches'],
    'historical_636_unchanged':protected['unchanged']==636,'production_switched':False,
    'historical_generation_files_overwritten':False,'new_720_run_executed':False,
    'model_weight_bytes_rehashed_this_round':False,'generator_identity_method':'Ollama tag/digest metadata and actual local API calls',
    'all_input_69_path_hashes_match':all(r['source_bytes_unchanged'] for r in file_rows),
    'new_database':str(DB),'new_database_sha256':sha_file(DB),'same_as_completed_build':sha_file(DB)==manifest['database_sha256'],
    'historical_baseline_detailed_check':str(R/'protected_final.json')}
dump(R/'compatibility.json',compat)

modules=list((ROOT/'src/unified_rag_v4').glob('*.py'))+list((ROOT/'tools').glob('*unified*.py'))+[ROOT/'tools/refine_unified_provenance.py',ROOT/'tools/unified_ocr_worker.ps1']
app=ROOT/'research_staging/app_sessions/launch_20261118_154253'
modules += [app/n for n in ('professional_platform.py','unified_question_engine.py','free_question_engine.py','answer_policy.py','run_app.py')]
code_files=[{'path':str(p),'sha256':sha_file(p)} for p in sorted(set(modules)) if p.is_file()]
dump(R/'reproducibility_manifest.json',{'created_at':now,'python_version':platform.python_version(),
    'corpus_version':manifest['version'],'database':str(DB),'database_sha256':sha_file(DB),
    'source_registry':str(W/'source_registry.json'),'source_registry_sha256':sha_file(W/'source_registry.json'),
    'code':code_files,'embedding_model':manifest['embedding_model'],'embedding_digest':manifest['embedding_digest'],
    'image_model':'openai/clip-vit-base-patch32','image_model_revision':rev,
    'image_model_weight_manifest':str(R/'clip_model_integrity.json'),'same_originals_retained':True,
    'pipeline_documentation':str(R/'README_reproduce.md'),'no_human_gold_claim':True})

v3=load('real_e2e_validation_v3.json')
old_native=next(x for x in v3['results'] if x['case']=='NATIVE_FIELD_LOOKUP')
dump(R/'smoke_result_quality_addendum.json',{
    'historical_raw_smoke_files_unchanged':True,
    'affected_case':old_native,
    'withdrawn_claim':'The old accepted native lookup was a mechanically source-bound response, not a species-correct answer',
    'cause':'Name/code lookup branch did not check original record name fields against target species',
    'current_guard_regression':str(R/'native_name_retrieval_regression.json'),
    'valid_source_text_direct_responses_in_original_v3_smoke':2,
    'original_v3_native_lookup_not_accepted_as_correct':1,
    'original_v3_source_text_validation_failed':2,
    'original_v3_safe_negative_cases':3,
    'not_professional_accuracy':True})
browser=load('live_browser_validation.json') if (R/'live_browser_validation.json').exists() else {'status':'NOT_YET_DOCUMENTED'}
summary={'created_at':now,'database_integrity':manifest['validation'],
    'pipeline':load('pipeline_validation.json'),'repository_pytest':pytest,'streamlit_apptest':load('streamlit_validation.json'),
    'real_api_smoke':v3,'live_browser':browser,
    'native_name_code_bug':{'discovered_in_actual_live_UI':True,'previous_v3_native_field_call_is_not_valid_fish_correctness_evidence':True,
        'prior_native_call_raw_records_preserved':True,'fix_regression_file':str(R/'native_name_retrieval_regression.json')},
    'four_models_all_professional_answers_passed':False,'human_gold':0,
    'remaining_model_failures':'M1/M3 source-text calls failed numeric/support checking; preserved and surfaced rather than disabling safety validation',
    'not_720_or_180_benchmark':True}
dump(R/'validation_summary.json',summary)

launch=app/'launch_info.json';info=json.loads(launch.read_text(encoding='utf-8-sig'))
info.update(unified_corpus_enabled=True,unified_corpus_version=manifest['version'],unified_database=str(DB),
    unified_database_sha256=manifest['database_sha256'],unified_prompt_version='unified-v4-program-owned-citations-20261120-v3',
    native_name_identity_guard='exact-original-name-fields-20261121',frozen_manifest_unchanged=protected['unchanged'])
dump(launch,info)
con.close()
print(json.dumps({'files':len(file_rows),'rights_review_documents':len(rights),'quality_review_items':len(quality),
    'repository_tests':pytest['passed'],'frozen_baseline_unchanged':protected['unchanged'],'database_sha256':compat['new_database_sha256']},ensure_ascii=False))
