"""Reporting only; private identity and AI labels never enter the blind Workbench."""
from __future__ import annotations

import copy
import json
from collections import Counter

from .core import ai_human_agreement, categorical_agreement, latest_events, support_summary
from .history import primary_state


def update_shortlist(previous, human_by_model, complete, criteria):
    result = copy.deepcopy(previous)
    result['human_primary_review_complete'] = complete
    result['criteria_v2'] = criteria
    result['no_composite_score'] = True
    result['final_edge_model_selected'] = False
    for name, row in result['models'].items():
        row.pop('citation_audit', None)  # Do not rebrand the prior AI audit as human validation.
        row['human_claim_citation_audit'] = human_by_model.get(name) if complete else None
        row['human_support_status'] = 'reviewed_sample' if complete else 'not_reviewed'
        row['reference_generator'] = 'Gemma 2 9B'
        row['reference_alignment_bias_possible'] = True
        row['sample_only_descriptive'] = True
        if name == 'qwen2.5-coder:7b':
            row['independent_generation_quality_unresolved'] = True
            h = human_by_model.get(name, {})
            # Predeclared necessary conditions, not an aggregate quality score.
            sufficient = (complete and h.get('n_reviewed_claims', 0)>0
                and h.get('outputs_reviewed')==12
                and (h.get('human_fully_supported_claim_rate') or 0) >= criteria['qwen_conditional_min_fully_supported']
                and (h.get('human_unsupported_by_context_rate') if h.get('human_unsupported_by_context_rate') is not None else 1)
                    <= criteria['qwen_conditional_max_unsupported_by_context']
                and (h.get('human_cannot_determine_rate') if h.get('human_cannot_determine_rate') is not None else 1)
                    <= criteria['qwen_conditional_max_cannot_determine'])
            row['status'] = 'conditional_candidate' if sufficient else 'evaluation_unresolved'
            row['edge_test_recommendation'] = ('conditional hardware/quality study; independent judge still needed'
                                              if sufficient else 'performance-only exploratory; generation quality unresolved')
            row['qwen_human_gate_met'] = sufficient
            row['not_eligible_for_automatic_strong_promotion'] = True
        else:
            # Human sample does not erase schema reliability, judge independence or reference bias limits.
            row['status'] = previous['models'][name]['status']
        row['final_edge_model_selected'] = False
    return result


def inter_reviewer(state, subset_ids):
    reviewers = {r['assignment']: r for r in state['reviewers']}
    if 'primary' not in reviewers or 'second' not in reviewers:
        return dict(status='unavailable_no_second_reviewer', n_paired_claims=0,
                    raw_agreement=None, cohen_kappa=None)
    latest = latest_events(state['claims'], 'claim_id')
    left, right = [], []
    for cid in subset_ids:
        a = latest.get((reviewers['primary']['reviewer_id'], cid))
        b = latest.get((reviewers['second']['reviewer_id'], cid))
        if a and b:
            left.append(a['new_value']['cited_set_support']);right.append(b['new_value']['cited_set_support'])
    result = categorical_agreement(left, right)
    result.update(status='paired_reviews_available' if left else 'awaiting_paired_reviews',
                  n_paired_claims=len(left), predeclared_subset_size=len(subset_ids),
                  sample_selection='fixed before first human review; not selected from disagreements')
    return result


def build_reports(records, state, private_rows, ai_pairs, previous_shortlist, manifest):
    progress, claims, pairs = primary_state(records, state)
    complete = progress['primary_review_complete']
    progress.update(human_labels_auto_filled=False, human_review_execution='not_performed' if not claims else 'human_submissions',
                    deblinding_permitted=complete, report_name='Human-reviewed Claim-Citation Support Audit',
                    human_gold_benchmark=False, expert_gold_qa=False,
                    reviewer_role=[r['reviewer_role'] for r in state['reviewers']],
                    second_reviewer_present=any(r['assignment']=='second' for r in state['reviewers']))
    summary = support_summary(claims, pairs)
    all_claims = [c for r in records for c in r['claims']]
    cited_count = sum(bool(c['audit_citation_set']) for c in all_claims)
    summary.update(primary_frozen_claim_denominator=len(all_claims),
                   primary_frozen_pair_denominator=sum(len(c['audit_citation_set']) for c in all_claims),
                   frozen_declared_claim_citation_coverage=cited_count/len(all_claims) if all_claims else None,
                   frozen_inline_binding_claim_count=sum(c['citation_binding']=='claim_inline' for c in all_claims),
                   claim_citation_coverage_definition='Declared association, not human support; answer-level binding remains provisional',
                   reviewed_claim_coverage=progress['claim_completion_rate'],
                   human_review_complete=complete, metrics_available=bool(claims),
                   no_primary_denominator_changed=True,
                   sample_limitation='48 quota-sampled outputs; only 12 per model and retrieval misses oversampled. Descriptive, not population superiority.')
    # Unique declared citations are a separate provenance denominator from claim x citation pairs.
    unique = {}
    for p in pairs:
        unique.setdefault((p['answer_id'], p['context_id']), []).append(p['new_value']['provenance'])
    valid = sum(all(x=='valid' for x in labels) for labels in unique.values())
    summary['unique_citation_provenance'] = dict(n_reviewed=len(unique), n_valid=valid,
        validity_rate=valid/len(unique) if unique else None,
        aggregation='valid only if every primary human observation agrees valid; disagreements retained')
    identity = {r['answer_id']: r for r in private_rows}
    by_model = {}
    if complete:
        for model in previous_shortlist['models']:
            cs = [c for c in claims if identity[c['answer_id']]['generator']==model]
            ps = [p for p in pairs if identity[p['answer_id']]['generator']==model]
            s = support_summary(cs, ps)
            s['outputs_reviewed'] = sum(identity[a]['generator']==model for a in progress['completed_answer_ids'])
            s['descriptive_only'] = True
            by_model[model] = s
    summary.update(by_model=by_model, by_model_status='available_descriptive' if complete else 'withheld_until_primary_review_complete')
    agreement = ai_human_agreement(ai_pairs, pairs)
    agreement.update(status='paired_human_reviews' if pairs else 'unavailable_no_human_reviews',
                     model_split_status='deblinded' if complete else 'withheld_until_primary_review_complete',
                     qwen_self_judge_conflict=True,
                     self_judge_metrics_are_exploratory=True, human_is_not_ai_ground_truth=True)
    if complete:
        agreement['qwen_self_judge_exploratory'] = ai_human_agreement(ai_pairs,
            [p for p in pairs if identity[p['answer_id']]['generator']=='qwen2.5-coder:7b'])
        agreement['non_self_judge'] = ai_human_agreement(ai_pairs,
            [p for p in pairs if identity[p['answer_id']]['generator']!='qwen2.5-coder:7b'])
    shortlist = update_shortlist(previous_shortlist, by_model, complete, manifest['shortlist_criteria'])
    ir = inter_reviewer(state, manifest['second_reviewer_claim_ids'])
    failures = [c for c in claims if c['new_value']['attribution_failure_type']=='citation_selection_failure']
    unsupported = [c for c in claims if c['new_value']['attribution_failure_type']=='unsupported_by_provided_context']
    atomicity = [c for c in claims if c['new_value']['atomicity']!='atomic']
    return dict(status=progress, summary=summary, ai_agreement=agreement,
                inter_reviewer=ir, shortlist=shortlist, selection_failures=failures,
                unsupported=unsupported, atomicity=atomicity)


