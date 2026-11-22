from __future__ import annotations
import collections, hashlib, json, re, statistics, sys
from decimal import Decimal
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import phase_g_pipeline as pg

OUT=pg.OUT
MODELS=['M1','M2','M3','M4']


def load_valid_round(name):
    path=OUT/name
    rows=pg.read_jsonl(path) if path.exists() else []
    result={}
    for r in rows:
        ann=r.get('annotations') or {}
        try: ranks={int(k) for k in ann}
        except Exception: ranks=set()
        if not r.get('error') and ranks=={1,2,3,4,5}:
            result[r['question_id']]=r
    return result


def answer_from_question(q):
    pieces=[]
    text=q.get('candidate_reference_answer')
    if isinstance(text,str) and text.strip(): pieces.append(text.strip())
    options=q.get('options') or {}
    key=str(q.get('candidate_correct_option') or '').strip()
    if key and isinstance(options,dict) and isinstance(options.get(key),str) and options[key].strip(): pieces.append(options[key].strip())
    return pieces


def qualified_evidence(e):
    return bool(e.get('source_verified') is True and e.get('source_verification_status')=='verified'
      and e.get('source_checksum') and e.get('source_url') and e.get('locator')
      and e.get('retrieval_eligibility')=='retrieval' and e.get('benchmark_eligible') is True)


def build_reference_registry(data):
    rows=[]; ref_stats=collections.Counter()
    for qid in sorted(data['qmap']):
        q=data['qmap'][qid]
        ev=pg.full_corpus_evidence(q,data['corpus'],data['doc_map'],top_n=8)
        qualified=[e for e in ev if qualified_evidence(e)]
        answer_phrases=answer_from_question(q)
        direct=[]
        for e in qualified:
            t=pg.compact_text(e.get('text',''))
            for ans in answer_phrases:
                norm=pg.compact_text(ans)
                if len(norm)>=8 and norm in t:
                    direct.append((e,ans))
        if direct:
            # An exact string is only a candidate; source rights/current version still need a separate gate.
            status='PARTIALLY_SUPPORTED'
            reason='Exact answer text occurs in a qualified chunk, but this run has no independently completed semantic/applicability review; conservative abstention.'
            supporting=[e for e,_ in direct]
        elif not qualified:
            status='SOURCE_UNAVAILABLE'
            reason='No source-verified, checksum-pinned, versioned retrieval-eligible Corpus v2 evidence was available in the full-corpus candidate search.'
            supporting=[]
        else:
            status='INSUFFICIENT_EVIDENCE'
            reason='Qualified source candidates exist, but no exact answer support span was automatically established; no answer was inferred from workbook claims or Top-5 alone.'
            supporting=[]
        row={
          'question_id':qid,'species':q.get('species_chinese'),'category':q.get('inferred_category'),
          'question_text':q.get('question_text'),'candidate_reference_answer':q.get('candidate_reference_answer'),
          'candidate_answer_status_in_source_file':q.get('answer_verification_status'),
          'automated_verification_status':status,'verified_reference_answer':None,
          'verification_reason':reason,'support_quote':None,'support_quote_locatable':False,
          'evidence_search_method':'deterministic full Corpus v2 search across all chunks; exact candidate-answer span test; no Generator answer accessed',
          'evidence_candidates':[{k:e.get(k) for k in ['chunk_id','document_id','source_id','source_title','source_url','source_checksum','source_version','publication_date','effective_date','legal_status','source_verified','source_verification_status','retrieval_eligibility','benchmark_eligible','indexable','locator','candidate_match_score','exact_source_url_match']} for e in ev],
          'supporting_chunk_ids':[e.get('chunk_id') for e in supporting],
          'supporting_source_locators':[{'document_id':e.get('document_id'),'chunk_id':e.get('chunk_id'),'page':e.get('page_start'),'source_url':e.get('source_url'),'source_sha256':e.get('source_checksum')} for e in supporting],
          'source_integrity_gate':bool(supporting),'source_version_status':'content_checksum_pinned' if supporting else ('candidate_sources_found_but_answer_span_not_verified' if qualified else 'unverified_or_missing'),
          'legal_current_gate':'not_applicable','logical_applicable':False,'logical_rubric':None,'rubric_status':'not_created_source_answer_gate_not_passed',
          'confidence':'low','scope_or_version_warning':'No Human Gold; no AI semantic entailment pass completed. Candidate answer is not treated as evidence.',
          'annotator_model':'deterministic_source_match_screen','annotator_digest':None,
          'verification_method':'conservative exact-span source screen; no semantic answer correctness claim',
          'human_gold_reviewed':False,'gold_status':pg.GOLD_STATUS,'candidate_options':q.get('options'),
          'fact_ids':q.get('fact_ids'),'candidate_source_urls':q.get('candidate_source_urls'),
          'answer_verified':False,'source_candidates_with_qualified_metadata':len(qualified),
          'source_candidate_count':len(ev),'generation_outputs_included':False,
        }
        rows.append(row); ref_stats[status]+=1
    pg.write_jsonl('reference_answer_verification_180.jsonl',rows)
    pg.write_json('reference_verification_summary.json',{
      'question_count':len(rows),'statuses':dict(ref_stats),'source_verification_precedes_generator_review':True,
      'full_corpus_search_used':True,'human_gold_count':0,'semantic_judge_calls':0,
      'method_limitation':'Strict source matching was used as an automatic screen. It did not establish semantic entailment, source rights, or species applicability, so no item was promoted to SOURCE_VERIFIED_AUTOMATED.'})
    # Logical rubrics are frozen before any generation output is loaded.
    pg.write_jsonl('logical_rubric_registry.jsonl',[])
    empty_hash=pg.sha256_text('')
    pg.write_json('logical_rubric_lock.json',{'rubric_count':0,'rubric_registry_sha256':empty_hash,'locked_before_generator_answers_loaded':True,'human_gold_reviewed':False,'status':'AI_AUTO_ANNOTATED_NOT_HUMAN_GOLD','reason':'No reference answer passed the source-verification gate; no source-grounded logical rubric can be responsibly frozen.'})
    return rows,ref_stats


