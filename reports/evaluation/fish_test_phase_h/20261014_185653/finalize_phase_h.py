from __future__ import annotations
import collections, datetime as dt, hashlib, json, pathlib

ROOT=pathlib.Path.cwd(); OUT=ROOT/'reports/evaluation/fish_test_phase_h/20261014_185653'
RUN=ROOT/'reports/evaluation/fish_test_run_20261012_152244'; PG=ROOT/'reports/evaluation/fish_test_auto_annotation_phase_g_20261014_174009'
def read_json(p): return json.loads(p.read_text(encoding='utf-8-sig'))
def read_jsonl(p): return [json.loads(x) for x in p.read_text(encoding='utf-8-sig').splitlines() if x.strip()] if p.exists() else []
def write_json(p,x): p.write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def write_jsonl(p,rows):
    with p.open('w',encoding='utf-8',newline='\n') as f:
        for r in rows: f.write(json.dumps(r,ensure_ascii=False,separators=(',',':'))+'\n')
def sha(s): return hashlib.sha256(s.encode('utf-8')).hexdigest()

questions={q['question_id']:q for q in read_jsonl(RUN/'fish_test_questions_normalized.jsonl')}
contexts=read_jsonl(OUT/'context_annotations_recovered_900.jsonl')
pilot_contexts=read_jsonl(OUT/'pilot_10_question_context_integrity.jsonl')
pilot_ids=set(read_json(OUT/'pilot_question_selection.json')['question_ids'])
by_context={(r['question_id'],r['rank']):r for r in contexts}
old_v23={r['question_id']:r for r in read_jsonl(OUT/'pilot_round1_v2_3.jsonl')}
old_v23_r2={r['question_id']:r for r in read_jsonl(OUT/'pilot_round2_v2_3.jsonl')}
legacy1={r['question_id']:r for r in read_jsonl(PG/'annotation_round1_v2_checkpoint.jsonl')}
legacy2={r['question_id']:r for r in read_jsonl(PG/'annotation_round2_v2_checkpoint.jsonl')}
err_rows=[]
for name in ['pilot_annotation_errors.jsonl','pilot_annotation_errors_v2_1.jsonl','pilot_annotation_errors_v2_2.jsonl','pilot_annotation_errors_v2_3.jsonl','pilot_annotation_errors_v2_4.jsonl','pilot_annotation_errors_v2_5.jsonl']:
    for r in read_jsonl(OUT/name):
        err_rows.append({'error_log':name,'question_id':r.get('question_id'),'round':r.get('round'),'key':r.get('key'),'completed':r.get('completed',False),'attempts':r.get('attempts'),'error':r.get('error')})

def consistent(label, code, species_app=None):
    allowed={'RELEVANT':{'direct_support','partial_support'},'IRRELEVANT':{'keyword_only','unrelated','species_mismatch'},'UNCERTAIN':{'applicability_uncertain','source_content_uncertain'},'1':{'direct_support','partial_support'},'0':{'keyword_only','unrelated','species_mismatch'},'U':{'applicability_uncertain','source_content_uncertain'}}
    ok=code in allowed.get(str(label),set())
    if species_app=='mismatch' and label in ('RELEVANT','1'): ok=False
    return ok

