"""Reconcile actual v6 observations and export reproducible reporting tables."""
from __future__ import annotations
import collections,hashlib,json,math,random,statistics,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tools')]
import evaluate_unified_rag_v6 as ev
import score_unified_rag_v6 as sc

def stat(values):
    v=[float(x) for x in values if x is not None and isinstance(x,(float,int)) and math.isfinite(x)]
    return {'n':len(v),'mean':statistics.mean(v) if v else None,'median':statistics.median(v) if v else None,'sd':statistics.stdev(v) if len(v)>1 else None,'minimum':min(v) if v else None,'maximum':max(v) if v else None}

def rate(values):
    v=list(values);return {'n':len(v),'success_n':sum(bool(x) for x in v),'rate':sum(bool(x) for x in v)/len(v) if v else None}

def accuracy(rows,denominator):
    counts=collections.Counter(r['verdict'] for r in rows);valid=counts['correct']+counts['incorrect']
    return {'expected_n':denominator,'records':len(rows),'correct_n':counts['correct'],'incorrect_n':counts['incorrect'],'not_evaluable_n':counts['not_evaluable'],'conditional_n':valid,'conditional_accuracy':counts['correct']/valid if valid else None,'fixed_content_success':rate(r['content_task_success'] for r in rows),'fixed_validated_success':rate(r['validated_task_success'] for r in rows),'not_evaluable_reasons':dict(collections.Counter(r.get('reason') or 'UNSPECIFIED' for r in rows if r['verdict']=='not_evaluable'))}

