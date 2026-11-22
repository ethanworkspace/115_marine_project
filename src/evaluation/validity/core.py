"""Pure, deterministic sampling and verbatim claim/provenance operations."""
from __future__ import annotations

import hashlib
import json
import math
import re
import statistics
from collections import Counter

MODELS = ('gemma2:9b', 'deepseek-r1:8b', 'qwen2.5-coder:7b', 'deepseek-r1:7b')
CONDITIONS = ('oracle', 'e4_top5')
VERDICTS = ('entailed', 'partially_entailed', 'not_entailed', 'citation_missing', 'cannot_determine')
REFERENCE_INDEPENDENT = ('faithfulness', 'answer_relevancy', 'citation_provenance',
    'citation_entailment', 'claim_citation_coverage', 'abstention', 'schema_reliability')
REFERENCE_DEPENDENT = ('silver_reference_correctness', 'silver_token_f1')
BIAS = dict(reference_generator='Gemma 2 9B', reference_alignment_bias_possible=True,
            benchmark_type='silver', human_expert_verified=False)
SAMPLE_RULE = {
    'version': 'phase18_coverage_first_v1', 'eligible_status': 'answered',
    'judge_target': 96, 'judge_per_model_condition': 12,
    'audit_target': 48, 'audit_per_model_e4': 12,
    'selection': 'Greedy least-covered levels, then stable SHA-256; no manual selection',
    'strata_order': ['query_style', 'retrieval_availability', 'primary_quality_band',
                     'citation_recall_band', 'category', 'species'],
    'primary_quality_band': {'low': '<0.5', 'medium': '0.5<=score<0.8', 'high': '>=0.8',
                             'metric': 'faithfulness; missing stays unavailable'},
    'citation_recall_band': {'high': 'strict recall >=0.8', 'low': '<0.8'},
    'edge_target': 60, 'edge_per_style': 20,
    'context_length_bands': 'fixed corpus E4 Top-5 character tertiles before hardware testing',
}


def digest(value: str) -> str:
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def identity(row):
    return (row['generator'], row['condition'], row['question_id'])


def answer_id(row):
    return 'A' + digest('|'.join(identity(row)))[:20]


def independent_candidates(models, generator_digests):
    """Artifact independence is necessary; embeddings/classifiers are not judges."""
    records = []
    for m in models:
        cap = m.get('capabilities', [])
        conflict = m.get('digest') in set(generator_digests)
        records.append({**m, 'generator_artifact_conflict': conflict,
                        'independent_eligible': bool(m.get('digest')) and not conflict and 'completion' in cap,
                        'ineligible_reason': 'generator_artifact' if conflict else
                            ('not_completion_model' if 'completion' not in cap else None)})
    return records


def score_band(row):
    m = row.get('metrics', {}).get('faithfulness', {})
    value = m.get('score')
    if m.get('status') != 'valid' or not isinstance(value, (int, float)):
        return 'unavailable'
    return 'low' if value < .5 else ('medium' if value < .8 else 'high')


def strata(row):
    recall = row['deterministic_generation']['required_evidence_citation'].get('strict_recall_all_questions', 0)
    return (row.get('query_style', 'unknown'),
            'hit' if row['required_evidence_complete_in_top5'] else 'miss', score_band(row),
            'high' if recall >= .8 else 'low', row.get('category') or 'unknown',
            row.get('species') or 'unknown')


def coverage_sample(rows, count, salt, strata_fn=strata):
    candidates = sorted(rows, key=lambda r: digest(salt + '|'.join(identity(r))))
    if len({identity(r) for r in candidates}) != len(candidates):
        raise ValueError('Duplicate output identities')
    chosen = []
    counts = [Counter() for _ in SAMPLE_RULE['strata_order']]
    while candidates and len(chosen) < count:
        row = min(candidates, key=lambda r: tuple(counts[i][x] for i, x in enumerate(strata_fn(r)))
                  + (digest(salt + '|'.join(identity(r))),))
        chosen.append(row)
        candidates.remove(row)
        for i, value in enumerate(strata_fn(row)):
            counts[i][value] += 1
    return chosen


def stratified_outputs(rows, *, audit=False):
    selected = []
    for model in MODELS:
        for condition in (('e4_top5',) if audit else CONDITIONS):
            pool = [r for r in rows if r['generator'] == model and r['condition'] == condition
                    and r['status'] == 'answered']
            subset = coverage_sample(pool, 12, 'phase18_audit' if audit else 'phase18_judge')
            if len(subset) != 12:
                raise ValueError(f'Insufficient answered outputs: {model}/{condition}')
            selected.extend(subset)
    return selected


