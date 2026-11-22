"""Frozen input bridge; UI reads blind data only, reporting reads private data separately."""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

from .core import blind_view, digest, object_digest, pairs_for, validate_record
from .history import ReviewStore, read_jsonl

ROOT = Path(__file__).resolve().parents[3]
PHASE18 = ROOT/'reports/evaluation/validity/phase18'
OUT = ROOT/'reports/evaluation/validity/phase18_1'
SOURCE = PHASE18/'blind_audit_records_v2.jsonl'


def file_sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(1024*1024), b''):
            h.update(block)
    return h.hexdigest()


def freeze_write(path, data):
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError('Refusing to replace frozen Phase 18.1 input: '+str(path))
        return
    with path.open('xb') as f:
        f.write(data)


def second_reviewer_subset(records, private_rows, per_model=9):
    """Assign claims, not new outputs. No labels or disagreement outcomes are used."""
    metadata = {r['answer_id']:r for r in private_rows}
    claims = [(r, c) for r in records for c in r['claims']]
    selected = []
    for model in sorted({r['generator'] for r in private_rows}):
        pool = [(r,c) for r,c in claims if metadata[r['answer_id']]['generator']==model]
        counts = [Counter() for _ in range(4)]
        for _ in range(min(per_model, len(pool))):
            def strata(r):
                m = metadata[r['answer_id']]
                return (m['query_style'], m['category'], m.get('species') or 'unknown',
                        'hit' if m['required_evidence_complete_in_top5'] else 'miss')
            def key(rc):
                r,c = rc
                return (sum(counts[i][v] for i,v in enumerate(strata(r))),
                        digest('phase18.1_second_claims_v1|'+c['claim_id']))
            r,c = min(pool, key=key);pool.remove((r,c))
            for i,v in enumerate(strata(r)):
                counts[i][v] += 1
            selected.append(dict(claim_id=c['claim_id'], answer_id=r['answer_id']))
    return selected