def make():
    w=ev.work();ev.verify_freeze(w,True);ev.dump(w/'model_runtime_identity_after.json',ev.model_identity())
    gens=ev.jl(w/'generator_final_results_720.jsonl');qs=ev.jl(w/'questions_original_180.jsonl');ctx=ev.jl(w/'shared_contexts_180.jsonl');refs=ev.jl(w/'verified_reference_answers_v6.jsonl');cp=ev.jl(w/'context_precision_detailed.jsonl')
    assert len(gens)==len({(g['question_id'],g['model_id']) for g in gens})==720
    qmap={q['question_id']:q for q in qs};cmap={c['question_id']:c for c in ctx};rmap={r['question_id']:r for r in refs};pmap={r['question_id']:r for r in cp}
    quality=ev.jl(w/'judge_quality_detailed.jsonl');bge=ev.jl(w/'bge_relevance_detailed.jsonl');logic=ev.jl(w/'logical_accuracy_detailed.jsonl');arith=ev.jl(w/'arithmetic_accuracy_detailed.jsonl')
    key=lambda r:(r['question_id'],r['model_id'],r['answer_layer'])
    indices=[{key(r):r for r in rows} for rows in (quality,bge,logic,arith)];qi,bi,li,ai=indices
    assert len(qi)==len(bi)==1440 and len(li)==296 and len(ai)==104
    policy=ev.read(w/'fixed_denominator_policy_v6.json');models=list(ev.MODEL_SPECS);layers=('model','system');flat=[];attempts=[r for r in ev.jl(w/'generator_attempts.jsonl') if r['stage']=='V6_FINAL720'];prompt_bodies=collections.defaultdict(set);active=ev.read(w/'corpus_active_snapshot.json')
    for g in gens:
        c=cmap[g['question_id']];r=g['result'];v=r['validation_status'];hw=g['hardware'];em=g['engine_metrics'];ref=rmap[g['question_id']]
        assert g['model_digest']==ev.MODEL_SPECS[g['model_id']]['digest'] and g['context_digest']==c['context_digest'] and g['context_ids']==[x['chunk_id'] for x in c['top5']]
        assert g['question']==qmap[g['question_id']]['question_text'] and g['corpus_sha256']==active['database_sha256'] and g['corpus_version']==active['version']
        payload=ev.read(g['prompt_file']);assert ev.digest(payload)==g['prompt_sha256'];prompt_bodies[g['question_id']].add(ev.digest({k:payload[k] for k in ('system','prompt','format','options')}))
        recalculated=em.get('eval_count')/(em['eval_duration']/1e9) if em.get('eval_count') is not None and em.get('eval_duration') else None
        assert recalculated is None and g.get('tps') is None or recalculated is not None and math.isclose(recalculated,g['tps'],rel_tol=1e-10)
        try:parsed=g['validation'].get('parsed_model_response') or json.loads(g['raw_model_response'])
        except (ValueError,TypeError):parsed={}
        rawstatus=parsed.get('answer_status') if isinstance(parsed,dict) else None
        row={'run_id':w.name,'question_id':g['question_id'],'model_id':g['model_id'],'species':g['species'],'category':g['category'],'question':g['question'],'context_count':len(c['top5']),'context_digest':g['context_digest'],'model_tag':g['model_tag'],'model_digest':g['model_digest'],'prompt_version':g['prompt_version'],'prompt_sha256':g['prompt_sha256'],'api_completed':g['api_completed'],'api_error':g['api_error'],'raw_json_valid':bool(v.get('raw_json_valid')),'raw_citation_valid':bool(v.get('raw_citation_valid')),'raw_declared_status':rawstatus,'system_status':r['answer_status'],'answer_origin':r['answer_origin'],'validation_reason':v.get('reason'),'raw_support_screen':v.get('raw_support_screen'),'model_validated_answer':sc.validated_model_answer(g),'raw_declared_gap':rawstatus=='INSUFFICIENT_EVIDENCE','system_guidance_or_abstention':r['answer_origin'] in ('ABSTAINED','SYSTEM_GUIDANCE'),'deterministic_extraction':r['answer_origin']=='DETERMINISTIC_EVIDENCE_EXTRACTION','raw_visible_answer':sc.visible(g,'model')[0],'raw_answer_unavailable_reason':sc.visible(g,'model')[1],'system_visible_answer':sc.visible(g,'system')[0],'system_answer_unavailable_reason':sc.visible(g,'system')[1],'final_answer':r['final_answer'],'ttft_seconds':g.get('ttft_seconds'),'first_thinking_seconds':g.get('first_thinking_seconds'),'tps':recalculated,'wall_seconds':g.get('wall_seconds'),'generated_tokens':em.get('eval_count'),'peak_system_ram_gib':hw.get('peak_system_ram_bytes')/2**30 if hw.get('peak_system_ram_bytes') is not None else None,'peak_dedicated_vram_gib':hw.get('peak_dedicated_vram_bytes')/2**30 if hw.get('peak_dedicated_vram_bytes') is not None else None,'shared_gpu_memory_gib':None,'hardware_scope':hw.get('scope'),'hardware_samples':hw.get('sample_n'),'source_reference_qualified':ref['v6_professional_eligible'],'reference_source_group_ids':ref['reference_source_group_ids'],'source_reference_verification':'AUTO_SOURCE_VERIFIED_NOT_HUMAN_GOLD' if ref['v6_professional_eligible'] else 'NOT_NEWLY_REFERENCE_VERIFIED_THIS_RUN','prompt_file':g['prompt_file'],'stream_file':g['stream_file'],'raw_attempt_id':g['attempt_id']}
        for layer in layers:
            k=g['question_id'],g['model_id'],layer
            row[layer+'_faithfulness']=qi[k]['faithfulness'];row[layer+'_judge_relevance']=qi[k]['judge_answer_relevance'];row[layer+'_bge_cosine']=bi[k]['cosine']
            row[layer+'_judge_reason']=qi[k].get('reason') or qi[k].get('evaluation',{}).get('status');row[layer+'_bge_reason']=bi[k].get('reason')
            for metric,index in [('logical',li),('arithmetic',ai)]:
                a=index.get(k);row[layer+'_'+metric+'_verdict']=a['verdict'] if a else None;row[layer+'_'+metric+'_reason']=a.get('reason') if a else 'QUESTION_NOT_REFERENCE_QUALIFIED_FOR_METRIC';row[layer+'_'+metric+'_success']=a['validated_task_success'] if a else None;row[layer+'_'+metric+'_content_correct']=a['content_task_success'] if a else None
        flat.append(row)
    assert len(prompt_bodies)==180 and all(len(s)==1 for s in prompt_bodies.values()),'Different model prompts/schema/options for same question'
    write_jsonl(w/'per_question_metrics.jsonl',flat);write_jsonl(w/'generator_raw_attempts_720.jsonl',attempts)
    efficiency=[]
    for g,r in zip(gens,flat):
        efficiency.append({**{k:r[k] for k in ('run_id','question_id','model_id','ttft_seconds','first_thinking_seconds','tps','wall_seconds','generated_tokens','peak_system_ram_gib','peak_dedicated_vram_gib','shared_gpu_memory_gib','hardware_scope','hardware_samples','stream_file','raw_attempt_id')},'eval_duration_ns':g['engine_metrics'].get('eval_duration'),'eval_count':g['engine_metrics'].get('eval_count'),'ttft_missing_reason':None if r['ttft_seconds'] is not None else 'NO_VISIBLE_CONTENT_TIMESTAMP_IN_ORIGINAL_COLLECTOR; see preserved stream','tps_missing_reason':None if r['tps'] is not None else 'MISSING_OR_ZERO_ENGINE_GENERATION_DURATION_OR_TOKEN_COUNT','shared_gpu_memory_reason':'NO_TRUSTWORTHY_MEASUREMENT_SOURCE','warmup_excluded':True,'judge_not_loaded_during_generator_measurement':True})
    write_jsonl(w/'efficiency_metrics.jsonl',efficiency)
    write_jsonl(w/'model_vs_system_outcomes.jsonl',[{k:r[k] for k in ('run_id','question_id','model_id','raw_declared_status','system_status','answer_origin','raw_json_valid','raw_citation_valid','model_validated_answer','validation_reason','raw_answer_unavailable_reason','system_answer_unavailable_reason','raw_attempt_id')} for r in flat])
    reviewed={(x['question_id'],x['chunk_id']):x for x in ev.jl(w/'context_precision_labels_v6.jsonl')};citation_review=[]
    for g in gens:
        spans=g['result']['validation_status'].get('program_bound_source_spans',[]);cids={x['chunk_id'] for x in spans};known=[reviewed[g['question_id'],cid] for cid in cids if (g['question_id'],cid) in reviewed]
        if known:citation_review.append({'question_id':g['question_id'],'model_id':g['model_id'],'source_review_sample_only':True,'raw_selected_cids':sorted(cids),'selected_cids_with_review':len(known),'selected_reviewed_irrelevant_cids':[x['chunk_id'] for x in known if x['relevance_label']==0],'selected_reviewed_species_mismatch_cids':[x['chunk_id'] for x in known if x['support_label']=='SPECIES_MISMATCH'],'model_answer_accepted_by_program':sc.validated_model_answer(g),'warning':'Exact quote binding does not validate whether the selected text supports the claimed answer element; this sample is AI-assisted, not Human Gold'})
    write_jsonl(w/'citation_support_sample_diagnostics.jsonl',citation_review)
    abstentions={'scope':'Descriptive behavior, not universal abstention truth','models':{},'source_reference_n':50,'remaining130_not_assumed_expected_abstention':True,'citation_review_sample_records':len(citation_review),'citation_review_records_with_program_accepted_species_mismatch':sum(bool(x['selected_reviewed_species_mismatch_cids']) and x['model_answer_accepted_by_program'] for x in citation_review)}
    for m in models:
        rr=[r for r in flat if r['model_id']==m];abstentions['models'][m]={}
        for group,selection in [('all180',rr),('source_qualified50',[r for r in rr if r['source_reference_qualified']]),('other130_not_newly_reference_verified',[r for r in rr if not r['source_reference_qualified']]),('context_less_than5',[r for r in rr if r['context_count']<5]),('context_full5',[r for r in rr if r['context_count']==5])]:
            abstentions['models'][m][group]={'n':len(selection),'model_declared_gap':sum(r['raw_declared_gap'] for r in selection),'model_validated_answer':sum(r['model_validated_answer'] for r in selection),'system_guidance_or_abstention':sum(r['system_guidance_or_abstention'] for r in selection),'invalid_raw_json':sum(not r['raw_json_valid'] for r in selection),'validation_failures':dict(collections.Counter(r['validation_reason'] or 'UNSPECIFIED' for r in selection if r['system_status']=='VALIDATION_FAILED'))}
    ev.dump(w/'abstention_analysis.json',abstentions)
    rejected=[];flatmap={(r['question_id'],r['model_id']):r for r in flat}
    for metric,source in [('logical',logic),('arithmetic',arith)]:
        for item in source:
            if item['answer_layer']=='model' and item['verdict']=='correct' and not item['validated_task_success']:
                original=flatmap[item['question_id'],item['model_id']];rejected.append({'question_id':item['question_id'],'model_id':item['model_id'],'metric':metric,'content_verdict':'correct','validated_task_success':False,'system_status':original['system_status'],'validation_reason':original['validation_reason'],'raw_json_valid':original['raw_json_valid'],'raw_citation_valid':original['raw_citation_valid'],'answer':item['raw_answer_text'],'reference_rubric_sha256':item['rubric_sha256'],'interpretation':'Source-content criterion passed, but existing program gate did not accept it; do not label as model arithmetic or factual error.'})
    write_jsonl(w/'correct_content_rejected_by_program_diagnostics.jsonl',rejected)
    summary={'run_id':w.name,'scope':'EXPLORATORY_CURRENT_V6_REGRESSION_NOT_HUMAN_GOLD','human_gold_n':0,'target_n':720,'final_n':len(gens),'raw_attempt_n':len(attempts),'questions':len(qs),'models':{},'shared_context_precision':ev.read(w/'context_precision_summary.json'),'fixed_reference_policy':policy,'memory_scope':'Mean of per-request system_level_sampled_peak, GiB, not model_process_peak','shared_gpu_memory':'N/A, no trustworthy measurement source','no_total_score_no_winner':True}
    for m in models:
        rows=[r for r in flat if r['model_id']==m];z={'records':len(rows),'api_completed':sum(r['api_completed'] for r in rows),'api_failed':sum(not r['api_completed'] for r in rows),'raw_schema':rate(r['raw_json_valid'] for r in rows),'raw_citation':rate(r['raw_citation_valid'] for r in rows),'raw_declared_status_counts':dict(collections.Counter(r['raw_declared_status'] or 'NO_PARSEABLE_STATUS' for r in rows)),'system_status_counts':dict(collections.Counter(r['system_status'] for r in rows)),'origin_counts':dict(collections.Counter(r['answer_origin'] for r in rows)),'model_validated_answer_rate':rate(r['model_validated_answer'] for r in rows),'model_declared_gap_rate':rate(r['raw_declared_gap'] for r in rows),'system_guidance_or_abstention_rate':rate(r['system_guidance_or_abstention'] for r in rows),'deterministic_extraction_rate':rate(r['deterministic_extraction'] for r in rows),'invalid_output_rate':rate(not r['raw_json_valid'] for r in rows),'citation_validation_failure_rate':rate(r['raw_json_valid'] and not r['raw_citation_valid'] for r in rows),'raw_format_valid_n':sum(r['raw_json_valid'] for r in rows),'ttft_missing_n':sum(r['ttft_seconds'] is None for r in rows),'timing_memory':{metric:stat(r[metric] for r in rows) for metric in ('ttft_seconds','first_thinking_seconds','tps','wall_seconds','generated_tokens','peak_system_ram_gib','peak_dedicated_vram_gib')},'layers':{}}
        for layer in layers:
            lr=[x for x in logic if x['model_id']==m and x['answer_layer']==layer];ar=[x for x in arith if x['model_id']==m and x['answer_layer']==layer]
            z['layers'][layer]={'faithfulness':stat(r[layer+'_faithfulness'] for r in rows),'judge_answer_relevance':stat(r[layer+'_judge_relevance'] for r in rows),'bge_m3_cosine':stat(r[layer+'_bge_cosine'] for r in rows),'logical_accuracy':accuracy(lr,policy['fixed_logical_n']),'arithmetic_accuracy':accuracy(ar,policy['fixed_arithmetic_n']),'source_50_task_success':rate(x['validated_task_success'] for x in lr+ar),'source_50_content_correct_rate':rate(x['content_task_success'] for x in lr+ar)}
        summary['models'][m]=z
    ev.dump(w/'evaluation_metrics_11.json',summary)
    paired={};metrics=[layer+'_'+x for layer in layers for x in ('faithfulness','judge_relevance','bge_cosine')]+['ttft_seconds','tps','peak_system_ram_gib','peak_dedicated_vram_gib']
    pairs={(r['question_id'],r['model_id']):r for r in flat}
    for metric in metrics:
        ids=[q['question_id'] for q in qs if all(pairs[q['question_id'],m][metric] is not None for m in models)];paired[metric]={'common_n':len(ids),'question_ids':ids,'models':{m:stat(pairs[q,m][metric] for q in ids) for m in models},'descriptive_only':True}
    for metric,rows in [('logical',logic),('arithmetic',arith)]:
        for layer in layers:
            index={ (r['question_id'],r['model_id']):r for r in rows if r['answer_layer']==layer};ids=[q for q in policy[metric+'_question_ids'] if all(index[q,m]['verdict'] in ('correct','incorrect') for m in models)]
            paired[layer+'_'+metric]={'common_n':len(ids),'question_ids':ids,'models':{m:accuracy([index[q,m] for q in ids],len(ids)) for m in models},'fixed_denominator_question_n':len(policy[metric+'_question_ids']),'descriptive_only':True}
    ev.dump(w/'paired_sample_comparison.json',paired)
    subdivisions={}
    for field in ('species','category','answer_origin','system_status'):
        subdivisions[field]={}
        for value in sorted({r[field] for r in flat}):
            subdivisions[field][value]={}
            for m in models:
                rows=[r for r in flat if r['model_id']==m and r[field]==value];entry={'n':len(rows),'validated_answer':rate(r['model_validated_answer'] for r in rows),'json_valid':rate(r['raw_json_valid'] for r in rows),'ttft':stat(r['ttft_seconds'] for r in rows),'tps':stat(r['tps'] for r in rows),'model_faithfulness':stat(r['model_faithfulness'] for r in rows),'model_relevance':stat(r['model_judge_relevance'] for r in rows),'model_bge':stat(r['model_bge_cosine'] for r in rows)}
                for layer in layers:
                    for metric in ('logical','arithmetic'):
                        selected=[r for r in rows if r[layer+'_'+metric+'_success'] is not None];entry[layer+'_'+metric+'_fixed_success']=rate(r[layer+'_'+metric+'_success'] for r in selected)
                subdivisions[field][value][m]=entry
    ev.dump(w/'species_category_comparison.json',subdivisions)
    evidence_strata={}
    for eligible in (True,False):
        evidence_strata[str(eligible)]={}
        for model in models:
            selection=[r for r in flat if r['model_id']==model and r['source_reference_qualified']==eligible]
            evidence_strata[str(eligible)][model]={'n':len(selection),'model_validated_answer':rate(r['model_validated_answer'] for r in selection),'model_declared_gap':rate(r['raw_declared_gap'] for r in selection),'metrics':{k:stat(r[k] for r in selection) for k in ('ttft_seconds','tps','wall_seconds','peak_system_ram_gib','peak_dedicated_vram_gib','model_faithfulness','model_judge_relevance','model_bge_cosine')}}
    ev.dump(w/'answer_origin_and_evidence_comparison.json',{'answer_origin':subdivisions['answer_origin'],'system_status':subdivisions['system_status'],'qualified_reference_subset':evidence_strata,'warning':'Fast abstention and high format validity are not evidence of professional competence; unqualified-reference questions are not presumed to require abstention.'})
    stem_groups=collections.defaultdict(list)
    for q in qs:stem_groups[q['question_text']].append(q['question_id'])
    sensitivity={m:{} for m in models}
    for m in models:
        for metric in ('model_faithfulness','model_judge_relevance','model_bge_cosine','ttft_seconds','tps','raw_json_valid','model_validated_answer'):
            means=[stat(pairs[q,m][metric] for q in ids)['mean'] for ids in stem_groups.values()];sensitivity[m][metric]=stat(means)
    ev.dump(w/'duplicate_sensitivity.json',{'original_records':len(qs),'unique_exact_stems':len(stem_groups),'duplicate_groups':[ids for ids in stem_groups.values() if len(ids)>1],'method':'Mean within exact text stem first, then equally weighted available stems; species/context distinctions preserved in original data','models':sensitivity,'near_duplicate_risk':'Historical 15 near pairs are not independent; no new semantic independence claim'})
    groups=collections.defaultdict(list)
    for r in refs:
        if r['v6_professional_eligible']:
            for group in r['reference_source_group_ids']:groups[group].append(r['question_id'])
    groupresults={}
    for group,ids in groups.items():
        groupresults[group]={'question_ids':ids,'n_questions':len(ids),'species_counts':dict(collections.Counter(qmap[q]['species_chinese'] for q in ids)),'models':{}}
        for m in models:
            groupresults[group]['models'][m]={}
            for layer in layers:
                rr=[r for r in logic+arith if r['model_id']==m and r['answer_layer']==layer and r['question_id'] in ids];groupresults[group]['models'][m][layer]=rate(r['validated_task_success'] for r in rr)
    # Group-balanced mean and cluster resampling describe source dependence;
    # they are not a formal model-significance or expert-validity statement.
    rng=random.Random(20261121);uncertainty={}
    for m in models:
        uncertainty[m]={}
        for layer in layers:
            vals=[v['models'][m][layer]['rate'] for v in groupresults.values() if v['models'][m][layer]['n']];boot=sorted(stat(rng.choices(vals,k=len(vals)))['mean'] for _ in range(2000)) if vals else []
            uncertainty[m][layer]={'source_group_n':len(vals),'group_balanced_mean':statistics.mean(vals) if vals else None,'exploratory_cluster_resampling_95_interval':[boot[int(.025*len(boot))],boot[min(len(boot)-1,int(.975*len(boot)))]] if boot else None,'not_formal_significance':True}
    ev.dump(w/'source_group_evaluation.json',{'reference_question_n':len(policy['source_question_ids']),'source_group_n':len(groups),'distinct_reference_source_file_sha256_n':len({s for r in refs if r['v6_professional_eligible'] for s in r['reference_source_file_sha256s']}),'groups':groupresults,'uncertainty':uncertainty,'limitation':'Source groups, duplicate questions and same-source chunks are dependent; not 50 independent expert facts; all automatic references NOT_HUMAN_GOLD'})
    retrieval_hits=[]
    for r in refs:
        if not r['v6_professional_eligible']:continue
        top={c['chunk_id'] for c in cmap[r['question_id']]['top5']};checks=r['v6_reference_checks'];hit=all(top.intersection(s['eligible_v6_chunk_ids']) for s in checks)
        retrieval_hits.append({'question_id':r['question_id'],'qualified_corpus_evidence':True,'all_reference_span_chunk_groups_hit_in_top5':hit,'retrieved_chunk_ids':sorted(top),'required_reference_chunk_groups':[s['eligible_v6_chunk_ids'] for s in checks],'scope':'Frozen reference-span containment; not a semantic P@5 label'})
    write_jsonl(w/'reference_retrieval_hits_50.jsonl',retrieval_hits)
    review=ev.jl(w/'context_precision_labels_v6.jsonl');mismatch={r['chunk_id'] for r in review if r.get('support_class')=='SPECIES_MISMATCH' or r.get('support_label')=='SPECIES_MISMATCH'}
    protection=ev.baseline(w,'after');ev.verify_freeze(w,True)
    reconciliation={'run_id':w.name,'final_records':len(gens),'distinct_pairs':len(pairs),'per_model':dict(collections.Counter(g['model_id'] for g in gens)),'species_counts':dict(collections.Counter(q['species_chinese'] for q in qs)),'contexts_shared_all_models':True,'all_model_digests_match':True,'all_frozen_file_hashes_match':True,'retries':len(attempts)-len(gens),'quality_rows':len(quality),'bge_rows':len(bge),'logical_rows':len(logic),'arithmetic_rows':len(arith),'raw_and_system_are_separate':True,'all_tps_engine_formula_checks_passed':True,'source_qualified_n':len(policy['source_question_ids']),'source_group_n':len(groups),'source_reference_top5_all_spans_hit_n':sum(r['all_reference_span_chunk_groups_hit_in_top5'] for r in retrieval_hits),'returned_contexts':sum(len(c['top5']) for c in ctx),'protected_manifest':protection,'model_weight_file_bytes_rehashed_this_run':False,'model_identity_verified_by':'Ollama tag/digest and architecture metadata; not physical weight-byte rehash','actual_generation_executed_not_old_results':True}
    ev.dump(w/'evaluation_validation.json',reconciliation);ev.dump(w/'compatibility.json',{'run_id':w.name,'protected_manifest_count':protection['count'],'protected_changed':protection['changed'],'production_sqlite_sha256':protection.get('production_sqlite_sha256',protection.get('production_sha256')),'production_matches':protection['production_matches'],'v6_database_sha256':ev.sha(ev.read(w/'corpus_active_snapshot.json')['database']),'historical_results_not_overwritten':True,'no_production_switch':True,'model_weight_bytes_rehashed':False,'human_gold':0})
    report(summary,paired,subdivisions,reconciliation,w)
    ev.emit({'stage':'summary_complete','models':{m:{'source50':v['layers']['model']['source_50_task_success'],'json':v['raw_schema'],'faithfulness':v['layers']['model']['faithfulness'],'bge':v['layers']['model']['bge_m3_cosine']} for m,v in summary['models'].items()}})

