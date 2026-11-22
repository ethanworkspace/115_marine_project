from __future__ import annotations
import collections, json, pathlib

ROOT=pathlib.Path.cwd(); OUT=ROOT/'reports/evaluation/fish_test_phase_h/20261014_185653'
RUN=ROOT/'reports/evaluation/fish_test_run_20261012_152244'; PE=ROOT/'reports/evaluation/fish_test_results_audit_v2_20261012_222741'; PG=ROOT/'reports/evaluation/fish_test_auto_annotation_phase_g_20261014_174009'
def j(p): return json.loads(p.read_text(encoding='utf-8-sig'))
def jl(p): return [json.loads(s) for s in p.read_text(encoding='utf-8-sig').splitlines() if s.strip()] if p.exists() else []
def v(x):
    if isinstance(x,(dict,list)): x=json.dumps(x,ensure_ascii=False,separators=(',',':'))
    if isinstance(x,str):
        return ''.join(ch for ch in x if ch in '\t\n\r' or 0x20 <= ord(ch) <= 0xD7FF or 0xE000 <= ord(ch) <= 0xFFFD or 0x10000 <= ord(ch) <= 0x10FFFF)
    if x is None: return None
    if isinstance(x,bool): return x
    return x
questions=jl(RUN/'fish_test_questions_normalized.jsonl'); qmap={q['question_id']:q for q in questions}
traces=jl(RUN/'retrieval_trace.jsonl'); tmap={r['question_id']:r for r in traces}
gen=jl(RUN/'generation_outputs.jsonl'); genmap={(r.get('question_id'),r.get('model_id')):r for r in gen}
metrics=jl(RUN/'per_question_metrics.jsonl'); metricmap={(r.get('question_id'),r.get('model_id')):r for r in metrics}
eff=jl(RUN/'efficiency_metrics.jsonl'); effmap={(r.get('question_id'),r.get('model_id')):r for r in eff}
judge=jl(PE/'judge_structure_consistency_audit.jsonl'); judgemap={(r['question_id'],r['model_id']):r for r in judge}
bge=jl(PE/'bge_m3_answer_relevance.jsonl'); bgemap={(r['question_id'],r['model_id']):r for r in bge}
contexts=jl(OUT/'context_annotations_recovered_900.jsonl'); ctx_by_q=collections.defaultdict(list)
for r in contexts: ctx_by_q[r['question_id']].append(r)
prec=jl(OUT/'context_precision_by_question.jsonl'); precmap={r['question_id']:r for r in prec}
sources=jl(OUT/'source_mapping_recovery_180.jsonl'); srcmap={r['question_id']:r for r in sources}
ref=jl(OUT/'reference_verification_v2.jsonl'); refmap={r['question_id']:r for r in ref}
arith_ref=jl(OUT/'arithmetic_reference_verification.jsonl'); arithmap={r['question_id']:r for r in arith_ref}
arith_rows=jl(PG/'arithmetic_accuracy_by_model_rows.jsonl'); arith_model={(r['question_id'],r['model_id']):r for r in arith_rows}
logical_rows=jl(PG/'logical_accuracy_by_model.jsonl')
paired=j(PE/'paired_sample_comparison.json'); source_summary=j(OUT/'source_mapping_recovery_summary.json'); cp_summary=j(OUT/'context_precision_summary_v2.json')
diag=j(OUT/'arithmetic_diagnostic_accuracy.json'); source_arith=j(OUT/'arithmetic_accuracy_verified.json'); logical=j(OUT/'logical_accuracy_verified.json'); scoring=j(PE/'scoring_policy_status.json'); compat=j(OUT/'compatibility.json')
run_id='fish_test_run_20261012_152244'; models=['M1','M2','M3','M4']

