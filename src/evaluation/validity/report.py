"""Separate absent independent judgments, AI diagnostics, human evidence and bias."""
from __future__ import annotations

import json
import statistics
from collections import Counter
from itertools import combinations

from .core import (MODELS, CONDITIONS, BIAS, VERDICTS, REFERENCE_INDEPENDENT, REFERENCE_DEPENDENT,
    shortlist_status, agreement, verify_claim, digest)
from .runner import OUT, PRIOR, ROOT, check_inputs, load_inputs, write_json, write_jsonl
from ..generation.frozen import read_jsonl
from ..generation_models.core import scalar, pareto


def human_progress(records, events):
    claims={c['claim_id']:(r,c) for r in records for c in r['claims']}
    valid=[]; invalid=[]; no_assertion=[]
    by_answer={r['answer_id']:r for r in records}
    for e in events:
        if e.get('review_scope')=='answer_no_assertion':
            record=by_answer.get(e.get('answer_id'))
            if (record and not record['claims'] and e.get('review_source')=='human'
                    and e.get('human_verified') is True and str(e.get('reviewer') or '').strip()
                    and str(e.get('notes') or '').strip() and e.get('reviewed_at')
                    and e.get('answer_sha256')==record['answer_sha256']):
                no_assertion.append(e)
            else:invalid.append(e)
            continue
        found=claims.get(e.get('claim_id'))
        if (not found or e.get('review_source')!='human' or e.get('human_verified') is not True
                or not str(e.get('reviewer') or '').strip() or not e.get('reviewed_at')
                or e.get('verdict') not in set(VERDICTS)-{'citation_missing'}
                or e.get('answer_sha256')!=found[0]['answer_sha256']
                or e.get('claim_text_sha256')!=found[1]['claim_text_sha256']):
            invalid.append(e);continue
        valid.append(e)
    latest={e['claim_id']:e for e in valid}
    no_claim_ids={e['answer_id'] for e in no_assertion}
    complete=[r for r in records if r['answer_id'] in no_claim_ids or
              r['claims'] and all(c['claim_id'] in latest for c in r['claims'])]
    return {'target_outputs':len(records),'total_claims':len(claims),
        'human_reviewed_claims':len(latest),'human_completed_outputs':len(complete),
        'human_review_events':len(valid)+len(no_assertion),'invalid_review_events':len(invalid),
        'completed_answer_ids':[r['answer_id'] for r in complete],
        'human_no_assertion_reviews':len(no_claim_ids),
        'outputs_without_extracted_assertions':sum(not r['claims'] for r in records),
        'claim_verdict_counts':dict(Counter(e['verdict'] for e in latest.values())),
        'workbench':'tools/claim_citation_audit_app.py','human_ai_results_separate':True}