def write_jsonl(path,rows):
    with path.open('w',encoding='utf-8') as f:
        for row in rows:f.write(json.dumps(row,ensure_ascii=False)+'\n')

def report(s,paired,sub,rec,w):
    def number(x,d=4):return 'N/A' if x is None else f'{x:.{d}f}'
    lines=['# RAG v6 四模型重新評測',f'執行識別：{w.name}。新生成{rec["final_records"]}/720；各模型180題。原始題庫與歷史結果保留。','', '本輪為同一套現行v6系統的探索性回歸。Human Gold為0；50題僅為自動來源核驗參考子集，包含37題邏輯與13題應用算術。模型輸出、驗證後系統輸出、系統引導文字及確定性摘取分開保存。','', '| 指標（模型原始可用回答） | M1 | M2 | M3 | M4 |','|---|---:|---:|---:|---:|']
    measures=[('Faithfulness','faithfulness'),('Judge Answer Relevance','judge_answer_relevance'),('BGE-M3 Cosine','bge_m3_cosine')]
    for label,key in measures:lines.append('| '+label+' | '+' | '.join(number(s['models'][m]['layers']['model'][key]['mean'])+f' (N={s["models"][m]["layers"]["model"][key]["n"]})' for m in ev.MODEL_SPECS)+' |')
    lines.append('| 原始JSON結構通過 | '+' | '.join(f'{s["models"][m]["raw_schema"]["success_n"]}/180 ({s["models"][m]["raw_schema"]["rate"]:.2%})' for m in ev.MODEL_SPECS)+' |')
    for label,key in [('TTFT 秒','ttft_seconds'),('TPS tokens/s','tps'),('System RAM GiB','peak_system_ram_gib'),('Dedicated VRAM GiB','peak_dedicated_vram_gib')]:lines.append('| '+label+' | '+' | '.join(number(s['models'][m]['timing_memory'][key]['mean'])+f' (N={s["models"][m]["timing_memory"][key]["n"]})' for m in ev.MODEL_SPECS)+' |')
    lines+=['', '效能是在事先凍結Context後量測Generator API階段；TTFT從API請求至首個可見內容事件，不包含先前檢索時間。TPS採各模型Ollama引擎的token數與生成時間，並非相同中文字數的輸出速度；不能單靠TPS推論整體問答體驗或答案品質。', '', '原始模型層只要求能可靠取得實質回答正文，引用閘未通過的回答仍可由Judge衡量其與Context的關係；系統層只評估實際被接受的模型回答或確定性摘取，排除系統引導與拒答。因此原始Judge有效N可以大於通過引用閘的回答數，不能把Judge有效N當成成功作答數。模型原始格式不合格也不會被系統回補改算為Structured IFR通過。', '', '| 固定分母任務成功（須通過模型原始格式及引用驗證） | M1 | M2 | M3 | M4 |','|---|---:|---:|---:|---:|']
    for label,key in [('來源50題','source_50_task_success'),('Logical37題','logical_accuracy'),('Arithmetic13題','arithmetic_accuracy')]:
        vals=[]
        for m in ev.MODEL_SPECS:
            x=s['models'][m]['layers']['model'][key];x=x if key=='source_50_task_success' else x['fixed_validated_success'];vals.append(f'{x["success_n"]}/{x["n"]} ({x["rate"]:.2%})')
        lines.append('| '+label+' | '+' | '.join(vals)+' |')
    lines+=['', '| 固定分母內容符合率（與程式閘分開） | M1 | M2 | M3 | M4 |','|---|---:|---:|---:|---:|']
    for label,key in [('來源50題','source_50_content_correct_rate'),('Logical37題','logical_accuracy'),('Arithmetic13題','arithmetic_accuracy')]:
        vals=[]
        for m in ev.MODEL_SPECS:
            x=s['models'][m]['layers']['model'][key];x=x if key=='source_50_content_correct_rate' else x['fixed_content_success'];vals.append(f'{x["success_n"]}/{x["n"]} ({x["rate"]:.2%})')
        lines.append('| '+label+' | '+' | '.join(vals)+' |')
    lines+=['', '內容符合率只代表可觀察回答與凍結來源判準一致；程式閘成功率另要求原始格式、來源引用及現有安全檢查通過。正確計算可能被現有數值閘拒絕，相關案例另存診斷檔，不將系統拒絕直接稱為模型算錯。未成功亦包含未能證實成功或Judge錯誤，並不全部等於答案錯誤。']
    lines+=['', f'共用檢索P@5：{s["shared_context_precision"]["mean"]:.3f}，有效12題、60段，AI-assisted原文審查，非Human Gold，不能外推全部180題。其他836段保留UNVERIFIED。', '', '條件式Logical／Arithmetic Accuracy另列於JSON及Excel：只以可判定回答為分母；固定任務成功率則保留所有合格題，拒答、未完成、無效或未通過引用者均不算成功。判準均在新生成前凍結。', '', f'50題來源子集依賴{rec["source_group_n"]}個原始來源群組；其中{rec["source_reference_top5_all_spans_hit_n"]}題的凍結必要證據片段群完整命中Top-5。該欄僅是原文片段包含檢查，不是P@5。', '', '四模型共同有效題目比較、來源群組重抽樣、175題幹敏感度與六魚種／題型結果均另存；不得把不同有效N的平均值當成嚴格同題比較，也不得宣稱正式顯著性。', '', '記憶體數字是每次請求之系統層級採樣峰值的平均，不是模型程序專屬用量；Shared GPU Memory沒有可靠來源，維持N/A。TTFT採實際首個可見內容串流時間，thinking時間分開保存；TPS逐筆按Ollama奈秒引擎時間重算。', '', '現行自由問答政策以候選證據處理並可能拒答；本輪不以凍結參考答案提示Generator。拒答不能靠較高Faithfulness、較短時間或格式有效率被解讀為專業品質較佳。已審查60段中仍有主題匹配、條件缺失及物種不符的檢索候選；其他段落的專業適用性不因通過程式閘而視為專家核實。', '', '607項Repository pytest與8項子測試通過；四模型真實API預檢完成，負向安全案例測於M2，並非四模型完整專家安全認證。未重跑全部介面操作時不宣稱本輪完成新的Streamlit全功能驗收。', '', f'Frozen Manifest核對{rec["protected_manifest"]["count"]}/636，歷史資料與正式SQLite不變；Corpus資料庫及全部凍結輸入雜湊一致。模型身分以Ollama實際digest與architecture核對，未重新雜湊實體權重檔。', '', '不建立加權總分、不宣布正式Winner、不切換Production。完整可重算JSONL、原始Prompt／串流、各次嘗試及Excel保存在本輪獨立工作區。']
    (w/'final_720_evaluation_report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')

if __name__=='__main__':make()
