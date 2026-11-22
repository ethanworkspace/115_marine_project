from __future__ import annotations
import collections, datetime as dt, hashlib, json, pathlib, re

ROOT=pathlib.Path.cwd()
OUT=ROOT/'reports/evaluation/fish_test_phase_i_20261014_195032'
RUN=ROOT/'reports/evaluation/fish_test_run_20261012_152244'
def readj(path): return json.loads(path.read_text(encoding='utf-8-sig'))
def readjl(path): return [json.loads(s) for s in path.read_text(encoding='utf-8-sig').splitlines() if s.strip()]
def writej(name,obj): (OUT/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def writjl(name,rows):
 with (OUT/name).open('w',encoding='utf-8',newline='\n') as f:
  for r in rows: f.write(json.dumps(r,ensure_ascii=False,separators=(',',':'))+'\n')
def sha(text): return hashlib.sha256(text.encode('utf-8')).hexdigest()

selected=readj(OUT/'pilot_question_selection.json')
errors=readjl(OUT/'pilot_v4_annotation_errors.jsonl')
mapping=readjl(OUT/'source_mapping_recovery_180.jsonl')
quotes=readjl(OUT/'local_source_quote_verification.jsonl')
docs=readj(OUT/'local_source_pdf_integrity.json')['files']
urls=readjl(OUT/'source_url_accessibility_30.jsonl')
source_by_q={r['question_id']:r for r in mapping}
error_by_q=collections.defaultdict(list)
for e in errors: error_by_q[e.get('question_id')].append(e)

attempted_quote_audit=[]
for e in errors:
 raw=e.get('raw_response')
 try: obj=json.loads(raw) if raw else None
 except Exception: obj=None
 rankmatch=re.search(r'program-bound rank (\d+)',e.get('error',''))
 failed_rank=int(rankmatch.group(1)) if rankmatch else None
 row=next((r for r in selected if r['question_id']==e['question_id']),None)
 contexts={int(c['rank']):c for c in (row or {}).get('contexts',[])}
 anns=(obj or {}).get('passages',[]) if isinstance(obj,dict) else []
 for i,a in enumerate(anns,1):
  if a.get('label')!='RELEVANT' or not a.get('quoted_evidence'): continue
  context=contexts.get(i,{})
  text=context.get('text','')
  quote=a['quoted_evidence']
  start=text.find(quote)
  attempted_quote_audit.append({'question_id':e['question_id'],'pass':e.get('pass'),'attempt':e.get('attempt'),
   'program_bound_rank':i,'failed_validation_rank':failed_rank,'chunk_id':context.get('chunk_id'),
   'model_quote':quote,'exact_in_program_bound_chunk':start>=0,'start':start if start>=0 else None,
   'end':start+len(quote) if start>=0 else None,'accepted_as_evidence':False,
   'raw_response_sha256':e.get('raw_response_sha256'),'prompt_sha256':e.get('prompt_sha256'),
   'reason':'whole pass rejected; exact-quote validation reported a rank-specific mismatch'})
writjl('pilot_attempted_quote_verification.jsonl',attempted_quote_audit)

pilot_rows=[]
for q in selected:
 qid=q['question_id']; qerrors=error_by_q.get(qid,[])
 q_pass1_errors=[e for e in qerrors if e.get('pass')==1]
 q_pass1_failed=bool(q_pass1_errors) and max(e.get('attempt',0) for e in q_pass1_errors)>=2
 for c in q['contexts']:
  rank=int(c['rank']); digest=sha(c.get('text',''))
  p1='ANNOTATION_ERROR' if q_pass1_failed else 'INCOMPLETE'
  p2='INCOMPLETE'
  errors_for_context=[{'pass':e.get('pass'),'attempt':e.get('attempt'),'error_type':e.get('error_type'),'error':e.get('error'),
                       'raw_response_sha256':e.get('raw_response_sha256'),'prompt_sha256':e.get('prompt_sha256')}
                      for e in qerrors if e.get('pass')==1 and (f'rank {rank}' in (e.get('error') or '') or e.get('attempt',0)>=2)]
  pilot_rows.append({'question_id':qid,'species':q.get('species'),'category':q.get('category'),'question_text':q.get('question_text'),
   'chunk_id':c.get('chunk_id'),'document_id':c.get('document_id'),'rank':rank,'source_page':c.get('page'),
   'context_sha256_expected':c.get('text_sha256'),'context_sha256_actual':digest,'context_integrity_valid':digest==c.get('text_sha256') and c.get('sha256_matches') is True,
   'first_pass_status':p1,'first_pass_completed':False,'first_pass_label':None,
   'second_pass_status':p2,'second_pass_completed':False,'second_pass_label':None,
   'final_status':p1 if p1=='ANNOTATION_ERROR' else 'INCOMPLETE','final_label':None,'disagreement':None,
   'accepted_exact_quote':None,'quote_start':None,'quote_end':None,'attempt_error_refs':errors_for_context,
   'judge_model':'mistral-nemo:12b-instruct-2407-q4_K_M','judge_digest':'daf6737417121831e572a9c482e92a221ee0c33537f35f1f857c7b4f7191df55',
   'prompt_version':'phase-i-context-relevance-jsonschema-v4.0-compact-program-bound-rank-species-guard',
   'human_gold_status':'NOT_HUMAN_GOLD','not_run_reason':'pilot stopped after first selected question exhausted two exact-quote validation attempts; no annotation result accepted'})
writjl('pilot_10_question_annotation_results.jsonl',pilot_rows)
status=collections.Counter(r['final_status'] for r in pilot_rows)
round_counts=collections.Counter(r[k] for r in pilot_rows for k in ('first_pass_status','second_pass_status'))
pilot_summary={'selected_questions':len(selected),'selected_context_rows':len(pilot_rows),'distinct_species':sorted({q.get('species') for q in selected}),
 'first_pass_completed_contexts':sum(r['first_pass_completed'] for r in pilot_rows),
 'second_pass_completed_contexts':sum(r['second_pass_completed'] for r in pilot_rows),
 'both_passes_completed_contexts':sum(r['first_pass_completed'] and r['second_pass_completed'] for r in pilot_rows),
 'final_status_counts':dict(status),'attempted_judge_calls':len(errors),'attempted_quote_count':len(attempted_quote_audit),
 'attempted_quotes_exact_in_program_bound_chunk':sum(x['exact_in_program_bound_chunk'] for x in attempted_quote_audit),
 'accepted_relevant_labels':0,'accepted_quotes_with_verified_offsets':0,
 'all_50_context_text_checksums_valid':all(r['context_integrity_valid'] for r in pilot_rows),
 'known_tilapia_mullet_control_in_pilot':True,'control_judge_two_pass_completed':False,
 'pilot_passed':False,'stop_reason':'FT-tilapia-Q01 pass 1 exhausted two responses with exact-quote rank mismatch; pass 2 and remaining questions intentionally not run under fail-fast pilot policy.',
 'annotator':'mistral-nemo:12b-instruct-2407-q4_K_M','annotator_digest':'daf6737417121831e572a9c482e92a221ee0c33537f35f1f857c7b4f7191df55',
 'counts_by_round_status':dict(round_counts),'annotation_level':'AI_AUTO_ANNOTATED attempt audit only; NOT_HUMAN_GOLD'}
writej('pilot_10_question_summary.json',pilot_summary)

quote_count=collections.Counter(str(r.get('answer_supported')) for r in quotes)
quote_verified=sum(bool(r.get('quote_verified')) for r in quotes)
quote_methods=collections.Counter(r.get('quote_capture_method') for r in quotes if r.get('quote_verified'))
local_valid_qids=set()
for d in docs:
 if d.get('exists') and d.get('checksum_match'):
  # Use the phase-H source mapping's explicit question list, but exclude the known erroneous association.
  pass
doc_mapping=readjl(OUT/'source_documents_29_mapping.jsonl')
mapped_qids={qid for d in doc_mapping for qid in d.get('questions',[])}
wrong_qids={'FT-milkfish-Q12'}
valid_local_qids=mapped_qids-wrong_qids
for qid in valid_local_qids:
 row=source_by_q.get(qid)
 if row and row.get('local_original_checksum_verified'): local_valid_qids.add(qid)
source_url_summary=readj(OUT/'source_url_accessibility_summary.json')
quote_by_q={r['question_id']:r for r in quotes}
source_trace_rows=[]
for r in mapping:
 qid=r['question_id']; qv=quote_by_q.get(qid,{})
 srcid=qv.get('source_id') or r.get('source_id')
 source_trace_rows.append({'question_id':qid,'source_id':srcid,'source_urls':r.get('source_urls') or [],
  'source_access_status':r.get('source_url_browser_status'),'local_source_path':r.get('local_original_path'),
  'local_source_sha256':r.get('local_original_sha256'),'local_source_checksum_verified':r.get('local_original_checksum_verified',False),
  'document_version':r.get('source_version') if srcid in {'S05','S09'} else None,
  'document_version_status':'page_or_local_document_version_recorded' if srcid in {'S05','S09'} else 'unknown_or_only_topic_label',
  'exact_quote':r.get('exact_quote'),'quote_locator':r.get('page_or_locator'),'quote_verified':bool(r.get('quote_verified')),
  'quote_capture_method':qv.get('quote_capture_method'),'answer_supported':r.get('answer_supported'),
  'species_applicability':r.get('species_applicability'),'blocker_reason':r.get('blocker_reason'),
  'human_gold_status':'NOT_HUMAN_GOLD'})
writjl('source_trace_verification_180.jsonl',source_trace_rows)
quote_report={'review_date':'2026-10-14','question_source_mapping_rows':len(mapping),
 'local_source_document_count':len(docs),'local_source_files_exists_and_checksum_verified':sum(bool(d.get('exists') and d.get('checksum_match')) for d in docs),
 'local_source_question_mapping_rows':len(quotes),'intended_unique_question_ids_with_local_source':len(valid_local_qids),
 'intended_question_ids_mapped_to_checksum_verified_local_source_files':'28; file association only, not proof that the associated file supplied each verified quote',
 'known_erroneous_mapping':{'question_id':'FT-milkfish-Q12','incorrectly_associated_document':'my_data/my_data/動物用藥品管理法.pdf','actual_candidate_source_id':'S06','actual_candidate_source':'FA-385 寒害網頁','status':'mapping_error_excluded_from_support'},
 'local_question_answer_support_status_counts':dict(quote_count),
 'exact_quote_verified_rows_from_local_pdf_or_readable_official_webpage':quote_verified,
 'exact_quote_verified_unique_question_ids':len({r['question_id'] for r in quotes if r.get('quote_verified') and r.get('question_id') in valid_local_qids}),
 'exact_quote_capture_method_counts':dict(quote_methods),
 'exact_quotes_from_local_pdf_bytes':sum('pypdf exact substring' in str(k) for k,v in quote_methods.items() for _ in range(v)),
 'exact_quotes_from_readable_official_webpage_not_archived_as_raw_html':sum('official_law_webpage_read_only' in str(k) for k,v in quote_methods.items() for _ in range(v)),
 'direct_answer_support_questions':sum(r.get('answer_supported') is True for r in quotes),
 'partial_answer_support_questions':sum(r.get('answer_supported')=='partial' for r in quotes),
 'no_valid_answer_support_or_wrong_mapping_questions':sum(r.get('answer_supported') is None for r in quotes),
 'retrieval_context_quote_attempts_from_pilot':len(attempted_quote_audit),
 'retrieval_context_quotes_accepted':0,
 'source_url_accessibility':source_url_summary,
 '151_question_records_without_verified_local_original':151,
 '23_readable_urls_are_not_local_originals_or_rights_decisions':True,
 'acquisition_this_phase':'No new original source bytes downloaded; direct shell network blocked with WinError 10013; no proxy/security bypass attempted.',
 'limitations':['Document checksum proves file identity, not answer correctness.',
  'Partial support does not establish the full candidate answer.',
  'The 2020/2025 source availability and version limitations remain per source_mapping_recovery_180.jsonl.',
  'The erroneous milkfish Q12 mapping is retained as a blocker rather than used as evidence.']}
writej('official_quote_verification_report.json',quote_report)

root=readj(OUT/'phase_g_root_cause_analysis.json')
root['phase_i_v4_pilot']={'prompt_version':'phase-i-context-relevance-jsonschema-v4.0-compact-program-bound-rank-species-guard',
 'judge_model':'mistral-nemo:12b-instruct-2407-q4_K_M','judge_digest':'daf6737417121831e572a9c482e92a221ee0c33537f35f1f857c7b4f7191df55',
 'attempted_question_count':1,'attempted_context_count':5,'round1_calls':2,'round1_accepted':False,'round2_started_or_accepted':False,
 'failure':'Both round-1 JSON replies returned a Relevant quote that did not occur in the chunk bound to its output position (attempt 1 rank 2; attempt 2 rank 5). No label from either response was accepted. Process was stopped before continuing the other 9 questions.',
 'checkpoint_state':'Q01 pass 1 has two errors and no completed result; all other pass slots remain unstarted/incomplete.',
 'implementation_repairs_applied':['full local schema-shape/type/enum/length validation in addition to Ollama constrained JSON format',
  'program binds question/chunk/rank; judge emits only position-ordered passage annotations',
  'exact quote is checked against the corresponding full chunk and offsets are recorded only when valid',
  'explicit named-species mismatch guard; generic bass and named bass species are kept distinct',
  'errors preserve raw response, prompt version/hash, retry number and validation reason; failed prompt body archival fixed for future attempts',
  'checkpoint distinguishes accepted complete result from error/incomplete state'],
 'pipeline_selftest':'passed; 6 offline assertions; no Judge call'}
writej('phase_g_root_cause_analysis.json',root)

compat=readj(OUT/'frozen_baseline_compatibility.json')
compat['phase_i_outputs_outside_protected_manifest']=True
compat['source_pilot_passed']=False
compat['900_context_batch_started']=False
compat['original_720_generations_reexecuted']=False
writej('compatibility.json',compat)

repair_md='''# Phase I 標註器修復與試點報告\n\n## 根因\n\nPhase G 的 895 筆第二輪缺失並非原始 Context 缺文：Phase H 核對了 900 段原始全文與 SHA-256。Phase G 只有 10 筆有效第一輪、5 筆有效第二輪；三個失敗批次回傳序號型題目 ID 或格式錯誤資料，管線提前停止。其後 finalizer 把沒有完成的輪次填為 U，並把部分來源中繼資料缺失混同為內容不確定。\n\nPhase I 修正版使用 Ollama JSON 約束、額外本地 schema 驗證、程式綁定 question/chunk/rank、逐字引文及 offset 驗證、明確物種守門、raw response 與 checkpoint 保存。離線自測通過 6 項。\n\n## 試點結果\n\n試點在第一題 FT-tilapia-Q01 即觸發停止：Judge 兩次回覆均把其他 rank 的段落內容當成引文。第一次錯引指向程式綁定 rank 2，第二次錯引指向 rank 5；兩份回覆均未被接受。第一題第二輪及其餘九題未完成。50 段中雙輪完成 0 段，接受的 Relevant 標籤及引文皆為 0。故試點未通過，900 段批次未啟動，也未新增 P@5。\n\n這不是把 U 改成相關性判定：沒有被接受的標籤，失敗與未執行狀態分別保留為 ANNOTATION_ERROR 與 INCOMPLETE。既有 v4 失敗呼叫保存原始回覆、模型身分、Prompt 版本／雜湊與重試次數；失敗路徑未保存完整 Prompt 本文，程式已修補未來失敗呼叫的 Prompt 封存，但本輪不重跑。\n\n## 尚待修正\n\n模型目前無法可靠地將逐字引文綁到相應段落。物種守門可在單元測試中攔截明確跨物種誤判，但真實的烏魚／吳郭魚控制題尚未完成兩輪，所以不能宣稱混淆問題已由端到端試點排除。失敗呼叫已保留原始回覆、模型、摘要雜湊、prompt 版本與重試次數；本次失敗呼叫的完整 prompt body 因修復前程式未寫入 prompt archive 而無法回溯。修正版已調整，未再次呼叫模型。\n'''
(OUT/'annotation_repair_report.md').write_text(repair_md,encoding='utf-8')

final_md='''# Phase I 最終報告\n\n## 執行結果\n\n- Phase G 的主要問題：三個批次輸出包含錯置序號 ID、非有效 JSON／重複結構並提前停止；finalizer 又把未執行輪次標為 U。900 段原始內容與 digest 完整，缺的是可靠標註結果。\n- 修正版程式已加入完整本地 schema 驗證、程式綁定 ID/rank、引文逐字定位與失敗 checkpoint 區分；離線邏輯測試 6/6 通過。\n- Pilot：10 題、50 段；實際完成雙輪 0/50。第一題第一輪 2 次均因跨 rank 引文不相符而拒絕；第二輪與其餘 9 題未執行。\n- 引文：本機 3 份來源 PDF 均存在且 checksum 相符；29 筆題目-來源映射行中 28 個是預期來源題目 ID，另有 FT-milkfish-Q12 誤連至動物用藥品管理法，已排除。28 個題目有精確原文定位，其中 23 筆來自可讀官方法規網頁（未保存原始 HTML），5 筆由本機 PDF bytes 抽取；完整答案直接受支持 12 題、部分支持 16 題。這是來源核驗紀錄，不是 Human Gold。\n- 180 題來源：所有題目保留來源追溯列。151 題沒有已核實的本機原始來源；30 個唯一 URL 中 23 個可透過官方網頁工具讀取、7 個回傳工具錯誤。這些網頁可讀狀態不等同原件已下載、版本已固定或使用權已確認。本輪未下載新原件；直接本機 HTTP 路徑遇 WinError 10013，未改代理或繞過限制。\n- 新指標：因試點失敗，未計算新 P@5；沒有新增可核驗的 Arithmetic 或 Logical Accuracy 樣本。舊有指標及 720 筆生成結果未重跑、未改寫。\n- 是否能安全擴至 900 段：否。停止條件已觸發。\n\n## 物種與引文控制\n\n修正版在程式層可將明確來源物種不符標為 mismatch；離線測試含烏魚來源對吳郭魚問題的攔截。真實 pilot 的錯引已由程式拒絕，但因 0/50 完成雙輪，端到端物種混淆排除尚未驗證。\n\n## Frozen Baseline\n\n本輪重新計算 Phase A 保護清單：636/636 未變，0 mismatch、0 missing；SQLite SHA-256 仍為 `d7d06d4d2a57d0a57d05bcb6131ffb24aefb226c6bd36349dbc5118d33b11087`。720 筆生成未重跑，Phase E/G/H 歷史報表未覆寫，未執行刪除、清理、Corpus/E4 變更或模型評分。\n\n## 交付檔案\n\n- `pilot_10_question_annotation_results.jsonl`：50 段明確標記 ANNOTATION_ERROR 或 INCOMPLETE。\n- `pilot_attempted_quote_verification.jsonl`：失敗回覆引文與目標 rank 對照。\n- `source_mapping_recovery_180.jsonl`：180 題來源核驗及阻塞。\n- `official_quote_verification_report.json`：29 筆映射及 3 個本機 PDF 核驗摘要。\n- `annotation_pipeline_repaired.py`：修正後程式；不代表 pilot 通過。\n- `phase_i_repair_selftest.py`：6 項離線測試。\n- `compatibility.json`：Frozen Baseline 重核結果。\n\n所有 AI 輔助紀錄均為 `NOT_HUMAN_GOLD`。本階段停止於 pilot gate，未產生 Excel v5。\n'''
(OUT/'phase_i_final_report.md').write_text(final_md,encoding='utf-8')

validation={'pilot_rows':len(pilot_rows),'unique_question_ids':len({r['question_id'] for r in pilot_rows}),
 'unique_question_chunk_rank_keys':len({(r['question_id'],r['chunk_id'],r['rank']) for r in pilot_rows}),
 'context_integrity_valid_rows':sum(r['context_integrity_valid'] for r in pilot_rows),
 'two_pass_completed_rows':pilot_summary['both_passes_completed_contexts'],
 'accepted_relevant_quote_rows':sum(r['final_label']=='RELEVANT' and r['accepted_exact_quote'] for r in pilot_rows),
 'source_mapping_rows':len(mapping),'source_question_ids':len({r['question_id'] for r in mapping}),
 'quote_rows':len(quotes),'quote_verified_rows':quote_verified,
 'pilot_passed':False,'p_at_5_new_samples':0,'new_arithmetic_accuracy_samples':0,'new_logical_accuracy_samples':0,
 'compatibility_636_unchanged':compat.get('all_636_unchanged') is True}
writej('phase_i_artifact_validation.json',validation)
print(json.dumps({'pilot_passed':pilot_summary['pilot_passed'],'completed_two_pass':pilot_summary['both_passes_completed_contexts'],'final_status_counts':dict(status),'quote_report_counts':{'full':quote_report['direct_answer_support_questions'],'partial':quote_report['partial_answer_support_questions'],'blocked':quote_report['no_valid_answer_support_or_wrong_mapping_questions']},'validation':validation},ensure_ascii=False))
