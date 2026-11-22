"""Final read-only result checks and a manifest; no model or score reruns."""
import collections,json,math,pathlib,sys
ROOT=pathlib.Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tools')]
import evaluate_unified_rag_v6 as ev
import score_unified_rag_v6 as sc

def main():
    w=ev.work();ev.verify_freeze(w,True);g=ev.jl(w/'generator_final_results_720.jsonl');quality=ev.jl(w/'judge_quality_detailed.jsonl');arith=ev.jl(w/'arithmetic_accuracy_detailed.jsonl');logic=ev.jl(w/'logical_accuracy_detailed.jsonl');assert len(g)==720 and len(quality)==1440
    workbook=ev.read(w/'workbook_validation.json');assert workbook['cached_formula_values_match_json'] and workbook['sha256']==ev.sha(w/'rag_v6_evaluation_results.xlsx')
    quality_errors=[]
    for r in quality:
        if r.get('evaluation',{}).get('status')=='judge_error':
            assert r['faithfulness'] is None and r['judge_answer_relevance'] is None;quality_errors.append({k:r.get(k) for k in ('question_id','model_id','answer_layer','input_key','evaluation')})
        for key in ('faithfulness','judge_answer_relevance'):
            if r[key] is not None:assert math.isfinite(r[key]) and 0<=r[key]<=1
    issues=[];ttft=[]
    for r in g:
        answer,reason=sc.visible(r,'model')
        if reason in ('QUESTION_ECHO','UNANSWERED_INTERROGATIVE','INCOMPLETE_CONDITION_ONLY'):issues.append({'question_id':r['question_id'],'model_id':r['model_id'],'reason':reason,'raw_model_response':r['raw_model_response'],'record_preserved':True})
        if r['ttft_seconds'] is None:
            events=ev.jl(r['stream_file']);content=[x for x in events if x['event'].get('response')];thinking=[x for x in events if x['event'].get('thinking')]
            ttft.append({'question_id':r['question_id'],'model_id':r['model_id'],'stream_file':r['stream_file'],'stream_event_count':len(events),'first_content_event_seconds':content[0]['elapsed_seconds'] if content else None,'first_thinking_event_seconds':thinking[0]['elapsed_seconds'] if thinking else None,'eval_count':r['engine_metrics'].get('eval_count'),'eval_duration_ns':r['engine_metrics'].get('eval_duration'),'original_ttft_seconds':None,'reason':'NO_VISIBLE_CONTENT_EVENT' if not content else 'CONTENT_EVENT_PRESENT_REQUIRES_SEPARATE_CORRECTION','no_imputation':True})
    species_warnings=[]
    for r in logic:
        details=r.get('evaluation',{}).get('scores') or {}
        if 'goldfish' in json.dumps(details,ensure_ascii=False).lower() and r['species']!='金魚':species_warnings.append({'question_id':r['question_id'],'model_id':r['model_id'],'answer_layer':r['answer_layer'],'source_species':r['species'],'original_verdict':r['verdict'],'judge_scores':details,'warning':'Judge mentions goldfish in a different-species case; AI translation/scope requires review. Original score retained; not expert truth.'})
    for name,rows in [('judge_quality_error_review.jsonl',quality_errors),('model_answer_content_issue_review.jsonl',issues),('ttft_missingness_audit.jsonl',ttft),('judge_species_wording_review.jsonl',species_warnings)]:
        with (w/name).open('w',encoding='utf-8') as f:
            for r in rows:f.write(json.dumps(r,ensure_ascii=False)+'\n')
    source_qc=ev.read(w/'evaluation_metrics_11_source_qc.json');assert source_qc['post_run_source_qc']['original_metrics_sha256']==ev.sha(w/'evaluation_metrics_11.json') and source_qc['post_run_source_qc']['original_logical_rows_sha256']==ev.sha(w/'logical_accuracy_detailed.jsonl')
    protection=ev.baseline(w,'final_delivery');ev.verify_freeze(w,True)
    result={'at':ev.now(),'generator_final_records':720,'quality_layer_records':1440,'logical_layer_records':len(logic),'arithmetic_layer_records':len(arith),'quality_error_layer_records':len(quality_errors),'quality_error_by_model':dict(collections.Counter(r['model_id'] for r in quality_errors)),'content_issue_records':len(issues),'content_issue_by_model':dict(collections.Counter(r['model_id'] for r in issues)),'ttft_missing_records':ttft,'judge_species_wording_warning_n':len(species_warnings),'judge_species_wording_correct_verdict_warning_n':sum(r['original_verdict']=='correct' for r in species_warnings),'scores_not_modified_by_final_review':True,'human_gold_n':0,'workbook_sha256':workbook['sha256'],'protected':protection,'no_weighted_total_or_winner':True}
    result['separate_post_run_source_qc']=source_qc['post_run_source_qc'];result['scores_not_modified_by_final_review']='Original frozen Judge JSONL and evaluation_metrics_11.json are unchanged; separate corrected derived files explicitly versioned.'
    ev.dump(w/'final_result_quality_audit.json',result)
    artifacts=['frozen_evaluation_manifest.json','questions_original_180.jsonl','shared_contexts_180.jsonl','verified_reference_answers_v6.jsonl','evaluation_rubrics_v6_frozen.json','metric_spec_v6.json','model_runtime_identity.json','model_runtime_identity_after.json','generator_raw_attempts_720.jsonl','generator_final_results_720.jsonl','per_question_metrics.jsonl','efficiency_metrics.jsonl','model_vs_system_outcomes.jsonl','judge_raw_attempts.jsonl','judge_quality_detailed.jsonl','bge_relevance_detailed.jsonl','logical_accuracy_detailed.jsonl','arithmetic_accuracy_detailed.jsonl','evaluation_metrics_11.json','paired_sample_comparison.json','species_category_comparison.json','source_group_evaluation.json','duplicate_sensitivity.json','context_precision_labels_v6.jsonl','context_precision_detailed.jsonl','context_precision_summary.json','abstention_analysis.json','answer_origin_and_evidence_comparison.json','correct_content_rejected_by_program_diagnostics.jsonl','reference_original_file_integrity.json','repository_pytest_results.json','evaluation_validation.json','workbook_validation.json','final_result_quality_audit.json','compatibility.json','final_720_evaluation_report.md','rag_v6_evaluation_results.xlsx']
    artifacts+=['evaluation_metrics_11_source_qc.json','logical_accuracy_source_qc_detailed.jsonl','source_qc_judge_review_9.jsonl','paired_logical_source_qc.json']
    manifest={'run_id':w.name,'completed_at':ev.now(),'files':[{'path':str(w/n),'sha256':ev.sha(w/n),'bytes':(w/n).stat().st_size} for n in artifacts],'reporting_code':[{'path':str(p),'sha256':ev.sha(p)} for p in [ROOT/'tools/summarize_unified_rag_v6.py',ROOT/'tools/validate_v6_evaluation_workbook.py',ROOT/'tools/source_qc_v6_judge_results.py',pathlib.Path(__file__),w/'build_evaluation_workbook.mjs']],'raw_data_and_frozen_inputs_unchanged':True,'source_qc_scope':source_qc['post_run_source_qc'],'workbook_formula_engine_repair':'AVERAGEIFS error was replaced by mathematically equivalent SUMIFS / explicit valid-N; all 88 original mean/N pairs and source-QA summaries independently checked; initial invalid export retained in outputs/.'}
    ev.dump(w/'result_artifact_manifest.json',manifest);ev.dump(w/'finalization_status.json',{'stage':'ALL_COMPLETE','status':'COMPLETE','at':ev.now(),'workbook_reopened_and_validated':True,'initial_workbook_formula_error_preserved_and_repaired':True,'raw_generation_rerun_after_completion':False});ev.emit(result)

if __name__=='__main__':main()