def sheet(name,headers,rows,widths=None): return {'name':name,'headers':headers,'rows':[[v(x) for x in row] for row in rows],'widths':widths or {}}
sheets=[]
# Dashboard is a factual status summary, not a composite score or ranking.
dash=[
 ['Questions',180,'Fish Test normalized records','Frozen input; 6 species x 30'],
 ['Generator outputs',len(gen),'Original run JSONL','No generation rerun'],
 ['Retrieval records',len(traces),'Original shared Retrieval','One shared Top-5 per question'],
 ['Context text integrity',cp_summary.get('full_context_text_checksum_valid_count'),'retrieval_trace.jsonl','All context SHA-256 values rechecked'],
 ['Context P@5 evaluable questions',cp_summary.get('computable_p_at_5_questions'),'Phase H AI annotation','0; pilot failed quality gate'],
 ['Context Precision@5',None,'Shared metric','N/A; no complete question-level P@5'],
 ['Source-verified answers',source_summary.get('questions_with_answer_support_verified'),'Phase H provenance reconciliation','0; spans/applicability not verified'],
 ['Source-verified Arithmetic N',sum(x.get('evaluable_n',0) for x in source_arith.values()),'Decimal + authoritative formula gate','0; all 68 candidates blocked'],
 ['Arithmetic diagnostic paired N',diag.get('arithmetic_diagnostic_four_model_paired_question_count'),'Question-text arithmetic only','0; no four-model arithmetic ranking'],
 ['Logical Accuracy evaluable questions',logical.get('evaluable_question_count'),'Source-supported frozen rubric','0'],
 ['Human Gold',0,'No researcher review record','NOT_HUMAN_GOLD'],
 ['Formal composite / Winner',None,'Weight policy not approved','Not calculated / not selected'],
 ['Protected manifest',compat.get('historical_636_rechecked'),'Protected files manifest','636/636 unchanged'],
 ['SQLite SHA-256 matches',compat.get('sqlite_matches_expected'),'Expected digest verified','Frozen baseline intact'],
]
sheets.append(sheet('Dashboard',['Item','Value','Basis','Interpretation'],dash,{'A':36,'B':18,'C':38,'D':64}))

# Model comparison: historical usable metrics and new/diagnostic metrics stay separate.
comp=[]; allm=paired['all_available_samples']
for metric,key in [('Judge Faithfulness','judge_faithfulness'),('Judge Answer Relevance','judge_answer_relevance'),('BGE-M3 Answer Relevance Cosine','bge_m3_answer_relevance_cosine'),('Structured Output Valid Rate','structured_output_valid'),('TTFT visible content seconds','ttft_final_content_seconds'),('TPS','tps_ollama_eval_rate'),('System RAM sampled peak (GB)','system_level_sampled_ram_peak_bytes'),('Dedicated VRAM sampled peak (GB)','system_level_sampled_dedicated_vram_peak_bytes')]:
    for mid in models:
        rec=allm.get(key,{}).get(mid,{})
        mean=rec.get('mean')
        if mean is not None and 'bytes' in key: mean=mean/(1024**3)
        comp.append([mid,metric,rec.get('n',0),mean,'Phase E existing metric; exploratory; no model-output re-run'])
for mid in models:
    d=diag['arithmetic_diagnostic_all_available'][mid]
    comp.append([mid,'Arithmetic Diagnostic Accuracy',d['n_evaluable'],d['accuracy'],'題幹內數字直接算術；未驗證領域公式；ARITHMETIC_DIAGNOSTIC'])
    s=source_arith[mid]
    comp.append([mid,'Source-verified Arithmetic Accuracy',s['evaluable_n'],None,'NOT_EVALUABLE; authoritative formula/source validation count is 0'])
    l=logical['by_model'][mid]
    comp.append([mid,'Logical Accuracy',l['evaluable_n'],None,'NOT_EVALUABLE; no source-verified objective rubric'])
comp.append(['Shared Retrieval','Context Precision@5',cp_summary['computable_p_at_5_questions'],None,'Shared retrieval metric; no model-specific P@5; AI_AUTO_ANNOTATED; all P@5 N/A'])
sheets.append(sheet('Model_Comparison',['model_id','metric','valid_n','value','status_or_basis'],comp,{'A':20,'B':42,'C':16,'D':18,'E':72}))

