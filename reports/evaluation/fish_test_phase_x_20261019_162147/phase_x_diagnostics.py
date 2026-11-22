from __future__ import annotations
import json, hashlib
from pathlib import Path
from collections import Counter, defaultdict

ROOT=Path(__file__).resolve().parents[3]
W=ROOT/'reports/evaluation/fish_test_phase_w_20261019_133804'
V=ROOT/'reports/evaluation/fish_test_phase_v_20261018_224918'
X=ROOT/'reports/evaluation/fish_test_phase_x_20261019_162147'

def read_jsonl(p):
    with p.open(encoding='utf-8-sig') as f:
        return [json.loads(line) for line in f if line.strip()]
def read_json(p):
    return json.loads(p.read_text(encoding='utf-8-sig'))
def write_json(p,obj): p.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def write_jsonl(p,rows): p.write_text(''.join(json.dumps(x,ensure_ascii=False,separators=(',',':'))+'\n' for x in rows),encoding='utf-8')

wg=read_jsonl(W/'generator_results_v3.jsonl')
wr=read_jsonl(W/'retrieval_results_v3_updated.jsonl')
vr=read_jsonl(V/'retrieval_results_v3_final.jsonl')
refs=read_jsonl(W/'reference_answers_v3.jsonl')
source_rows=read_jsonl(W/'source_resolution_final.jsonl')
facts=read_jsonl(W/'research_fact_cards_w.jsonl')
wg_by={(x['question_id'],x['model_id']):x for x in wg}
wr_by={x['question_id']:x for x in wr}; vr_by={x['question_id']:x for x in vr}

# M2 cause analysis; distinguishes deterministic safety override from model-reported abstention.
m2=[x for x in wg if x.get('model_id')=='M2']
counts=Counter(); groups=defaultdict(Counter); detail=[]
for x in m2:
    qid=x['question_id']; rr=wr_by[qid]; n=int(rr.get('final_top5_count',len(rr.get('reranked_top5',[]))))
    grp='NO_CONTEXT' if n==0 else ('PARTIAL_CONTEXT' if n<5 else 'FULL_TOP5')
    status=x.get('status'); model_status=x.get('model_reported_status') or x.get('model_answer_before_safety_gate')
    reason=x.get('safety_guard_reason') or x.get('abstention_reason')
    parse_err=x.get('parse_error'); citation=(x.get('citation_validation') or {})
    possible_prompt=False
    if status=='invalid_output' or status=='api_error':
        cause='PARSER_OR_VALIDATION_REJECTION' if parse_err or citation.get('valid') is False or status=='invalid_output' else 'UNKNOWN_CAUSE'
    elif x.get('safety_guard_applied'):
        cause='NO_EVIDENCE' if n==0 else 'INSUFFICIENT_EVIDENCE'
    elif model_status=='abstain' or status=='abstain':
        # No deterministic guard was applied: this is a model-level abstention,
        # even when the model's own JSON says evidence was insufficient.
        cause='MODEL_ABSTENTION'
        possible_prompt=(n>0)
    elif status=='answered': cause='UNKNOWN_CAUSE'
    else: cause='UNKNOWN_CAUSE'
    counts[cause]+=1; groups[grp][cause]+=1
    detail.append({
        'question_id':qid,'model_id':'M2','model_tag':x.get('model_tag'),'model_digest':x.get('model_digest'),
        'context_count':n,'context_group':grp,'retrieval_status':rr.get('retrieval_status'),
        'effective_status':status,'model_reported_status':model_status,'safety_guard_applied':x.get('safety_guard_applied'),
        'safety_guard_reason':x.get('safety_guard_reason'),'evidence_sufficiency':x.get('evidence_sufficiency'),
        'abstention_reason':reason,'parse_error':parse_err,'retry_used':x.get('retry_used'),
        'citation_validation':citation,'prompt_sha256':x.get('prompt_sha256'),
        'cause_classification':cause,'possible_prompt_too_restrictive':possible_prompt,
    'possible_unnecessary_candidate':bool(possible_prompt and x.get('evidence_sufficiency') in ('sufficient','partial')),
        'diagnostic_limit':'No source-verified gold answer; this classifies execution path, not unnecessary refusal correctness.'
    })
