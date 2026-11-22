"""Pure validation and support taxonomy for actual human submissions."""
from __future__ import annotations

import copy
import hashlib
import json
from collections import Counter
from datetime import datetime

SUPPORT = ('fully_supported', 'partially_supported', 'not_supported', 'cannot_determine')
ELSEWHERE = ('supported_elsewhere', 'partially_supported_elsewhere',
             'not_supported_anywhere', 'cannot_determine', 'not_applicable')
ATOMICITY = ('atomic', 'compound', 'not_factual', 'ambiguous')
PROVENANCE = ('valid', 'invalid', 'cannot_determine')
RECORD_KEYS = ('answer_id', 'question_id', 'question', 'answer', 'answer_sha256',
               'citations', 'claims', 'contexts')
CLAIM_KEYS = ('answer_id', 'claim_id', 'claim_text', 'claim_text_sha256',
              'answer_start', 'answer_end', 'context_heading', 'citation_binding',
              'linked_citations', 'answer_level_citations', 'audit_citation_set',
              'warnings', 'extraction_method', 'atomicity_human_verified')
CONTEXT_KEYS = ('context_id', 'chunk_id', 'document_id', 'page', 'content_checksum', 'text')


def digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def object_digest(value):
    return digest(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')))


def blind_view(record):
    """Allowlist, not a blacklist: private identity/judge fields cannot reach the UI."""
    row = {k: copy.deepcopy(record[k]) for k in RECORD_KEYS if k in record}
    row['claims'] = [{k: copy.deepcopy(c[k]) for k in CLAIM_KEYS if k in c}
                     for c in record['claims']]
    row['contexts'] = [{k: copy.deepcopy(c[k]) for k in CONTEXT_KEYS if k in c}
                       for c in record['contexts']]
    return row


def validate_record(record):
    if digest(record['answer']) != record['answer_sha256']:
        raise ValueError('Frozen answer checksum mismatch')
    claims, contexts = set(), set()
    for c in record['claims']:
        if c['claim_id'] in claims or c['answer_id'] != record['answer_id']:
            raise ValueError('Duplicate/mismatched frozen claim')
        claims.add(c['claim_id'])
        if (record['answer'][c['answer_start']:c['answer_end']] != c['claim_text']
                or digest(c['claim_text']) != c['claim_text_sha256']):
            raise ValueError('Frozen claim span/checksum mismatch')
    for c in record['contexts']:
        if c['context_id'] in contexts or digest(c['text']) != c['content_checksum']:
            raise ValueError('Frozen context identity/checksum mismatch')
        contexts.add(c['context_id'])
        if not c['chunk_id'] or not c['document_id'] or not isinstance(c['page'], int):
            raise ValueError('Missing page/chunk/document provenance')
    return True


def pairs_for(record, claim):
    """Freeze ordinal as well as ID; repeated original citations are not deduplicated."""
    contexts = {c['context_id']: c for c in record['contexts']}
    pairs = []
    for ordinal, cid in enumerate(claim['audit_citation_set'], 1):
        c = contexts.get(cid)
        pairs.append(dict(pair_id='P'+object_digest([record['answer_id'], claim['claim_id'], ordinal, cid])[:24],
                          answer_id=record['answer_id'], question_id=record['question_id'],
                          claim_id=claim['claim_id'], citation_ordinal=ordinal, context_id=cid,
                          chunk_id=c['chunk_id'] if c else None,
                          document_id=c['document_id'] if c else None,
                          page=c['page'] if c else None,
                          content_checksum=c['content_checksum'] if c else None))
    return pairs


def attribution(support, elsewhere):
    if support not in SUPPORT or elsewhere not in ELSEWHERE:
        raise ValueError('Unknown human support label')
    if support == 'fully_supported':
        return 'correct_citation_support'
    if support == 'partially_supported':
        return 'partial_citation_support'
    if support == 'cannot_determine':
        return 'cannot_determine'
    if elsewhere == 'supported_elsewhere':
        return 'citation_selection_failure'
    if elsewhere == 'not_supported_anywhere':
        return 'unsupported_by_provided_context'
    # Incomplete alternative evidence does not establish either full support or absence.
    return 'cannot_determine'


def validate_elsewhere(support, value, ids, allowed):
    if value not in ELSEWHERE or len(ids) != len(set(ids)) or not set(ids) <= set(allowed):
        raise ValueError('Invalid full-context support selection')
    if value == 'not_applicable' and support != 'fully_supported':
        raise ValueError('not_applicable requires fully supported cited evidence')
    if value in ('supported_elsewhere', 'partially_supported_elsewhere') and not ids:
        raise ValueError('Human must identify supporting alternative context IDs')
    if value not in ('supported_elsewhere', 'partially_supported_elsewhere') and ids:
        raise ValueError('Alternative IDs conflict with full-context support label')


def validate_submission(record, claim_id, submission):
    """No AI defaults, silent label filling or claim edits; all choices are explicit."""
    validate_record(record)
    claim = next((c for c in record['claims'] if c['claim_id'] == claim_id), None)
    if claim is None:
        raise ValueError('Unknown frozen claim')
    required = {'atomicity', 'cited_set_support', 'elsewhere_support', 'elsewhere_context_ids',
                'notes', 'citations', 'human_confirmed'}
    if set(submission) != required or submission['human_confirmed'] is not True:
        raise ValueError('Explicit human submission required; no AI or additional metadata')
    if submission['atomicity'] not in ATOMICITY or submission['cited_set_support'] not in SUPPORT:
        raise ValueError('Atomicity and cited-set support must be chosen by reviewer')
    if not isinstance(submission['notes'], str):
        raise ValueError('Notes must be text')
    expected = pairs_for(record, claim)
    decisions = submission['citations']
    if [x.get('pair_id') for x in decisions] != [x['pair_id'] for x in expected]:
        raise ValueError('All and only the frozen citation pairs must be reviewed in order')
    contexts = {c['context_id'] for c in record['contexts']}
    for d, p in zip(decisions, expected):
        if set(d) != {'pair_id', 'support', 'elsewhere_support', 'elsewhere_context_ids', 'provenance', 'notes'}:
            raise ValueError('Unexpected or missing citation review fields')
        if d['support'] not in SUPPORT or d['provenance'] not in PROVENANCE or not isinstance(d['notes'], str):
            raise ValueError('Every citation needs explicit support and provenance review')
        if p['chunk_id'] is None and (d['provenance'] == 'valid'
                                     or d['support'] in ('fully_supported', 'partially_supported')):
            raise ValueError('Unknown citation cannot have valid provenance or observed support')
        validate_elsewhere(d['support'], d['elsewhere_support'], d['elsewhere_context_ids'],
                           contexts - {p['context_id']})
    support = submission['cited_set_support']
    if any(d['support'] == 'fully_supported' for d in decisions) and support != 'fully_supported':
        raise ValueError('Cited-set review contradicts a fully supporting cited chunk')
    if support == 'fully_supported' and not any(
            d['support'] in ('fully_supported', 'partially_supported') for d in decisions):
        raise ValueError('Full cited-set support requires supporting citations')
    if support == 'partially_supported' and not any(
            d['support'] == 'partially_supported' for d in decisions):
        raise ValueError('Partial cited-set support requires partial cited evidence')
    validate_elsewhere(support, submission['elsewhere_support'], submission['elsewhere_context_ids'],
                       contexts - set(claim['audit_citation_set']))
    return claim, expected


def make_events(record, claim_id, submission, reviewer, timestamp, transaction_id, previous=None):
    claim, pairs = validate_submission(record, claim_id, submission)
    if (not reviewer.get('reviewer_id', '').strip() or not reviewer.get('reviewer_role', '').strip()
            or reviewer.get('review_source') != 'human'):
        raise ValueError('Registered human reviewer ID and role required')
    if datetime.fromisoformat(timestamp).tzinfo is None:
        raise ValueError('Review timestamp must include timezone')
    common = dict(answer_id=record['answer_id'], question_id=record['question_id'], claim_id=claim_id,
                  reviewer_id=reviewer['reviewer_id'], reviewer_role=reviewer['reviewer_role'],
                  review_source='human', timestamp=timestamp, transaction_id=transaction_id,
                  answer_sha256=record['answer_sha256'], claim_text_sha256=claim['claim_text_sha256'])
    prev_claim = (previous or {}).get('claim')
    current = {k: copy.deepcopy(submission[k]) for k in ('atomicity', 'cited_set_support',
              'elsewhere_support', 'elsewhere_context_ids', 'notes')}
    current.update(atomicity_issue=submission['atomicity'] == 'compound',
                   attribution_failure_type=attribution(submission['cited_set_support'], submission['elsewhere_support']))
    claim_event = {**common, 'event_id': transaction_id+'_claim',
                   'previous_event_id': prev_claim['event_id'] if prev_claim else None,
                   'previous_value': prev_claim['new_value'] if prev_claim else None, 'new_value': current}
    pair_events = []
    for p, d in zip(pairs, submission['citations']):
        old = (previous or {}).get('pairs', {}).get(p['pair_id'])
        value = {k: copy.deepcopy(d[k]) for k in ('support', 'elsewhere_support', 'elsewhere_context_ids', 'provenance', 'notes')}
        value['attribution_failure_type'] = attribution(d['support'], d['elsewhere_support'])
        pair_events.append({**common, **p, 'event_id': transaction_id+'_'+p['pair_id'],
                            'previous_event_id': old['event_id'] if old else None,
                            'previous_value': old['new_value'] if old else None, 'new_value': value})
    return claim_event, pair_events


def latest_events(events, key):
    rows = {}
    for e in events:
        if e.get('review_source') != 'human':
            continue
        rows[(e['reviewer_id'], e[key])] = e
    return rows


def support_summary(claims, pairs):
    """Main denominator: reviewed frozen claims, including compound/non-factual flags."""
    n, np = len(claims), len(pairs)
    labels = Counter(c['new_value']['cited_set_support'] for c in claims)
    reasons = Counter(c['new_value']['attribution_failure_type'] for c in claims)
    ratio = lambda a, b: a/b if b else None
    return dict(n_reviewed_claims=n, n_reviewed_pairs=np, support_counts=dict(labels),
                attribution_counts=dict(reasons),
                human_fully_supported_claim_rate=ratio(labels['fully_supported'], n),
                human_partially_supported_claim_rate=ratio(labels['partially_supported'], n),
                human_unsupported_cited_claim_rate=ratio(labels['not_supported'], n),
                human_cannot_determine_rate=ratio(labels['cannot_determine'], n),
                human_citation_selection_failure_rate=ratio(reasons['citation_selection_failure'], n),
                human_unsupported_by_context_rate=ratio(reasons['unsupported_by_provided_context'], n),
                human_provenance_validity=ratio(sum(p['new_value']['provenance']=='valid' for p in pairs), np),
                provenance_cannot_determine_count=sum(p['new_value']['provenance']=='cannot_determine' for p in pairs),
                atomicity_counts=dict(Counter(c['new_value']['atomicity'] for c in claims)),
                atomicity_issue_count=sum(c['new_value']['atomicity_issue'] for c in claims),
                denominators={'semantic_claim_rates': 'all reviewed frozen primary claims, no atomicity exclusions',
                              'provenance': 'all reviewed claim-citation pairs, including cannot_determine'},
                unsupported_definition='Not supported by this question\'s provided evidence; no assertion of real-world falsity')


def categorical_agreement(left, right, labels=SUPPORT):
    if len(left) != len(right):
        raise ValueError('Agreement observations must be paired')
    if any(v not in labels for v in left+right):
        raise ValueError('Unknown agreement label')
    n = len(left)
    matrix = {a: {b: sum(x==a and y==b for x,y in zip(left,right)) for b in labels} for a in labels}
    raw = sum(a==b for a,b in zip(left,right))/n if n else None
    lc, rc = Counter(left), Counter(right)
    pe = sum(lc[a]*rc[a] for a in labels)/(n*n) if n else None
    kappa = (raw-pe)/(1-pe) if n and pe != 1 else None
    return dict(n_paired=n, raw_agreement=raw, percent_agreement=raw*100 if n else None,
                cohen_kappa=kappa, confusion_matrix=matrix,
                kappa_limitation='Undefined for no pairs or constant agreement; class imbalance affects interpretation')


def ai_human_agreement(ai, human_pairs):
    mapping = {'entailed':'fully_supported', 'partially_entailed':'partially_supported',
               'not_entailed':'not_supported', 'cannot_determine':'cannot_determine'}
    left, right = [], []
    for h in human_pairs:
        value = ai.get(h['pair_id'])
        if value is None:
            raise ValueError('Human pair missing frozen AI comparison reference')
        left.append(mapping[value['effective_verdict']]);right.append(h['new_value']['support'])
    result = categorical_agreement(left, right)
    result.update(ai_false_support_candidate=sum(a=='fully_supported' and b=='not_supported' for a,b in zip(left,right)),
                  ai_false_unsupported_candidate=sum(a=='not_supported' and b=='fully_supported' for a,b in zip(left,right)),
                  ai_is_not_ground_truth=True, comparison_unit='claim-citation pair')
    return result