# Existing metrics detailed by q/model; source-level and historical values remain separate.
existing=[]
for q in questions:
  qid=q['question_id']
  for mid in models:
    m=metricmap.get((qid,mid),{}); e=effmap.get((qid,mid),{}); jr=judgemap.get((qid,mid),{}); br=bgemap.get((qid,mid),{})
    existing.append([qid,mid,run_id,jr.get('judge_score_valid'),jr.get('structure_valid'),jr.get('judge_faithfulness'),jr.get('judge_answer_relevance'),br.get('bge_m3_answer_relevance_cosine'),br.get('status'),m.get('schema_valid'),m.get('ttft_seconds'),m.get('tps'),(m.get('system_ram_peak_bytes_sampled') or e.get('system_ram_peak_bytes_sampled') or 0)/(1024**3) if (m.get('system_ram_peak_bytes_sampled') or e.get('system_ram_peak_bytes_sampled')) else None,(m.get('dedicated_vram_peak_bytes_sampled') or e.get('dedicated_vram_peak_bytes_sampled') or 0)/(1024**3) if (m.get('dedicated_vram_peak_bytes_sampled') or e.get('dedicated_vram_peak_bytes_sampled')) else None,'system_level_sampled_peak; not model_process_peak',None,'Original Phase E/Run; N/A retained'])
sheets.append(sheet('Existing_Metrics',['question_id','model_id','run_id','judge_score_valid','structure_valid','judge_faithfulness','judge_answer_relevance','bge_m3_answer_relevance_cosine','bge_status','structured_ifr_valid','ttft_seconds','tps','system_ram_sampled_peak_gb','dedicated_vram_sampled_peak_gb','memory_scope','shared_gpu_memory_gb','provenance'],existing,{'A':23,'B':12,'C':33,'E':17,'F':18,'G':22,'H':28,'I':20,'N':44,'Q':50}))

question_rows=[]
for q in questions:
    r=srcmap.get(q['question_id'],{}); rv=refmap.get(q['question_id'],{})
    question_rows.append([q['question_id'],q.get('original_question_id'),q.get('species_chinese'),q.get('species_label_in_test_data'),q.get('inferred_category'),q.get('question_format'),q.get('question_text'),q.get('candidate_reference_answer'),q.get('candidate_scoring_key_points'),q.get('candidate_source_urls'),q.get('source_workbook'),q.get('question_bank_excel_row'),q.get('split_label'),q.get('human_gold_reviewed'),rv.get('verification_status'),r.get('verification_status')])
sheets.append(sheet('Questions',['question_id','original_question_id','species','species_label','category','question_type','question_text','candidate_reference_answer','candidate_scoring_key_points','candidate_source_urls','source_workbook','source_row','historical_split_label','human_gold_reviewed','answer_verification_status','source_mapping_status'],question_rows,{'A':22,'C':16,'D':24,'E':21,'G':64,'H':58,'I':55,'J':58,'K':42,'O':32,'P':46}))

raw_idx=[]
for q in questions:
 for mid in models:
  g=genmap.get((q['question_id'],mid),{}); attempt=(g.get('attempts') or [{}])[0]; parsed=attempt.get('parsed') or {}; final=attempt.get('final_event') or {}; raw=attempt.get('raw_output') or ''
  raw_idx.append([q['question_id'],mid,run_id,attempt.get('model_tag') or g.get('model_tag'),attempt.get('model_digest') or g.get('model_digest'),attempt.get('generation_status') or g.get('generation_status'),bool(parsed),parsed.get('answer'),parsed.get('uncertainty'),len(raw),raw[:6000],attempt.get('request_sha256'),g.get('attempt_count'),g.get('retry_policy')])
sheets.append(sheet('Raw_Generation_Index',['question_id','model_id','run_id','model_tag','model_digest','generation_status','parsed_object_available','parsed_answer','parsed_uncertainty','raw_output_chars','raw_output_excerpt_max_6000','request_sha256','attempt_count','retry_policy'],raw_idx,{'A':22,'B':12,'C':32,'D':45,'E':68,'G':22,'H':50,'I':54,'K':76,'L':68,'N':46}))

cp_rows=[]
for qid in sorted(precmap):
 r=precmap[qid]; labs=r.get('final_labels_rank1_to_5') or [None]*5
 cp_rows.append([qid,r.get('species'),r.get('category'),*(labs+[None]*5)[:5],r.get('relevant_count'),r.get('irrelevant_count'),r.get('uncertain_count'),r.get('incomplete_count'),r.get('p_at_5'),r.get('p_at_5_lower_bound'),r.get('p_at_5_upper_bound'),r.get('status'),r.get('context_sha256'),r.get('human_gold_reviewed')])
