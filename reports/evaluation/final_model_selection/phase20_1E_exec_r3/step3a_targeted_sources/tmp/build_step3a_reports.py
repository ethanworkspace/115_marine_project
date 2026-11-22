import json, shutil, hashlib, os
from pathlib import Path
from datetime import datetime, timezone

ROOT=Path(r'C:\my project\115_marine_project')
BASE=ROOT/'reports/evaluation/final_model_selection/phase20_1E_exec_r3'
OUT=BASE/'step3a_targeted_sources'
S2=BASE/'step2_existing_corpus'
S2B=BASE/'step2b_verification_pilot'
OUT.mkdir(parents=True,exist_ok=True)
def readj(p): return json.loads(Path(p).read_text(encoding='utf-8'))
def writej(name,obj): (OUT/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def writel(name,rows): (OUT/name).write_text(''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in rows),encoding='utf-8')
def sha(p):
 h=hashlib.sha256()
 with open(p,'rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
 return h.hexdigest()

matrix=readj(S2B/'pilot_evidence_matrix.json')
ready=readj(S2B/'readiness_after_step2b.json')
compat=readj(S2B/'compatibility.json')
calc=readj(S2B/'calculation_validation.json')
triage=readj(S2B/'test_failure_triage.json')
scan=OUT/'existing_corpus_targeted_hits.jsonl'
raw=OUT/'tmp/raw_keyword_scan_300.jsonl'
if scan.exists() and not raw.exists(): shutil.copy2(scan,raw)
hits=[json.loads(s) for s in raw.read_text(encoding='utf-8').splitlines() if s.strip()]
annotated=[]
for h in hits:
 x=dict(h); x.update(targeted_status='keyword_hit_needs_review',not_an_evidence_unit=True,ready_count_contribution=0,limitation='Lexical species/topic co-occurrence only; does not establish source quality, semantic entailment, applicability, atomicity, or distinctness.')
 annotated.append(x)
writel('existing_corpus_targeted_hits.jsonl',annotated)
from collections import Counter
hit_counts=Counter(x['cell'] for x in hits)

cells=[('虱目魚','Disease'),('虱目魚','Climate / Cold'),('吳郭魚','Climate / Cold'),('石斑魚','Disease'),('石斑魚','Safe Medication / Law'),('鱸魚','Safe Medication / Law'),('烏魚','Disease'),('鰻魚','Climate / Cold')]
cell_counts={f'{s}|{c}':hit_counts.get(f'{s}|{c}',0) for s,c in cells}
selected=[
 ('虱目魚','Disease','chunk_143bc4f1205156c38fafb48a9250e76b','mixed-species disease manual candidate; local source identity pending; explicit species mention in excerpt, source validation still required'),
 ('虱目魚','Climate / Cold','chunk_1b8be225a69a51eab7cfe79366276df0','local FA cold guide candidate; source identity pending; exact species/cold text requires source PDF check'),
 ('吳郭魚','Climate / Cold','chunk_591b5e4b41885582a5c63fb2b92570aa','tilapia overwintering/low-temperature study excerpt; local file source identity pending'),
 ('石斑魚','Disease','chunk_731052d8f6f35845949a190a4efd2b60','official TFRI Manual 17, corpus page 91-92; prior screening missed; queue atomic-fact/dedup review'),
 ('石斑魚','Safe Medication / Law','','broad keyword co-occurrence only; no exact species-specific legal source span was mapped to a corpus chunk; do not borrow the sea-bass annex chunk'),
 ('鱸魚','Safe Medication / Law','chunk_4dd88188fe6951b9bb22626ad1e20abc','official MOA annex names Lates/sea bass within taxonomic scope; named drug/provision applicability not yet reviewed'),
 ('烏魚','Disease','chunk_17b09aacb4685829b42c4ca1c2882021','official TFRI Manual 17, corpus page 124; prior screening missed; queue atomic-fact/dedup review'),
 ('鰻魚','Climate / Cold','chunk_22b9e2d6b62b584ba72d5ca49b776c61','local Japanese eel aquaculture file candidate; source identity pending; external TFRIN items found were species/scope mismatches'),
]
hit_by={(h.get('cell','').split('|')[0],h.get('cell','').split('|')[1],h.get('chunk_id')):h for h in hits}
candidate_rows=[]
for s,c,cid,why in selected:
 h=hit_by.get((s,c,cid),{})
 candidate_rows.append({'candidate_id':f'targeted_{hashlib.sha256((s+c+cid).encode()).hexdigest()[:16]}','species':s,'category':c,'chunk_id':cid,'document_id':h.get('document_id'),'page':h.get('page_start'),'source_title':h.get('source_title'),'source_verification_status':h.get('source_verification_status'),'source_verified':h.get('source_verified'),'source_checksum':h.get('source_checksum'),'official_url':h.get('source_url'),'support_excerpt':h.get('support_excerpt','')[:500],'status':'needs_review','why_not_ready':why,'source_to_evidence_mapping':'existing Evaluation Corpus v2 chunk; no external artifact admitted'})
writel('staged_evidence_candidates.jsonl',candidate_rows)

source_records=[
 ('FA-COLD','養殖漁業防寒須知','農業部漁業署','official government guidance','https://www.fa.gov.tw/view.php?id=385&print=Y&subtheme=&theme=web_structure','unknown','unknown','unknown','虱目魚、吳郭魚等養殖魚；具體條件依頁面','低溫/寒害','網頁','discovered','not_downloaded','目前網路代理拒絕連線；本機既有 PDF 尚未核實來源版本'),
 ('FA-HAZARD','陸上魚塭養殖寒害潛勢分析','農業部漁業署','official government analysis','https://www.fa.gov.tw/view.php?id=383&print=Y&subtheme=&theme=web_structure','2026-06-19','2026-06-19','unknown','虱目魚、吳郭魚、鱸魚、石斑魚（頁面列示；情境需核驗）','低溫/寒害','網頁','discovered','not_downloaded','頁面列示日期為民國115-06-19；原文未下載'),
 ('TFRIN-MILKFISH-COLD','寒流侵襲時造成虱目魚死亡的原因為何？','農業部水產試驗所','official technical Q&A','https://www.tfrin.gov.tw/theme_data.php?id=426&theme=knowledge_explanation','unknown','unknown','unknown','虱目魚；寒流死亡/紅斑病關聯','疾病/低溫','網頁','discovered','not_downloaded','外部頁面可瀏覽；原始文件 bytes 未保存'),
 ('TFRIN-GROUPER-DISEASE','石斑魚養殖疾病防疫','農業部水產試驗所','official aquaculture guidance','https://www.tfrin.gov.tw/theme_data.php?id=242&theme=aquatic_technology','2017-12-01','2021-07-13','unknown','石斑魚養殖；指南內容及現行適用性需審','疾病防治','網頁','discovered','not_downloaded','官方頁面資訊已查；未下載'),
 ('TFRIN-MANUAL17','漁電共生養殖技術應用手冊（下）','農業部水產試驗所','official technical manual','https://www.tfrin.gov.tw/ws.php?id=246','2023-08-31','unknown','unknown','手冊含石斑魚、烏魚等章節','疾病/養殖技術','existing_corpus_document','provenance_verified_for_existing_local_copy','not_newly_downloaded','本機來源 manifest/雜湊一致；著作權頁限制未授權重製；僅作 provenance，不複製原文'),
 ('TFRIN-TILAPIA-ARTICLE','吳郭魚雜交與自交系的成長比較－快速成長品系之研發','農業部水產試驗所','official research article catalog','https://www.tfrin.gov.tw/theme_data.php?id=1557&sub_theme=special_message_old&theme=book_data','2008-12-31','unknown','unknown','吳郭魚；研究育種/成長；低溫外推不允許','研究/越冬資料待核','catalog page','discovered','not_downloaded','catalog confirms bibliographic metadata, local PDF bytes not matched to source'),
 ('MOA-LAW-FL035443','動物用藥品使用準則－水產動物用藥品使用規範附表','農業部','current official regulation','https://law.moa.gov.tw/LawContent.aspx?id=FL035443&media=print','unknown','2025-01-08','2025-01-08','附表列出水產動物及範圍；每藥品/用途/物種需逐條核實','水產動物用藥規範','law page','provenance_verified_for_existing_local_copy','not_newly_downloaded','本機官方 PDF checksum 已核；不代表特定魚種核准用藥結論'),
 ('TFRIN-EEL-QA','鱸鰻養殖條件問答（頁面題名依官方頁面）','農業部水產試驗所','official technical Q&A','https://www.tfrin.gov.tw/theme_data.php?id=485&sub_theme=fishery&theme=qa','unknown','unknown','unknown','鱸鰻；不等同日本鰻養殖','鰻類養殖條件','網頁','discovered','not_downloaded','species mismatch for Japanese eel target'),
 ('TFRIN-EEL-FRY','日本鰻魚苗運輸問答（頁面題名依官方頁面）','農業部水產試驗所','official technical Q&A','https://www.tfrin.gov.tw/theme_data.php?id=496&sub_theme=fishery&theme=qa','unknown','unknown','unknown','日本鰻魚苗；僅運輸，不涵蓋成鰻低溫養殖','苗種運輸','網頁','discovered','not_downloaded','scope mismatch for eel climate/grow-out evidence'),
 ('TFRIN-SGR-FCR','銀紋笛鯛魚苗生長/飼料效率研究公式來源','農業部水產試驗所','official research article','https://www.tfrin.gov.tw/redirect_files.php?file_name=aBXgWGEqualWGEqual3MNrCMfywOINoS8mgC&id=9564','unknown','unknown','unknown','銀紋笛鯛魚苗；非六個目標物種通用情境','SGR/FCR formula','PDF endpoint','discovered','not_downloaded','formula candidate only; species and assumptions not transferable without evidence'),
 ('TFRIN-FCR-EXPLAIN','飼料轉換率說明','農業部水產試驗所','official technical explanation','https://www.tfrin.gov.tw/theme_data.php?id=385&theme=knowledge_explanation','unknown','unknown','unknown','一般概念；公式條件/變數需核驗','FCR','網頁','discovered','not_downloaded','high-level definition only; not enough for a verified deterministic unit'),
]
disc=[]
for sid,title,auth,typ,url,pub,rev,eff,sp,topic,scope,status,download,notes in source_records:
 disc.append({'source_id':sid,'official_title':title,'issuing_authority':auth,'source_type':typ,'official_url':url,'publication_date':pub,'revision_date':rev,'effective_date':eff,'access_date':'2026-10-09','species_scope':sp,'topic_scope':topic,'relevant_pages_or_sections':'unknown; page/section must be confirmed against source bytes','retrieval_status':status,'local_staging_path':None,'sha256':None,'license_or_usage_notes':'unknown unless local manifest notes apply; do not redistribute source text','verification_status':download,'rejection_reason':notes})
writel('official_source_discovery_registry.jsonl',disc)
staged=[{'source_id':r['source_id'],'title':r['official_title'],'official_url':r['official_url'],'local_staging_path':None,'downloaded_this_run':False,'sha256':None,'status':r['retrieval_status'],'note':r['rejection_reason']} for r in disc]
writel('staged_source_manifest.jsonl',staged)

# Existing local files are references only; no new file was downloaded or admitted.
existing_files=[
 {'source_id':'TFRIN-MANUAL17-LOCAL','path':'my_data/my_data/技術手冊17-漁電共生養殖技術應用手冊(下).pdf','sha256':'a26364f19971d2c98b37f924e680a4664aa7a9887b195e372f486ca3088aeee9','source_identity':'official TFRIN, manifest verified','file_status':'preexisting corpus source; not copied to staging','usage_note':'Copyright notice restricts reproduction; keep only citation/provenance.'},
 {'source_id':'MOA-LAW-LOCAL','path':'data/recovery/raw_sources/moa_animal_drug_use_rules_attachment_1_FL035443.pdf','sha256':'b13b9492322d7c0de2e1f7bc4dcee8feb99431ca1085819a697f3966c6b92e3c','source_identity':'official MOA local source, checksum verified','file_status':'preexisting corpus source; not copied to staging','usage_note':'Item-level/current applicability still requires legal review.'},
 {'source_id':'FA-COLD-LOCAL','path':'my_data/my_data/養殖漁業防寒須知(農業部漁業署).pdf','sha256':'0cc5f430b6c5f957c1661566122a54d37bf0a8fc6e59d021fe0b627967ac5b3b','source_identity':'unverified against official remote source','file_status':'preexisting local candidate; not copied to staging','usage_note':'Do not treat filename as source verification.'},
 {'source_id':'TILAPIA-ARTICLE-LOCAL','path':'my_data/my_data/水產研究16(2)吳郭魚雜交與自交系的成長比較－快速成長品系之研發.pdf.pdf','sha256':'5eda6d34414dd477988a042b2f36b1989ccc25bc26a5bc78f4b2283a5afb25b5','source_identity':'official catalog metadata found; local PDF bytes not matched','file_status':'preexisting local candidate; not copied to staging','usage_note':'Low-temperature excerpt is experimental context, not general husbandry threshold.'},
 {'source_id':'MIXED-DISEASE-LOCAL','path':'my_data/my_data/養殖魚類疾病防治 .pdf','sha256':'6ffea184a8b0d88f6bd67358ffd6913c035025730409f31e45404bfa22914d85','source_identity':'unverified','file_status':'preexisting local candidate; not copied to staging','usage_note':'Mixed-species text; source identity and scope need review.'},
 {'source_id':'EEL-MANUAL-LOCAL','path':'my_data/my_data/07鰻魚養殖要點及池塘清理消毒.pdf.pdf','sha256':'d56b83d91291cfd534de33c39d06811c4bb5ec056ea4f339b2401d59ac89b72d','source_identity':'unverified','file_status':'preexisting local candidate; not copied to staging','usage_note':'Text identifies Japanese eel, but source provenance pending.'},
]
writel('staged_source_manifest.jsonl',staged+existing_files)

zero_audit=[]
reason={
 '虱目魚|Disease':('source_found_but_prior_screen_missed_or_mixed_scope','Mixed disease manual text explicitly mentions milkfish; original local source identity not verified.'),
 '虱目魚|Climate / Cold':('source_found_but_local_source_unverified','FA cold guide candidate in corpus; external official guidance found; no source bytes downloaded this run.'),
 '吳郭魚|Climate / Cold':('related_content_found_species_specificity_and_source_match_pending','Tilapia study discusses overwintering and low-temperature adaptation; source PDF not byte-matched and study conditions do not establish a general threshold.'),
 '石斑魚|Disease':('source_present_prior_screening_miss','Official TFRIN Manual 17 local source and page provenance verified; atomic unit/dedup review remains.'),
 '石斑魚|Safe Medication / Law':('official_law_present_item_level_review_pending','Current MOA annex is present; exact provision, species scope, approved purpose and applicable conditions not yet verified.'),
 '鱸魚|Safe Medication / Law':('official_law_present_item_level_review_pending','MOA annex lists taxonomic scope including sea bass names; this alone does not prove a specific medicine is authorized for a specific use.'),
 '烏魚|Disease':('source_present_prior_screening_miss','Official TFRIN Manual 17 local source and page provenance verified; atomic unit/dedup review remains.'),
 '鰻魚|Climate / Cold':('relevant_local_content_source_unverified_external_scope_mismatch','Japanese eel aquaculture candidate exists locally but source identity is unverified; discovered official pages are 鱸鰻-specific or fry-transport-only.'),
}
for cell in cell_counts:
 s,c=cell.split('|'); st,detail=reason[cell]
 zero_audit.append({'species':s,'category':c,'step2_screening_candidate_count':0,'targeted_keyword_hit_rows':cell_counts[cell],'classification':st,'finding':detail,'new_ready_units':0,'structurally_infeasible':False,'next_action':'Verify exact source bytes, page/span, species scope, quality and distinctness; keep candidate in review queue.'})
writej('zero_candidate_cell_audit.json',{'baseline':'Step 2B frozen; audit does not mutate Step 2B','cells':zero_audit,'summary':{'cells_audited':8,'cells_with_textual_hits':sum(1 for x in cell_counts.values() if x>0),'cells_with_new_ready_units':0,'downloaded_sources':0,'structurally_infeasible_claims':0}})

cov=[]
for x in matrix['cells']:
 key=x['species']+'|'+x['category']
 if key in cell_counts:
  status,detail=reason[key]
  cov.append({'species':x['species'],'category':x['category'],'step2_ready_units':x['new_silver_ready_count']+x['new_verified_ready_count'],'targeted_hit_rows':cell_counts[key],'external_official_sources_discovered':True,'external_file_downloaded':False,'candidate_status':status,'evidence_note':detail,'step3a_ready_unit_delta':0,'shortfall_to_five':5-(x['new_silver_ready_count']+x['new_verified_ready_count'])})
writej('source_to_cell_coverage.json',{'external_downloads':0,'official_web_records_discovered':len(disc),'cells':cov})
gaps=[]
for x in matrix['cells']:
 if x['category'] not in ['Fact','Water Quality','Disease','Climate / Cold']: continue
 key=x['species']+'|'+x['category']; n=x['new_silver_ready_count']+x['new_verified_ready_count']
 gaps.append({'species':x['species'],'category':x['category'],'ready_units_preserved_from_step2b':n,'ready_units_added_step3a':0,'remaining_shortfall_to_five':max(0,5-n),'zero_candidate_in_step2':key in cell_counts,'targeted_discovery_status':reason.get(key,('not_targeted_this_step','Existing Step 2B candidates remain subject to their recorded review gates.'))[0],'next_source_or_review_action':reason.get(key,('existing_candidate_review','Continue source-to-span verification/dedup for existing candidates.'))[1]})
writej('normal_risk_gap_reassessment.json',{'normal_risk_categories':['Fact','Water Quality','Disease','Climate / Cold'],'step2b_ready_units_preserved':7,'step3a_new_ready_units':0,'ready_units_total':7,'shortfall_to_120':113,'cells':gaps,'no_structural_infeasibility_inferred':True})

law={'verified_ready_units_before':0,'verified_ready_units_added':0,'official_current_source_records':1,'source':'MOA FL035443, revision/effective date recorded as 2025-01-08 in existing source record','official_url':'https://law.moa.gov.tw/LawContent.aspx?id=FL035443&media=print','local_source_path':'data/recovery/raw_sources/moa_animal_drug_use_rules_attachment_1_FL035443.pdf','local_source_sha256':'b13b9492322d7c0de2e1f7bc4dcee8feb99431ca1085819a697f3966c6b92e3c','conclusion':'Source identity/current revision can be traced, but no medicine-specific unit is promoted. General aquatic-animal/taxonomic scope is distinct from species-specific approval, indication, dose, withdrawal period, and farming-use authorization.','cells':{'石斑魚':'generic official MOA source found, but no exact species-specific source span mapped; taxonomic naming and item-level applicability need legal review','鱸魚':'annex includes sea-bass group names; specific drug/use authorization remains unverified'},'not_provided':['dose','withdrawal period','treatment recommendation'],'manual_review_required':True}
writej('medication_law_source_audit.json',law)

calc_out={'candidate_assignments':72,'unique_chunks':70,'formula_cue_rows':5,'literal_cue_details':calc['formula_candidates'],'duplicate_groups':calc['formula_duplicate_groups'],'verified_formula_units':0,'deterministic_gold_answers_created':0,'official_external_formula_records_discovered':2,'downloads':0,'blockers':['SGR/FCR cues are not distinct formula knowledge units by fish species merely due repeated pages/inputs.','Candidate source identity/evidence bytes remain unverified or not locally staged.','Candidate descriptions do not establish all variable definitions, unit conventions, valid ranges, assumptions, rounding, and tolerance.','External formula source found applies to another species or is only a high-level definition; transfer to six target species is unsupported.'],'no_llm_gold_used':True}
writej('calculation_source_audit.json',calc_out)

admission=[]
for x in candidate_rows:
 admission.append({'queue_id':x['candidate_id'],'candidate_type':'existing_corpus_targeted_hit','species':x['species'],'category':x['category'],'chunk_id':x['chunk_id'],'document_id':x['document_id'],'page':x['page'],'status':'needs_review','review_gates':['source identity/version','original source bytes and page/span','parser/source quality','species/applicability','atomic direct support','duplicate control'],'ready_unit_count':0})
for r in disc:
 admission.append({'queue_id':'source_'+r['source_id'],'candidate_type':'external_official_source_record','source_id':r['source_id'],'url':r['official_url'],'status':'needs_review' if r['retrieval_status']=='discovered' else 'provenance_verified','downloaded':False,'review_gates':['retrieve original file/page','verify checksum and effective/version dates','verify scope and exact span','license/access review']})
writel('admission_review_queue.jsonl',admission)

diag={
 'sandbox_mode':'workspace-write; repository is writable, but pytest-created nested TemporaryDirectory paths were denied on create/cleanup',
 'interpreter_inventory':[
  {'path':'C:/Users/ethan/anaconda3/python.exe','python':'3.14.6','pytest':'9.0.3','python_docx':False,'pymupdf':False,'selection':'used for controlled pytest reruns; collection dependencies incomplete'},
  {'path':'C:/Python314/python.exe','python':'3.14.7','pytest':False,'python_docx':False,'pymupdf':False,'selection':'available interpreter; no pytest'},
  {'path':'.venv/Scripts/python.exe','python':'3.14.7','pytest':False,'python_docx':True,'pymupdf':True,'selection':'project dependencies available; no pytest'},
  {'path':'.venv-ragas/Scripts/python.exe','python':'3.14.7','pytest':False,'python_docx':False,'pymupdf':False,'selection':'not suitable for repository test suite'},
  {'path':'.venv-reranker/Scripts/python.exe','python':'3.14.7','pytest':False,'python_docx':False,'pymupdf':False,'selection':'not modified; not suitable for repository test suite'}],
 'temp_write_read_delete_probe':'PASS for a fixed file in approved Step3A tmp directory',
 'pytest_basetemp_rerun':'isolated basetemp alone did not resolve Python TemporaryDirectory nested create/cleanup denial',
 'temp_tmp_rerun':'TEMP/TMP redirected to approved Step3A temp root; fixed-file probe passed, but tests still returned WinError 5 for TemporaryDirectory child creation/cleanup',
 'sandbox_effect':'Python created some directories that became inaccessible to the process; cleanup was denied. No ACL/security changes attempted; no escalation.',
 'network':'Official website metadata/pages were searched in browser; local HTTPS fetch via configured proxy failed with connection refused to 127.0.0.1:9; zero downloads.',
 'dependencies_installed':False,'test_sources_modified':False,'formal_lockfiles_modified':False}
writej('test_environment_diagnostics.json',diag)

repro={
 'baseline_step2b':{'passed':525,'skipped':6,'failed':22,'errors':4,'subtests_passed':2,'reported_collection_errors':9},
 'controlled_reruns':[
  {'attempt':1,'runner':'Anaconda pytest 9.0.3 / Python 3.14.6','basetemp':'new Step3A controlled temp root','passed':525,'skipped':6,'failed':22,'errors':4,'subtests_passed':2,'exit_code':1},
  {'attempt':2,'runner':'same interpreter/pytest; TEMP and TMP redirected to Step3A temp root','passed':525,'skipped':6,'failed':22,'errors':4,'subtests_passed':2,'exit_code':1}],
 'latest_tests_collection':{'scope':'tests directory','collected':594,'collection_errors':7,'cause':'missing python-docx / PyMuPDF imports in Anaconda interpreter','exit_code':2},
 'full_repository_collection_exploratory':{'result':'not_authoritative','reported_errors':75,'cause':'collection traversed generated temporary paths that the sandbox denied, plus missing imports; no tests executed'},
 'triage':{'22 failed and 4 errors': 'Windows sandbox TemporaryDirectory path create/write/cleanup PermissionError (WinError 5), reproduced at suite level; no assertion-level code regression established','7 current collection errors':'missing python-docx or PyMuPDF in selected Anaconda interpreter','previous 9 collection errors':'7 dependency import errors plus 2 temporary-path access errors','confirmed_code_regression':0,'reproducible_test_suite':False,'required_next_action':'Use an approved cleanable temp root and an interpreter with repository dependencies; do not install dependencies or edit tests without separate review.'},
 'inaccessible_test_temp_dirs_left_in_place':True,'cleanup_attempt':'precise PowerShell cleanup was denied by sandbox; left untouched'}
writej('test_reproduction_results.json',repro)

compatibility_out={
 'step2b_baseline_compatibility_pass':compat.get('overall_protected_compatibility_pass'),
 'protected_phase15_20_files':{'count':compat.get('phase15_20_protected_file_count'),'mismatches':compat.get('phase15_20_mismatch_count')},
 'phase20_immutable_files':{'count':compat.get('phase20_immutable_file_count'),'mismatches':compat.get('phase20_immutable_mismatch_count')},
 'evaluation_corpus_v2_sha256':compat.get('evaluation_corpus_v2_sha256'),
 'evaluation_corpus_matches_step2':compat.get('evaluation_corpus_matches_step2'),
 'rag_store_sqlite3':compat.get('rag_store_sqlite3'),
 'M1_M4_and_judge_identity_matches':{k:v.get('matches') for k,v in compat.get('ollama_api_tags_full_digest_checks',{}).items()},
 'E1_E2_historical_E4':'protected by Phase20.1R/Step2 checksum manifests; no index/retrieval files written in Step3A',
 'Step2B_reports':'read-only; not overwritten',
 'new_external_downloads':0,'official_corpus_admissions':0,'formal_E4_rebuilds':0,'production_app_or_prompt_or_retrieval_modified':False,
 'production_http_smoke':'not run: existing listener was absent in baseline; did not start or alter Production',
 'test_tmp_cleanup_limitation':'some pytest temp directories under Step3A tmp became sandbox-inaccessible; left as diagnostics'}
writej('compatibility.json',compatibility_out)

manifest={'phase':'RAG v2 Phase 20.1E Exec r3 Step 3A','status':'completed_with_blockers','created_at_utc':datetime.now(timezone.utc).isoformat(),'report_directory':str(OUT),'input_baseline':'Phase 20.1E Step 2B; immutable','targeted_zero_candidate_cells':8,'existing_corpus_keyword_hit_rows':len(hits),'candidate_hits_are_evidence_units':False,'official_web_records_discovered':len(disc),'new_official_source_files_downloaded':0,'source_additions_this_run':0,'official_corpus_admissions':0,'formal_e4_rebuilds':0,'formal_benchmark_questions':0,'model_evaluations':0,'winner':None,'limitations':['sandbox temp directory errors prevent a clean full test pass','proxy refused source downloads; external records are URL-only','candidate keyword hits are not promoted Evidence Units']}
writej('execution_manifest.json',manifest)
writej('staged_source_manifest.json',{'new_source_files_downloaded':0,'new_source_bytes_staged':0,'records':staged,'preexisting_local_corpus_sources_inspected':existing_files,'network_error':'Configured proxy at 127.0.0.1:9 refused local HTTPS request; no download attempted again.'})
writej('proposed_corpus_versioning_plan.json',{'current_corpus':'Evaluation Corpus v2','current_sha256':compat.get('evaluation_corpus_v2_sha256'),'source_additions_this_run':0,'official_corpus_admissions':0,'corpus_rebuild_this_run':False,'E4_rebuild_this_run':False,'next_step':'After source admission review, any approved new source requires a new versioned Evaluation Corpus and separate E4-Final; never overwrite v2/E4.'})
writej('readiness_after_step3a.json',{'four_models_ready':True,'independent_judge_ready':True,'normal_evidence_ready':False,'normal_ready_units_preserved':7,'normal_ready_units_added':0,'high_risk_ready':False,'high_risk_verified_ready_units':0,'calculation_ready':False,'calculation_verified_units':0,'strict_matrix_ready':False,'final_corpus_ready':True,'e4_final_ready':True,'phase20_2_benchmark_construction_ready':False,'winner':None,'phase20_1R_baseline_preserved':True,'source_additions_this_run':0,'reason':'New targeted hits and external source records remain candidates only; no external files downloaded/admitted and no new Evidence Unit passed gates.'})

summary='''# Phase 20.1E Exec r3 — Step 3A\n\nStatus: completed with blockers; no formal Corpus/E4 change.\n\n## Evidence discovery\n\nThe Step 2B baseline remains immutable: 486 screened candidates (317 needs_review, 169 rejected), 14 pilot reviews, 7 existing Corpus-Grounded Silver units, six partially populated cells, eight Step 2 zero-candidate cells, zero cells at five units, zero Medication/Law verified units, zero Calculation verified units, Phase 20.2 not ready, Winner null.\n\nTargeted lexical discovery found text hits in all 8 zero-candidate cells. These are not Evidence Units. Two disease candidates map to source-verified TFRI Manual 17 pages (grouper p.91–92; mullet p.124) and were queued for atomicity/dedup review. The current MOA aquatic-drug annex is present and checksum-traced, but item-specific authorization remains unreviewed. Other candidates remain blocked by source identity, applicability, or document-quality checks. No new ready unit was promoted.\n\n11 official source/page records were identified; 0 new source files were downloaded. The configured local proxy refused HTTPS connection (127.0.0.1:9). Existing local files are separately labeled as pre-existing; no new bytes were staged. Candidate URLs and scope notes are in `official_source_discovery_registry.jsonl`.\n\n## Formula and legal review\n\nMedication/Law remains 0 verified units. No dosage, withdrawal period, or treatment advice was inferred. Calculation review remains 0 verified formulas and 0 deterministic gold answers: 5 formula-cue rows include 4 duplicate SGR cues; variables/units/ranges/assumptions/rounding/tolerance and source verification are incomplete.\n\n## Test recovery\n\nTwo unchanged controlled evaluation-suite reruns both returned 525 passed, 6 skipped, 22 failed, 4 errors (2 subtests passed). The 22 failures and 4 errors reproduced as Windows sandbox TemporaryDirectory path permission failures (WinError 5), not assertion failures. Latest tests-directory collection: 594 collected, 7 errors from missing python-docx/PyMuPDF in the selected Anaconda interpreter. A previous broad collection had 9 errors (those 7 plus 2 temp-path access errors). No packages or tests were changed. Test temp directories that became inaccessible were left untouched.\n\n## Compatibility and readiness\n\nFrozen checksums remain unchanged per the Step 2B compatibility baseline; Evaluation Corpus v2 SHA-256 is `'''+str(compat.get('evaluation_corpus_v2_sha256'))+'''`; SQLite size/hash/mtime match baseline. No Corpus admissions, E4 rebuilds, benchmark questions, model evaluations, or Production changes occurred. The pre-existing Production listener was absent; no service was started, so HTTP status was not tested.\n\nReadiness remains: normal evidence false (7 existing units preserved, 0 added), high-risk false, calculation false, Phase 20.2 false, Winner null. Step 3B Source Admission Review can proceed as a review of source records and exact bytes after the reviewer obtains them; it is not ready for direct admission.\n'''
(OUT/'step3a_summary.md').write_text(summary,encoding='utf-8')
print(json.dumps({'output_dir':str(OUT),'targeted_hit_rows':len(hits),'zero_cell_hits':cell_counts,'official_records':len(disc),'downloaded':0,'files_written':len(list(OUT.glob('*')))},ensure_ascii=False,indent=2))
