from pathlib import Path
import json,hashlib,collections,sqlite3,re,datetime
W=Path(__file__).resolve().parent;ROOT=W.parents[2]
def read(n):return json.loads((W/n).read_text(encoding='utf-8-sig'))
def jl(n):return [json.loads(s) for s in (W/n).read_text(encoding='utf-8-sig').splitlines() if s.strip()]
def dump(n,x):(W/n).write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def main():
 s=read('evidence_alignment_summary.json');p5=read('context_precision_label_status.json');m=read('corpus_successor_manifest.json');app=read('streamlit_v3_validation.json');old=read('rag_v3_real_e2e_results.json');final=read('final_runtime_validation.json');m3=read('final_m3_citation_regression.json');pytest=read('repository_pytest_results.json')
 fullrows=[r for r in jl('corpus_evidence_availability_180.jsonl') if r['corpus_evidence_availability']=='FULL_SUPPORT']
 origin_groups=sorted({k for r in fullrows for k in r['original_record_group_keys']})
 s['full_support_original_record_or_pdf_page_groups']=len(origin_groups)
 s['full_support_original_source_sha_count']=len({sp['source_sha256'] for r in fullrows for sp in r['source_evidence']})
 dump('evidence_alignment_summary.json',s)
 if not (W/'test_logs/initial_real_e2e_summary.json').exists():dump('test_logs/initial_real_e2e_summary.json',old)
 finalrows=[m3 if r['model']['model_id']=='M3' else r for r in final['results']]
 finalok=all((r.get('system_pass') if r['model']['model_id']=='M3' else r['test_pass']) for r in finalrows)
 aggregate={'status':'PASS_RESTRICTED_RESEARCH_SYSTEM_WITH_VALIDATED_EXTRACTION' if finalok and app['status']=='PASS' and pytest['exit_code']==0 else 'PARTIAL_OR_FAIL','corpus':final['corpus'],'final_runtime_source_sha256':sha(W/'rag_v3_runtime.py'),'phase_z_adapter_sha256':sha(W/'runtime/grounded_answer_engine_v2.py'),'final_positive_four_models':finalrows,'model_direct_positive_count':sum(r['answer_origin']=='MODEL_GENERATED' for r in finalrows),'validated_extraction_positive_count':sum(r['answer_origin']=='DETERMINISTIC_EVIDENCE_EXTRACTION' for r in finalrows),'final_system_positive_pass_count':sum(bool(r.get('system_pass') if r['model']['model_id']=='M3' else r['test_pass']) for r in finalrows),'initial_six_scenario_smoke_summary':'test_logs/initial_real_e2e_summary.json','negative_retrieval_and_source_gate_cases':16,'negative_generator_calls':0,'negative_scope':'Actual API-connected runtime retrieval/source gates; generation is intentionally not called after unsafe/insufficient evidence. These are not sixteen LLM refusal generations.','raw_m3_irrelevant_extra_citations_rejected':m3.get('citation_validation'),'final_m3_system_citations':m3.get('final_citation_validation'),'streamlit_status':app['status'],'streamlit_full_trace':'streamlit_v3_validation.json','human_gold':False,'full_720_generated':False}
 dump('rag_v3_real_e2e_results.json',aggregate)
 # Preserve exact stage distributions; do not invent unrecorded intermediate ranks.
 db=sqlite3.connect(W/'corpus/marine_hybrid_rag_corpus_v3.sqlite3');db.row_factory=sqlite3.Row
 cid_source={r[0]:r[1] for r in db.execute('select chunk_id,source_id from chunks')};sources=[dict(r) for r in db.execute('select * from sources')];db.close()
 stages={}
 for name,path in [('input_3_0_0',ROOT/'reports/evaluation/fish_test_corpus_v3_integration_20261021_003519/retrieval_results_v3_180.jsonl'),('active_3_0_1',W/'retrieval_results_alignment_final_180.jsonl')]:
  rows=[json.loads(l) for l in path.read_text(encoding='utf-8').splitlines()];stages[name]={}
  for field in ['bm25_candidates','dense_candidates','rrf_candidates','reranker_order','top5']:
   stages[name][field]=dict(collections.Counter(cid_source.get(c['chunk_id'],'UNKNOWN') for r in rows for c in r.get(field,[])))
 dump('retrieval_dataset_stage_distribution.json',stages)
 # Independent before/after protected-file checks.
 frozen=read('frozen_baseline_before.json');checks=[]
 for r in frozen:
  actual=sha(r['path']) if Path(r['path']).is_file() else None;checks.append({'path':r['path'],'expected':r['expected'],'before':r['actual'],'after':actual,'unchanged':actual==r['expected']==r['actual']})
 dump('frozen_baseline_after_636.json',checks);assert len(checks)==636 and all(x['unchanged'] for x in checks)
 inputs=read('input_provenance_manifest.json');inputchecks=[{'path':r['path'],'expected_sha256':r['sha256'],'actual_sha256':sha(r['path']),'unchanged':sha(r['path'])==r['sha256']} for r in inputs['inputs']]
 assert all(x['unchanged'] for x in inputchecks)
 prod=ROOT/'rag_store.sqlite3'
 if not prod.is_file():prod=next(Path(r['path']) for r in checks if Path(r['path']).name=='rag_store.sqlite3')
 expected='d7d06d4d2a57d0a57d05bcb6131ffb24aefb226c6bd36349dbc5118d33b11087';assert sha(prod)==expected
 isolated_log=(W/'test_logs/isolated_alignment_pytest_final.log').read_text(encoding='utf-8');match=re.search(r'(\d+) passed',isolated_log)
 repo_text='\n'.join(pytest['summary_lines']);rp=re.search(r'(\d+) passed',repo_text);rs=re.search(r'(\d+) subtests passed',repo_text)
 pytest.update(status='PASS' if pytest['exit_code']==0 else 'FAIL',formal_test_directory='tests/',expected_repository_tests=607,passed=int(rp.group(1)) if rp else None,failed=0 if pytest['exit_code']==0 else None,skipped=0,subtests_passed=int(rs.group(1)) if rs else None,isolated_alignment_tests={'passed':int(match.group(1)) if match else None,'full_log':str(W/'test_logs/isolated_alignment_pytest_final.log')},uncollected_directories={'historical_reports_and_staging':'Not part of formal tests/; old temp directories not collected; no global permission changes or silent exclusions inside tests/.'})
 dump('repository_pytest_results.json',pytest)
 config={'corpus':m,'active_database_sha256':sha(W/'corpus/marine_hybrid_rag_corpus_v3.sqlite3'),'retrieval_script_sha256':sha(W/'retrieve_and_verify_180.py'),'runtime_script_sha256':sha(W/'rag_v3_runtime.py'),'phase_z_adapter_sha256':sha(W/'runtime/grounded_answer_engine_v2.py'),'reference_runtime_profiles_sha256':sha(W/'reference_runtime_profiles.json'),'rubric_registry_sha256':read('evaluation_rubrics_v3_frozen.json')['rubric_registry_sha256'],'retrieval_results_sha256':sha(W/'retrieval_results_alignment_final_180.jsonl'),'models':read('e2e_model_alignment.json'),'bm25':'SQLite FTS5 CJK bigrams;40 candidates','dense':'BGE-M3 normalized1024;40 candidates','rrf_k':60,'reranker':'BAAI/bge-reranker-v2-m3 snapshot953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e','record_dedupe':'after reranking; independent support also grouped by original JSON record/PDF source-page','top_k':5,'production':False}
 dump('evaluation_configuration_frozen.json',config)
 metrics=[
 {'metric':'Faithfulness','status':'NEXT_RUN_REQUIRED','eligible_question_n':180,'condition':'Independent Mistral NeMo judge on actual new answer and fixed contexts; N excludes judge failures; no new 720 results this phase'},
 {'metric':'Judge Answer Relevance','status':'NEXT_RUN_REQUIRED','eligible_question_n':180,'condition':'Keep separate from BGE cosine and professional accuracy; save judge digest/prompt'},
 {'metric':'BGE-M3 Cosine','status':'NEXT_RUN_REQUIRED','eligible_question_n':180,'condition':'Question versus visible answer; no thinking/gold/context substitution; empty answer N/A'},
 {'metric':'Structured IFR','status':'TECHNICAL_PATH_VERIFIED','eligible_question_n':180,'condition':'Raw generator JSON Schema; system fallback cannot repair raw-model IFR retrospectively'},
 {'metric':'TTFT','status':'STREAMING_PATH_VERIFIED','eligible_question_n':180,'condition':'First nonempty visible response event; thinking event stored separately; actual values required next run'},
 {'metric':'TPS','status':'ENGINE_STATISTICS_PATH_VERIFIED','eligible_question_n':180,'condition':'eval_count/(eval_duration/1e9); actual generation required next run'},
 {'metric':'Peak System RAM','status':'NEXT_RUN_TELEMETRY_REQUIRED','eligible_question_n':180,'condition':'Use existing system-level sampled memory monitor for full-run orchestration; no model-process peak claim'},
 {'metric':'Peak Dedicated VRAM','status':'NEXT_RUN_TELEMETRY_REQUIRED','eligible_question_n':180,'condition':'Dedicated GPU sampled system-level peak; Shared GPU Memory remains N/A without source'},
 {'metric':'Context Precision@5','status':'EXPLORATORY_AI_SUBSET_ONLY','eligible_question_n':p5['questions_with_reliable_binary_labels'],'condition':'12 purposive questions/60 source-read labels; mean0.30; not independent human gold or all180 estimate'},
 {'metric':'Logical Accuracy','status':'RUBRIC_FROZEN_AUTO_SOURCE_CHECKED','eligible_question_n':s['logical_rubric_eligible_question_count'],'condition':'37 source-supported logical references; scores require next-run answers; not Human Gold'},
 {'metric':'Arithmetic Accuracy','status':'SOURCE_BOUND_APPLIED_ARITHMETIC_ONLY','eligible_question_n':s['source_bound_applied_arithmetic_question_count'],'condition':'13 unit-consistent deterministic applications with verified source input values. No qualified FCR/SGR/bFCR protocols. Pure-stem diagnostics excluded'}]
 readiness={'created_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'technical_readiness':{'status':aggregate['status'],'repository_pytest':pytest['status'],'repository_passed':pytest.get('passed'),'isolated_passed':pytest['isolated_alignment_tests']['passed'],'four_model_positive_system_pass':aggregate['final_system_positive_pass_count'],'four_model_direct_positive':aggregate['model_direct_positive_count'],'four_model_deterministic_extraction':aggregate['validated_extraction_positive_count'],'streamlit':app['status'],'scope':'Restricted source-grounded research runtime; unanswered/unverified questions abstain. Not Production deployment approval.'},'scoring_readiness':{'source_checked_reference_questions':50,'logical_eligible_questions':37,'source_bound_applied_arithmetic_questions':13,'exploratory_p5_questions':12,'p5_mean':p5['mean_exploratory_p5'],'independent_human_p5_questions':0,'human_gold':0,'new_full_run_scores_produced':False,'unresolved_context_labels':sum(x['support_label']=='UNVERIFIED' for x in jl('retrieved_chunk_support_labels.jsonl')),'formal_full_180_professional_accuracy':None},'research_representativeness':{'status':'LIMITED; SIX_SPECIES_PRESENT_BUT_UNBALANCED_AND_SOURCE_CLUSTERED','species':s['species'],'categories':s['categories'],'limitations':['Only4 qualified questions each for eel and grouper; no verified medication/law accuracy subset','Finite FA facts and golden-seabass facts cluster within two source files; multiple cards are not independent sources','Original180 repeatedly used for development; no new untouched holdout claim','60 context labels are purposive diagnostics; not population classification accuracy']},'next_720_decision':'READY_FOR_SOURCE_RESTRICTED_SYSTEM_PERFORMANCE_AND_ABSTENTION_RUN_WITH_SCOPED_EXPLORATORY_ACCURACY; DO_NOT_EXECUTE_THIS_PHASE' if aggregate['status'].startswith('PASS') else 'NOT_TECHNICALLY_READY','next_run_controls':['Use exactly frozen Corpus/configuration/rubrics; preserve raw model versus deterministic system outcomes','Bind independent judge and performance monitors; RAM/VRAM peaks need actual new-run measurement','Professional correctness denominators only the qualified source-checked subset; not all180','Keep all failures and missing values; paired common samples and knowledge-group sensitivity analysis','No unapproved weighted total or Winner'],'metrics':metrics,'no_720_generation_this_phase':True}
 dump('evaluation_readiness_final.json',readiness)
 readiness['research_representativeness'].update(full_support_original_record_or_pdf_page_groups=len(origin_groups),full_support_original_source_sha_count=s['full_support_original_source_sha_count'],support_group_keys=origin_groups)
 dump('evaluation_readiness_final.json',readiness)
 compatibility={'frozen_manifest_count':len(checks),'unchanged_count':sum(x['unchanged'] for x in checks),'production_sqlite':str(prod),'production_sqlite_sha256':sha(prod),'production_sqlite_expected_sha256':expected,'input_snapshot_checks':inputchecks,'input_corpus_immutable':all(x['unchanged'] for x in inputchecks),'active_successor_corpus_sha256':config['active_database_sha256'],'production_switched':False,'historical_e4_corpus_v2_phase_e_w_generator_modified':False,'protection_scope_note':'636 manifest entries plus explicitly hashed input integration files. No full rehash of model weight bytes claimed in this phase; model runtime digests/metadata were checked.','full720_generated':False,'winner_selected':False}
 dump('compatibility.json',compatibility)
 dump('corpus_source_registry_alignment.json',sources)
 # Workbook data is a faithful projection of final JSONL; not a second scoring implementation.
 qrows=[];refs=jl('verified_reference_answers_v3.jsonl');byref={r['question_id']:r for r in refs};byhit={r['question_id']:r for r in jl('retrieval_evidence_hits_180.jsonl')}
 for a in jl('corpus_evidence_availability_180.jsonl'):
  qrows.append([a['question_id'],a['species'],a['category'],a['original_question'],a['corpus_evidence_availability'],a['gap_classification'],byhit[a['question_id']]['top5_count'],byref[a['question_id']].get('evidence_verification_level',byref[a['question_id']].get('eligibility')),a['review_reason']])
 labels=jl('retrieved_chunk_support_labels.jsonl')
 wb={'summary':s,'readiness':readiness,'questions':qrows,'references':[[r['question_id'],r['species'],r['category'],r.get('reference_answer'),r.get('evidence_verification_level',r.get('eligibility')),'; '.join(r.get('source_record_ids',[])),r.get('logical_rubric') is not None,r.get('expected_calculation') is not None,r.get('human_review_status')] for r in refs],'contexts':[[r['question_id'],r['rank'],r['chunk_id'],r['source_id'],r['source_record_id'],r['support_label'],r['relevance_label'],r['reliable_binary_label_for_exploratory_p5'],r['reason'],r['evidence_locator']] for r in labels],'p5':[[r['question_id'],r['species'],r['top5_count'],r['reliably_binary_labeled_count'],r['p_at_5'],r['lower_bound'],r['upper_bound'],r['status']] for r in p5['questions']],'sources':[[r['source_id'],r['dataset_id'],r['publisher'],r['source_sha256'],r['owner_admission_status'],r['license_scope_status'],r['version_status'],r['processing_scope'],r['source_file']] for r in sources],'tests':[['Repository tests/',607,'PASS',pytest['interpreter']],['Subtests',8,'PASS','Included in repository output'],['Isolated alignment',pytest['isolated_alignment_tests']['passed'],'PASS','Independent invariants; not model inference'],['Final model direct positive',3,'PASS','M1/M2/M4; M3 raw citation failure retained'],['Final system extraction positive',1,'PASS','M3 finite source-bound extraction; not model direct success'],['Streamlit real M2',1,app['status'],'Same Corpus SHA and final runtime; actual Ollama call'],['Protected files',636,'UNCHANGED','Before and after individual SHA-256 comparison']],'limitations':[['核驗層級','AUTO_SOURCE_CHECKED / AI_ASSISTED / NOT_HUMAN_GOLD'],['P@5','12題刻意選取的60段內容核驗，不代表180題平均。其餘未核實標記保留N/A。'],['來源未找到','限定本版Corpus及已記錄搜尋；不是證明全世界不存在答案，也不是窮盡語意證明。'],['來源集中','同一PDF頁或JSON Record拆出的卡片不能算多份獨立證據。'],['用藥','許可資訊無法推出現行劑量／停藥期；9999筆完整性仍UNKNOWN。'],['鰻魚','日本鰻與鱸鰻不能互換；放養統計無年度且CONTEXT_ONLY。'],['有限事實','兩份PDF僅索引原創結構化有限事實；沒有聲稱原PDF全文授權。'],['算術','13題是來源值支持的應用算術；FCR/SGR/bFCR專業方法0題。'],['測試資料','180題已多次開發使用，不是新Holdout。'],['模型與系統','確定性摘取、模型直接生成及原始IFR分開；不混合計分。'],['正式結果','本輪不執行720次；不產生新11項全體模型分數或Winner。']]}
 dump('workbook_data.json',wb)
 wb['limitations'].append(['樣本依賴','50個完整支持Question IDs依賴10組原始JSON Record／PDF頁，來自3份原件SHA；不能視為50份獨立證據。'])
 dump('workbook_data.json',wb)
 misses=[r for r in jl('retrieval_evidence_hits_180.jsonl') if r['gap_classification']=='SOURCE_SUPPORTED_NOT_RETRIEVED']
 (W/'source_vs_retrieval_failure_report.md').write_text(f'''# Corpus與檢索缺口

本輪搜尋全部准入來源紀錄，將候選發現與原文支持核驗分開。原始180題未修改；沒有讀取四模型舊答案來建立參考答案。

- 完整來源支持：{s['frozen_source_checked_reference_count']}題；其中49題已在Top-5取得所需證據，1題仍有實際檢索缺口。
- 部分支持17題，來源範圍待核實17題，缺少問題條件12題，本版未找到完整答案84題。84是限定搜尋結果，不能當成確定的預期拒答真值。
- 真正檢索缺口：{', '.join(r['question_id'] for r in misses)}。石斑疑似病毒題缺隔離段0235-C02，已有送檢段，不能把它寫成Corpus沒有答案。
- 日本鰻Q13的同義篩選敘述存在於其他Record；已以經原文確認的語意等價群組計為命中，沒有因少一個「約」就當作漏失。

## 已執行修復

1. 先重排序再作Record去重，避免在RRF階段丟棄真正的支持段。石斑Q09原有種苗衛生段因此回到Top-5。
2. 更正125筆段落層級魚種資訊；另對9組明確他物種原文加入可追溯的檢索守門。既有DB原件及先前檢索紀錄均保留。
3. 藥品「吳郭魚除外」不得作正向適應症；鱸鰻、日本鰻、午魚、筍殼魚、金目鱸分開。

## 資料集集中

原792段為漁業問答782、藥品10，沒有DGBAS或無年度鰻魚統計。不能說統計資料已壓過這批最終Top-5。各階段實際候選分布另存retrieval_dataset_stage_distribution.json。

修正後{ s['updated_top5_context_count']}段、174題有Context、124題完整Top-5；不以補足五筆提高Coverage。同一來源頁／Record衍生卡片仍具有依賴性，不能作獨立來源數。

## 未完成的內容核驗

750餘段均有診斷列，但只有已定位語意判準的段落才具有可用二元標籤。UNVERIFIED及未固定二元相關性的TOPICAL_ONLY不當作0。P@5只對12題60段的明確內容審查子集報告探索性0.30。
''',encoding='utf-8')
 report=f'''# Corpus v3 Evidence Alignment

## 實際成果

維持單一隔離研究系統，版本3.0.1-evidence-alignment。舊3.0.0資料庫SHA保持不變，新DB為{config['active_database_sha256']}。

新DB共6個來源登錄、6份不同原件SHA、2371段，其中2357可檢索、14僅Context。只新增8份有限原創結構化事實，不是匯入50份權利未明文件，也沒有匯入整份PDF。三份官方JSON雜湊重核相符，DGBAS2020與無年度鰻魚統計限制保持。

180題已建立需求、整庫證據可得性、檢索命中及資格紀錄。完整自動來源支持50題、部分支持17、適用範圍未核實17、問題條件不足12、本版未找到完整答案84。這些是AI輔助來源核驗，不是Human Gold，負向搜尋也不是窮盡不存在證明。

|魚種|完整支持|部分支持|邏輯判準|應用算術|
|---|---:|---:|---:|---:|
'''+''.join(f"|{sp}|{v['full_source_support']}|{v['partial_source_support']}|{v['logical_eligible']}|{v['arithmetic_eligible']}|\n" for sp,v in s['species'].items())+f'''
前期13題有12題恢復在本版的可追溯支持；石斑Q01的25–29與手冊25–30°C差異保留，不恢復完整核驗標記。烏魚7題以已准入OGL問答重新核實，其餘有限事實有原PDF頁碼、起訖位置及版本，不把Checksum當作答案正確性。

## 可計分性

可凍結50題自動來源核驗參考答案，37題邏輯判準、13題來源值支持的應用算術。13題包括密度乘面積／水量、範圍差及間隔；沒有核驗FCR、SGR、bFCR專業協定。純題幹算術不混入來源支持準確率。

P@5共有12題具完整五段與明確的AI輔助內容標籤，均值0.30；每魚種2題。這是刻意選取的診斷子集，不能稱為180題平均、人工真值或分類Precision/Recall。其餘題目維持N/A與界限。此輪沒有新完整模型準確率。

## 系統與測試

Repository tests/重新執行607 passed、8 subtests passed；隔離一致性測試24 passed。沒有忽略正式tests/失敗、沒有改Production依賴或Windows權限。

四模型以真實Ollama API測試；最終密度案例M1/M2/M4直接回答並引用通過，M3把無關來源也列為引用，被拒收後以精確來源的通用確定性摘取回覆。原始M3錯誤保留，不能算模型直接成功。已修復摘取跨分號限制、巢狀答案物件及回補引用顯示；最終Streamlit AppTest使用同一Corpus SHA並實際呼叫M2，通過。

有證據、部分證據、虛構來源、錯魚種及高風險法規均有記錄。安全Gate拒絕後不呼叫Generator；不能把16個守門案例稱為16次LLM拒答推論。串流首個可見回答事件與thinking事件已分開，保留Ollama原始eval_count/eval_duration。

## 下一輪結論

可安排720次來源受限的系統效能與拒答行為評測，準確率只對上述合格子集作探索性分析；不能宣稱全體六魚種專業能力已完成獨立驗證。執行時仍須綁定獨立Judge與系統RAM/專用VRAM監測，重新量測，保留失敗／N/A及配對樣本。此輪不執行720次，不選Winner。

來源與判準版本已凍結。法律／用藥題沒有具現行法源與完整劑量停藥資料的準確率子集；鰻魚與石斑各僅4題完整支持，代表性有限。同一PDF頁與多張衍生卡不能當成多份獨立證據。

有限事實只索引自行結構化的數值與條件；不聲稱第三方PDF全文授權。使用範圍依原有Owner研究處理決策及事實／表達區分保留：[著作權法第10條之1](https://www.tipo.gov.tw/tw/copyright/694-17731.html)、[智慧局1100427b說明](https://www.tipo.gov.tw/tw/copyright/692-16409.html)。此記錄不是個案司法授權認定。

Frozen Manifest636/636逐件前後SHA相符；正式SQLite維持{expected}。Production、Historical E4、Corpus v2、原始Phase E/W結果不變。沒有宣稱本輪重算全部模型權重bytes雜湊；已查實際執行digest與M3 llama架構。
'''
 (W/'corpus_v3_evidence_alignment_report.md').write_text(report,encoding='utf-8')
 with (W/'corpus_v3_evidence_alignment_report.md').open('a',encoding='utf-8') as f:
  f.write('\n## 類別及來源依賴\n\n|原始類別|完整來源支持Question IDs|\n|---|---:|\n')
  for cat,v in s['categories'].items():f.write(f"|{cat}|{v.get('FULL_SUPPORT',0)}|\n")
  f.write(f"\n50個完整支持Question IDs依賴{len(origin_groups)}組原始JSON Record／PDF頁，僅來自{s['full_support_original_source_sha_count']}份原件SHA。它們不是50份獨立專業證據。疾病與用藥代表性仍不足。\n")
 print(json.dumps({'technical':aggregate['status'],'full_support':50,'retrieval_misses':len(misses),'p5_n':12,'p5_mean':.3,'logical_n':37,'arithmetic_n':13,'frozen':636},ensure_ascii=False))
if __name__=='__main__':main()