def build_context_registry(data):
    r1=load_valid_round('annotation_round1_v2_checkpoint.jsonl')
    r2=load_valid_round('annotation_round2_v2_checkpoint.jsonl')
    arb_path=OUT/'annotation_adjudication_v2_checkpoint.jsonl'
    arb={}
    if arb_path.exists():
        for r in pg.read_jsonl(arb_path):
            if r.get('final_label') in {'0','1','U'}: arb[(r.get('question_id'),int(r.get('rank',0)))]=r
    out=[]; qrows=[]; disputes=[]
    qmap,rmap=data['qmap'],data['rmap']; cmap,dmap=data['corpus_by_chunk'],data['doc_map']
    stable_final=0; fully_dual_pass_q=0; completed_rounds=collections.Counter()
    for qid in sorted(qmap):
        q=qmap[qid]; trace=rmap[qid]
        payload=pg.context_prompt_payload(q,trace,cmap,dmap)
        one=r1.get(qid); two=r2.get(qid)
        if one: completed_rounds[1]+=1
        if two: completed_rounds[2]+=1
        ann1=one.get('annotations',{}) if one else {}
        ann2=two.get('annotations',{}) if two else {}
        suff1=one.get('answer_support_sufficiency','uncertain') if one else 'not_run'
        suff2=two.get('answer_support_sufficiency','uncertain') if two else 'not_run'
        if one and two: fully_dual_pass_q+=1
        qlabels=[]
        for ctx in payload['passages']:
            rank=int(ctx.get('rank'))
            a=ann1.get(str(rank)) or ann1.get(rank)
            b=ann2.get(str(rank)) or ann2.get(rank)
            same=bool(a and b and a.get('label')==b.get('label'))
            adjudication=arb.get((qid,rank))
            conflict=bool(a and b and a.get('label')!=b.get('label'))
            if conflict and adjudication:
                label=pg.parse_label(adjudication.get('final_label'))
                reason=str(adjudication.get('reason') or 'third-pass adjudication')
            elif conflict:
                label='U';reason='independent prompt rounds disagree; third arbitration was not completed before Judge runtime block'
            elif same:
                label=pg.parse_label(a.get('label'))
                reason=(str(a.get('reason') or '')+' | second independent pass: '+str(b.get('reason') or ''))[:1400]
            else:
                label='U';reason='two independent prompt passes not both completed; no single-pass label was promoted'
            if label=='1' and not pg.source_metadata_reliable(ctx):
                label='U';reason=(reason+' | source/version/checksum/locator gate not fully verifiable in Corpus v2 metadata')[:1600]
            if conflict:
                disputes.append({'question_id':qid,'chunk_id':ctx.get('chunk_id'),'rank':rank,'round1_label':(a or {}).get('label'),'round2_label':(b or {}).get('label'),'final_label':label,'status':'third_arbitration_completed' if adjudication else 'third_arbitration_not_completed','reason':reason,'annotator_model':pg.JUDGE_TAG,'human_reviewed':False})
            if not same and not conflict:
                disputes.append({'question_id':qid,'chunk_id':ctx.get('chunk_id'),'rank':rank,'round1_label':(a or {}).get('label'),'round2_label':(b or {}).get('label'),'final_label':'U','status':'dual_round_incomplete','reason':reason,'annotator_model':pg.JUDGE_TAG if one or two else None,'human_reviewed':False})
            if same and label in {'0','1'} and not (label=='1' and not pg.source_metadata_reliable(ctx)):
                stable_final+=1
            row={
              'question_id':qid,'chunk_id':ctx.get('chunk_id'),'rank':rank,'relevance_label':label,
              'relevance_reason':reason,'support_type':(a or b or {}).get('support_type','unknown'),
              'species_applicability':(a or b or {}).get('species_applicability','unknown'),
              'source_id':ctx.get('corpus_source_id'),'source_title':ctx.get('source_title'),'source_url':ctx.get('source_url'),
              'source_sha256':ctx.get('source_checksum'),'source_version':ctx.get('source_version'),'source_verified':ctx.get('source_verified'),
              'evidence_locator':ctx.get('page_locator'),'document_id':ctx.get('document_id'),'context_text_sha256':ctx.get('text_sha256'),
              'context_sha256':trace.get('context_sha256'),'corpus_version':trace.get('corpus_version'),
              'retrieval_eligibility':ctx.get('retrieval_eligibility'),
              'annotation_method':'Mistral NeMo two independent prompt rounds when both checkpoints exist; otherwise explicit U blocker; third pass required for conflicts',
              'annotator_model':pg.JUDGE_TAG if (one or two) else None,'annotator_digest':pg.JUDGE_DIGEST if (one or two) else None,
              'round1_label':(a or {}).get('label'),'round2_label':(b or {}).get('label'),
              'adjudication_label':adjudication.get('final_label') if adjudication else None,
              'confidence_or_uncertainty_reason':reason,'needs_review':label=='U','human_reviewed':False,
              'annotation_status':pg.ANNOTATION_STATUS if same and not conflict else ('ANNOTATION_INCOMPLETE_U' if label=='U' else pg.ANNOTATION_STATUS),
              'generation_output_included':False,
            }
            out.append(row); qlabels.append(label)
        ones=qlabels.count('1'); us=qlabels.count('U')
        complete=len(qlabels)==5 and us==0
        p_at=ones/5 if complete else None
        suff=suff1 if one and two and suff1==suff2 else 'uncertain'
        qrows.append({'question_id':qid,'species':q.get('species_chinese'),'category':q.get('inferred_category'),
          'relevance_labels_rank1_to_5':qlabels,'relevant_count':ones,'irrelevant_count':qlabels.count('0'),'uncertain_count':us,
          'p_at_5':p_at,'p_at_5_lower_bound':ones/5,'p_at_5_upper_bound':(ones+us)/5,
          'answer_support_sufficiency':suff,'sufficiency_round1':suff1,'sufficiency_round2':suff2,
          'sufficiency_reason':'from two independent judge passes' if one and two else 'dual-pass assessment not complete; answer support not inferred',
          'context_sha256':trace.get('context_sha256'),'corpus_version':trace.get('corpus_version'),
          'annotation_status':'AI_AUTO_ANNOTATED' if p_at is not None else 'INCOMPLETE_U_OR_REVIEW_REQUIRED',
          'human_gold_reviewed':False})
    pg.write_jsonl('context_auto_annotations_900.jsonl',out)
    pg.write_jsonl('context_precision_by_question.jsonl',qrows)
    pg.write_jsonl('auto_annotation_disagreement_review.jsonl',disputes)
    valid=[r for r in qrows if r['p_at_5'] is not None]
    def agg(field):
        keys=sorted({r.get(field) for r in qrows if r.get(field) is not None})
        return [{'group':k,'n_questions':sum(r.get(field)==k for r in valid),'mean_p_at_5':statistics.mean([r['p_at_5'] for r in valid if r.get(field)==k]) if any(r.get(field)==k for r in valid) else None} for k in keys]
    labels=collections.Counter(r['relevance_label'] for r in out)
    ranks=[]
    for rank in range(1,6):
        rr=[r for r in out if r['rank']==rank]
        ranks.append({'rank':rank,'relevant':sum(x['relevance_label']=='1' for x in rr),'irrelevant':sum(x['relevance_label']=='0' for x in rr),'uncertain':sum(x['relevance_label']=='U' for x in rr)})
    summary={'annotation_status':'AI_AUTO_ANNOTATED_PARTIAL','annotation_complete':len(valid)==180,'context_records':len(out),'question_records':len(qrows),
      'round1_completed_questions':len(r1),'round2_completed_questions':len(r2),'questions_with_two_complete_passes':fully_dual_pass_q,
      'final_stable_labels_before_source_uncertainty_downgrade':stable_final,'third_round_adjudications':len(arb),
      'label_counts':dict(labels),'rank_distribution':ranks,'computable_p_at_5_questions':len(valid),
      'mean_p_at_5':statistics.mean([r['p_at_5'] for r in valid]) if valid else None,
      'by_species':agg('species'),'by_category':agg('category'),'lower_bound_mean':statistics.mean([r['p_at_5_lower_bound'] for r in qrows]) if qrows else None,
      'upper_bound_mean':statistics.mean([r['p_at_5_upper_bound'] for r in qrows]) if qrows else None,
      'mistral_prompt_runtime_block':True,'generation_output_included':False,'human_gold_reviewed':False,'human_gold_count':0,
      'limitation':'Only completed checkpointed judge rounds were used. All incomplete dual-pass labels and unresolved conflicts are U; no P@5 is computed for any row containing U.'}
    pg.write_json('context_precision_summary.json',summary)
    return out,qrows,summary


