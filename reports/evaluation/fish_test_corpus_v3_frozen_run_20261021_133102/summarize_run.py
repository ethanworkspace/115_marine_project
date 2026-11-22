from pathlib import Path
import sys,json,collections,statistics,math,random,itertools,datetime
W=Path(__file__).resolve().parent;sys.path.insert(0,str(W))
from frozen_runner import jl,write,append,digest,verify_frozen,MODELS
from score_frozen_run import visible
def summary(values):
 vs=[v for v in values if isinstance(v,(float,int)) and math.isfinite(v)]
 return {'n':len(vs),'mean':statistics.mean(vs) if vs else None,'median':statistics.median(vs) if vs else None,'sd':statistics.stdev(vs) if len(vs)>1 else None,'min':min(vs) if vs else None,'max':max(vs) if vs else None}
def accuracy(rows):
 c=collections.Counter(r['verdict'] for r in rows);n=c['correct']+c['incorrect']
 return {'eligible_response_n':len(rows),'evaluable_n':n,'correct_n':c['correct'],'incorrect_n':c['incorrect'],'not_evaluable_n':c['not_evaluable'],'accuracy':c['correct']/n if n else None,'correct_per_eligible_response':c['correct']/len(rows) if rows else None,'not_evaluable_reasons':dict(collections.Counter(r.get('reason') for r in rows if r['verdict']=='not_evaluable'))}