def extract_claims(row):
    """Verbatim sentence/clause candidates, never rewrite or invent omitted subjects.

    Sentence/list units can be compound; reviewer-visible atomicity warnings retain
    this limitation instead of claiming perfect automatic semantic decomposition.
    """
    answer = row['answer']
    boundaries = [0]
    nesting = 0
    for i, ch in enumerate(answer):
        if ch in '（([':
            nesting += 1
        elif ch in '）)]':
            nesting = max(0, nesting - 1)
        decimal = ch == '.' and i > 0 and i + 1 < len(answer) and answer[i-1].isdigit() and answer[i+1].isdigit()
        if not nesting and (ch in '。！？；;\n' or (ch == '.' and not decimal
                and i+1 < len(answer) and answer[i+1].isspace())):
            boundaries.append(i+1)
    boundaries.append(len(answer))
    claims = []
    heading = None
    for start, end in zip(boundaries, boundaries[1:]):
        while start < end and answer[start].isspace():
            start += 1
        while end > start and answer[end-1].isspace():
            end -= 1
        text = answer[start:end]
        if not text or re.fullmatch(r'[\s|:\-–—]+', text):
            continue
        # Explicit Markdown headings remain context, not invented assertions.
        if text.startswith('#') or text.endswith(('：', ':')):
            heading = text
            continue
        cid = answer_id(row) + '_K' + digest(f'{start}:{end}:{text}')[:12]
        inline = re.findall(r'[\[【（(]\s*(C[1-9]\d*(?:\s*[,、]\s*C[1-9]\d*)*)\s*[\]】）)]', text)
        refs = list(dict.fromkeys(re.findall(r'C[1-9]\d*', ' '.join(inline))))
        answer_refs = list(dict.fromkeys(row['deterministic_generation'].get('citations') or []))
        binding = 'claim_inline' if refs else 'answer_level_only'
        warnings = []
        if len(text) > 250 or re.search(r'並且|此外|同時|；|以及', text):
            warnings.append('compound_claim_candidate_manual_atomicity_review')
        if text.count('|') >= 2:
            warnings.append('table_row_requires_header_context')
        claims.append({'answer_id': answer_id(row), 'claim_id': cid, 'claim_text': text,
            'answer_start': start, 'answer_end': end, 'claim_text_sha256': digest(text),
            'extraction_method': 'verbatim_sentence_clause_v1', 'context_heading': heading,
            'citation_binding': binding, 'linked_citations': refs,
            'answer_level_citations': answer_refs,
            'audit_citation_set': refs if refs else answer_refs, 'warnings': warnings,
            'atomicity_human_verified': False})
    return claims


def verify_claim(claim, answer):
    return (answer[claim['answer_start']:claim['answer_end']] == claim['claim_text']
            and digest(claim['claim_text']) == claim['claim_text_sha256'])


def structural_only(claim):
    """Exclude formatting artifacts, never exclude a short factual numeric answer."""
    text=claim['claim_text'].strip()
    if re.fullmatch(r'\d+\.',text):
        return 'list_number_only'
    if re.fullmatch(r'C[1-9]\d*(?:\s*[,、]\s*C[1-9]\d*)*',text):
        return 'citation_ids_only'
    return None


def blind_record(row, claims):
    """Allowlist excludes all generator, judge, metric and reference identity fields."""
    contexts = [dict(context_id=c['context_id'], chunk_id=c['chunk_id'], document_id=c['document_id'],
                    page=c['page'], content_checksum=c['content_checksum'], text=t)
                for c, t in zip(row['context_provenance'], row['contexts'], strict=True)]
    for c in contexts:
        if digest(c['text']) != c['content_checksum']:
            raise ValueError('Frozen context snapshot checksum mismatch')
    return {'answer_id': answer_id(row), 'question_id': row['question_id'],
            'question': row['question'], 'answer': row['answer'],
            'answer_sha256': digest(row['answer']), 'claims': claims, 'contexts': contexts,
            'citations': row['deterministic_generation'].get('citations') or []}


def judge_payload(record, claim):
    contexts = {c['context_id']: c for c in record['contexts']}
    return {'question': record['question'], 'claim': claim['claim_text'],
            'verbatim_heading_context': claim.get('context_heading'),
            'cited_contexts': [{'context_id': cid, 'text': contexts[cid]['text']}
                for cid in claim['audit_citation_set'] if cid in contexts]}


def entailment_schema(context_ids):
    return {'type': 'object', 'additionalProperties': False, 'required': ['judgments'],
        'properties': {'judgments': {'type': 'array', 'minItems': len(context_ids), 'maxItems': len(context_ids),
            'items': {'type': 'object', 'additionalProperties': False,
                'required': ['context_id', 'verdict', 'supporting_quote', 'reason'],
                'properties': {'context_id': {'type': 'string', 'enum': context_ids},
                    'verdict': {'type': 'string', 'enum': [v for v in VERDICTS if v != 'citation_missing']},
                    'supporting_quote': {'type': 'string', 'maxLength': 240},
                    'reason': {'type': 'string', 'maxLength': 160}}}}}}


def validate_entailment(parsed, context_ids):
    from jsonschema import Draft202012Validator
    Draft202012Validator(entailment_schema(context_ids)).validate(parsed)
    actual = [j['context_id'] for j in parsed['judgments']]
    if len(actual) != len(set(actual)) or set(actual) != set(context_ids):
        raise ValueError('Missing, extra or duplicate citation judgment')
    return parsed


