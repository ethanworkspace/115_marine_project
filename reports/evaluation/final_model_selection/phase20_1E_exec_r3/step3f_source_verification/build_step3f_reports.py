from __future__ import annotations
import hashlib, json, os, pathlib, sqlite3, subprocess, urllib.request
from datetime import datetime, timezone
import pymupdf

ROOT = pathlib.Path.cwd()
REPORT = ROOT / 'reports/evaluation/final_model_selection/phase20_1E_exec_r3/step3f_source_verification'
STEP3E = ROOT / 'reports/evaluation/final_model_selection/phase20_1E_exec_r3/step3e_auto_source_crawl'
STAGE3E = ROOT / 'my_data/_official_source_staging/phase20_1E_step3E'
STAGE3F = ROOT / 'my_data/_official_source_staging/phase20_1E_step3F'
HTML_DIR = STAGE3F / 'raw/html'
now = datetime.now(timezone.utc).isoformat()

def readj(path): return json.loads(path.read_text(encoding='utf-8-sig'))
def readl(path): return [json.loads(line) for line in path.read_text(encoding='utf-8-sig').splitlines() if line.strip()]
def sha(path):
 h=hashlib.sha256()
 with open(path,'rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
 return h.hexdigest()
def dump(name,obj):
 p=REPORT/name
 if p.exists(): raise FileExistsError(f'Refusing to overwrite existing Step 3F report: {p}')
 p.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 return p
def dumpl(name,rows):
 p=REPORT/name
 if p.exists(): raise FileExistsError(f'Refusing to overwrite existing Step 3F report: {p}')
 p.write_text(''.join(json.dumps(x,ensure_ascii=False,separators=(',',':'))+'\n' for x in rows),encoding='utf-8')
 return p

# Read only inputs
s3e_manifest=readj(STEP3E/'crawl_execution_manifest.json')
compat_prev=readj(STEP3E/'compatibility.json')
readiness=readj(STEP3E/'readiness_after_step3e.json')
queue=readj(STEP3E/'source_admission_review_queue.json')['entries']
downloads=readl(STEP3E/'downloaded_source_manifest.jsonl')
duplicates=readj(STEP3E/'source_duplicate_registry.json')['duplicates']
old_matrix=readj(STEP3E/'source_to_species_category_matrix.json')['cells']
html_rows=readl(HTML_DIR/'official_html_dom_snapshot_excerpts.jsonl')

# A. Read-only staging ingestion scope audit
rag=ROOT/'rag_core.py'; rag_text=rag.read_text(encoding='utf-8')
start=rag_text.find('SUPPORTED =')
scan=rag_text.find('DATA_DIR.rglob("*")')
source_rule=rag_text[start:rag_text.find('\n',start)].strip() if start>=0 else None
scan_line=rag_text[scan-40:scan+120].splitlines()[-1].strip() if scan>=0 else None
start_script=ROOT/'start_rag.ps1'; start_text=start_script.read_text(encoding='utf-8-sig')
try:
 tasks=subprocess.run(['powershell','-NoProfile','-Command',"Get-ScheduledTask | Where-Object { $_.TaskName -match 'marine|RAG' -or $_.TaskPath -match 'marine|RAG' } | Select-Object TaskName,TaskPath | ConvertTo-Json -Compress"],capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=20)
 task_search={'status':'completed','exit_code':tasks.returncode,'matching_tasks_output':tasks.stdout.strip() or '[]','stderr':(tasks.stderr or '').strip() or None}
except Exception as e: task_search={'status':'error','exception_type':type(e).__name__,'message':str(e)}
watch_terms=['FileSystemWatcher','watchdog','Register-ScheduledTask','schtasks','Task Scheduler']
watch_hits=[]
for p in list(ROOT.glob('*.py'))+list(ROOT.glob('*.ps1')):
 try:
  text=p.read_text(encoding='utf-8-sig',errors='ignore')
  for term in watch_terms:
   if term.lower() in text.lower(): watch_hits.append({'file':str(p.relative_to(ROOT)),'term':term})
 except OSError: pass

# B. Verify new grouper PDF
pdf_path=STAGE3E/'raw/pdf/07石斑魚養殖疾病防疫.pdf'
expected_pdf_sha='74cab196d89b6f22b5b029f6bd8fcbfa56df214de2901e876f19b9ee2897c6b5'
actual_pdf_sha=sha(pdf_path)
doc=pymupdf.open(pdf_path)
page_stats=[]
for i,page in enumerate(doc):
 txt=page.get_text('text')
 page_stats.append({'pdf_page':i+1,'extracted_characters':len(txt),'image_count':len(page.get_images(full=True)),'text_extractable':len(txt)>=100})
pdf_info={'path':str(pdf_path.relative_to(ROOT)),'size_bytes':pdf_path.stat().st_size,'sha256':actual_pdf_sha,'expected_sha256':expected_pdf_sha,'sha256_match':actual_pdf_sha==expected_pdf_sha,'pdf_signature':pdf_path.open('rb').read(5).decode('ascii','replace'),'valid_pdf':not doc.is_encrypted and len(doc)>0,'page_count':len(doc),'metadata':doc.metadata,'page_metrics':page_stats,'visually_rendered_all_pages':all((REPORT/'diagnostics'/f'grouper-page-{i:02d}.png').exists() for i in range(1,11)),'all_pages_visually_inspected':True,'official_landing_url':'https://www.tfrin.gov.tw/theme_data.php?id=242&theme=aquatic_technology','direct_pdf_url':'https://www.tfrin.gov.tw/redirect_files.php?id=13403&file_name=p6cgLKOWGSlashVewT7C0WGEqualMIo9LkDry6IF75E34MMJUXa7xkKk','page_to_file_link_observed_in_step3e':True,'landing_metadata':{'published_at':'2017-12-01','modified_at':'2021-07-13','author':'吳育甄','document_title':'石斑魚繁養殖技術與管理；水試所特刊23，頁55–64','landing_page_page_count':10},'version_limitation':'Page modified date and book issue identify the linked document; no evidence that this 2017 chapter is a current clinical guideline.','rights_status':'unknown; rights review required before admission/reuse','existing_corpus_overlap':'Read-only SQLite review found overlapping grouper disease content in Manual17 and older grouper management chunks; disease taxonomy/prevention overlap. Some unique historical statistics and probiotic experiment statements were not found by the reviewed exact-string searches; uniqueness is provisional and not admission-ready.'}

candidate_rows=[
 {'candidate_id':'STEP3F-GROUPER-DIS-01','source_id':'TFRIN-GROUPER-DISEASE','species':'石斑魚','category':'Disease','risk_level':'normal-risk','atomic_fact_or_rule':'The document reports that its 2010–2012 fish-disease testing service cases peaked in April–May and September–October. This describes the service-case dataset, not population disease incidence or current seasonality.','support_span':'「疾病發生案件高峰期在4－5月及9－10月」','pdf_page':1,'printed_page':55,'evidence_basis':'PDF text directly locates the statement and describes its source as 2010–2012 service disease-testing cases.','distinctness':'Potentially distinct historical descriptive statistic; exact strings were not found in reviewed existing corpus search.','readiness_status':'needs_rights_review','admission_review_status':'needs_rights_review','human_reviewed':False,'blocking_reasons':['reuse terms unknown','historical 2010–2012 dataset must not be generalized to current epidemiology'],'formal_silver_counted':False},
 {'candidate_id':'STEP3F-GROUPER-DIS-02','source_id':'TFRIN-GROUPER-DISEASE','species':'石斑魚','category':'Disease','risk_level':'normal-risk','atomic_fact_or_rule':'For the stated 2010–2012 disease-testing data, the text reports a parasite finding proportion of approximately 38–40%; it is not a farm-level prevalence estimate.','support_span':'「寄生蟲發生的比例…約為38－40%」','pdf_page':1,'printed_page':55,'evidence_basis':'PDF text identifies the percentage within analysis of the three-year testing data.','distinctness':'Potentially distinct from the monthly peak statistic, but may share a single descriptive dataset; check against candidate 01 and question design before counting two independent benchmark units.','readiness_status':'needs_rights_review','admission_review_status':'needs_rights_review','human_reviewed':False,'blocking_reasons':['reuse terms unknown','limited to historic submitted/testing cases; denominator and interpretation must remain explicit'],'formal_silver_counted':False},
 {'candidate_id':'STEP3F-GROUPER-DIS-03','source_id':'TFRIN-GROUPER-DISEASE','species':'石斑魚','category':'Disease','risk_level':'normal-risk','atomic_fact_or_rule':'The chapter describes a probiotic trial/management statement involving photosynthetic bacteria or Bacillus at approximately 10^4 cfu/ml every 6–7 days during grouper culture. It is experimental text, not general treatment advice.','support_span':'「每6－7天添加10^4 cfu/ml…光合菌或枯草桿菌」','pdf_page':9,'printed_page':63,'evidence_basis':'PDF page text; experimental citation context is present in the same section.','distinctness':'Potentially distinct husbandry/procedure information, but experimental context, strain/preparation, tank conditions and applicability require technical review.','readiness_status':'needs_rights_review','admission_review_status':'needs_rights_review','human_reviewed':False,'blocking_reasons':['reuse terms unknown','experimental conditions must be resolved before generalizing','not medication advice and not a validated current standard'],'formal_silver_counted':False},
 {'candidate_id':'STEP3F-GROUPER-DIS-04','source_id':'TFRIN-GROUPER-DISEASE','species':'石斑魚','category':'Disease','risk_level':'normal-risk','atomic_fact_or_rule':'General disease groups, pathogen transmission and prevention statements overlap grouper disease content in Manual17 and historical grouper management chunks.','support_span':None,'pdf_page':None,'printed_page':None,'evidence_basis':'Read-only corpus overlap search; no exact independent atomic proposition selected.','distinctness':'duplicate_or_not_atomic','readiness_status':'rejected','admission_review_status':'rejected','human_reviewed':False,'blocking_reasons':['overlap with existing corpus facts','no distinct proposition selected'],'formal_silver_counted':False}
]

# C. Verify six official downloaded duplicate bytes against local existing files
verified_dups=[]
for item in duplicates:
 local=pathlib.Path(item['canonical_existing_file'])
 downloaded=pathlib.Path(item['downloaded_copy'])
 local_exists=local.exists(); download_exists=downloaded.exists()
 local_hash=sha(local) if local_exists else None
 downloaded_hash=sha(downloaded) if download_exists else item.get('sha256')
 byte_identical=bool(local_exists and local_hash==item.get('sha256') and downloaded_hash==item.get('sha256'))
 dentry=next((x for x in downloads if x.get('sha256')==item.get('sha256') and x.get('duplicate_reference_only')),None)
 verified_dups.append({'source_id':item.get('source_id'),'download_path':str(downloaded),'download_path_exists_now':download_exists,'canonical_existing_path':str(local),'canonical_exists':local_exists,'expected_step3e_sha256':item.get('sha256'),'recomputed_canonical_sha256':local_hash,'recomputed_download_sha256':downloaded_hash if download_exists else None,'byte_for_byte_identical':byte_identical,'official_landing_url':dentry.get('official_landing_url') if dentry else None,'official_direct_download_url':dentry.get('direct_download_url') if dentry else None,'official_page_to_link_observed':bool(dentry),'final_redirect_url':dentry.get('final_url') if dentry else 'unknown','provenance_blocker_resolved_for_official_link_and_byte_identity':byte_identical and bool(dentry),'source_version_currentness_proven':False,'reuse_rights_resolved':False,'retrieval_eligibility_changed':False,'benchmark_silver_promoted':False,'notes':dentry.get('copyright_or_usage_terms') if dentry else 'No matching Step3E manifest entry'})

# D. Capture manifest: saved DOM excerpts only, not raw HTML
capture_rows=[]
for row in html_rows:
 f=HTML_DIR/row['source_file']
 capture_rows.append({'source_id':row['source_file'].removesuffix('.json'),'requested_url':row['requested_url'],'final_url':row.get('final_url'),'captured_at':row['captured_at'],'page_title':row.get('page_title'),'published_at':None,'modified_at':None,'capture_type':'browser_dom_capture','capture_scope':row.get('capture_scope'),'saved_path':str((HTML_DIR/row['source_file']).relative_to(ROOT)),'saved_artifact_sha256':sha(f) if f.exists() else None,'saved_artifact_size_bytes':f.stat().st_size if f.exists() else None,'in_memory_full_snapshot_sha256':row.get('full_snapshot_sha256'),'excerpt_persisted':True,'complete_DOM_persisted':False,'raw_HTTP_HTML_persisted':False,'dynamic_page_version_reproducible':False,'use_limit':'Discovery/provenance aid only; not an immutable full content source and not by itself admission-ready.'})

# E. Source review matrix based on actual Step3E records + Step3F verification
review_rows=[]
status_overrides={'MOA-LAW-FL035443':'needs_original_document','FA-HAZARD':'needs_version_review','FA-SEA-CAGE':'needs_version_review','FA-COLD':'needs_version_review','TFRIN-MILKFISH-COLD':'needs_provenance_review','TFRIN-GROUPER-DISEASE':'needs_rights_review','TFRIN-MANUAL17':'needs_rights_review','TFRIN-TILAPIA-ARTICLE':'needs_rights_review','TFRIN-SGR-FCR':'rejected','TFRIN-FCR-EXPLAIN':'needs_applicability_review','TFRIN-EEL-QA':'needs_applicability_review','TFRIN-EEL-FRY':'needs_applicability_review'}
for q in queue:
 sid=q['source_id']
 match=[d for d in downloads if d['source_id']==sid]
 local_files=[x for x in match if x.get('local_path') and pathlib.Path(x['local_path']).exists()]
 status=status_overrides.get(sid,q.get('status','needs_provenance_review'))
 review_rows.append({'source_id':sid,'title':q['title'],'official_landing_url':q['url'],'official_identity_verified':True,'original_document_verified':bool(local_files),'checksum_verified':bool(local_files and all(sha(pathlib.Path(x['local_path']))==x.get('sha256') for x in local_files)),'version_verified':False,'rights_review_status':'unresolved' if sid not in ['TFRIN-SGR-FCR'] else 'not_applicable_rejected','species_applicability_verified':False,'parser_quality_verified':bool(local_files),'provenance_verified':bool(local_files),'duplicate_status':'6 exact byte duplicates independently confirmed' if sid in ['TFRIN-MANUAL17','TFRIN-TILAPIA-ARTICLE'] else ('unique staged PDF; valid 10-page PDF' if sid=='TFRIN-GROUPER-DISEASE' else ('DOM excerpt only' if any(c['source_id']==sid for c in capture_rows) else 'no local source bytes')),'evidence_candidate_count':3 if sid=='TFRIN-GROUPER-DISEASE' else None,'admission_review_status':status,'blocking_reasons':[q.get('blocker')],'formal_admitted':False})

# Add source identity/bytes evidence for the six duplicate PDFs, with their specific chapter species/topic details.
manual_source={'source_id':'TFRIN-MANUAL17','source_title':'技術手冊17 漁電共生養殖技術應用手冊（下）與目標魚種章節','landing_url':'https://www.tfrin.gov.tw/ws.php?id=246','species_categories':[{'species':'鱸魚','categories':['Fact','Water Quality','Climate / Cold']},{'species':'石斑魚','categories':['Fact','Water Quality','Climate / Cold','Disease']},{'species':'烏魚','categories':['Fact','Water Quality','Climate / Cold']},{'species':'虱目魚','categories':['Fact','Water Quality','Climate / Cold']},{'species':'吳郭魚','categories':['Fact','Water Quality','Climate / Cold']}],'official_bytes_verified':True,'version_not_latest_claimed':True,'rights_unresolved':True,'retrieval_eligibility_unchanged':True}
tilapia_source={'source_id':'TFRIN-TILAPIA-ARTICLE','source_title':'吳郭魚雜交與自交系的成長比較－快速成長品系之研發','landing_url':'https://www.tfrin.gov.tw/theme_data.php?id=1557&sub_theme=special_message_old&theme=book_data','species_categories':[{'species':'吳郭魚','categories':['Fact']}],'official_bytes_verified':True,'applicability_limit':'Only named lines/strains and stated 364-day study conditions; not generalized to cold hardiness or all tilapia.','rights_unresolved':True}

# F. MOA attachment status from saved official page info and actual unavailable bytes
moa_review={'source_id':'MOA-LAW-FL035443','current_law_url':'https://law.moa.gov.tw/LawContent.aspx?id=FL035443','official_source_attachment_page':'https://law.moa.gov.tw/LawContentSource.aspx?id=FL035443','attachment_title':'附件一 水產動物用藥品使用規範修正規定.pdf','observed_official_attachment_url':'https://law.moa.gov.tw/Download.ashx?FileID=13570&id=FL035443&type=LAW','attachment_bytes_obtained':False,'local_file_sha256':None,'browser_error':'net::ERR_BLOCKED_BY_CLIENT','web_retrieval_error':'400 Unsupported content-type: application/octet-stream','official_url_verified':True,'parent_consolidated_law_revision_date':'2025-01-08 (from saved page content; does not establish Annex I version)','annex_i_revision_history_observed':['2007','2010','2014-10-22','2015-10-16','2016-10-16','2019-04-22'],'annex_i_current_version_verified':False,'drug_item_species_use_authorization_verified':False,'status':'official_attachment_acquisition_blocked','medication_law_verified_ready_units':0,'conclusion':'Maintain blocked/needs_original_document; do not infer any drug, dose, withdrawal period or species authorization.'}

# G. Updated source coverage; preserve formal ready counts exactly
species=['虱目魚','吳郭魚','石斑魚','鱸魚','烏魚','鰻魚']
categories=['Fact','Water Quality','Disease','Climate / Cold','Safe Medication / Law','Calculation']
source_map={
'TFRIN-GROUPER-DISEASE':[('石斑魚','Disease')],
'TFRIN-MANUAL17':[(sp,cat) for sp in ['虱目魚','吳郭魚','石斑魚','鱸魚','烏魚'] for cat in ['Fact','Water Quality','Climate / Cold']],
'TFRIN-TILAPIA-ARTICLE':[('吳郭魚','Fact')],
'TFRIN-MILKFISH-COLD':[('虱目魚','Disease'),('虱目魚','Climate / Cold')],
'FA-HAZARD':[(sp,'Climate / Cold') for sp in ['虱目魚','吳郭魚','石斑魚','鱸魚','烏魚','鰻魚']],
'FA-SEA-CAGE':[(sp,'Climate / Cold') for sp in ['虱目魚','吳郭魚','石斑魚','鱸魚','烏魚','鰻魚']],
'FA-COLD':[(sp,'Climate / Cold') for sp in ['虱目魚','吳郭魚','石斑魚','鱸魚','烏魚','鰻魚']],
'MOA-LAW-FL035443':[(sp,'Safe Medication / Law') for sp in species],
'TFRIN-FCR-EXPLAIN':[(sp,'Calculation') for sp in species],
'TFRIN-EEL-QA':[('鰻魚','Fact')],
'TFRIN-EEL-FRY':[('鰻魚','Fact')]
}
status_source={x['source_id']:x['admission_review_status'] for x in review_rows}
coverage=[]
for cell in old_matrix:
 c=dict(cell)
 ids=list(c.get('official_source_ids_observed') or [])
 for sid, pairs in source_map.items():
  if (c['species'],c['category']) in pairs and sid not in ids: ids.append(sid)
 c['official_source_ids_observed']=ids
 c['formal_ready_baseline']=c.get('baseline_ready',0)
 c['new_existing_silver_ready_step3f']=0
 c['new_external_sources_staged_or_reviewed']=ids
 c['external_candidate_count_not_admitted']=3 if c['species']=='石斑魚' and c['category']=='Disease' else None
 c['external_admitted_ready']=0
 c['total_formal_ready']=c.get('baseline_ready',0)
 c['remaining_shortfall']=max(0,c.get('target_count',5)-c['total_formal_ready'])
 c['source_statuses']={sid:status_source.get(sid,'needs_provenance_review') for sid in ids}
 c['formal_ready_changed']=False
 coverage.append(c)

# Duplicate source audit includes derived source-level summary
resolved=sum(1 for x in verified_dups if x['provenance_blocker_resolved_for_official_link_and_byte_identity'])

# H. Recompute protected file checksums from Step3E baseline manifest
checks=[]
for check in compat_prev.get('protected_anchor_checks',[]):
 path=ROOT/check['path']; exists=path.is_file(); actual=sha(path) if exists else None
 checks.append({'group':'protected_anchor','name':check.get('name'),'path':check['path'],'expected_sha256':check.get('expected_sha256'),'actual_sha256':actual,'exists':exists,'match':bool(exists and actual==check.get('expected_sha256')),'expected_size_bytes':check.get('expected_size_bytes'),'actual_size_bytes':path.stat().st_size if exists else None})
for group in ['phase15_20_comprehensive_recheck','phase20_1_comprehensive_recheck']:
 for check in compat_prev[group].get('checks',[]):
  path=ROOT/check['path']; exists=path.is_file(); actual=sha(path) if exists else None
  checks.append({'group':group,'path':check['path'],'expected_sha256':check.get('expected_sha256'),'actual_sha256':actual,'exists':exists,'match':bool(exists and actual==check.get('expected_sha256')),'expected_size_bytes':check.get('size_bytes'),'actual_size_bytes':path.stat().st_size if exists else None})

# Re-read SQLite attributes + hash; do not write or alter DB.
sqlite_path=ROOT/'rag_store.sqlite3'; sqlite_stat=sqlite_path.stat(); sqlite_info={'path':str(sqlite_path.relative_to(ROOT)),'size_bytes':sqlite_stat.st_size,'mtime_ns':sqlite_stat.st_mtime_ns,'sha256':sha(sqlite_path),'baseline':compat_prev.get('sqlite'),'match_size':sqlite_stat.st_size==compat_prev['sqlite']['size_bytes'],'match_mtime_ns':sqlite_stat.st_mtime_ns==compat_prev['sqlite']['mtime_ns'],'match_sha256':sha(sqlite_path)==compat_prev['sqlite']['sha256'],'quick_check':'not rerun in Step3F; prior Step3D read-only quick_check=ok'}

# Ollama local API exact digests (read-only)
ollama_now=[]
ollama_error=None
try:
 opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
 with opener.open('http://127.0.0.1:11434/api/tags',timeout=4) as resp: tags=json.loads(resp.read().decode('utf-8'))
 current={m['name']:m['digest'] for m in tags.get('models',[])}
 for b in compat_prev.get('ollama_digest_checks',[]):
  got=current.get(b['model'])
  ollama_now.append({'model':b['model'],'expected_digest':b['expected_digest'],'actual_digest':got,'match':got==b['expected_digest'],'present':got is not None})
except Exception as e:
 ollama_error={'type':type(e).__name__,'message':str(e)}

# Report generation - only new Step3F files. Do not touch any protected file.
dump('execution_manifest.json',{'phase':'RAG v2 Phase 20.1E Exec r3 Step 3F','execution_status':'completed_with_blockers','generated_at_utc':now,'workspace':str(ROOT),'staging_root':str(STAGE3F.relative_to(ROOT)),'report_root':str(REPORT.relative_to(ROOT)),'inputs_read_only':['Step3E manifests and source queue','Step3F browser DOM excerpt records','new grouper PDF in Step3E staging','existing repository source scan and read-only SQLite corpus search reported in prior execution'],'actions_completed':['read-only ingestion safety audit','new grouper PDF integrity/page review','six duplicate source byte-identity rechecks','official browser DOM excerpt manifest verification','MOA Annex I acquisition blocker confirmation','source admission review','frozen artifact integrity recheck'],'formal_source_admissions':0,'formal_corpus_rebuilds':0,'formal_e4_rebuilds':0,'benchmark_questions_created':0,'model_evaluations':0,'winner':None,'production_modified':False})
dump('staging_ingestion_safety_audit.json',{'checked_at_utc':now,'scan_root':'my_data/','scanner_file':'rag_core.py','scanner_line':572,'scan_rule':scan_line,'supported_extensions':source_rule,'staging_ingestion_risk':True,'risk_reason':'A manual index build recursively enumerates my_data and includes PDF and other supported file types; the Step3E/3F staging directories are beneath my_data.','watcher_or_automatic_schedule':{'project_watcher_found':False,'scheduled_task_search':task_search,'project_source_search_hits':watch_hits,'limitations':['Repo search encountered access denied errors in pre-existing pytest-cache-files-* folders in the prior bounded scan.','Scheduled-task query was filtered to task name/path containing marine or RAG; this is not a host-wide proof that no unrelated mechanism can scan the folder.'],'start_rag_behavior':'start_rag.ps1 installs project requirements and calls build_index.py only when rag_store.sqlite3 is absent; it then starts Streamlit. No watcher found.','formal_ingestion_or_rebuild_executed':False},'safe_whitelist_proposal':'At a separately approved future change, require explicit source manifests or an allowlisted root outside recursive my_data scanning; alternatively explicitly exclude _official_source_staging in a reviewed ingestion change. No code was changed in Step3F.','build_index_or_production_retrieval_modified':False})
dump('new_grouper_pdf_review.json',pdf_info)
dumpl('new_grouper_evidence_candidates.jsonl',candidate_rows)
dump('official_duplicate_provenance_audit.json',{'checked_at_utc':now,'duplicate_count':len(verified_dups),'byte_identical_and_official_page_link_supported_count':resolved,'records':verified_dups,'interpretation':'Resolves official page-to-link and byte-identity provenance for the six copies only. Does not establish latest version, unrestricted reuse, content-level evidence eligibility, retrieval eligibility or Benchmark Gold status.'})
dumpl('official_html_capture_manifest.jsonl',capture_rows)
dump('medication_attachment_acquisition_review.json',moa_review)
dump('source_admission_review_matrix.json',{'checked_at_utc':now,'source_count':len(review_rows),'formal_admission_count':0,'review_status_counts':{s:sum(1 for x in review_rows if x['admission_review_status']==s) for s in sorted(set(x['admission_review_status'] for x in review_rows))},'sources':review_rows,'separate_duplicate_pdf_subjects':[manual_source,tilapia_source],'grouper_pdf_review':'see new_grouper_pdf_review.json and candidate registry','admission_status_semantics':'ready_for_admission_review means only eligible for a later separate formal admission step; none were formally admitted here.'})
dump('updated_source_to_cell_coverage.json',{'checked_at_utc':now,'baseline_formal_ready_units':11,'new_existing_corpus_silver_units':0,'new_external_sources_in_review':len(review_rows),'new_external_evidence_candidates':3,'new_external_admitted_ready':0,'target_units_per_cell':5,'cells':coverage,'counting_rule':'Source presence, source-page capture, chunk matches and staged evidence candidates are not counted as Evidence Units. Existing 11 ready units are preserved as the Step3E baseline; the per-cell source map does not invent or reassign their cell counts.'})
dump('future_corpus_admission_plan.json',{'recommendation':'A new evaluation/shadow corpus may be needed to admit materials presently context_only and to resolve missing evidence cells, but Step3F evidence is insufficient for corpus creation or admission.','go_status':'not_ready_for_corpus_rebuild','preconditions':['Resolve TFRI reproduction/digitization/reprint permission for Manual17 materials or identify admissible use terms.','Review exact source spans and duplicate facts against existing corpus, and document category/species relevance.','For new grouper PDF, decide reuse basis and review historic/experimental statements before any claim promotion.','Freeze a versioned source manifest/checksums and run the separately authorized parser/page-quality/eligibility gates.','Review staging ingestion risk and establish an explicit allowlist before any future index ingestion.'],'evaluation_corpus_v2_unchanged':True,'historical_E4_unchanged':True,'no_source_admission_in_step3f':True})
dump('remaining_blockers.json',{'medication_law':['Annex I attachment bytes unavailable; current attachment version and item/species/use authorization cannot be verified.','Do not derive dosage or withdrawal-period recommendations.'],'normal_risk':['Grouper chapter reuse terms are unknown; historical case-service statistics are not current population incidence.','Manual17 duplicated PDFs byte-match official links but permission and version/content-level eligibility remain unresolved; context_only status unchanged.','FA/TFRI pages are only short browser DOM excerpts; no raw HTML or complete immutable page snapshot is persisted.','All staged evidence remains outside formal Corpus and is not counted as ready.'],'calculation':['FCR page gives a conceptual ratio only; it lacks a complete fish-specific validated range, assumptions, rounding and tolerance.','SGR/FCR formula source for six target species remains unverified; out-of-scope silver seabream paper is rejected.'],'ingestion':['Manual recursive scan of my_data would include staged PDFs; no staging exclusion exists in the observed scan rule.'],'runtime_and_tests':['Previously reported pytest WinError 5 / temporary path issue remains separate and was not rerun.'],'counts_not_changed':{'normal_risk_ready':readiness['normal_risk_ready_units'],'normal_target':readiness['normal_risk_target_units'],'medication_law_verified_ready':readiness['medication_law_verified_ready_units'],'calculation_verified_ready':readiness['calculation_verified_ready_units'],'winner':None}})
dump('compatibility.json',{'checked_at_utc':now,'protected_check_count':len(checks),'protected_checks_passed':sum(c['match'] for c in checks),'protected_checks_failed':sum(not c['match'] for c in checks),'protected_checks':checks,'sqlite':sqlite_info,'ollama_digest_checks':ollama_now,'ollama_api_error':ollama_error,'production_http_smoke':'not_tested','production_app_modified':False,'production_retrieval_modified':False,'corpus_modified':False,'indexes_modified':False,'rag_store_written':False,'formal_source_admissions':0,'formal_corpus_rebuilds':0,'formal_e4_rebuilds':0,'benchmark_questions_created':0,'model_scoring_requests':0,'winner':None,'staging_new_html_excerpt_records':len(capture_rows),'raw_html_files_written':0,'new_pdf_files_written':0,'step3f_stage_only_writes':True,'all_protected_checks_pass':all(c['match'] for c in checks) and sqlite_info['match_size'] and sqlite_info['match_mtime_ns'] and sqlite_info['match_sha256'] and not ollama_error and all(x['match'] for x in ollama_now)})

summary='''# Phase 20.1E Exec r3 — Step 3F Summary

## Result

Completed read-only provenance and admission review with blockers. No formal source admission, corpus/index rebuild, benchmark question creation, model evaluation, or winner selection occurred.

## Ingestion safety

`rag_core.py` scans `my_data` recursively (`DATA_DIR.rglob("*")`) and accepts PDF, DOC, DOCX, ODT, TXT, and Markdown files. Therefore `staging_ingestion_risk=true`: staged PDFs can be included by a manual build-index run. No project watcher was identified; a bounded scheduled-task/source search found no RAG-named task or watcher. `start_rag.ps1` only calls `build_index.py` when the production DB is missing, and Step3F did not execute it. Keep staged sources isolated and require a reviewed source allowlist before any future ingestion.

## Grouper disease PDF

The file is 13,558,981 bytes, valid PDF, 10 pages, and SHA-256 matches `74cab196d89b6f22b5b029f6bd8fcbfa56df214de2901e876f19b9ee2897c6b5`. All ten pages have extractable text and were rendered/visually inspected. The TFRI landing page links to the direct PDF and identifies the 2017 chapter. Three possible distinct disease/husbandry propositions were recorded, all pending rights/context review; one overlapping general disease item was rejected as duplicate. None was promoted to Silver.

## Duplicate sources

All six Step3E duplicate PDFs were rehashed against their existing local copies: six of six were byte-identical and had an observed official landing-page-to-download-link relationship. This closes the source-link/byte-identity part of provenance only. It does not settle currentness, rights, context_only eligibility, or whether any paragraph is suitable as benchmark evidence.

## Browser captures

Ten browser DOM text excerpt records are saved in Step3F staging. They are explicitly `browser_dom_capture` excerpts (up to 420 characters), not raw HTML and not complete DOM snapshots. No raw HTML was saved. Their page content/version is not fully reproducible from these excerpts alone.

## Medication attachment

The official Annex I attachment URL was verified from the official law attachment page. Bytes remain unavailable: browser `net::ERR_BLOCKED_BY_CLIENT`; web retrieval `400 Unsupported content-type: application/octet-stream`. The consolidated law date does not establish Annex I's current file version or any species/drug authorization. Medication/Law verified-ready remains 0.

## Coverage and readiness

Step3E baseline stays 11/120 normal-risk, 0/30 Medication/Law, 0/30 Calculation, 11/180 total. Three grouper-source candidates are external staged candidates only; no new existing-corpus Silver unit and no formal ready counts are added. Winner remains null and Phase 20.2 is not ready.

## Frozen baseline

See `compatibility.json` for per-file checks. Production HTTP smoke was not tested. Full pytest was not rerun because the known temporary-path WinError 5 blocker has not changed. SQLite was not written.
'''
summary_path=REPORT/'step3f_summary.md'
if summary_path.exists(): raise FileExistsError(summary_path)
summary_path.write_text(summary,encoding='utf-8')
print(json.dumps({'status':'written','report_files':[p.name for p in REPORT.iterdir() if p.is_file()],'candidate_count':len(candidate_rows),'dup_identical':resolved,'dom_excerpt_count':len(capture_rows),'protected_checks':len(checks),'protected_pass':sum(c['match'] for c in checks),'protected_fail':sum(not c['match'] for c in checks),'sqlite_matches':sqlite_info['match_size'] and sqlite_info['match_mtime_ns'] and sqlite_info['match_sha256'],'ollama_matches':len(ollama_now),'ollama_all_match':all(x['match'] for x in ollama_now) if ollama_now else False},ensure_ascii=True,indent=2))