sheets.append(sheet('Context_Precision',['question_id','species','category','rank1_label','rank2_label','rank3_label','rank4_label','rank5_label','relevant_n','irrelevant_n','uncertain_n','incomplete_n','p_at_5_reported','lower_bound','upper_bound','status','context_sha256','human_gold_reviewed','p_at_5_formula_check'],cp_rows,{'A':22,'B':16,'C':22,'D':18,'E':18,'F':18,'G':18,'H':18,'P':36,'Q':68}))

ctx_rows=[]
for r in contexts:
 ctx_rows.append([r.get('question_id'),r.get('species'),r.get('category'),r.get('chunk_id'),r.get('rank'),r.get('source_id'),r.get('source_title'),r.get('source_url'),r.get('source_version'),r.get('document_id'),r.get('page'),r.get('retrieval_eligibility'),r.get('context_text'),r.get('context_text_sha256'),r.get('text_integrity_status'),r.get('first_pass_completed'),r.get('first_pass_label'),r.get('first_pass_reason_code'),r.get('first_pass_consistency_valid'),r.get('second_pass_completed'),r.get('second_pass_label'),r.get('second_pass_reason_code'),r.get('second_pass_consistency_valid'),r.get('disagreement'),r.get('final_label'),r.get('annotation_status'),r.get('reason'),r.get('exact_evidence_text'),r.get('prompt_version'),r.get('annotator_model_digest'),r.get('human_reviewed')])
sheets.append(sheet('Context_Annotation_QA',['question_id','species','category','chunk_id','rank','source_id','source_title','source_url','source_version','document_id','page','retrieval_eligibility','context_text','context_text_sha256','text_integrity_status','first_pass_completed','first_pass_label','first_pass_reason_code','first_pass_consistency_valid','second_pass_completed','second_pass_label','second_pass_reason_code','second_pass_consistency_valid','disagreement','final_label','annotation_status','reason','exact_evidence_text','prompt_version','annotator_model_digest','human_reviewed'],ctx_rows,{'A':22,'B':16,'D':44,'G':48,'H':54,'I':30,'M':85,'N':68,'Z':25,'AA':58,'AB':56,'AC':34,'AD':68}))

ref_rows=[]
for q in questions:
 r=refmap[q['question_id']]; s=srcmap[q['question_id']]
 ref_rows.append([r.get('question_id'),q.get('species_chinese'),q.get('inferred_category'),r.get('candidate_reference_answer'),r.get('verification_status'),r.get('source_ids'),r.get('source_urls'),r.get('source_location'),r.get('source_url_resolution'),r.get('local_originals'),r.get('exact_support_span'),r.get('answer_supported'),r.get('species_applicability'),r.get('blocker_reason'),r.get('verification_method'),r.get('human_gold_reviewed')])
sheets.append(sheet('Reference_Verification',['question_id','species','category','candidate_answer','automated_status','source_ids','source_urls','source_location','corpus_url_resolution','local_original_file_checksums','exact_support_span','answer_supported','species_applicability','blocker_reason','verification_method','human_gold_reviewed'],ref_rows,{'A':22,'B':16,'C':22,'D':60,'E':40,'F':28,'G':60,'H':40,'I':75,'J':78,'K':46,'N':70,'O':62}))

verified_arith=[]
for mid in models:
 s=source_arith[mid]; verified_arith.append([mid,s['required'],s['evaluable_n'],s['correct_n'],s['incorrect_n'],s['not_evaluable_n'],s['accuracy'],'Source formula/protocol/source span verified candidates = 0; all N/A'])
sheets.append(sheet('Arithmetic_Accuracy',['model_id','required_n','evaluable_n','correct_n','incorrect_n','not_evaluable_n','accuracy','status'],verified_arith,{'A':16,'H':72}))

arith_diag_rows=[]
for a in arith_ref:
 qid=a['question_id']
 for mid in models:
  r=arith_model.get((qid,mid),{})
  arith_diag_rows.append([qid,mid,qmap.get(qid,{}).get('species_chinese'),qmap.get(qid,{}).get('inferred_category'),a.get('phase_e_candidate'),a.get('original_question_structured_calculation'),a.get('phase_g_verification'),a.get('formula_source_verified'),a.get('deterministic_recalculation'),a.get('candidate_reference_answer'),a.get('candidate_matches_decimal'),a.get('self_contained_operands_in_question'),r.get('arithmetic_status'),r.get('numeric_parse'),r.get('reference_candidate_match'),r.get('formula_verification_status'),r.get('human_gold_reviewed'),'ARITHMETIC_DIAGNOSTIC; not source verified'])