write_jsonl(X/'m2_abstention_detail_180.jsonl',detail)
write_json(X/'m2_abstention_root_cause.json',{
    'question_count':len(m2),'effective_status_counts':dict(Counter(x.get('status') for x in m2)),
    'model_reported_status_counts':dict(Counter(x.get('model_reported_status') or x.get('model_answer_before_safety_gate') for x in m2)),
    'safety_guard_overrides':sum(x.get('safety_guard_applied') is True for x in m2),
    'cause_counts':dict(counts),'by_context_group':{k:dict(v) for k,v in groups.items()},
    'model_level_abstentions_without_deterministic_guard':sum(x['possible_prompt_too_restrictive'] for x in detail),
    'potentially_unnecessary_candidates_where_model_claimed_sufficient_or_partial':sum(x['possible_unnecessary_candidate'] for x in detail),
    'model_level_abstentions_reporting_insufficient':sum(x.get('evidence_sufficiency')=='insufficient' and x['cause_classification']=='MODEL_ABSTENTION' for x in detail),
    'confirmed_unnecessary_refusals':0,
    'other_findings':{
      'prompt_too_restrictive_rule':'RAGEngine.evidence_sufficiency uses narrow keyword/regex checks. It can reject a potentially usable Context when a prompt phrase requires a numeric/unit pattern that the heuristic does not recognize. No fully verified answer reference exists to confirm false refusals.',
      'postprocessing':'For full-run calls, evaluate_refusal=True causes deterministic abstention to override model output whenever context is empty or the local sufficiency heuristic fails.',
      'parser_citation':'Invalid output is counted separately; retries are preserved. It is not the explanation for 179 effective M2 abstentions.'
    },
    'limitations':['Classification is based on stored retrieval, prompt, parser, model output, safety gate and validation fields.','Without independent answer evidence, this cannot establish answerability or a false-refusal rate.']
})

# Per-question V/W retrieval regression.
reg=[]; delta=Counter(); bucket=Counter()
for qid in sorted(set(vr_by)&set(wr_by)):
    a,b=vr_by[qid],wr_by[qid]
    an=int(a.get('final_top5_count',len(a.get('reranked_top5',[])))); bn=int(b.get('final_top5_count',len(b.get('reranked_top5',[]))))
    change='same'
    if bn<an:
        change='coverage_down'; delta['coverage_down']+=1
    elif bn>an:
        change='coverage_up'; delta['coverage_up']+=1
    else: delta['same']+=1
    if an>0 and bn==0:
        cause='W_SCOPE_FILTER_OR_SOURCE_ALLOWLIST_CHANGE'
    elif an>=5 and bn<5:
        cause='W_CANDIDATE_POOL_OR_SPECIES_SCOPE_CHANGE'
    elif bn==0:
        cause=b.get('retrieval_failure_reason') or b.get('retrieval_status')
    elif bn<5:
        cause='ELIGIBLE_CANDIDATE_POOL_BELOW_FIVE'
    else: cause='NO_COVERAGE_REGRESSION'
    bm25=int(b.get('bm25_candidate_count',0)); dense=int(b.get('dense_candidate_count',0)); rrf=int(b.get('rrf_candidate_count',0)); eligible=int(b.get('species_applicability_pass_count',0)); rer=int(b.get('reranker_candidate_count',0))
    record={
      'question_id':qid,'species':b.get('species'),'category':b.get('category'),'question_text':b.get('question_text'),
      'phase_v_context_count':an,'phase_w_context_count':bn,'delta':bn-an,'change':change,
      'phase_v_retrieval_status':a.get('retrieval_status'),'phase_v_failure_reason':a.get('retrieval_failure_reason'),
      'phase_v_query':a.get('query'),'phase_v_source_allowlist':a.get('scope_allowed_source_ids'),
      'phase_w_retrieval_status':b.get('retrieval_status'),'phase_w_failure_reason':b.get('retrieval_failure_reason'),
      'phase_w_query':b.get('query'),'phase_w_allowed_source_ids':(b.get('requirement_profile') or {}).get('allowed_source_ids'),
      'phase_w_candidates':{'bm25':bm25,'dense':dense,'rrf':rrf,'source_qualified':int(b.get('source_qualification_pass_count',0)),'species_qualified':eligible,'reranker':rer,'final':bn},
      'diagnosed_stage':cause,
      'corpus_version_phase_v':a.get('corpus_version'),'corpus_version_phase_w':b.get('corpus_version'),
      'same_corpus_version':a.get('corpus_version')==b.get('corpus_version'),
      'query_text_equivalent':(a.get('query') or '').strip()==(b.get('query') or '').strip(),
      'diagnostic':'Coverage delta is attributed only to recorded stage counts/filters; it is not an evidence-quality score.'
    }
    reg.append(record); bucket[cause]+=1