def claim_verdict(pairs):
    verdicts = [p['effective_verdict'] for p in pairs]
    if not verdicts:
        return 'citation_missing'
    if 'entailed' in verdicts:
        return 'entailed'
    if 'partially_entailed' in verdicts:
        return 'partially_entailed'
    if 'cannot_determine' in verdicts:
        return 'cannot_determine'
    return 'not_entailed'


def human_review_event(record, claim_id, reviewer, verdict, notes, reviewed_at, citation_judgments=None):
    if not reviewer.strip() or not reviewed_at or verdict not in set(VERDICTS) - {'citation_missing'}:
        raise ValueError('Human reviewer, timestamp and allowed verdict required')
    claim = next((c for c in record['claims'] if c['claim_id'] == claim_id), None)
    if claim is None or not verify_claim(claim, record['answer']):
        raise ValueError('Unknown or altered claim snapshot')
    if citation_judgments is not None:
        expected=set(claim['audit_citation_set'])
        if set(citation_judgments)!=expected or any(v not in set(VERDICTS)-{'citation_missing'} for v in citation_judgments.values()):
            raise ValueError('Each declared citation needs an explicit human judgment')
    return {'answer_id': record['answer_id'], 'claim_id': claim_id, 'reviewer': reviewer.strip(),
            'verdict': verdict, 'notes': notes, 'reviewed_at': reviewed_at,
            'answer_sha256': record['answer_sha256'], 'claim_text_sha256': claim['claim_text_sha256'],
            'review_source': 'human', 'human_verified': True,
            'citation_judgments':citation_judgments}


def human_no_assertion_event(record, reviewer, notes, reviewed_at):
    if record['claims'] or not reviewer.strip() or not notes.strip() or not reviewed_at:
        raise ValueError('Explicit human notes/reviewer required for a no-assertion output')
    return {'answer_id':record['answer_id'],'claim_id':None,'review_scope':'answer_no_assertion',
        'reviewer':reviewer.strip(),'notes':notes,'reviewed_at':reviewed_at,
        'verdict':'cannot_determine','answer_sha256':record['answer_sha256'],
        'review_source':'human','human_verified':True,'claim_support_verified':False}


def edge_subset(rows, count=60):
    # Every model uses these question IDs; select from immutable Gemma G1 inputs.
    pool = [r for r in rows if r['generator'] == MODELS[0] and r['condition'] == 'e4_top5']
    lengths = sorted(sum(len(t) for t in r['contexts']) for r in pool)
    cuts = (lengths[(len(lengths)-1)//3], lengths[2*(len(lengths)-1)//3])
    def bands(r):
        length = sum(len(t) for t in r['contexts'])
        band = 'short' if length <= cuts[0] else ('medium' if length <= cuts[1] else 'long')
        return (band, r.get('species') or 'unknown', r.get('category') or 'unknown',
                'hit' if r['required_evidence_complete_in_top5'] else 'miss', r.get('difficulty'), r['query_style'])
    selected = []
    for style in ('direct', 'paraphrase', 'contextual'):
        selected.extend(coverage_sample([r for r in pool if r['query_style'] == style], count//3,
                                       'phase18_edge_v1', bands))
    return selected, cuts


def shortlist_status(name, schema_rate, *, judge_conflict, independent_ready=False,
                     human_claim_reviews=0, human_completed_outputs=0, faithfulness=None):
    """Eligibility gates, no weighted score and no automatic winner."""
    if judge_conflict and not independent_ready:
        return 'evaluation_unresolved'
    if schema_rate < .95:
        return 'low_priority'
    if schema_rate < .99 or human_claim_reviews == 0 or human_completed_outputs < 48 or not independent_ready:
        return 'conditional_candidate'
    return 'strong_candidate' if faithfulness is not None and faithfulness >= .8 else 'conditional_candidate'


def agreement(pairs):
    # Null when absent/constant: never invent an independent judge score.
    if not pairs:
        return dict(n=0, pearson=None, spearman=None, mean_absolute_difference=None,
                    score_difference_distribution=[])
    x, y = zip(*pairs)
    def corr(a, b):
        ma, mb = statistics.fmean(a), statistics.fmean(b)
        va = sum((v-ma)**2 for v in a); vb = sum((v-mb)**2 for v in b)
        return sum((u-ma)*(v-mb) for u,v in zip(a,b)) / math.sqrt(va*vb) if va and vb else None
    def ranks(v):
        return [statistics.fmean([i+1 for i,z in enumerate(sorted(v)) if z == q]) for q in v]
    return dict(n=len(x), pearson=corr(x,y), spearman=corr(ranks(x),ranks(y)),
                mean_absolute_difference=statistics.fmean(abs(a-b) for a,b in pairs),
                score_difference_distribution=[b-a for a,b in pairs],
                threshold_agreement=statistics.fmean((a>=.5)==(b>=.5) for a,b in pairs))