for mid in models:
 d=diag['arithmetic_diagnostic_all_available'][mid]
 arith_diag_rows.append([None,mid,None,None,None,None,None,False,None,None,None,None,'SUMMARY',None,None,'not_verified',False,f"All available: {d['n_correct']}/{d['n_evaluable']} = {d['accuracy']}; four-model paired N=0"])
sheets.append(sheet('Arithmetic_Diagnostic',['question_id','model_id','species','category','phase_e_candidate','original_structured_calc','phase_g_status','formula_source_verified','deterministic_recalculation','candidate_reference_answer','candidate_matches_decimal','self_contained_operands','diagnostic_status','numeric_parse','reference_candidate_match','formula_verification_status','human_gold_reviewed','scope_and_basis'],arith_diag_rows,{'A':22,'B':12,'C':16,'D':22,'I':48,'J':42,'M':34,'N':55,'R':72}))

logical_summary=[]
for mid in models:
 s=logical['by_model'][mid]; logical_summary.append([mid,s['required'],s['evaluable_n'],s['correct_n'],s['incorrect_n'],s['not_evaluable_n'],s['accuracy'],logical['status']])
sheets.append(sheet('Logical_Accuracy',['model_id','required_n','evaluable_n','correct_n','incorrect_n','not_evaluable_n','accuracy','status'],logical_summary,{'A':16,'H':70}))

retrieval_rows=[]
for q in questions:
 tr=tmap[q['question_id']]; cs=sorted(tr.get('contexts',[]),key=lambda x:x.get('top5_rank',999))
 retrieval_rows.append([q['question_id'],q.get('species_chinese'),q.get('inferred_category'),tr.get('corpus_version'),tr.get('context_sha256'),[c.get('chunk_id') for c in cs],[c.get('document_id') for c in cs],[c.get('top5_rank') for c in cs],len(cs),tr.get('retrieval_config'),tr.get('retrieval_hit'),tr.get('context_sufficient_by_judge'),'Same frozen Top-5 shared by M1–M4; no model-specific P@5'])
sheets.append(sheet('Retrieval',['question_id','species','category','corpus_version','context_digest','top5_chunk_ids','top5_document_ids','ranks','context_count','retrieval_config','retrieval_hit_or_status','judge_context_sufficiency','use_note'],retrieval_rows,{'A':22,'B':16,'C':22,'D':26,'E':68,'F':80,'G':80,'J':64,'M':60}))

def grouped_metric(qids,mid):
 keys={'judge_faithfulness':'judge_faithfulness','judge_answer_relevance':'judge_answer_relevance','bge_m3_answer_relevance_cosine':'bge_m3_answer_relevance_cosine','ttft_final_content_seconds':'ttft_seconds','tps_ollama_eval_rate':'tps'}
 out={}
 for metric,key in keys.items():
  vals=[]
  for qid in qids:
   if metric.startswith('judge_'):
    z=judgemap.get((qid,mid),{}); x=z.get(key) if z.get('judge_score_valid') else None
   elif metric=='bge_m3_answer_relevance_cosine':
    z=bgemap.get((qid,mid),{}); x=z.get(key) if z.get('status')=='scored' else None
   else: x=metricmap.get((qid,mid),{}).get(key)
   if x is not None: vals.append(float(x))
  out[metric]={'n':len(vals),'mean':sum(vals)/len(vals) if vals else None}
 schema=[judgemap.get((qid,mid),{}).get('structure_valid') for qid in qids]; schema=[x for x in schema if x is not None]
 out['structured_output_valid']={'n':len(schema),'mean':sum(bool(x) for x in schema)/len(schema) if schema else None}
 dr=[arith_model.get((qid,mid),{}).get('arithmetic_status') for qid in qids]; ev=[x for x in dr if x in {'correct','incorrect'}]
 out['arithmetic_diagnostic']={'n':len(ev),'correct_n':sum(x=='correct' for x in ev),'mean':sum(x=='correct' for x in ev)/len(ev) if ev else None}
 return out