def write_reports(folder, reports):
    mapping = {'human_audit_status.json':'status', 'human_support_summary.json':'summary',
               'ai_vs_human_agreement.json':'ai_agreement', 'inter_reviewer_agreement.json':'inter_reviewer',
               'model_shortlist_v2.json':'shortlist'}
    for filename, key in mapping.items():
        (folder/filename).write_text(json.dumps(reports[key], ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    for filename, key in (('citation_selection_failures.jsonl','selection_failures'),
                          ('unsupported_by_context.jsonl','unsupported'), ('atomicity_issues.jsonl','atomicity')):
        # These are current analysis exports, NOT the immutable append-only review history.
        (folder/filename).write_text(''.join(json.dumps(r, ensure_ascii=False, sort_keys=True)+'\n'
                                            for r in reports[key]), encoding='utf-8')
    p, s = reports['status'], reports['summary']
    lines = ['# Phase 18.1 — Blinded Human Claim-Citation Support Audit', '',
             'This is an evaluation-only review workflow, not a Human Gold Benchmark or Expert Gold QA.', '',
             f'Frozen inputs: {p["target_outputs"]} outputs, {p["target_claims"]} primary claims, {p["target_pairs"]} citation pairs.',
             f'Human reviewed: {p["outputs_reviewed"]} outputs / {p["claims_reviewed"]} claims / {p["pairs_reviewed"]} pairs.',
             f'Primary review complete: {p["primary_review_complete"]}.', '',
             '## Human support results', '',
             ('No human labels were submitted. Human semantic/provenance rates and AI/human agreement are unavailable (null), not zero support.'
              if not p['claims_reviewed'] else json.dumps(s, ensure_ascii=False, indent=2)), '',
             '## Integrity and blinding', '',
             'Frozen answers, claims and AI judgments are unchanged. Human decisions are not prefilled by AI.',
             'The blind interface allowlists question, answer, verbatim claim/span, citations and all provided contexts.',
             'Model identity and all judge/reference metrics are withheld. Per-model human reporting unlocks only after the complete primary audit.',
             'History is append-only and hash-chained. Revisions preserve previous/new values, reviewer ID/role and UTC timestamp.',
             '36 optional second-reviewer claims are selected before review by a fixed stratified rule; no second reviewer is assumed.', '',
             '## Interpretation', '',
             'unsupported_by_provided_context means absence of support in this question\'s evidence, not real-world falsity.',
             'Compound/non-factual/ambiguous flags do not change the frozen 122-claim primary denominator.',
             'Joint cited-set support is explicitly reviewed; answer-level citation association is not inferred claim-level support.',
             'Qwen AI audit remains self-judge exploratory; human citation support alone cannot establish broad model superiority.',
             'Gemma reference alignment bias, missing independent judge and the small quota sample remain limitations.', '',
             '## Shortlist and next step', '',
             'No automatic winner or composite score. Until human submissions exist the previous provisional shortlist is retained.',
             'Actual edge-device feasibility testing can be planned, but final quality selection lacks human support and independent judge evidence.',
             'Current user direction: continue tooling without conducting human review this round.', '',
             'Workbench: http://127.0.0.1:8779 ; reporting refresh: scripts/phase18_1_human_audit.py --report.',
             'No generation, retrieval, judge execution, sampling replacement or production migration was performed.', '']
    (folder/'phase18_1_summary.md').write_text('\n'.join(lines), encoding='utf-8')