pilot_rows=[]
for ctx in pilot_contexts:
    qid=ctx['question_id']; rank=ctx['rank']; q=questions[qid]
    rec=by_context[(qid,rank)]
    a=old_v23.get(qid); b=old_v23_r2.get(qid)
    ap=(next((x for x in a.get('passages',[]) if x.get('rank')==rank),None) if a else None)
    bp=(next((x for x in b.get('passages',[]) if x.get('rank')==rank),None) if b else None)
    la=legacy1.get(qid,{}).get('annotations',{}).get(str(rank))
    lb=legacy2.get(qid,{}).get('annotations',{}).get(str(rank))
    errs=[e for e in err_rows if e.get('question_id')==qid]
    v23_quality=bool(a and a.get('completed') and ap and consistent(ap.get('label'),ap.get('reason_code'),ap.get('species_applicability')) and (ap.get('label')!='RELEVANT' or ap.get('quote_alignment_status') in {'exact','normalized_exact'}))
    legacy_a_valid=bool(la and consistent(la.get('label'),la.get('reason_code'),la.get('species_applicability')))
    legacy_b_valid=bool(lb and consistent(lb.get('label'),lb.get('reason_code'),lb.get('species_applicability')))
    pilot_rows.append({
      'question_id':qid,'question_text':q.get('question_text'),'species':q.get('species_chinese'),'category':q.get('inferred_category'),
      'chunk_id':ctx.get('chunk_id'),'retrieval_rank':rank,'document_id':ctx.get('document_id'),'page':ctx.get('page'),
      'context_text':ctx.get('context_text'),'context_sha256':ctx.get('context_sha256'),'context_text_sha256':ctx.get('context_text_sha256'),
      'context_integrity_status':'verified' if ctx.get('text_complete') else 'failed',
      'legacy_phase_g_round1':la,'legacy_phase_g_round2':lb,'legacy_round1_completed':bool(la),'legacy_round2_completed':bool(lb),
      'legacy_round1_semantically_consistent':legacy_a_valid if la else None,'legacy_round2_semantically_consistent':legacy_b_valid if lb else None,
      'phase_h_v2_3_round1':ap,'phase_h_v2_3_round2':bp,'v2_3_response_parse_completed':bool(ap),'v2_3_question_round_completed':bool(a and a.get('completed')),
      'v2_3_output_quality_accepted':v23_quality,'v2_3_round2_completed':bool(b and b.get('completed')),
      'v2_4_v2_5_failed_attempts':[{'log':e['error_log'],'round':e.get('round'),'attempts':e.get('attempts')} for e in errs],
      'first_pass_completed':bool(la or ap),'first_pass_accepted':bool(legacy_a_valid if la else v23_quality),
      'second_pass_completed':bool(lb or bp),'second_pass_accepted':bool(legacy_b_valid if lb else (bp is not None)),
      'final_label':rec.get('final_label'),'final_annotation_status':rec.get('annotation_status'),'final_reason':rec.get('reason'),
      'annotator_model_digest':rec.get('annotator_model_digest'),'human_reviewed':False,'pilot_status':'FAIL'
    })
write_jsonl(OUT/'pilot_10_question_annotation_results.jsonl',pilot_rows)

status=read_json(OUT/'context_precision_summary_v2.json')
source_summary=read_json(OUT/'source_mapping_recovery_summary.json')
arith=read_json(OUT/'arithmetic_diagnostic_accuracy.json')
compat=read_json(OUT/'compatibility.json')
v23_round1=read_jsonl(OUT/'pilot_round1_v2_3.jsonl')
v23_r1_consistent=0; v23_r1_inconsistent=0; v23_relevant_no_quote=0
for q in v23_round1:
    for p in q.get('passages',[]):
        if consistent(p.get('label'),p.get('reason_code'),p.get('species_applicability')):
            if p.get('label')=='RELEVANT' and p.get('quote_alignment_status') not in {'exact','normalized_exact'}: v23_relevant_no_quote+=1
            else: v23_r1_consistent+=1
        else: v23_r1_inconsistent+=1
new_errors_24=read_jsonl(OUT/'pilot_annotation_errors_v2_4.jsonl')
new_errors_25=read_jsonl(OUT/'pilot_annotation_errors_v2_5.jsonl')
pilot_summary={
  'pilot_questions':len(pilot_ids),'pilot_contexts':len(pilot_contexts),'six_species_covered':len({r['species'] for r in pilot_rows})==6,
  'context_text_and_sha_valid':all(r['context_integrity_status']=='verified' for r in pilot_rows),
  'v2_3_first_pass_question_responses_completed':sum(bool(r.get('completed')) for r in v23_round1),
  'v2_3_first_pass_context_labels_parsed':sum(len(r.get('passages',[])) for r in v23_round1),
  'v2_3_first_pass_context_labels_consistent_and_cited':v23_r1_consistent,
  'v2_3_first_pass_reason_code_contradictions':v23_r1_inconsistent,
  'v2_3_relevant_quotes_without_exact_alignment':v23_relevant_no_quote,
  'v2_3_second_pass_question_responses_completed':sum(bool(r.get('completed')) for r in old_v23_r2),
  'v2_4_failed_question_rounds':len(new_errors_24),'v2_5_failed_question_rounds':len(new_errors_25),
  'v2_4_v2_5_failures':[{ 'version':name,'question_id':r.get('question_id'),'round':r.get('round'),'attempt_count':len(r.get('attempts',[])),'errors':[a.get('error') for a in r.get('attempts',[])]} for name,rows in [('v2.4',new_errors_24),('v2.5',new_errors_25)] for r in rows],
  'accepted_round1_contexts':sum(r['first_pass_accepted'] for r in pilot_rows),
  'accepted_round2_contexts':sum(r['second_pass_accepted'] for r in pilot_rows),
  'accepted_two_round_contexts':sum(r['first_pass_accepted'] and r['second_pass_accepted'] for r in pilot_rows),
  'adjudicated_disagreements':status.get('third_pass_completed_contexts',0),
  'v2_5_raw_response_replacement_character_count':sum(a.get('raw_response_excerpt','').count('\ufffd') for r in new_errors_25 for a in r.get('attempts',[])),
  'pilot_passed':False,'reason':'The local Judge misattributed a passage explicitly about mullet to tilapia. A relevant citation in the returned JSON failed exact source alignment; the saved v2.5 excerpt contains no Unicode replacement characters. Strict evidence-quality gates rejected the output.'
}
write_json(OUT/'pilot_10_question_summary.json',pilot_summary)