species_counts=collections.Counter(q.get('species_chinese') for q in questions)
species_rows=[]
for sp in sorted(species_counts):
 qids=[q['question_id'] for q in questions if q.get('species_chinese')==sp]
 for mid in models:
  a=grouped_metric(qids,mid)
  species_rows.append([sp,mid,species_counts[sp],None,0,a['judge_faithfulness']['mean'],a['judge_faithfulness']['n'],a['judge_answer_relevance']['mean'],a['judge_answer_relevance']['n'],a['bge_m3_answer_relevance_cosine']['mean'],a['bge_m3_answer_relevance_cosine']['n'],a['structured_output_valid']['mean'],a['structured_output_valid']['n'],a['arithmetic_diagnostic']['mean'],a['arithmetic_diagnostic']['n'],None,0,None,0,a['ttft_final_content_seconds']['mean'],a['ttft_final_content_seconds']['n'],a['tps_ollama_eval_rate']['mean'],a['tps_ollama_eval_rate']['n'],'P@5, source-verified arithmetic and Logical N=0; existing metrics remain exploratory'])
sheets.append(sheet('Species_Comparison',['species','model_id','question_n','context_p_at_5_mean','context_p_at_5_n','judge_faithfulness_mean','judge_faithfulness_n','judge_relevance_mean','judge_relevance_n','bge_m3_cosine_mean','bge_m3_cosine_n','structured_ifr_mean','structured_ifr_n','arithmetic_diagnostic_mean','arithmetic_diagnostic_n','source_verified_arithmetic_mean','source_verified_arithmetic_n','logical_accuracy_mean','logical_accuracy_n','ttft_mean_seconds','ttft_n','tps_mean','tps_n','limitation'],species_rows,{'A':16,'B':12,'X':82}))
cat_counts=collections.Counter(q.get('inferred_category') for q in questions)
category_rows=[]
for cat in sorted(cat_counts):
 qids=[q['question_id'] for q in questions if q.get('inferred_category')==cat]
 for mid in models:
  a=grouped_metric(qids,mid)
  category_rows.append([cat,mid,cat_counts[cat],None,0,a['judge_faithfulness']['mean'],a['judge_faithfulness']['n'],a['judge_answer_relevance']['mean'],a['judge_answer_relevance']['n'],a['bge_m3_answer_relevance_cosine']['mean'],a['bge_m3_answer_relevance_cosine']['n'],a['structured_output_valid']['mean'],a['structured_output_valid']['n'],a['arithmetic_diagnostic']['mean'],a['arithmetic_diagnostic']['n'],None,0,None,0,a['ttft_final_content_seconds']['mean'],a['ttft_final_content_seconds']['n'],a['tps_ollama_eval_rate']['mean'],a['tps_ollama_eval_rate']['n'],'P@5, source-verified arithmetic and Logical N=0; existing metrics remain exploratory'])
sheets.append(sheet('Category_Comparison',['category','model_id','question_n','context_p_at_5_mean','context_p_at_5_n','judge_faithfulness_mean','judge_faithfulness_n','judge_relevance_mean','judge_relevance_n','bge_m3_cosine_mean','bge_m3_cosine_n','structured_ifr_mean','structured_ifr_n','arithmetic_diagnostic_mean','arithmetic_diagnostic_n','source_verified_arithmetic_mean','source_verified_arithmetic_n','logical_accuracy_mean','logical_accuracy_n','ttft_mean_seconds','ttft_n','tps_mean','tps_n','status'],category_rows,{'A':24,'B':12,'X':82}))

paired_rows=[]
for analysis_name,group in [('All Available',paired.get('all_available_samples',{})),('Four-model Paired',paired.get('paired_common_samples',{}))]:
 for metric,by_model in group.items():
  if isinstance(by_model,dict) and all(mid in by_model for mid in models):
   # paired common groups store shared question list and model-specific stats for each metric.
   for mid in models:
    r=by_model.get(mid,{})
    if isinstance(r,dict): paired_rows.append([analysis_name,metric,mid,r.get('n'),r.get('mean'),r.get('median'),r.get('std'),r.get('lower_ci'),r.get('upper_ci'),'Exploratory; paired status follows Phase E source'])
  elif analysis_name=='Four-model Paired' and 'question_ids' in by_model:
   paired_rows.append([analysis_name,metric,'ALL4',by_model.get('n'),None,None,None,None,None,'Question IDs shared across all 4 models; see Phase E paired_sample_comparison.json'])
