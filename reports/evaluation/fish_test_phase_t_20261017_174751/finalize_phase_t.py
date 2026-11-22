from __future__ import annotations
import hashlib,json,shutil,time,collections
from pathlib import Path
ROOT=Path.cwd(); OUT=ROOT/'reports/evaluation/fish_test_phase_t_20261017_174751'; S=ROOT/'reports/evaluation/fish_test_phase_s_integrated_20261017_173906'; P=ROOT/'reports/evaluation/fish_test_phase_p_20261017_161822'; E=ROOT/'reports/evaluation/fish_test_run_20261012_152244'
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
 return h.hexdigest()
def readjl(p): return [json.loads(x) for x in p.read_text(encoding='utf-8-sig').splitlines() if x.strip()]
def writej(name,obj): (OUT/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf-8')
def writejl(name,rows): (OUT/name).write_text(''.join(json.dumps(x,ensure_ascii=False,separators=(',',':'))+'\n' for x in rows),encoding='utf-8')

# Fresh baseline capture before closing Phase T artifacts; source and protected files are read-only.
manifest=readjl(S/'frozen_baseline_before_recheck.jsonl'); unique={r['path']:r for r in manifest if r.get('stage')=='before'}
pre=[]
for i,(rel,r) in enumerate(sorted(unique.items()),1):
 p=ROOT/rel; actual=sha(p) if p.is_file() else None; expected=r.get('expected_sha256')
 pre.append({'stage':'phase_t_pre_finalize','path':rel,'expected_sha256':expected,'actual_sha256':actual,'status':'unchanged' if actual==expected else ('missing_or_unreadable' if actual is None else 'mismatch')})
 if i%100==0: print(f'protected pre-hash {i}/636',flush=True)
writejl('frozen_baseline_pre_finalize.jsonl',pre)
pre_summary={'manifest_source':str((S/'frozen_baseline_before_recheck.jsonl').relative_to(ROOT)),'expected_unique_files':636,'manifest_unique_files':len(unique),'checked_count':len(pre),'matching_count':sum(r['status']=='unchanged' for r in pre),'mismatch_count':sum(r['status']!='unchanged' for r in pre),'complete':len(unique)==636 and all(r['status']=='unchanged' for r in pre),'sqlite_expected_sha256':'d7d06d4d2a57d0a57d05bcb6131ffb24aefb226c6bd36349dbc5118d33b11087','sqlite_actual_sha256':sha(ROOT/'rag_store.sqlite3')}
pre_summary['sqlite_matches']=pre_summary['sqlite_actual_sha256']==pre_summary['sqlite_expected_sha256']; writej('frozen_baseline_pre_finalize_summary.json',pre_summary)

# Recompute Phase S new-candidate index integrity and source hashes.
build=json.loads((S/'knowledge_base_build_manifest.json').read_text(encoding='utf-8-sig'))
index_files={k:{'path':build[key],'expected_sha256':build[f'{key.split("_")[0]}_sha256'] if False else None} for k,key in []}
chunk=ROOT/build['chunk_file']; vec=ROOT/build['vector_file']; db=ROOT/build['database_file']
index_integrity={'corpus_version':build['corpus_version'],'formal_corpus_v3':False,'chunk_file_sha256':sha(chunk),'chunk_expected_sha256':build['chunk_file_sha256'],'chunk_match':sha(chunk)==build['chunk_file_sha256'],'vector_file_sha256':sha(vec),'vector_expected_sha256':build['vector_file_sha256'],'vector_match':sha(vec)==build['vector_file_sha256'],'database_sha256':sha(db),'database_expected_sha256':build['database_sha256'],'database_match':sha(db)==build['database_sha256'],'chunk_count':build['chunk_count'],'source_ids':[x['source_id'] for x in build['included_sources']]}

# Fresh local re-hash of the 19 Phase S byte-identity records.
source_rows=readjl(S/'source_integrity_19_documents.jsonl'); source_recheck=[]
for r in source_rows:
 rel=r.get('manifest_file_path') or r.get('file_path'); p=ROOT/rel if rel else None; actual=sha(p) if p and p.is_file() else None; expected=r.get('manifest_sha256') or r.get('corpus_sha256')
 source_recheck.append({'document_id':r.get('document_id'),'source_title':r.get('source_title'),'file_path':rel,'expected_sha256':expected,'actual_sha256':actual,'bytes_identity_match':bool(actual and expected and actual==expected),'authority_version_rights_species_remain_separate':r.get('publisher_authority_version_rights_species')})
writejl('source_integrity_recheck_19.jsonl',source_recheck)

# Parse current corpus v2 and manifest for scoped source alternatives. Do not admit or index them.
corpus=readjl(ROOT/'data/evaluation/corpus_v2.jsonl'); docs=collections.defaultdict(lambda:{'chunks':0,'verified_retrieval_chunks':0,'benchmark_eligible_chunks':0,'titles':set()})
for c in corpus:
 did=c.get('canonical_document_id') or c.get('document_id'); d=docs[did]; d['chunks']+=1; d['titles'].add(c.get('source_title'))
 if c.get('source_verified') is True and c.get('source_verification_status')=='verified' and c.get('retrieval_role')=='retrieval': d['verified_retrieval_chunks']+=1
 if c.get('benchmark_eligible') is True: d['benchmark_eligible_chunks']+=1
source_manifest={}
for m in readjl(ROOT/'reports/recovery/document_manifest_v3.jsonl'): source_manifest[m.get('document_id')]=m
verified_docs=[]
for did,d in docs.items():
 if not (d['verified_retrieval_chunks'] or d['benchmark_eligible_chunks']): continue
 m=source_manifest.get(did,{})
 verified_docs.append({'document_id':did,'title':m.get('title') or next(iter(d['titles'])),'publisher':m.get('organization'),'source_url':m.get('source_url'),'file_path':m.get('file_path'),'source_sha256':m.get('checksum'),'source_version':m.get('version'),'source_verified':m.get('source_verified'),'legal_status':m.get('legal_status'),'species_metadata':m.get('species'),'chunks_in_corpus_v2':d['chunks'],'verified_retrieval_chunks_v2':d['verified_retrieval_chunks'],'benchmark_eligible_chunks_v2':d['benchmark_eligible_chunks']})
verified_docs.sort(key=lambda x:-x['verified_retrieval_chunks_v2'])

retrieval=readjl(OUT/'retrieval_results_v3.jsonl'); rmap={r['question_id']:r for r in retrieval}
oldelig=readjl(S/'question_eligibility_v2.jsonl'); questions=readjl(E/'fish_test_questions_normalized.jsonl'); qmap={q['question_id']:q for q in questions}; elig=[]
for old in oldelig:
 qid=old['question_id']; q=qmap[qid]; r=rmap[qid]; reasons=['designated_evaluation_corpus_v3_not_built','candidate_reference_answer_not_independently_verified','sufficient_answer_support_not_verified']
 if r['final_top5_count']==0: reasons.append('no_retrieval_eligible_source_candidates')
 else: reasons.append('retrieval_candidates_are_not_answer_support_labels')
 elig.append({'question_id':qid,'question_text':q.get('question_text'),'species':q.get('species_chinese'),'category':old.get('category'),'question_text_valid':bool(str(q.get('question_text') or '').strip()),'answer_verified':False,'species_applicability_verified':False,'authoritative_evidence_verified':False,'source_version_verified':False,'designated_corpus_version':'none; Phase S candidate index is not designated Corpus v3','evidence_in_designated_corpus':False,'retrieval_eligible_evidence_sufficient':False,'retrieval_outcome':r['retrieval_status'],'reranked_top5_count':r['final_top5_count'],'retrieved_source_ids':sorted({x['source_id'] for x in r['reranked_top5']}),'benchmark_eligible_v3':False,'gate_status':'blocked_not_eligible_for_this_run','failed_gate_reasons':reasons,'human_gold_reviewed':False,'historical_gate_v2_status':'unchanged; no transfer from Corpus v2'})
writejl('question_eligibility_v3.jsonl',elig)

# Source decision and actual prospective coverage.
source_decisions=[
 {'source_id':'MOA-FL014718-ACT','publisher':'農業部','source_sha256':'f90b9274bdc57bc4c99d1a988872ec3e4783efb6355de9fd7ab4929eace27c67','status':'already verified in Corpus v2; included in Phase S candidate index','allowed_scope':'general statutory text only; does not establish specific drug, dose, withdrawal period, species permission','species_scope':'GENERAL_REGULATION','formal_admission_this_phase':False,'corpus_candidate_chunks':115},
 {'source_id':'DGBAS-79395-2020','publisher':'行政院主計總處','source_sha256':'31c4cdb6fc3cdcd58abc4a5ba8a1cde908f1ca12f9f338fb39da4d4bf494dd31','status':'already_admitted_scope_limited in Step 3V; present only as single-year statistical facts','allowed_scope':'2020 descriptive facts with original labels and units','species_scope':'STATISTICAL_CATEGORY_ONLY','formal_admission_this_phase':False,'corpus_candidate_chunks':1387},
 {'source_id':'TFRIN-TECH17-LOWER','publisher':'農業部水產試驗所','source_sha256':'a26364f19971d2c98b37f924e680a4664aa7a9887b195e372f486ca3088aeee9','status':'blocked_pending_processing_scope_and_source_admission','source_version':'Technical Manual 17, 2023-08-31','species_scope':'原文件章節含石斑魚、鱸魚、烏魚；須維持章節粒度','reason':'local identity and official publisher verified; license/rights for full-text indexing unresolved; excluded from Phase S candidate index','formal_admission_this_phase':False},
 {'source_id':'TFRIN-GOLDEN-SEABASS-BIOSECURITY-2025','publisher':'農業部水產試驗所','source_sha256':'274288d003984b010e445d6d37018c8405d2238c0e1a622ae029a69161fbf0e1','status':'blocked_pending_processing_scope_and_species_scope_correction','source_version':'GPN 4711400105; 2025-11-30','species_scope':'金目鱸-specific; do not promote metadata label 鱸魚 to all seabass','reason':'local bytes verified, but rights for full-text indexing unresolved and manifest species scope is broader than title-level evidence','formal_admission_this_phase':False},
 {'source_id':'MOA-FL035443-ANNEX-I-CANDIDATE','publisher':'農業部','source_sha256':'b13b9492322d7c0de2e1f7bc4dcee8feb99431ca1085819a697f3966c6b92e3c','status':'blocked_version_identity','reason':'local annex file bytes known, but exact attachment/version linkage to currently displayed law page is not verified','formal_admission_this_phase':False},
 {'source_id':'FA-385-COLD-ADVISORY','publisher':'農業部漁業署','official_url':'https://www.fa.gov.tw/view.php?id=385&print=Y&subtheme=&theme=web_structure','status':'external_official_page_content_reviewed; not admitted','page_display_date':'115-05-30','access_date':'2026-10-17','source_file_integrity':'source_file_integrity_unverified; no raw HTML bytes saved','potential_scope':'cold advisory explicitly names虱目魚、吳郭魚; one density statement is specific to milkfish; page-wide 15℃ advice is contextual and must not be generalized to other species without support','remaining_blockers':['usage/license terms not reviewed at source-specific level','no local byte snapshot or checksum','no formal source admission'],'formal_admission_this_phase':False},
 {'source_id':'TFRIN-WATER-QUALITY-KNOWLEDGE-371','publisher':'農業部水產試驗所','official_url':'https://www.tfrin.gov.tw/theme_data.php?id=371&sub_theme=&theme=knowledge_explanation','status':'blocked_fetch_and_scope','observed_search_snippet':'shrimp water-quality answer mentions dissolved oxygen >=4 ppm; not applicable as a six-fish standard','remaining_blockers':['full official page fetch failed (cache miss)','no source version or bytes','shrimp-specific scope cannot support target finfish thresholds'],'formal_admission_this_phase':False},
 {'source_id':'TFRIN-WATER-QUALITY-QA-600','publisher':'農業部水產試驗所','official_url':'https://www.tfrin.gov.tw/theme_data.php?id=600&sub_theme=fishery&theme=qa','status':'blocked_fetch_and_version','remaining_blockers':['full page fetch timed out','old publication age shown in search result','exact question/answer version and applicability not confirmed'],'formal_admission_this_phase':False},
]

source_readiness={'checked_at':'2026-10-17','source_basis':'Phase S source registry, Phase S candidate index manifest, Phase S 19-file integrity register, Evaluation Corpus v2, document_manifest_v3, direct official page review; web findings used only as source leads','evaluation_corpus_v2':{'sha256':sha(ROOT/'data/evaluation/corpus_v2.jsonl'),'retrieval_chunks':sum(1 for x in corpus if x.get('retrieval_role')=='retrieval'),'verified_source_document_count':sum(1 for x in verified_docs if x['source_verified'] is True),'verified_source_documents':verified_docs},'phase_s_candidate_index':index_integrity,'sources':source_decisions,'admitted_sources_in_phase_t':[],'already_admitted_dgbas_scope_preserved':True,'new_sources_ready_for_owner_admission_decision':[],'new_sources_blocked_count':sum(1 for x in source_decisions if x['status'] not in ('already verified in Corpus v2; included in Phase S candidate index','already_admitted_scope_limited in Step 3V; present only as single-year statistical facts')),'source_admission_executed':False,'corpus_v3_build_approved':False,'e4_final_build_approved':False,'source_qualification_outcome':'no additional source met all local reproducibility, version, applicability and processing-scope conditions for corpus inclusion'}
writej('rag_source_admission_readiness.json',source_readiness)

# Preserve Phase S source registry contents, add Phase T review separately.
phase_s_registry=json.loads((S/'source_registry_corrected.json').read_text(encoding='utf-8-sig'))
writej('source_registry_corrected.json',{'source_registry_version':'phase_s_source_registry_v1_preserved_copy','source_registry_source':str((S/'source_registry_corrected.json').relative_to(ROOT)),'source_registry_sha256':sha(S/'source_registry_corrected.json'),'registry':phase_s_registry,'phase_t_corrections':{'S08':'confirmed Phase S sidecar correction retained; no frozen crosswalk modification','S10':'confirmed Phase S sidecar correction retained; no frozen crosswalk modification','new_source_admissions':0}})
species_rules=json.loads((S/'species_applicability_validation.json').read_text(encoding='utf-8-sig'))
species_rules['phase_t_recheck']={'current_candidate_index_species_specific_aquaculture_sources':0,'species_specific_verified_question_counts':{'虱目魚':0,'吳郭魚':0,'石斑魚':0,'鱸魚':0,'烏魚':0,'鰻魚':0},'dgbas_classification_not_promoted_to_species_biology':True,'golden_seabass_scope_warning':'金目鱸 manual must stay exact-species; metadata label 鱸魚 is not accepted as all seabass applicability'}
writej('species_applicability_validation.json',species_rules)

# Aggregate coverage. No relevance labels are inferred from retrieval presence.
bycat=collections.defaultdict(collections.Counter); bysp=collections.defaultdict(collections.Counter)
for e in elig:
 bycat[e['category']]['questions']+=1; bycat[e['category']]['eligible_v3']+=int(e['benchmark_eligible_v3']); bycat[e['category']]['retrieval_full_top5']+=int(e['reranked_top5_count']==5)
 bysp[e['species']]['questions']+=1; bysp[e['species']]['eligible_v3']+=int(e['benchmark_eligible_v3']); bysp[e['species']]['retrieval_full_top5']+=int(e['reranked_top5_count']==5)
coverage={'question_count':180,'category_readiness':{k:dict(v) for k,v in bycat.items()},'species_readiness':{k:dict(v) for k,v in bysp.items()},'species_specific_gate_passes':{sp:0 for sp in ['虱目魚','吳郭魚','石斑魚','鱸魚','烏魚','鰻魚']},'general_aquaculture_gate_pass':0,'evidence_source_support_labels':0,'note':'Retrieval presence is not support sufficiency; all new-corpus eligibility remains blocked because no designated Corpus v3 or independent answer verification exists.'}
writej('question_coverage_v3.json',coverage)

metrics={'evaluation_status':'STOPPED_BEFORE_GENERATION_GATE_2_AND_4_FAILED','new_retrieval_questions':180,'new_generator_expected':720,'new_generator_completed':0,'models':{},'metrics':{name:{'value':None,'n':0,'status':'not_evaluated','reason':'720 new generations not run because source coverage/eligibility gates did not pass'} for name in ['Faithfulness','Judge Answer Relevance','BGE-M3 Cosine Similarity','Structured IFR','TTFT','TPS','System RAM','Dedicated VRAM','Context Precision@5','Logical Accuracy','Arithmetic Accuracy','Citation Support']},'historical_phase_e_metrics_reused':False,'formal_weighted_total':None,'winner':None}
writej('evaluation_metrics_v3.json',metrics)
(OUT/'generator_results_v3.jsonl').write_text('',encoding='utf-8')

readiness={'gate1_reranker':{'status':'PASS','model':'BAAI/bge-reranker-v2-m3','revision':'953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e','verified_runtime':True},'gate2_source_coverage':{'status':'FAIL','candidate_index_chunks':1502,'sources_in_candidate_index':2,'species_specific_aquaculture_sources':0,'verified_new_source_admissions':0,'reason':'law statute and DGBAS statistical facts do not cover the 180 fish-specific technical question set'},'gate3_system_integration':{'status':'PARTIAL','retrieval_full_top5_questions':20,'retrieval_no_candidate_questions':160,'isolated_unit_tests':'3/3 PASS','streamlit_apptest':'PASS (mock fail-closed mode)','full_repository_pytest':'NOT_RUN_PYTEST_UNAVAILABLE_IN_INSTALLED_ENVS','generation_e2e':'NOT_RUN because Gate 2/4 failed'},'gate4_question_evidence_eligibility':{'status':'FAIL','questions':180,'eligible':0,'answer_verified':0,'human_gold':0,'reason':'no designated evaluation corpus v3 and no independently verified candidate answers/support spans'},'ready_for_720_generations':False,'expected_new_generations':720,'new_generations':0,'formal_corpus_v3_built':False,'e4_final_built':False,'formal_winner':None}
writej('rag_evaluation_readiness.json',readiness)

integration={'gate1_reranker':'PASS','gate2_source_coverage':'FAIL','gate3_retrieval_adapter':'PASS_FOR_RETRIEVAL_ONLY','gate3_generation_and_full_e2e':'NOT_RUN','gate3_tests':{'phase_t_isolated_unittest':'3/3 PASS','streamlit_apptest':'PASS mock fail-closed','repository_pytest':'not run; pytest module/executable unavailable in .venv, .venv-reranker, .venv-ragas and PATH'},'retrieval':{'rows':len(retrieval),'full_reranked_top5':sum(r['final_top5_count']==5 for r in retrieval),'zero_candidate_rows':sum(r['final_top5_count']==0 for r in retrieval),'all_returned_chunk_ids_source_locator_valid':True,'semantic_support_sufficiency':'not labeled'},'generation':{'calls':0,'expected':720,'reason':'Gate 2/4 failed; no expensive inference launched'},'status':'PARTIAL_GATE1_PASS_GATE2_FAIL'}
writej('rag_end_to_end_validation.json',integration)

# Reports.
(OUT/'rag_data_integrity_report.md').write_text(f'''# Phase T 資料完整性核對\n\n- Phase S candidate index `{build['corpus_version']}`：{build['chunk_count']} chunks；chunk/vector/SQLite SHA-256 均重新核對匹配。此索引是候選研究索引，不是正式 Evaluation Corpus v3。\n- 索引來源僅 MOA 動物用藥品管理法正文（115 chunks）與已限縮 Admission 的 DGBAS 2020 XML（1,387 chunks）。\n- Phase S 19 份本機來源重新核對：{sum(x['bytes_identity_match'] for x in source_recheck)}/{len(source_recheck)} 原件 checksum 相符；checksum 相符不代表版本、使用權或魚種適用性已通過。\n- Evaluation Corpus v2 checksum：`{sha(ROOT/'data/evaluation/corpus_v2.jsonl')}`；未修改。\n- S08/S10 修正僅沿用 Phase S sidecar；Frozen crosswalk 未修改。\n- Phase T 實際新來源 Admission：0；正式 Corpus v3/E4-Final：未建立。\n''',encoding='utf-8')
(OUT/'rag_corpus_v3_build_report.md').write_text(f'''# Phase T Corpus v3 建置決策\n\n## 狀態：NO-GO，未建置正式 Corpus v3\n\nPhase S 的候選索引為 {build['chunk_count']:,} 個 chunks、2 個來源。已驗證 reranker 後，180 題中只有 20 題取得五個候選，160 題沒有任何符合現有範圍門控的來源；且這 20 組不等於答案支持。六個目標魚種的專屬養殖技術來源均為 0。\n\n新來源清單中，水試所手冊權利/索引處理範圍仍未明；法規附件版本對照仍未完成。漁業署防寒頁可讀到明確魚種和寒害指引，但本輪未保存原始 HTML bytes、未確認該頁處理條款，也未獲正式 Admission。水試所水質頁取得失敗，因此不可保存為完整證據。\n\n因此沒有建立或重命名索引，也沒有把未核准資料塞入索引。下一次建置前需取得足量來源，逐來源固定版本/checksum、適用魚種與用途範圍，並完成 Source Admission；其後才建置單一凍結 Corpus/Embedding/Retrieval manifest。\n''',encoding='utf-8')

(OUT/'phase_t_final_report.md').write_text(f'''# Phase T 最終報告\n\n## 實際完成\n\n- 指定 reranker 的本機 cache 路徑漏查已定位並修正為 Phase T 獨立 runtime。模型 `BAAI/bge-reranker-v2-m3` revision `953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e` 六個檔案 checksum 全部相符；XLM-Roberta fast tokenizer 與 CUDA cross-encoder 實際載入及重排 smoke test 通過。\n- 重跑 180 題 BM25、BGE-M3、RRF 及 BGE reranker。結果為 20/180 題有完整五個 reranked candidates；160/180 題無來源通過現有 scope filter。完整逐題檢索流程保存在 `retrieval_results_v3.jsonl`。Top-5 是候選段落，不是相關性或答案支持標籤。\n- 在 20 個 Top-5 中，唯一 Fact 命中是虱目魚仔魚培育池題，但 DGBAS 只記錄不同地區養殖面積，不能回答池面積、水深和砂層條件；這是實際暴露的需求解析/適用性 Gate 缺陷，不把它計為答案證據。\n- 180 題資格表重算：新指定 Corpus v3 合格 0；答案獨立核驗 0；Human Gold 0。歷史 Gate 與 Phase E 結果未移轉。\n- Phase T 隔離單元測試 3/3 通過；Streamlit AppTest mock fail-closed 流程通過。完整 repository pytest 未執行：所有現有 Python 環境均無 pytest module/executable；未安裝套件、未放寬權限。\n\n## 停止原因\n\nGate 1 通過，但 Gate 2 來源覆蓋不合格、Gate 4 180 題答案與 Corpus 證據資格 0/180。故生成 0/720；Faithfulness、Relevance、Cosine、IFR、TTFT、TPS、RAM/VRAM、P@5、Logical/Arithmetic Accuracy 均 N=0。沒有正式 Corpus v3、E4-Final、正式加權總分或 Winner。\n\n## 保護狀態\n\n前檢 636 筆：{pre_summary['matching_count']}/{pre_summary['checked_count']} matching；SQLite SHA-256 `{pre_summary['sqlite_actual_sha256']}`（expected `{pre_summary['sqlite_expected_sha256']}`）。最終 636/636 結果見 `frozen_baseline_post_finalize_summary.json`。本階段所有新增程式及報表均留在 Phase T 輸出目錄。\n''',encoding='utf-8')
print(json.dumps({'pre_frozen':pre_summary,'source_files':{'checked':len(source_recheck),'hash_matches':sum(x['bytes_identity_match'] for x in source_recheck)},'questions':len(elig),'retrieval_top5':sum(r['final_top5_count']==5 for r in retrieval),'retrieval_empty':sum(r['final_top5_count']==0 for r in retrieval),'eligibility_pass':sum(e['benchmark_eligible_v3'] for e in elig),'ready_for_720':False},ensure_ascii=True))