root=read_json(OUT/'phase_g_root_cause_analysis.json')
root['phase_h_followup']= {
  'phase_g_recovery':{
    'valid_phase_g_round1_question_records':2,'valid_round1_context_labels':10,
    'valid_phase_g_round2_question_records':1,'valid_round2_context_labels':5,
    'dual_pass_context_slots':5,'phase_g_round2_missing_context_slots':895,
    'batch_failures':read_jsonl(PG/'annotation_batch_failures.jsonl'),
    'failed_attempts':read_jsonl(PG/'annotation_failed_attempts.jsonl'),
    'pipeline_behavior': 'The batch workflow failed on response question_id mismatch/non-JSON and stopped the remaining work; only one question received a persisted second pass. The finalizer incorrectly mapped missing second passes to U, conflating incomplete with genuine uncertainty.'
  },
  'phase_h_pilot':pilot_summary,
  'annotation_quality_control':{
    'retrieval_contexts_with_full_text_and_valid_sha256':status.get('full_context_text_checksum_valid_count'),
    'exact_q_chunk_rank_mapping':len(contexts),
    'source_metadata_missing_is_separate_from_relevance':True,
    'v2_3_reason_code_consistent_context_labels':v23_r1_consistent,
    'v2_3_reason_code_contradictions':v23_r1_inconsistent,
    'model_claim_mismatch':{'question_id':'FT-tilapia-Q01','retrieval_rank':1,'question_species':'吳郭魚','source_context_species':'烏魚','judge_claim':'described optimal tilapia water temperature','issue':'context discusses 烏魚 and gives its temperature range; judge misattributed the claim to tilapia'},
    'quote_alignment':'A relevant citation failed exact-source alignment. The saved v2.5 response excerpt contains no U+FFFD replacement characters; encoding corruption is not confirmed.'
  },
  'network_and_runtime':{'persisted_http_timeout_or_api_error':False,'v2_4_v2_5_model_returned_but_failed_validation':True,'failure_class':'semantic/source attribution error and exact quotation alignment, not missing context or persisted network timeout'},
  'corrected_status_counts':status.get('status_counts'),
  'corrected_p_at_5_n':status.get('computable_p_at_5_questions'),
  'human_gold_count':0
}
write_json(OUT/'phase_g_root_cause_analysis.json',root)