def prepare():
    OUT.mkdir(parents=True, exist_ok=True)
    checksums = json.loads((PHASE18/'output_checksums.json').read_text(encoding='utf-8'))
    mismatches = [p for p,h in checksums.items() if file_sha(ROOT/p)!=h]
    if mismatches:
        raise ValueError('Phase 18 changed: '+str(mismatches))
    records = read_jsonl(SOURCE)
    ai = read_jsonl(PHASE18/'claim_citation_ai_audit.jsonl')
    private = read_jsonl(PHASE18/'claim_citation_sample.jsonl')
    if len({r['answer_id'] for r in records}) != len(records):
        raise ValueError('Duplicate frozen answer IDs')
    claims = {c['claim_id']:c for r in records for c in r['claims']}
    if len(claims) != sum(len(r['claims']) for r in records) or set(claims) != {c['claim_id'] for c in ai}:
        raise ValueError('Frozen claim inventory differs from AI audit')
    if {r['answer_id'] for r in records} != {r['answer_id'] for r in private}:
        raise ValueError('Private identity map does not cover exactly frozen outputs')
    corpus = {c['chunk_id']:c for c in read_jsonl(ROOT/'data/evaluation/corpus_v2.jsonl')}
    ai_map = {c['claim_id']:c for c in ai}
    private_map = {r['answer_id']:r for r in private}
    pairs = []
    for r in records:
        validate_record(r)
        if blind_view(r) != r or private_map[r['answer_id']]['answer_sha256'] != r['answer_sha256']:
            raise ValueError('Frozen blind record or private answer digest differs')
        for x in r['contexts']:
            c = corpus[x['chunk_id']]
            if c['text'] != x['text'] or c['document_id'] != x['document_id'] or not c['page_start'] <= x['page'] <= c['page_end']:
                raise ValueError('Frozen context differs from corpus provenance')
        for c in r['claims']:
            a = ai_map[c['claim_id']]
            if a['claim_text_sha256'] != c['claim_text_sha256'] or a['audit_citation_set'] != c['audit_citation_set']:
                raise ValueError('AI/frozen claim or citation list differs')
            ps = pairs_for(r,c)
            if [p['context_id'] for p in ps] != [p['context_id'] for p in a['citation_pairs']]:
                raise ValueError('Frozen citation pair order differs')
            for p, ap in zip(ps, a['citation_pairs']):
                for k in ('chunk_id','document_id','page'):
                    if p[k] != ap.get(k):
                        raise ValueError('Frozen pair provenance differs')
            pairs.extend(ps)
    counts = dict(outputs=len(records), primary_claims=len(claims), citation_pairs=len(pairs))
    if counts != dict(outputs=48, primary_claims=122, citation_pairs=310):
        raise ValueError('Phase 18.1 fixed audit count mismatch: '+str(counts))
    subset = second_reviewer_subset(records, private)
    if len(subset) != 36:
        raise ValueError('Optional reviewer subset must contain 36 frozen claims')
    paths = [SOURCE, PHASE18/'claim_citation_ai_audit.jsonl', PHASE18/'claim_citation_sample.jsonl',
             PHASE18/'model_shortlist.json', PHASE18/'audit_execution_protocol_v2.json',
             PHASE18/'output_checksums.json', PHASE18/'edge_benchmark_subset_v1.jsonl',
             ROOT/'data/evaluation/corpus_v2.jsonl']
    hashes = {p.relative_to(ROOT).as_posix():file_sha(p) for p in paths}
    manifest = dict(phase='18.1', protocol='blinded_human_claim_support_v1',
        audit_type='Human-reviewed Claim-Citation Support Audit', human_gold_benchmark=False,
        parent_phase18_immutable=True, protected_inputs=hashes, frozen_counts=counts,
        identity_inventory_sha256=object_digest([dict(answer_id=r['answer_id'], question_id=r['question_id'],
            answer_sha256=r['answer_sha256'], claims=r['claims'], contexts=r['contexts']) for r in records]),
        no_claim_reextraction=True, no_output_resampling=True, no_generator_execution=True,
        no_judge_execution=True, no_ai_prefilled_human_labels=True,
        human_review_requested_this_round=False,
        user_direction='Continue without conducting review; implement workflow and retain pending human labels.',
        reporting_deblinding_rule='All 122 primary claims, 310 pairs and 48 outputs reviewed by primary human',
        primary_reviewer_assignment='Explicit first primary registration; ID and role cannot be auto-created',
        second_reviewer_claim_ids=[x['claim_id'] for x in subset],
        second_reviewer_rule={'size':36, 'per_generator':9,
            'strata':['query_style','category','species','retrieval_hit_miss'],
            'selection':'least-covered summed counts; SHA256 tie-break phase18.1_second_claims_v1',
            'fixed_before_review':True, 'no_disagreement_selection':True},
        shortlist_criteria={'no_composite_score':True, 'no_automatic_strong_promotion':True,
            'qwen_conditional_min_fully_supported':0.80,
            'qwen_conditional_max_unsupported_by_context':0.05,
            'qwen_conditional_max_cannot_determine':0.10,
            'qwen_requires_complete_primary_sample_and_12_reviewed_outputs':True,
            'note':'Predeclared necessary human citation conditions only, not overall quality superiority'},
        primary_metric_denominator='Frozen 122 claims; completed-review rates also report their actual n',
        history='Hash-chained append-only transactions; append-only claim/citation projections; previous/new values retained')
    freeze_write(OUT/'experiment_manifest.json', (json.dumps(manifest,ensure_ascii=False,indent=2)+'\n').encode('utf-8'))
    freeze_write(OUT/'frozen_pair_inventory.jsonl', ''.join(json.dumps(p,ensure_ascii=False,sort_keys=True)+'\n' for p in pairs).encode('utf-8'))
    freeze_write(OUT/'second_reviewer_assignment.jsonl', ''.join(json.dumps(p,sort_keys=True)+'\n' for p in subset).encode('utf-8'))
    # Exact byte copy preserves all original fields, ordering and IDs, not a re-extraction.
    freeze_write(OUT/'blind_audit_records.jsonl', SOURCE.read_bytes())
    ReviewStore(OUT, records, manifest['second_reviewer_claim_ids'])
    return manifest


def load_blind(folder=OUT):
    """Only public allowlisted records and the frozen manifest; no AI/private-score reads."""
    folder = Path(folder)
    manifest = json.loads((folder/'experiment_manifest.json').read_text(encoding='utf-8'))
    expected = manifest['protected_inputs'][SOURCE.relative_to(ROOT).as_posix()]
    if file_sha(SOURCE) != expected or file_sha(folder/'blind_audit_records.jsonl') != expected:
        raise ValueError('Frozen blind audit checksum changed')
    records = read_jsonl(folder/'blind_audit_records.jsonl')
    for r in records:
        validate_record(r)
        if blind_view(r) != r:
            raise ValueError('Private fields appeared in public blind audit')
    return records, manifest


def report():
    from .report import build_reports, write_reports
    records, manifest = load_blind()
    for path, expected in manifest['protected_inputs'].items():
        if file_sha(ROOT/path) != expected:
            raise ValueError('Protected audit input checksum changed: '+path)
    state = ReviewStore(OUT, records, manifest['second_reviewer_claim_ids']).read()
    ai = {}
    source_ai = {c['claim_id']:c for c in read_jsonl(PHASE18/'claim_citation_ai_audit.jsonl')}
    for r in records:
        for c in r['claims']:
            for pair, original in zip(pairs_for(r,c), source_ai[c['claim_id']]['citation_pairs']):
                ai[pair['pair_id']] = original
    reports = build_reports(records, state, read_jsonl(PHASE18/'claim_citation_sample.jsonl'), ai,
        json.loads((PHASE18/'model_shortlist.json').read_text(encoding='utf-8')), manifest)
    write_reports(OUT, reports)
    return reports