paired_rows += [['Four-model Paired','Source-verified Arithmetic','ALL4',0,None,None,None,None,None,'No formula/source-verified arithmetic questions'],['Four-model Paired','Logical Accuracy','ALL4',0,None,None,None,None,None,'No frozen source-supported logical rubrics'],['Shared Retrieval','Context Precision@5','ALL4',0,None,None,None,None,None,'P@5 is shared and currently not computable']]
sheets.append(sheet('Paired_Comparison',['sample_policy','metric','model_id_or_group','n','mean','median','std','ci_low','ci_high','note'],paired_rows,{'A':25,'B':40,'J':74}))

source_rows=[]
for q in questions:
 s=srcmap[q['question_id']]; r=refmap[q['question_id']]
 source_rows.append([q['question_id'],q.get('species_chinese'),q.get('inferred_category'),s.get('source_ids'),s.get('source_urls'),s.get('verification_status'),s.get('source_url_resolution'),s.get('local_originals'),s.get('retrieved_context_sources'),s.get('questions_with_exact_support_span_verified'),r.get('verification_status'),r.get('answer_supported'),r.get('exact_support_span'),r.get('species_applicability'),r.get('blocker_reason'),'NOT_HUMAN_GOLD'])
sheets.append(sheet('Source_Provenance',['question_id','species','category','source_ids','source_urls','source_mapping_status','corpus_url_resolution','local_original_files','retrieved_context_source_links','exact_support_span_verified','answer_verification_status','answer_supported','exact_support_span','species_applicability','blocker_reason','human_gold_status'],source_rows,{'A':22,'B':16,'C':22,'D':26,'E':62,'F':50,'G':78,'H':76,'I':76,'J':32,'O':74}))

errors=[]
for log_name in ['annotation_failed_attempts.jsonl','annotation_batch_failures.jsonl']:
 for r in jl(PG/log_name): errors.append([log_name,r.get('question_id'),r.get('round'),r.get('error_type'),r.get('error'),None,r.get('prompt_version'),'Phase G historical failure; preserved, not rewritten'])
for log_name in ['pilot_annotation_errors.jsonl','pilot_annotation_errors_v2_1.jsonl','pilot_annotation_errors_v2_2.jsonl','pilot_annotation_errors_v2_3.jsonl','pilot_annotation_errors_v2_4.jsonl','pilot_annotation_errors_v2_5.jsonl']:
 for r in jl(OUT/log_name):
  for a in r.get('attempts',[]): errors.append([log_name,r.get('question_id'),r.get('round'),a.get('error_type'),a.get('error'),a.get('raw_response_sha256'),r.get('prompt_version'),(a.get('raw_response_excerpt') or '')[:800]])
for r in contexts:
 if r.get('annotation_status')=='ANNOTATION_ERROR': errors.append(['derived_quality_audit',r.get('question_id'),r.get('rank'),'ConsistencyError','Completed pass label/reason contradiction; excluded from P@5',None,r.get('prompt_version'),r.get('reason')])
sheets.append(sheet('Annotation_Errors',['source_log','question_id','round_or_rank','error_type','error','raw_response_sha256','prompt_version','details'],errors,{'A':44,'B':24,'D':34,'E':76,'F':68,'G':40,'H':76}))