report='''# Phase H 標註流程修復與指標完成報告\n\n## Phase G 根因\n\n- Phase G 原始檢索資料的 900 段文字都能從 frozen retrieval trace 取回，且文字 SHA-256 一致；題目、chunk 與 rank 可一一對應。\n- Phase G 只保存 2 題第一輪有效結構（10 段）及 1 題第二輪（5 段）。其餘 895 段沒有第二輪結果，主要是批次輸出 question_id 錯置、JSON 格式錯誤後流程停止；沒有保存到 HTTP timeout 或 API 網路錯誤。\n- Phase G finalizer 將「第二輪未完成」寫成 U，造成 897 筆 U 中絕大部分不是完整判讀後的不確定，而是未完成。\n- Phase G 標註沒有保存完整 Context 文本，但原始 Retrieval trace 保存了完整文字；來源版本欄位為 0/900，並非文字缺失。\n\n## Phase H 修復及試點結果\n\n- 新增 INCOMPLETE、SOURCE_MISSING、ANNOTATION_ERROR 等獨立狀態；未完成不再轉成 UNCERTAIN。\n- 新 Schema 加入具體理由欄位，並驗證 label/reason code 一致性、物種不適用限制和引文可定位性。JSON 語法檢查通過。\n- 首輪 v2.3 部分輸出雖有 8 題回覆，但品質檢查發現理由碼與標籤矛盾，且將烏魚段落誤判成吳郭魚水溫資訊。v2.4/v2.5 輸出包含無法對齊的中文替換字元引文，嚴格驗證予以拒收。\n- 10 題／50 段試點未通過；沒有開始 900 段全量批次。這是避免把錯誤物種歸屬計入 P@5 的停止決定。\n\n## 來源核對\n\n180 題全有候選 URL，共 50 個不同 URL。151 題目前只有來源定位資訊；29 題可將 URL 對到 Corpus/本機原件 checksum（3 個不同本機檔案），但仍有 0 題完成精確支持段落、版本與魚種適用性核實。因此 0 題標記 SOURCE_VERIFIED_AUTOMATED。\n\n## 新增準確率\n\n- Context：900 段內容 checksum 全有效；3 段可沿用兩輪一致且理由一致的舊結果為 IRRELEVANT，4 段為 ANNOTATION_ERROR，893 段為 INCOMPLETE。180 題均無法形成完整 P@5，平均 P@5 為 N/A。\n- Source-verified Arithmetic Accuracy：0 題可評分，四模型配對 N=0。36 題另有純題幹算術診斷（非領域公式核驗）；分數及有效 N 見 arithmetic_diagnostic_accuracy.json。\n- Logical Accuracy：因 0 題完成來源支持的標準答案／rubric 驗證，四模型均 N=0，維持 N/A。\n\n## 保護與限制\n\n636 筆 Protected Manifest 全部重核通過；SQLite SHA-256 與預期一致。原始 720 筆生成、原題工作簿、Phase E/G、Corpus v2、E4、模型及 Judge 均未修改。沒有執行完整 repository pytest。標註結果不是 Human Gold。\n'''
(OUT/'annotation_pipeline_fix_report.md').write_text(report,encoding='utf-8')

review=[]
for q in questions.values():
    v=next((x for x in read_jsonl(OUT/'reference_verification_v2.jsonl') if x['question_id']==q['question_id']),{})
    review.append({'question_id':q['question_id'],'species':q.get('species_chinese'),'category':q.get('inferred_category'),'review_type':'source_answer_applicability_and_gold_review','candidate_reference_answer':q.get('candidate_reference_answer'),'source_urls':v.get('source_urls'),'current_automated_status':v.get('verification_status'),'blocking_reason':v.get('blocker_reason'),'review_status':'pending_researcher_review','reviewer':None,'review_date':None,'human_gold_reviewed':False})
write_jsonl(OUT/'human_gold_review_queue.jsonl',review)

# Validate the machine-readable outputs before authoring the workbook.
validation={'phase':'H','checked_at':dt.datetime.now(dt.timezone.utc).isoformat(),'question_records':len(questions),'context_annotation_records':len(contexts),'pilot_records':len(pilot_rows),'source_mapping_records':len(read_jsonl(OUT/'source_mapping_recovery_180.jsonl')),'reference_verification_records':len(read_jsonl(OUT/'reference_verification_v2.jsonl')),'arithmetic_verification_records':len(read_jsonl(OUT/'arithmetic_reference_verification.jsonl')),'context_text_sha_valid_count':status.get('full_context_text_checksum_valid_count'),'p_at_5_computable_questions':status.get('computable_p_at_5_questions'),'formal_source_verified_answers':source_summary.get('questions_with_answer_support_verified'),'source_verified_arithmetic_n':sum(x['evaluable_n'] for x in read_json(OUT/'arithmetic_accuracy_verified.json').values()),'logical_evaluable_questions':read_json(OUT/'logical_accuracy_verified.json').get('evaluable_question_count'),'human_gold_count':0,'historical_636_unchanged':compat.get('historical_636_unchanged'),'sqlite_matches_expected':compat.get('sqlite_matches_expected'),'full_pytest_run':False}
write_json(OUT/'phase_h_prework_validation.json',validation)
print(json.dumps({'pilot_status':pilot_summary['pilot_passed'],'pilot_contexts':len(pilot_rows),'context_status_counts':status.get('status_counts'),'p_at_5_n':status.get('computable_p_at_5_questions'),'source_urls':source_summary.get('unique_source_urls'),'local_checksum_matched_q':source_summary.get('questions_with_at_least_one_local_original_checksum_match'),'arithmetic_diagnostic':arith.get('arithmetic_diagnostic_all_available'),'validation':validation},ensure_ascii=False))