def citation_summary(sample, judgments):
    total=sum(r['citation_count'] for r in sample)
    valid=sum(r['strict_citation_count'] for r in sample)
    pairs=[p for j in judgments for p in j['citation_pairs']]
    decidable=[p for p in pairs if p['effective_verdict'] in ('entailed','partially_entailed','not_entailed')]
    n=len(judgments);counts=Counter(j['claim_verdict'] for j in judgments)
    known=sum(counts[k] for k in ('entailed','partially_entailed','not_entailed'))
    def rate(value,den):return value/den if den else None
    return {'outputs':len(sample),'claims':n,'citation_pairs':len(pairs),
        'provenance_citations':total,'provenance_valid_citations':valid,
        'valid_citation_provenance_rate':rate(valid,total),
        'entailed_citation_rate':rate(sum(p['effective_verdict']=='entailed' for p in decidable),len(decidable)),
        'entailed_citation_rate_denominator':'decidable claim x declared-citation pairs',
        'citation_pair_cannot_determine':sum(p['effective_verdict']=='cannot_determine' for p in pairs),
        'fully_supported_claim_rate':rate(counts['entailed'],n),
        'partially_supported_claim_rate':rate(counts['partially_entailed'],n),
        'unsupported_cited_claim_rate':rate(counts['not_entailed'],known),
        'unsupported_cited_claim_rate_denominator':'decidable cited claims; no claim of outside-world falsity',
        'uncited_claim_rate':rate(counts['citation_missing'],n),
        'claim_citation_coverage':rate(sum(bool(j['audit_citation_set']) for j in judgments),n),
        'claim_citation_coverage_definition':'declared citation association; not proof of support',
        'valid_provenance_claim_coverage':rate(sum(any(p['provenance_valid'] for p in j['citation_pairs']) for j in judgments),n),
        'claim_level_binding_rate':rate(sum(j['citation_binding']=='claim_inline' for j in judgments),n),
        'claim_verdict_counts':dict(counts),
        'evaluation_failure_count':sum(j['judge_result']['evaluation_status']=='failed' for j in judgments),
        'invalid_supporting_quote_count':sum(p.get('supporting_quote_valid') is False and
             p['verdict'] in ('entailed','partially_entailed') for p in pairs),
        'human_verified':False,'independent_judge':False,'judge_based':True,
        'limitations':['Verbatim claim candidates require manual atomicity review.',
            'Answer-level citation set is provisional association, not proven claim-level binding.',
            'A claim is fully supported only when at least one cited chunk supports it entirely; jointly sufficient partial chunks require human review.',
            'Audit quota sample is not a prevalence estimate for all 169 questions.']}


def families(rows, family):
    metrics=('faithfulness','answer_relevancy') if family=='reference_independent' else REFERENCE_DEPENDENT
    prior_overall=json.loads((PRIOR/'overall_comparison.json').read_text(encoding='utf-8'))
    result={'family':family,'metric_names':REFERENCE_INDEPENDENT if family=='reference_independent' else REFERENCE_DEPENDENT,
            'reference_bias':dict(BIAS),'models':{}}
    for name in MODELS:
        result['models'][name]={}
        for cond in CONDITIONS:
            selected=[r for r in rows if r['generator']==name and r['condition']==cond]
            values={}
            for metric in metrics:
                vals=[scalar(r,metric) for r in selected]
                vals=[v for v in vals if v is not None]
                values[metric]={'mean':statistics.fmean(vals) if vals else None,'n_valid':len(vals),
                    'n_total':len(selected),'judge_conflict':name=='qwen2.5-coder:7b' and metric!='silver_token_f1',
                    **(BIAS if family=='reference_dependent' else {})}
            result['models'][name][cond]={'metrics':values,
                'answered':sum(r['status']=='answered' for r in selected),
                'abstained':sum(r['status']=='insufficient_evidence' for r in selected),
                'schema_validity':statistics.fmean(r['deterministic_generation']['schema_valid'] for r in selected),
                'citation_recall_macro_all_questions':statistics.fmean(scalar(r,'citation_recall') for r in selected),
                'citation_provenance_validity':sum(r['deterministic_generation']['strict_citation_count'] for r in selected)/
                    sum(r['deterministic_generation']['citation_count'] for r in selected)}
            result['models'][name][cond]['calculation_numeric_separate']=prior_overall[name][cond]['deterministic_metrics']['calculation_output_admissibility']
    result['no_composite_score']=True
    return result