write_jsonl(X/'retrieval_coverage_regression_180.jsonl',reg)
write_json(X/'retrieval_coverage_regression_summary.json',{
  'questions_compared':len(reg),'phase_v_any_context':sum(x.get('final_top5_count',0)>0 for x in vr),'phase_w_any_context':sum(x.get('final_top5_count',0)>0 for x in wr),
  'phase_v_full_top5':sum(x.get('final_top5_count',0)>=5 for x in vr),'phase_w_full_top5':sum(x.get('final_top5_count',0)>=5 for x in wr),
  'per_question_transition_counts':dict(delta),'observed_diagnostic_buckets':dict(bucket),
  'corpus_versions_same':len({x.get('corpus_version') for x in vr})==1 and len({x.get('corpus_version') for x in wr})==1 and next(iter({x.get('corpus_version') for x in vr}))==next(iter({x.get('corpus_version') for x in wr})),
  'query_text_identical_n':sum(x['query_text_equivalent'] for x in reg),
  'caveat':'Phase V had an explicit scope allowlist and broader candidate context. Phase W applies a narrower species/applicability profile and allowed-source filter. Lower coverage primarily reflects changed scope/qualification filters in the same frozen corpus, not a corpus-content change. Individual records preserve stage counts for attribution.'
})

# Source improvement register: do not promote processing approval to license/admission.
sc=Counter(x.get('admission_status') for x in source_rows)
source_summary={
 'phase_w_source_records':len(source_rows),'distinct_source_sha256':len({x.get('sha256_actual') for x in source_rows if x.get('sha256_actual')}),
 'owner_workflow_approved':sum(x.get('owner_decision')=='APPROVED' for x in source_rows),
 'admission_status_counts':dict(sc),'fulltext_index_rights_independently_verified_records':sum(x.get('fulltext_index_rights_independently_verified') is True for x in source_rows),
 'prior_50_blocked_formal_resolutions':0,'new_professional_source_files_admitted':0,'new_corpus_chunks_added':0,
 'research_fact_cards_created':len(facts),'fact_cards_by_category':dict(Counter(x.get('category') for x in facts)),
 'fact_cards_indexed':sum(x.get('corpus_status') not in ('not_indexed',None) for x in facts),
 'facts_with_archived_source_bytes_digest':sum(bool(x.get('source_bytes_sha256')) for x in facts),
 'facts_species_specific_for_six_target_species':sum(x.get('species_scope') in {'虱目魚','吳郭魚','石斑魚','鱸魚','烏魚','鰻魚'} for x in facts),
 'page139_general_freshwater_fact_cards':sum(x.get('source_id')=='TFRI-AQUATIC-TECH-139' for x in facts),
 'eel_historical_page190_cards':sum(x.get('source_id')=='TFRI-EEL-1988-DISEASE-SUMMARY-190' for x in facts),
 'interpretation':'The four concise cards are research-only and are not new formal source admission or corpus evidence. Owner approval authorizes the source processing workflow; it does not establish third-party full-text permission.'
}
write_json(X/'source_coverage_improvement.json',source_summary)

# Existing 28 answer candidates: expose qualification state; do not upgrade.
write_jsonl(X/'verified_reference_answer_candidates.jsonl',[{
 'question_id':r.get('question_id'),'species':r.get('species'),'category':r.get('category'),'original_question':r.get('original_question'),
 'source_id':r.get('source_id'),'source_version':r.get('source_version'),'exact_evidence_span':r.get('exact_evidence_span'),
 'expected_answer':r.get('expected_answer'),'logical_rubric':r.get('logical_rubric'),'arithmetic_formula':r.get('arithmetic_formula'),
 'verification_status':r.get('verification_status'),'prior_candidate_status':r.get('prior_candidate_status'),
 'corpus_version':r.get('corpus_version'),'human_gold_reviewed':False,
 'phase_x_disposition':'not_promoted_without_independent_source_span_and_frozen_rubric'
} for r in refs if str(r.get('verification_status','')).startswith('AI_ASSISTED') or r.get('prior_candidate_status')=='SOURCE_VERIFIED_AUTOMATED_CANDIDATE'])
print(json.dumps({'m2_cause_counts':dict(counts),'m2_groups':{k:dict(v) for k,v in groups.items()},'retrieval_summary':read_json(X/'retrieval_coverage_regression_summary.json'),'source':source_summary,'candidate_reference_rows':sum(1 for r in refs if str(r.get('verification_status','')).startswith('AI_ASSISTED') or r.get('prior_candidate_status')=='SOURCE_VERIFIED_AUTOMATED_CANDIDATE')},ensure_ascii=False,indent=2))