def main():
 verify_frozen();gens=jl(W/'generator_final_results_720.jsonl');attempts=jl(W/'generator_raw_attempts_720.jsonl')
 assert len(gens)==len({(g['question_id'],g['model_id']) for g in gens})==720
 refs={r['question_id']:r for r in jl(W/'verified_reference_answers_v3.jsonl')};availability={r['question_id']:r for r in jl(W/'corpus_evidence_availability_180.jsonl')}
 ctx={r['question_id']:r for r in jl(W/'frozen_corpus_and_contexts_180.jsonl')}
 jrows=jl(W/'judge_quality_detailed.jsonl');brows=jl(W/'bge_relevance_detailed.jsonl');ar=jl(W/'arithmetic_accuracy_detailed.jsonl');lr=jl(W/'logical_accuracy_detailed.jsonl')
 jm={(r['question_id'],r['model_id'],r['answer_layer']):r for r in jrows};bm={(r['question_id'],r['model_id'],r['answer_layer']):r for r in brows};am={(r['question_id'],r['model_id'],r['answer_layer']):r for r in ar};lm={(r['question_id'],r['model_id'],r['answer_layer']):r for r in lr}
 content={(r['question_id'],r['model_id'],r['answer_layer']):r for r in jl(W/'response_content_audit_1440.jsonl')}
 keys=['faithfulness','judge_answer_relevance','bge_m3_cosine','structured_ifr','ttft_seconds','tps','peak_system_ram_gib','peak_dedicated_vram_gib','logical_accuracy','arithmetic_accuracy']
 facts=[];outcomes=[]
 for i,g in enumerate(gens,1):
  qid,mid=g['question_id'],g['model_id'];ref=refs[qid];h=g['hardware'];raw_answer,raw_reason=visible(g,'model');system_answer,system_reason=visible(g,'system')
  rawp=g.get('parsed_model_response') or {};abstain=rawp.get('abstained')
  outcomes.append({'run_id':g['run_id'],'question_id':qid,'model_id':mid,'raw_model_response':g['raw_model_response'],'raw_model_answer':raw_answer,'raw_model_abstained':abstain,'raw_model_structure_valid':g['raw_model_structure_valid'],'raw_citation_validation':g['raw_citation_validation'],'final_system_answer':g['final_response'],'answer_origin':g['answer_origin'],'source_group_ids':g['source_group_ids'],'model_direct_answer_validated':g['answer_origin']=='MODEL_GENERATED','system_extraction_never_model_direct_success':True,'evidence_decision':g['evidence_decision'],'source_availability':availability[qid]['gap_classification'],'reference_status':ref.get('evidence_verification_level',ref.get('eligibility')),'raw_result_line':i,'source_file':'generator_final_results_720.jsonl'})
  for layer in ['model','system']:
   k=(qid,mid,layer);jr=jm[k];br=bm[k];a=am.get(k);l=lm.get(k)
   row={'run_id':g['run_id'],'question_id':qid,'model_id':mid,'answer_layer':layer,'species':g['species'],'category':g['category'],'answer_origin':g['answer_origin'],'context_count':g['context_count'],'context_digest':g['context_digest'],'source_group_ids':g['source_group_ids'],'knowledge_group_id':ref.get('knowledge_group_id'),'reference_qualified':bool(ref.get('logical_rubric') or ref.get('expected_calculation')),'reference_level':'AUTO_SOURCE_VERIFIED; NOT_HUMAN_GOLD' if ref.get('logical_rubric') or ref.get('expected_calculation') else ref.get('eligibility'),'faithfulness':jr.get('faithfulness'),'judge_answer_relevance':jr.get('judge_answer_relevance'),'bge_m3_cosine':br.get('cosine'),'structured_ifr':int(g['raw_model_structure_valid']) if g['api_completed'] else None,'ttft_seconds':g['ttft_visible_content_seconds'],'tps':g['tps'],'peak_system_ram_gib':h['peak_system_ram_bytes']/1024**3 if h['peak_system_ram_bytes'] is not None else None,'peak_dedicated_vram_gib':h['peak_dedicated_vram_bytes']/1024**3 if h['peak_dedicated_vram_bytes'] is not None else None,'logical_accuracy':1 if l and l['verdict']=='correct' else 0 if l and l['verdict']=='incorrect' else None,'arithmetic_accuracy':1 if a and a['verdict']=='correct' else 0 if a and a['verdict']=='incorrect' else None,'logical_verdict':l['verdict'] if l else 'NOT_APPLICABLE','arithmetic_verdict':a['verdict'] if a else 'NOT_APPLICABLE','logical_reason':l.get('reason') if l else 'NO_FROZEN_SOURCE_RUBRIC','arithmetic_reason':a.get('reason') if a else 'NO_VERIFIED_FORMULA_PROTOCOL','quality_missing_reason':jr.get('reason') or (jr.get('evaluation') or {}).get('status'),'bge_missing_reason':br.get('reason'),'raw_model_abstained':abstain,'raw_answer_visible':raw_answer is not None,'system_answer_visible':system_answer is not None,'raw_validation_error':g.get('validation_error'),'canonical_result_line':i,'source_jsonl':str(W/'generator_final_results_720.jsonl')}
   facts.append(row)
 for o in outcomes:
  o['raw_content_status']=content[(o['question_id'],o['model_id'],'model')]['content_status'];o['system_content_status']=content[(o['question_id'],o['model_id'],'system')]['content_status']
  o['model_direct_substantive_answer']=o['model_direct_answer_validated'] and o['raw_content_status']=='SUBSTANTIVE_OR_PARTIAL_ATTEMPT'
 for p in facts:p['response_content_status']=content[(p['question_id'],p['model_id'],p['answer_layer'])]['content_status']
 for name,rows in [('model_vs_system_outcomes.jsonl',outcomes),('per_question_metrics.jsonl',facts)]:
  (W/name).write_text(''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in rows),encoding='utf-8')
 allstats={};paired={}
 for layer in ['model','system']:
  allstats[layer]={};paired[layer]={}
  for mid in MODELS:
   rows=[r for r in facts if r['model_id']==mid and r['answer_layer']==layer]
   allstats[layer][mid]={k:summary([r[k] for r in rows]) for k in keys}
   allstats[layer][mid]['logical_counts']=accuracy([x for x in lr if x['model_id']==mid and x['answer_layer']==layer])
   allstats[layer][mid]['arithmetic_counts']=accuracy([x for x in ar if x['model_id']==mid and x['answer_layer']==layer])
  for metric in keys:
   eligible=[{r['question_id'] for r in facts if r['model_id']==mid and r['answer_layer']==layer and r[metric] is not None} for mid in MODELS]
   common=set.intersection(*eligible)
   paired[layer][metric]={'common_question_n':len(common),'question_ids':sorted(common),'models':{mid:summary([r[metric] for r in facts if r['model_id']==mid and r['answer_layer']==layer and r['question_id'] in common]) for mid in MODELS}}
 p=json.loads((W/'context_precision_label_status.json').read_text(encoding='utf-8'));p5=p['questions']
 (W/'context_precision_detailed.jsonl').write_text(''.join(json.dumps({**r,'run_id':W.name,'metric_name':'AI_Assisted_Exploratory_Context_Precision_at_5','method':'Carried frozen source-span diagnostic labels; not new AI relabeling','human_gold':False},ensure_ascii=False)+'\n' for r in p5),encoding='utf-8')
 psummary={'mean':summary([q['p_at_5'] for q in p5]),'species':{s:summary([q['p_at_5'] for q in p5 if q['species']==s]) for s in sorted({q['species'] for q in p5})},'scope':'12 purposively reviewed questions, 60 chunks; not representative of all 180','unverified_chunks_preserved':303,'shared_across_four_models':True,'full_top5_questions':sum(len(r['top5'])==5 for r in ctx.values())}
 metrics={'run_id':W.name,'canonical_result_count':len(gens),'raw_attempt_count':len(attempts),'api_completed':sum(g['api_completed'] for g in gens),'metric_names':keys+['shared_context_precision_at_5'],'all_available_samples':allstats,'four_model_paired_samples':paired,'context_precision_at_5':psummary,'professional_quality_status':'SOURCE_VERIFIED_CONDITIONAL_EXPLORATORY; NOT_HUMAN_GOLD','human_gold_n':0,'qualified_reference_question_n':50,'logical_qualified_question_n':37,'arithmetic_qualified_question_n':13,'measurement_scope':'system_level_sampled_peak; per-call peaks summarized, not model process memory','shared_gpu_memory':None,'memory_pressure_score':None,'formal_weighted_total':None,'winner':None,'refusals_not_scored_as_artificial_accuracy_zeros':True,'refusal_and_answer_rate_must_be_read_with_answer_only_accuracy':True}
 metrics['post_run_parser_erratum']={'file':'response_content_parser_erratum.json','scope':'BGE substantive-answer view and observable logical/arithmetic result missingness only; original scores archived','reference_rubrics_or_generator_changed':False,'judge_response_quality_scores_unchanged':True,'original_score_suffix':'_frozen_parser_v1.jsonl'}
 write('evaluation_metrics_11.json',metrics)
 abst={}
 for mid in MODELS:
  gs=[g for g in gens if g['model_id']==mid];os=[o for o in outcomes if o['model_id']==mid];groups={}
  for scope,choose in [('NO_CONTEXT',lambda g:g['context_count']==0),('PARTIAL_CONTEXT',lambda g:0<g['context_count']<5),('FULL_TOP5',lambda g:g['context_count']==5)]:
   sel=[g for g in gs if choose(g)];groups[scope]={'n':len(sel),'raw_model_declared_abstention':sum((g.get('parsed_model_response') or {}).get('abstained') is True for g in sel),'raw_nonabstained':sum((g.get('parsed_model_response') or {}).get('abstained') is False for g in sel),'schema_invalid':sum(not g['raw_model_structure_valid'] for g in sel),'system_abstained':sum(g['final_response']['abstained'] for g in sel)}
  qualified=[g for g in gs if refs[g['question_id']].get('logical_rubric') or refs[g['question_id']].get('expected_calculation')]
  policy=[g for g in gs if refs[g['question_id']].get('eligibility')=='EXPECTED_ABSTENTION_VERIFIED'];pn=len(policy)
  abst[mid]={'n':len(gs),'api_completed':sum(g['api_completed'] for g in gs),'api_failed':sum(not g['api_completed'] for g in gs),'raw_model_declared_abstentions':sum((g.get('parsed_model_response') or {}).get('abstained') is True for g in gs),'answer_origins':dict(collections.Counter(g['answer_origin'] for g in gs)),'context_groups':groups,'safety_gate_reasons':dict(collections.Counter(g['evidence_decision']['reason'] for g in gs if g.get('system_safety_gate_triggered'))),'qualified50_model_direct_answer_n':sum(g['answer_origin']=='MODEL_GENERATED' for g in qualified),'qualified50_system_answer_n':sum(not g['final_response']['abstained'] for g in qualified),'qualified50_unnecessary_abstention_candidates':[g['question_id'] for g in qualified if g['evidence_decision']['state']=='EVIDENCE_SUFFICIENT' and (g.get('parsed_model_response') or {}).get('abstained') is True],'raw_answers_with_insufficient_evidence':[g['question_id'] for g in gs if g['evidence_decision']['state']!='EVIDENCE_SUFFICIENT' and (g.get('parsed_model_response') or {}).get('abstained') is False],'raw_citation_failed':sum(g['raw_citation_validation']['status']=='FAIL' for g in gs),'final_citation_answer_n':sum(not g['final_response']['abstained'] for g in gs),'final_citation_pass_n':sum(not g['final_response']['abstained'] and g['final_citation_validation']['status']=='PASS' for g in gs),'wrong_species_citation_accepted':sum(not g['final_response']['abstained'] and g['evidence_decision']['state']=='SOURCE_INAPPLICABLE' for g in gs),'policy_abstention_correctness':{'eligible_n':pn,'system_correct_n':sum(g['final_response']['abstained'] for g in policy),'raw_model_declared_abstention_n':sum((g.get('parsed_model_response') or {}).get('abstained') is True for g in policy),'scope':'6 pre-frozen system safety policy cases, not independent clinical/no-answer truth for remaining130'},'remaining130_not_assumed_expected_abstention':True}
 for mid in MODELS:
  abst[mid]['raw_nonanswer_echo_or_incomplete_n']=sum(o['model_id']==mid and o['raw_content_status'] in {'QUESTION_ECHO_NO_ANSWER','INCOMPLETE_ANTECEDENT_NO_ANSWER'} for o in outcomes)
  abst[mid]['system_nonanswer_echo_or_incomplete_n']=sum(o['model_id']==mid and o['system_content_status'] in {'QUESTION_ECHO_NO_ANSWER','INCOMPLETE_ANTECEDENT_NO_ANSWER'} for o in outcomes)
  abst[mid]['qualified50_substantive_direct_answer_n']=sum(o['model_id']==mid and o['model_direct_substantive_answer'] and (refs[o['question_id']].get('logical_rubric') or refs[o['question_id']].get('expected_calculation')) is not None for o in outcomes)
 write('abstention_analysis.json',abst)
 breakdown={}
 for dim in ['species','category','answer_origin','reference_level']:
  breakdown[dim]={}
  for value in sorted({r[dim] or 'UNSPECIFIED' for r in facts}):
   breakdown[dim][value]={layer:{mid:{k:summary([r[k] for r in facts if (r[dim] or 'UNSPECIFIED')==value and r['answer_layer']==layer and r['model_id']==mid]) for k in keys} for mid in MODELS} for layer in ['model','system']}
 write('species_category_comparison.json',breakdown)
 # Exact stem dedup sensitivity retains first original question order; cross-species rows remain in full analysis.
 seen=set();selected=[]
 for r in ctx.values():
  if r['question'] not in seen:seen.add(r['question']);selected.append(r['question_id'])
 dedup={layer:{mid:{k:summary([r[k] for r in facts if r['model_id']==mid and r['answer_layer']==layer and r['question_id'] in selected]) for k in keys} for mid in MODELS} for layer in ['model','system']}
 write('duplicate_sensitivity.json',{'exact_stem_count':len(selected),'retained_question_ids':selected,'method':'First source question order per exact stem; sensitivity only; full180 preserves fish/context distinctions','descriptive_metrics':dedup,'near_duplicate_pairs':15,'near_pairs_are_dependency_risks_not_15_independent_errors':True})
 # Source group membership and connected components preserve shared-origin dependencies.
 full={qid for qid,r in refs.items() if r.get('logical_rubric') or r.get('expected_calculation')};groupqs=collections.defaultdict(set)
 for qid in full:
  for group in availability[qid]['original_record_group_keys']:groupqs[group].add(qid)
 remaining=set(full);components=[]
 while remaining:
  comp={min(remaining)};change=True
  while change:
   old=len(comp)
   for qset in groupqs.values():
    if comp&qset:comp|=qset
   change=len(comp)>old
  remaining-=comp;components.append(sorted(comp))
 groups={g:{'question_n':len(qs),'question_ids':sorted(qs),'metrics':{layer:{mid:{k:summary([r[k] for r in facts if r['question_id'] in qs and r['answer_layer']==layer and r['model_id']==mid]) for k in ['faithfulness','judge_answer_relevance','bge_m3_cosine','logical_accuracy','arithmetic_accuracy']} for mid in MODELS} for layer in ['model','system']}} for g,qs in sorted(groupqs.items())}
 rng=random.Random(21021);boot={}
 for layer in ['model','system']:
  boot[layer]={}
  for metric in ['logical_accuracy','arithmetic_accuracy']:
   common=set(paired[layer][metric]['question_ids']);eligiblecomp=[set(c)&common for c in components if set(c)&common]
   boot[layer][metric]={}
   for mid in MODELS:
    lookup={r['question_id']:r[metric] for r in facts if r['model_id']==mid and r['answer_layer']==layer and r['question_id'] in common}
    means=[statistics.mean(lookup[q] for q in c) for c in eligiblecomp]
    samples=sorted(statistics.mean(rng.choice(means) for _ in means) for _ in range(2000)) if means else []
    boot[layer][metric][mid]={'paired_question_n':len(common),'source_dependency_component_n':len(means),'equal_component_mean':statistics.mean(means) if means else None,'exploratory_component_bootstrap_95pct':[samples[49],samples[1949]] if len(means)>1 else None,'not_formal_significance':True}
 source_files={s['source_sha256'] for qid in full for s in refs[qid]['evidence_spans']}
 write('source_group_evaluation.json',{'original_group_n':len(groups),'original_source_file_sha256_n':len(source_files),'original_source_file_sha256':sorted(source_files),'qualified_question_n':len(full),'groups':groups,'group_memberships_can_overlap':True,'connected_dependency_components':components,'independent_components_n':len(components),'paired_component_bootstrap':boot,'bootstrap_replicates':2000,'seed':21021,'limits':'10 original record/PDF-page groups also share original source files; between-group dependence may remain. AI references/scoring are not expert Gold; this is not formal significance or a claim of fully independent groups.'})
 write('paired_sample_comparison.json',paired)
 print(json.dumps({'generations':len(gens),'attempts':len(attempts),'metrics_written':True,'model_summary':allstats['model']},ensure_ascii=False),flush=True)
if __name__=='__main__':sys.stdout.reconfigure(encoding='utf-8');main()