def sensitivity(rows):
    by_model={m:{r['question_id']:r for r in rows if r['generator']==m and r['condition']=='e4_top5'} for m in MODELS}
    primary=[m for m in MODELS if m!='qwen2.5-coder:7b']
    metricsets={'reference_independent':('faithfulness','answer_relevancy'),
                'reference_dependent':REFERENCE_DEPENDENT}
    output={'reference_bias':BIAS,'condition':'e4_top5','directions':{},'pareto':{},
            'judge_conflict_excluded':['qwen2.5-coder:7b'],'no_composite_score':True}
    for family,metrics in metricsets.items():
        shared=sorted(q for q in by_model[primary[0]] if all(
            all(scalar(by_model[m][q],k) is not None for k in metrics) for m in primary))
        points=[]
        for m in primary:
            point={'generator':m,'primary_eligible':True}
            for k in metrics:
                point[k]=statistics.fmean(scalar(by_model[m][q],k) for q in shared) if shared else None
            points.append(point)
        output['pareto'][family]={**pareto(points,{k:'max' for k in metrics}),
            'common_question_count':len(shared),'question_ids':shared,'points':points,
            'cohort_rule':'All three non-conflicted models answered with valid metrics in this family'}
        output['directions'][family]=[]
        for a,b in combinations(primary,2):
            rec={'left':a,'right':b,'direction':'right-left','metrics':{}}
            for k in metrics:
                common=[q for q in sorted(by_model[a]) if scalar(by_model[a][q],k) is not None and scalar(by_model[b][q],k) is not None]
                delta=statistics.fmean(scalar(by_model[b][q],k)-scalar(by_model[a][q],k) for q in common) if common else None
                rec['metrics'][k]={'n_paired':len(common),'mean_difference':delta,
                    'ci_source':'Phase 17 paired_bootstrap.json; not rejudged',
                    'point_direction_only':True}
            output['directions'][family].append(rec)
    output['interpretation']='Different metric-family directions show sensitivity, not a causal estimate of Gemma reference bias. Qwen quality ordering remains unresolved.'
    output['calculation']='Separate deterministic numeric match, n=3; not part of either Pareto frontier.'
    return output