def number_set(s):
    return {pg.decimal_val(x.replace(',','')) for x in re.findall(r'\d[\d,]*(?:\.\d+)?',s or '') if pg.decimal_val(x.replace(',','')) is not None}


def score_arithmetic_and_logical(refs):
    # Only after reference registry and zero-rubric lock are written do we open Generation outputs.
    data=pg.load_data(include_generation=True)
    answer_map, methods=pg.answer_text_map(data['generation'],data['bge'])
    qmap=data['qmap']
    phase_e_rows=pg.read_jsonl(pg.PHASE_E/'arithmetic_gold_candidate_review.jsonl')
    phase_e_by={r['question_id']:r for r in phase_e_rows}
    calc_q={qid:q for qid,q in qmap.items() if q.get('calculation_record')}
    calc_rows=[]; candidate_review=[]
    for qid,q in qmap.items():
        ex=pg.deterministic_expected(q)
        c=q.get('calculation_record') or {}
        operands=[pg.decimal_val(x) for x in (ex.get('operands') or []) if x is not None]
        reference=pg.decimal_val(c.get('人工核對') or c.get('公式答案'))
        math_kind=ex.get('kind') in {'midpoint','range_width','signed_difference','unit_multiplication','excess_over_limit','ratio_or_interval_count'}
        direct_inputs=bool(ex.get('eligible') and math_kind and operands and all(v in number_set(q.get('question_text','')) for v in operands))
        expected=pg.decimal_val(ex.get('expected'))
        ref_match=bool(direct_inputs and expected is not None and reference is not None and expected==reference and q.get('calculation_record',{}).get('單位'))
        for mid in MODELS:
            ans=answer_map.get((qid,mid))
            if direct_inputs and ref_match:
                scored=pg.parse_numeric_answer(ans,str(expected),ex.get('unit'))
                scope='exploratory arithmetic on operands explicitly stated in question; does not validate source-derived aquaculture premise'
                eligible=True
            elif q.get('calculation_record'):
                scored={'status':'not_evaluable','reason':'formula/operands/units or deterministic candidate result failed conservative self-contained arithmetic gate'}
                scope='not_evaluable_pending_authoritative method/source or complete inputs'
                eligible=False
            else:
                scored={'status':'not_applicable','reason':'no structured calculation record; heuristic category is not treated as calculation proof'}
                scope='not_applicable'
                eligible=False
            calc_rows.append({'question_id':qid,'model_id':mid,'run_id':next((r.get('run_id') for r in data['generation'] if r.get('question_id')==qid and r.get('model_id')==mid),None),
              'species':q.get('species_chinese'),'category':q.get('inferred_category'),'candidate_category_is_heuristic':q.get('category_basis')!='source_verified',
              'arithmetic_task_type':ex.get('kind'),'formula_id':pg.sha256_text(str(ex.get('expression')))[:16] if ex.get('expression') else None,
              'expression':ex.get('expression'),'operands':ex.get('operands'),'expected_numeric_result':str(expected) if expected is not None else None,
              'unit':ex.get('unit'),'generated_answer_text':ans,'answer_extraction_method':methods.get((qid,mid)),
              'arithmetic_status':scored.get('status'),'numeric_parse':scored,'formula_verification_status':'deterministically_recomputed_from_question_stated_operands' if eligible else 'not_verified',
              'formula_source_status':'question-provided values and explicit arithmetic expression; domain premise not validated' if eligible else 'source or protocol unresolved',
              'reference_candidate_match':ref_match if q.get('calculation_record') else None,'candidate_reference_status':'internal candidate matches independent Decimal result' if ref_match else 'not verified',
              'calculation_protocol':ex.get('protocol_status'),'rounding':'Decimal exact input; answer comparison tolerance 1e-6','tolerance':'0.000001',
              'annotator':'Python Decimal deterministic comparison','annotation_status':'AI_AUTO_ANNOTATED_EXPLORATORY' if eligible else 'NOT_EVALUABLE_OR_NOT_APPLICABLE',
              'human_gold_reviewed':False,'human_gold_status':'NOT_HUMAN_GOLD','evaluation_scope':scope,'source_question_id':qid})
        if q.get('calculation_record'):
            ph=phase_e_by.get(qid)
            candidate_review.append({'question_id':qid,'species':q.get('species_chinese'),'question_text':q.get('question_text'),
              'phase_e_candidate':bool(ph),'phase_e_status':ph.get('mechanical_consistency_status') if ph else None,
              'calculation_record':c,'deterministic_recalculation':ex,'manual_or_formula_answer':c.get('人工核對') or c.get('公式答案'),
              'candidate_matches_decimal':ref_match,'self_contained_operands_in_question':direct_inputs,
              'formula_source_verified':False,'arithmetic_accuracy_eligible_exploratory':bool(ref_match),
              'status':'deterministic_recalculation_only; no Human Gold'})
    # Include Phase E heuristic-only rows without a normalized calculation record, plus reconcile IDs.
    for qid,ph in phase_e_by.items():
        if qid not in calc_q:
            candidate_review.append({'question_id':qid,'species':ph.get('species'),'question_text':ph.get('question_text'),
              'phase_e_candidate':True,'phase_e_status':ph.get('mechanical_consistency_status'),'calculation_record':None,
              'deterministic_recalculation':{'eligible':False,'error':'no structured calculation_record in normalized question registry'},
              'manual_or_formula_answer':ph.get('workbook_manual_check_value'),'candidate_matches_decimal':False,
              'self_contained_operands_in_question':False,'formula_source_verified':False,
              'arithmetic_accuracy_eligible_exploratory':False,'status':'heuristic_calculation_candidate_without_structured_record'})
    pg.write_jsonl('arithmetic_reference_verification.jsonl',candidate_review)
    pg.write_jsonl('arithmetic_accuracy_by_model_rows.jsonl',calc_rows)
    # Logical Accuracy remains not evaluable unless an independently source-supported rubric exists.
    logical_rows=[]
    for qid,q in qmap.items():
      for mid in MODELS:
        logical_rows.append({'question_id':qid,'model_id':mid,'run_id':next((r.get('run_id') for r in data['generation'] if r.get('question_id')==qid and r.get('model_id')==mid),None),
          'status':'not_evaluable','reason':'no independently source-verified answer and frozen objective logical rubric for this question',
          'logical_applicable':'not_established','rubric_sha256':pg.sha256_text(''),'answer_available':bool(answer_map.get((qid,mid))),
          'human_gold_reviewed':False,'human_gold_status':'NOT_HUMAN_GOLD','annotation_status':'AI_AUTO_ANNOTATED_NOT_HUMAN_GOLD'})
    pg.write_jsonl('logical_accuracy_by_model.jsonl',logical_rows)
    by_model={}
    for mid in MODELS:
      rr=[r for r in calc_rows if r['model_id']==mid]
      evaluated=[r for r in rr if r['arithmetic_status'] in {'correct','incorrect'}]
      correct=sum(r['arithmetic_status']=='correct' for r in evaluated)
      by_model[mid]={'n_required':len(rr),'n_evaluable':len(evaluated),'n_correct':correct,'n_incorrect':len(evaluated)-correct,
        'n_not_evaluable':sum(r['arithmetic_status']=='not_evaluable' for r in rr),'n_not_applicable':sum(r['arithmetic_status']=='not_applicable' for r in rr),
        'accuracy':correct/len(evaluated) if evaluated else None,'status':'exploratory arithmetic-only; not Human Gold'}
    pg.write_json('arithmetic_accuracy_by_model.json',{'phase_e_candidate_rows':len(phase_e_rows),'normalized_structured_calculation_questions':len(calc_q),
      'question_registry_union_rows':len(candidate_review),'self_contained_arithmetic_questions':sum(r['arithmetic_accuracy_eligible_exploratory'] for r in candidate_review),
      'by_model':by_model,'formula_source_verified_count':0,'human_gold_count':0,
      'notes':['Simple arithmetic is scored only when all operands occur in the question, Decimal recomputation agrees with the candidate check, and a unit is present.','This does not verify the biological, regulatory, or source-derived premise.','Regulatory stop-period/date items are not scored without current law and annex verification.','Heuristic category assignment is not used as proof of calculation applicability.']})
    lsummary={}
    for mid in MODELS:
      rr=[r for r in logical_rows if r['model_id']==mid]
      lsummary[mid]={'required':len(rr),'evaluable':0,'correct':0,'incorrect':0,'not_evaluable':len(rr),'not_applicable':0,'accuracy':None}
    pg.write_json('logical_accuracy_by_model.json',{'rubric_count':0,'rubric_registry_sha256':pg.sha256_text(''),'by_model':lsummary,'human_gold_count':0,
      'status':'not_evaluable; no source-supported objective logical rubric passed reference verification'})
    # Per-question summary for workbook and report.
    calc_by_q={}
    for r in calc_rows:
      calc_by_q.setdefault(r['question_id'],[]).append(r)
    logical_by_q={}
    for r in logical_rows:logical_by_q.setdefault(r['question_id'],[]).append(r)
    per=[]
    refmap={r['question_id']:r for r in refs}
    for qid,q in qmap.items():
      for mid in MODELS:
        ar=next(x for x in calc_by_q[qid] if x['model_id']==mid)
        lo=next(x for x in logical_by_q[qid] if x['model_id']==mid)
        per.append({'question_id':qid,'model_id':mid,'species':q.get('species_chinese'),'category':q.get('inferred_category'),
          'reference_verification_status':refmap[qid]['automated_verification_status'],'arithmetic_status':ar['arithmetic_status'],
          'arithmetic_reason':ar['numeric_parse'].get('reason'),'logical_status':lo['status'],'logical_reason':lo['reason'],
          'human_gold_reviewed':False,'annotation_status':'AI_AUTO_ANNOTATED_EXPLORATORY'})
    pg.write_jsonl('per_question_accuracy.jsonl',per)
    # A compact cross-metric comparison; paired common rows are computed in the workbook stage.
    metric_compare=[]
    for mid in MODELS:
      for metric,rows,field in [('arithmetic_accuracy',calc_rows,'arithmetic_status'),('logical_accuracy',logical_rows,'status')]:
        rr=[r for r in rows if r['model_id']==mid]
        ev=[r for r in rr if r.get(field) in {'correct','incorrect'}]
        cor=sum(r.get(field)=='correct' for r in ev)
        metric_compare.append({'model_id':mid,'metric':metric,'valid_n':len(ev),'correct_n':cor,'incorrect_n':len(ev)-cor,'accuracy':cor/len(ev) if ev else None,'status':'EXPLORATORY' if metric=='arithmetic_accuracy' else 'NOT_EVALUABLE'})
    pg.write_json('model_accuracy_comparison.json',{'metrics':metric_compare,'human_gold_count':0,'formal_winner':None})
    return calc_rows,logical_rows,per


def main():
    data=pg.load_data(False)
    # Source answer verification and logical rubric lock happen before generator outputs are loaded.
    refs,ref_stats=build_reference_registry(data)
    context,questions,cp=build_context_registry(data)
    print('reference_statuses',dict(ref_stats),'context_rows',len(context),'computable_p_at_5',cp['computable_p_at_5_questions'],flush=True)
    calc,logical,per=score_arithmetic_and_logical(refs)
    print('arithmetic_rows',len(calc),'logical_rows',len(logical),'per_question_rows',len(per),flush=True)

if __name__=='__main__': main()