limits=[
 ['Context Precision@5','NOT_EVALUABLE','0/180 complete P@5','Local independent Judge misattributed an 烏魚 passage to 吳郭魚 and produced unalignable Chinese quotes; pilot failed; no full rerun'],
 ['Source answer verification','NOT_EVALUABLE','0/180 verified answer spans','29 questions map to 3 checksum-verified local files; none has exact support span + applicability verified'],
 ['Source-verified Arithmetic','NOT_EVALUABLE','0/68','No authoritative formula/protocol source span verified; keep all four model scores N/A'],
 ['Arithmetic diagnostic','EXPLORATORY','M1 7/9; M2 15/23; M3 4/7; M4 2/5; paired N=0','Question-text operand arithmetic only; not domain/formula accuracy'],
 ['Logical Accuracy','NOT_EVALUABLE','0/180; 0 rubrics','No source-verified reference answer and objective logical rubric'],
 ['Human Gold','NOT_COMPLETED','0','Automated checks are not researcher review'],
 ['Judge Faithfulness / Judge Relevance','EXISTING_EXPLORATORY','See Existing_Metrics','Preserved from Phase E; judge relevance remains distinct from BGE-M3 cosine'],
 ['BGE-M3 relevance cosine','EXISTING_EXPLORATORY','Phase E valid samples vary by model','Embedding similarity is not answer correctness'],
 ['Context Precision labels','AI_AUTO_ANNOTATED','3 IRRELEVANT; 4 ANNOTATION_ERROR; 893 INCOMPLETE','No completed exact P@5; not Human Gold'],
 ['Model weight policy','UNCONFIRMED','No composite score','Memory pressure and TTFT/TPS normalization unconfirmed; no Winner'],
 ['Selection/Holdout','NOT_FORMAL','All 180 participated in prior exploratory run','Cannot claim unseen formal holdout'],
 ['Tests','PARTIAL','Script syntax + data/workbook checks only','Full repository pytest not run; tempfile WinError 5 remains tracked'],
 ['Protected baseline','VERIFIED','636/636 unchanged; SQLite expected SHA matches','No originals, E4/Corpus v2, models, Judge or historical run outputs modified'],
]
sheets.append(sheet('Limitations',['metric_or_asset','status','sample_or_result','limitation'],limits,{'A':35,'B':26,'C':52,'D':110}))

provenance=[
 ['normalized_questions',str(RUN/'fish_test_questions_normalized.jsonl'),len(questions),'read-only input'],
 ['original_generations',str(RUN/'generation_outputs.jsonl'),len(gen),'read-only; no generator rerun'],
 ['shared_retrieval',str(RUN/'retrieval_trace.jsonl'),len(traces),'read-only; contexts fixed across four models'],
 ['phase_e_judge_audit',str(PE/'judge_structure_consistency_audit.jsonl'),len(judge),'read-only original metric audit'],
 ['phase_e_bge_m3',str(PE/'bge_m3_answer_relevance.jsonl'),len(bge),'read-only original embedding metric'],
 ['phase_g_arithmetic',str(PG/'arithmetic_accuracy_by_model_rows.jsonl'),len(arith_rows),'diagnostic-only; source verified N=0'],
 ['phase_h_context_annotations',str(OUT/'context_annotations_recovered_900.jsonl'),len(contexts),'new AI annotation statuses; full contexts checksum verified'],
 ['phase_h_source_mapping',str(OUT/'source_mapping_recovery_180.jsonl'),len(sources),'locator reconciliation; not entailment'],
 ['phase_h_workbook_output',str(OUT/'fish_test_evaluation_results_v4.xlsx'),None,'new separate report; no originals overwritten'],
 ['judge_model_digest','mistral-nemo:12b-instruct-2407-q4_K_M / daf6737417121831e572a9c482e92a221ee0c33537f35f1f857c7b4f7191df55',None,'identity verified via local Ollama tags'],
 ['embedding_model_digest','bge-m3:latest / 7907646426070047a77226ac3e684fbbe8410524f7b4a74d02837e43f2146bab',None,'Phase E verified existing runs; not recomputed'],
 ['protected_manifest',str(ROOT/'reports/evaluation/fish_test_phase_a_20261012/protected_files_manifest.json'),compat.get('historical_636_rechecked'),'636 hashes rechecked'],
]
sheets.append(sheet('Provenance',['asset','path_or_identity','record_count','notes'],provenance,{'A':30,'B':90,'C':18,'D':80}))

# Formulate the workbook with data only; exact P@5 formula is also added independently by the JS authoring step.
payload={'workbook':'fish_test_evaluation_results_v4.xlsx','created_at':'2026-10-14','classification':'EXPLORATORY; AI_AUTO_ANNOTATED; NOT_HUMAN_GOLD; no winner','sheets':sheets}
(OUT/'workbook_payload_v4.json').write_text(json.dumps(payload,ensure_ascii=False,allow_nan=False,separators=(',',':')),encoding='utf-8')
print(json.dumps({'sheets':len(sheets),'sheet_names':[s['name'] for s in sheets],'questions':len(questions),'generations':len(gen),'retrieval':len(traces),'contexts':len(contexts),'model_comparison_rows':len(comp),'payload_bytes':(OUT/'workbook_payload_v4.json').stat().st_size},ensure_ascii=False))