def render():
    manifest=check_inputs();rows=load_inputs()
    sample=read_jsonl(OUT/'claim_citation_sample.jsonl');blind=read_jsonl(OUT/'blind_audit_records_v2.jsonl')
    # Preserve original sample and extraction inventory; only formatting artifacts
    # are excluded by the predeclared v2 structural rule, never by judge verdict.
    sample=[dict(r,claim_count=len(next(b for b in blind if b['answer_id']==r['answer_id'])['claims'])) for r in sample]
    audited=read_jsonl(OUT/'claim_citation_ai_audit.jsonl') if (OUT/'claim_citation_ai_audit.jsonl').exists() else []
    expected={c['claim_id'] for r in blind for c in r['claims']}
    if {r['claim_id'] for r in audited}!=expected or len(audited)!=len(expected):
        raise ValueError('Every sampled claim must have an explicit audit record, including failures')
    private={r['answer_id']:r for r in sample}
    for r in blind:
        if not all(verify_claim(c,r['answer']) for c in r['claims']):
            raise ValueError('Answer/claim snapshot altered')
    events=read_jsonl(OUT/'human_reviews.jsonl') if (OUT/'human_reviews.jsonl').exists() else []
    hp=human_progress(blind,events);write_json(OUT/'human_audit_progress.json',hp)
    write_json(OUT/'independent_judge_agreement.json',{
        'status':'not_executed_no_independent_judge','sample_outputs':96,'independent_judge_ready':False,
        'metrics':{k:agreement([]) for k in ('faithfulness','answer_relevancy','silver_reference_correctness')},
        'qwen_independent_results':None,'n_evaluated':0})
    write_json(OUT/'judge_ranking_sensitivity.json',{
        'status':'not_identifiable_without_independent_judge','generator_ordering_changed':None,
        'qwen_vs_others_primary_quality_ranking':'unresolved',
        'phase17_primary_repeatability_source':'reports/evaluation/generation_models/phase17/judge_repeatability.json',
        'existing_primary_repeatability':json.loads((PRIOR/'judge_repeatability.json').read_text(encoding='utf-8')),
        'limitation':'Fresh-repeat agreement does not establish inter-judge validity; original versus repeat scores differed.'})
    by_model={m:citation_summary([s for s in sample if s['generator']==m],
        [j for j in audited if private[j['answer_id']]['generator']==m]) for m in MODELS}
    primary=citation_summary([s for s in sample if s['generator']!='qwen2.5-coder:7b'],
                             [j for j in audited if not j['judge_conflict']])
    cs={'all_ai_diagnostic':citation_summary(sample,audited),'non_self_judge_diagnostic':primary,
        'by_generator':by_model,'qwen_entailment_status':'self_judge_exploratory; no primary cross-model conclusion',
        'human_confirmed_entailment':None if not hp['human_reviewed_claims'] else hp,
        'audit_complete':True}
    write_json(OUT/'citation_entailment_summary.json',cs)
    raw=read_jsonl(OUT/'raw_audit_judge_outputs.jsonl')
    by_claim={j['claim_id']:j for j in audited}
    for a in raw:
        if a['claim_id'] not in by_claim or digest(a['raw_output'])!=a['raw_output_sha256']:
            raise ValueError('Audit attempt reference/raw checksum invalid')
        request=a['request'];payload=json.loads(request['messages'][1]['content'])
        if set(payload)!={'question','claim','verbatim_heading_context','cited_contexts','output_schema'}:
            raise ValueError('Unexpected or identity-bearing judge input field')
        if request['options']!=manifest['audit_judge']['options'] or request['model']!=manifest['audit_judge']['model']:
            raise ValueError('Blind judge configuration changed')
    corpus={r['chunk_id']:r for r in read_jsonl(ROOT/'data/evaluation/corpus_v2.jsonl')}
    context_count=0
    for b in blind:
        for c in b['contexts']:
            source=corpus[c['chunk_id']]
            if (source['document_id']!=c['document_id'] or source['text']!=c['text']
                    or not source['page_start']<=c['page']<=source['page_end']
                    or source['retrieval_role']!='retrieval'
                    or source['duplicate_status'] in ('exact_duplicate','duplicate_source')):
                raise ValueError('Blind context disagrees with frozen retrieval corpus')
            context_count+=1
    write_json(OUT/'audit_validation.json',{'main_audit_claims':len(audited),
        'main_raw_attempts':len(raw),'main_raw_sha256_valid':True,'judge_payload_allowlist_valid':True,
        'generator_identity_not_provided':True,'raw_schema_valid':all(a['schema_status'] for a in raw),
        'frozen_corpus_contexts_validated':context_count,'claim_source_spans_valid':True,
        'sampling_replaced_outputs':False,'independent_judge':False,'human_verified':False,
        'initial_diagnostic_in_flight_capture_gap_separately_preserved':True})
    protocol=json.loads((OUT/'audit_execution_protocol_v2.json').read_text(encoding='utf-8'))
    write_json(OUT/'audit_judge_manifest_v2.json',{**manifest['audit_judge'],
        'audit_protocol':'phase18_blind_audit_contract_v2','prompt_sha256':protocol['prompt_sha256'],
        'quote_max_length':240,'reason_max_length':160,
        'freeze_source':'audit_execution_protocol_v2.json; frozen before main v2 audit',
        'initial_diagnostics_retained':True})
    ind=families(rows,'reference_independent');dep=families(rows,'reference_dependent')
    ind['citation_entailment_scope']='See citation_entailment_summary.json: quota sample AI diagnostic, not full-benchmark or independent human metric'
    write_json(OUT/'reference_independent_comparison.json',ind);write_json(OUT/'reference_dependent_comparison.json',dep)
    # Aliases requested in Part C, distinct from any earlier immutable report.
    write_json(OUT/'comparison_reference_independent.json',ind);write_json(OUT/'comparison_reference_dependent.json',dep)
    bias=sensitivity(rows);write_json(OUT/'reference_bias_analysis.json',bias)
    shortlist={'no_single_winner':True,'no_composite_score':True,
        'criteria':{**manifest['shortlist_gates'],'strong_requires_human_completed_outputs':48},
        'independent_judge_ready':False,'human_completed_outputs':hp['human_completed_outputs'],'models':{}}
    for m in MODELS:
        d=ind['models'][m]['e4_top5'];faith=d['metrics']['faithfulness']['mean']
        status=shortlist_status(m,d['schema_validity'],judge_conflict=m=='qwen2.5-coder:7b',
                               faithfulness=faith,human_claim_reviews=hp['human_reviewed_claims'],
                               human_completed_outputs=hp['human_completed_outputs'])
        reasons=[]
        if m=='qwen2.5-coder:7b':reasons.append('Primary judge is identical artifact; independent judge unavailable')
        if d['schema_validity']<.99:reasons.append('Frozen common protocol final schema rate is below 99%')
        reasons.extend(['No independent evaluator','Human claim-citation verification incomplete',
                        'Reference-dependent scores have Gemma reference-alignment bias possibility'])
        shortlist['models'][m]={'status':status,'reasons':reasons,'schema_validity':d['schema_validity'],
            'faithfulness_primary_judge':faith,'citation_audit':by_model[m],
            'edge_test_recommendation':'primary hardware feasibility candidate' if m=='gemma2:9b' else
                ('performance-only exploratory candidate; quality unresolved' if m=='qwen2.5-coder:7b' else
                 'optional diagnostic; lower priority under the frozen execution protocol'),
            'final_edge_model_selected':False}
    write_json(OUT/'model_shortlist.json',shortlist)
    generator_manifest=json.loads((PRIOR/'generator_comparison_manifest.json').read_text(encoding='utf-8'))
    metadata=json.loads((PRIOR/'model_context_metadata.json').read_text(encoding='utf-8'))
    write_json(OUT/'edge_model_artifacts.json',{'source':'Frozen Phase 17 manifests; no model acquisition',
        'generator_manifest_sha256':manifest['input_sha256']['reports/evaluation/generation_models/phase17/generator_comparison_manifest.json'],
        'models':generator_manifest['generators'],'context_metadata':metadata,
        'actual_edge_device':None,'hardware_benchmark_executed':False})
    write_json(OUT/'phase19_preparation.json',{'protocol_ready':True,'fixed_subset_questions':60,
        'actual_edge_target_identified':False,'actual_edge_runtime_identified':False,
        'edge_execution_ready':False,'independent_judge_ready':False,
        'human_completed_outputs':hp['human_completed_outputs'],
        'evaluation_validity_ready_for_final_model_selection':False,
        'next_requirements':['Specify actual edge device, RAM/unified memory and power constraints, runtime',
            'Resolve independent judge or complete independent human support audit before strong quality selection'],
        'hardware_feasibility_study_can_follow_target_configuration':True,
        'not_a_production_migration':True})
    write_json(OUT/'completion.json',{'status':'completed_with_evaluation_limitations','independent_judge_ready':False,
        'judge_validation_outputs_evaluated':0,'claim_audit_outputs':48,'claim_audit_records':len(audited),
        'human_completed_outputs':hp['human_completed_outputs'],'edge_subset_questions':60,
        'phase19_hardware_protocol_prepared':True,'final_model_selection_validated':False,
        'generators_reexecuted':False,'edge_benchmark_executed':False})
    audit_failures=[{'claim_id':j['claim_id'],'answer_id':j['answer_id'],'failure':j['judge_result']}
                    for j in audited if j['judge_result']['evaluation_status']=='failed']
    write_jsonl(OUT/'audit_failures.jsonl',audit_failures)
    lines=['# Phase 18 — Evaluation Validity & Claim-Citation Audit','',
        'AI-generated Corpus-Grounded Silver Benchmark. All Generator outputs, contexts and Silver references remain frozen.','',
        '## Independent judge','',
        'No independent completion artifact exists in the installed local inventory. Independent judge ready = false. '
        'The 96-output validation sample is frozen, but inter-judge correlations, new independent Qwen scores and ranking stability remain unavailable.','',
        '## Blind citation audit','',
        f'48 E4 outputs (12/model), {len(audited)} verbatim claim candidates. '
        f'{sum(s["claim_count"]==0 for s in sample)} sampled outputs contain no extractable factual assertion. No replacement was selected.','',
        'The existing Qwen judge receives no Generator identity, Primary Judge score or Silver reference. '
        'It is not an independent judge. Qwen Generator judgments are self-judge exploratory. '
        'Answer-level citations are not silently promoted into confirmed claim-level bindings. '
        'Initial extraction inventory contains 165 candidates; 43 pure list/citation markers are excluded by a structural rule. '
        'The original 48 outputs were not replaced. Initial unbounded-quote diagnostics and the interrupted request uncertainty are retained in initial_diagnostics_v1. '
        'Main audit v2 limits quote/reason fields uniformly and retains the same judge/options/entailment definitions.','',
        '| Generator | Claims | Provenance valid | Entailed citation pairs | Fully supported claims | Partial claims | Unsupported cited claims |','|---|---:|---:|---:|---:|---:|---:|']
    def fmt(x):return 'unavailable' if x is None else f'{x:.2%}'
    for m,v in by_model.items():
        lines.append(f'| {m} | {v["claims"]} | {fmt(v["valid_citation_provenance_rate"])} | {fmt(v["entailed_citation_rate"])} | '
                     f'{fmt(v["fully_supported_claim_rate"])} | {fmt(v["partially_supported_claim_rate"])} | {fmt(v["unsupported_cited_claim_rate"])} |')
    lines.extend(['','Unsupported = AI diagnostic that supplied cited evidence does not support the claim; it is not proof of outside-world falsity. '
        'Pair rates use decidable claim×citation pairs; fully/partially supported rates use all extracted claims. '
        'A fully supported claim requires at least one individually sufficient cited chunk. Joint support from multiple partial chunks requires human review.','',
        f'Human-completed outputs: {hp["human_completed_outputs"]}/48; human-reviewed claims: {hp["human_reviewed_claims"]}. '
        'AI records are never marked human verified.','',
        '## Reference bias sensitivity','',
        'Reference generator = Gemma 2 9B; reference_alignment_bias_possible = true. '
        'Faithfulness/Relevancy and deterministic protocol metrics are separated from Silver correctness/F1. '
        'Question/evidence selection bias and Primary Judge limitations also remain in the reference-independent family.','',
        '| Metric family | Shared valid questions | Descriptive non-dominated models |','|---|---:|---|'])
    for family,p in bias['pareto'].items():lines.append(f'| {family} | {p["common_question_count"]} | {", ".join(p["non_dominated"])} |')
    lines.extend(['','No weighted score or causal reference-bias estimate is constructed. Qwen judge-based ranking remains unresolved.','',
        '## Shortlist','', '| Model | Status | Edge recommendation |','|---|---|---|'])
    for m,v in shortlist['models'].items():lines.append(f'| {m} | {v["status"]} | {v["edge_test_recommendation"]} |')
    lines.extend(['','No strong candidate or final winner is declared without independent evaluation and completed human support audit.','',
        '## Edge preparation','',
        'A fixed 60-question subset contains 20 Direct, 20 Paraphrase and 20 Contextual questions, balanced over available species/category/context lengths. '
        'The edge protocol requires target hardware identity, model artifact digest/quantization, cold/warm load, TTFT/TPS, full protocol latency, memory, '
        'power/thermal when measurable, capacity, reliability and the same quality evidence. No device benchmark has been run.','',
        'Protocol: docs/edge_benchmark_protocol.md. Actual device, memory/power limits and runtime must be specified before Phase 19 execution.','',
        '## Limitations','',
        '- Independent judge absent; same-artifact conflict unresolved for Qwen.',
        '- Human support judgments are incomplete; automatic atomicity and answer-level binding are provisional.',
        '- Audit quotas and distinct per-model sampled question IDs do not support prevalence or paired model superiority conclusions.',
        '- Citation quote checking detects malformed support quotations but is not human entailment verification.',
        '- Milkfish has no questions; calculation n=3. Historical Windows RTX 4060 latency is not final edge-device performance.',
        '- Earlier Phase 17 raw capture gap and evaluator-repeat instability remain documented; no earlier output is repaired.',
        ''])
    (OUT/'phase18_summary.md').write_text('\n'.join(lines),encoding='utf-8')
    print(json.dumps({'claims':len(audited),'ai_evaluation_failures':len(audit_failures),
        'human_completed_outputs':hp['human_completed_outputs'],'shortlist':{m:v['status'] for m,v in shortlist['models'].items()}}),flush=True)
