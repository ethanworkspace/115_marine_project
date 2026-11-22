"""Append-only, hash-chained transactions with recoverable append-only projections."""
from __future__ import annotations

import copy
import json
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .core import make_events, object_digest, latest_events, validate_submission


def read_jsonl(path):
    p = Path(path)
    if not p.exists():
        return []
    # A malformed/incomplete line is a hard error; never drop evidence history silently.
    return [json.loads(line) for line in p.read_text(encoding='utf-8').splitlines() if line.strip()]


def append_row(path, row):
    with Path(path).open('a', encoding='utf-8', newline='\n') as f:
        f.write(json.dumps(row, ensure_ascii=False, sort_keys=True)+'\n')
        f.flush()
        os.fsync(f.fileno())


@contextmanager
def file_lock(path):
    """Serialize writers on Windows and POSIX without another package."""
    p = Path(path);p.parent.mkdir(parents=True, exist_ok=True)
    with p.open('a+b') as f:
        if f.seek(0, os.SEEK_END) == 0:
            f.write(b'0');f.flush()
        f.seek(0)
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            f.seek(0)
            if os.name == 'nt':
                msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)


class ReviewStore:
    def __init__(self, folder, records, second_reviewer_claim_ids=()):
        self.folder = Path(folder)
        self.records = {r['answer_id']: r for r in records}
        self.claim_records = {c['claim_id']: r for r in records for c in r['claims']}
        self.second_claims = set(second_reviewer_claim_ids)
        if not self.second_claims <= set(self.claim_records):
            raise ValueError('Second-reviewer assignment contains unknown claim')
        self.folder.mkdir(parents=True, exist_ok=True)
        self.lock = self.folder / 'human_history.lock'
        # Never truncate existing files.
        for name in ('review_transactions.jsonl', 'human_claim_reviews.jsonl',
                     'human_citation_reviews.jsonl', 'human_output_reviews.jsonl', 'human_reviewers.jsonl'):
            p = self.folder / name
            try:
                p.open('x', encoding='utf-8').close()
            except FileExistsError:
                pass

    def reviewers(self):
        rows = read_jsonl(self.folder/'human_reviewers.jsonl')
        ids, slots = set(), set()
        for r in rows:
            if r['reviewer_id'] in ids or r['assignment'] in slots or r['review_source'] != 'human':
                raise ValueError('Reviewer roster integrity error')
            ids.add(r['reviewer_id']);slots.add(r['assignment'])
        return rows

    def register(self, reviewer_id, reviewer_role, assignment, human_confirmed):
        if not isinstance(reviewer_id, str) or not isinstance(reviewer_role, str):
            raise ValueError('Human reviewer ID/role must be text')
        if not reviewer_id.strip() or not reviewer_role.strip() or human_confirmed is not True:
            raise ValueError('Human reviewer must explicitly register ID and role')
        if assignment not in ('primary', 'second'):
            raise ValueError('Unknown reviewer assignment')
        if assignment == 'second' and not self.second_claims:
            raise ValueError('No predeclared second-reviewer subset')
        with file_lock(self.lock):
            rows = self.reviewers()
            existing = next((r for r in rows if r['reviewer_id']==reviewer_id.strip()), None)
            if existing:
                if existing['reviewer_role'] != reviewer_role.strip() or existing['assignment'] != assignment:
                    raise ValueError('Existing reviewer identity/assignment is immutable')
                return existing
            if any(r['assignment'] == assignment for r in rows):
                raise ValueError('Assignment already belongs to another reviewer')
            if assignment == 'second' and not any(r['assignment']=='primary' for r in rows):
                raise ValueError('Register primary reviewer before optional second reviewer')
            r = dict(reviewer_id=reviewer_id.strip(), reviewer_role=reviewer_role.strip(),
                     assignment=assignment, review_source='human', timestamp=datetime.now(timezone.utc).isoformat())
            append_row(self.folder/'human_reviewers.jsonl', r)
            return r

    def _transactions(self):
        rows = read_jsonl(self.folder/'review_transactions.jsonl')
        previous = None
        for i, row in enumerate(rows, 1):
            data = {k:v for k,v in row.items() if k != 'transaction_sha256'}
            if (row['sequence'] != i or row['previous_transaction_sha256'] != previous
                    or row['transaction_sha256'] != object_digest(data)):
                raise ValueError('Human transaction hash chain corrupted')
            previous = row['transaction_sha256']
        return rows

    def _sync_projections(self, transactions):
        fields = {'human_claim_reviews.jsonl':'claim_event',
                  'human_citation_reviews.jsonl':'pair_events',
                  'human_output_reviews.jsonl':'output_event'}
        for filename, field in fields.items():
            expected = []
            for t in transactions:
                x = t.get(field)
                expected.extend(x if isinstance(x, list) else ([x] if x else []))
            stored = read_jsonl(self.folder/filename)
            if stored != expected[:len(stored)]:
                raise ValueError('Human history projection changed or contains unknown event')
            # A journal commit survived but projection write did not: append missing events only.
            for e in expected[len(stored):]:
                append_row(self.folder/filename, e)

    def _validate_events(self, transactions):
        roster = {r['reviewer_id']:r for r in self.reviewers()}
        claims, pairs, outputs = [], [], []
        for t in transactions:
            rid = t['reviewer_id']
            if rid not in roster:
                raise ValueError('Unregistered human event')
            if t['kind'] == 'claim_review':
                record = self.records.get(t['answer_id'])
                if record is None:
                    raise ValueError('Human event not in frozen audit')
                oldc = latest_events(claims, 'claim_id').get((rid, t['claim_id']))
                oldp = {k[1]:v for k,v in latest_events(pairs, 'pair_id').items() if k[0]==rid}
                ce, pe = make_events(record, t['claim_id'], t['submission'], roster[rid],
                                     t['timestamp'], t['transaction_id'], {'claim':oldc, 'pairs':oldp})
                if ce != t['claim_event'] or pe != t['pair_events']:
                    raise ValueError('Human event previous/new values or frozen provenance changed')
                if roster[rid]['assignment']=='second' and t['claim_id'] not in self.second_claims:
                    raise ValueError('Second reviewer reviewed an unassigned claim')
                claims.append(ce);pairs.extend(pe)
            elif t['kind'] == 'output_review':
                record = self.records.get(t['answer_id'])
                if record is None or record['claims'] or roster[rid]['assignment'] != 'primary':
                    raise ValueError('Output-only review is limited to frozen no-claim outputs')
                e = t['output_event']
                prior = next((x for x in reversed(outputs) if x['answer_id']==record['answer_id'] and x['reviewer_id']==rid), None)
                expected = self._output_event(record, roster[rid], e['new_value']['notes'], t['timestamp'], t['transaction_id'], prior)
                if e != expected:
                    raise ValueError('Output review integrity error')
                outputs.append(e)
            else:
                raise ValueError('Unknown human history transaction')
        return claims, pairs, outputs

    def read(self):
        with file_lock(self.lock):
            ts = self._transactions()
            claims, pairs, outputs = self._validate_events(ts)
            self._sync_projections(ts)
            return dict(transactions=ts, claims=claims, pairs=pairs, outputs=outputs, reviewers=self.reviewers())

    def _commit(self, tx, transactions):
        tx.update(sequence=len(transactions)+1,
                  previous_transaction_sha256=transactions[-1]['transaction_sha256'] if transactions else None)
        tx['transaction_sha256'] = object_digest(tx)
        append_row(self.folder/'review_transactions.jsonl', tx)
        self._sync_projections(transactions+[tx])
        return tx

    def submit(self, answer_id, claim_id, reviewer_id, submission):
        with file_lock(self.lock):
            roster = {r['reviewer_id']:r for r in self.reviewers()}
            if reviewer_id not in roster:
                raise ValueError('Human reviewer must register before submitting')
            reviewer = roster[reviewer_id]
            if reviewer['assignment']=='second' and claim_id not in self.second_claims:
                raise ValueError('Claim outside predeclared second-reviewer subset')
            record = self.records.get(answer_id)
            if record is None:
                raise ValueError('Unknown frozen answer')
            validate_submission(record, claim_id, submission)
            transactions = self._transactions()
            claims, pairs, _ = self._validate_events(transactions)
            self._sync_projections(transactions)
            oldc = latest_events(claims, 'claim_id').get((reviewer_id, claim_id))
            oldp = {k[1]:v for k,v in latest_events(pairs, 'pair_id').items() if k[0]==reviewer_id}
            timestamp = datetime.now(timezone.utc).isoformat()
            txid = f'H{len(transactions)+1:08d}'
            ce, pe = make_events(record, claim_id, submission, reviewer, timestamp, txid, {'claim':oldc, 'pairs':oldp})
            tx = dict(transaction_id=txid, kind='claim_review', answer_id=answer_id, claim_id=claim_id,
                      reviewer_id=reviewer_id, timestamp=timestamp, submission=copy.deepcopy(submission),
                      claim_event=ce, pair_events=pe)
            return self._commit(tx, transactions)

    @staticmethod
    def _output_event(record, reviewer, notes, timestamp, txid, previous):
        return dict(event_id=txid+'_output', answer_id=record['answer_id'], question_id=record['question_id'],
                    reviewer_id=reviewer['reviewer_id'], reviewer_role=reviewer['reviewer_role'], review_source='human',
                    timestamp=timestamp, transaction_id=txid, answer_sha256=record['answer_sha256'],
                    previous_event_id=previous['event_id'] if previous else None,
                    previous_value=previous['new_value'] if previous else None,
                    new_value={'notes':notes, 'no_frozen_primary_claim':True, 'claim_support_verified':False})

    def submit_no_claim_output(self, answer_id, reviewer_id, notes, human_confirmed):
        if not isinstance(notes, str) or not notes.strip() or human_confirmed is not True:
            raise ValueError('Explicit human inspection and notes required')
        with file_lock(self.lock):
            roster = {r['reviewer_id']:r for r in self.reviewers()}
            if reviewer_id not in roster or roster[reviewer_id]['assignment'] != 'primary':
                raise ValueError('Primary reviewer required for no-claim output inspection')
            record = self.records.get(answer_id)
            if record is None or record['claims']:
                raise ValueError('Not a frozen no-claim output')
            ts = self._transactions();_,_,outputs = self._validate_events(ts)
            old = next((x for x in reversed(outputs) if x['answer_id']==answer_id and x['reviewer_id']==reviewer_id), None)
            timestamp = datetime.now(timezone.utc).isoformat();txid = f'H{len(ts)+1:08d}'
            e = self._output_event(record, roster[reviewer_id], notes.strip(), timestamp, txid, old)
            return self._commit(dict(transaction_id=txid, kind='output_review', answer_id=answer_id,
                                     reviewer_id=reviewer_id, timestamp=timestamp, output_event=e), ts)


def primary_state(records, state):
    primary = next((r for r in state['reviewers'] if r['assignment']=='primary'), None)
    rid = primary['reviewer_id'] if primary else None
    claims = [v for (r,_),v in latest_events(state['claims'], 'claim_id').items() if r==rid]
    pairs = [v for (r,_),v in latest_events(state['pairs'], 'pair_id').items() if r==rid]
    output_checks = {v['answer_id'] for v in state['outputs'] if v['reviewer_id']==rid}
    reviewed = {c['claim_id'] for c in claims}
    complete = [r['answer_id'] for r in records
                if (r['claims'] and all(c['claim_id'] in reviewed for c in r['claims']))
                or (not r['claims'] and r['answer_id'] in output_checks)]
    total_claims = sum(len(r['claims']) for r in records)
    total_pairs = sum(len(c['audit_citation_set']) for r in records for c in r['claims'])
    progress = dict(target_outputs=len(records), target_claims=total_claims, target_pairs=total_pairs,
                    outputs_reviewed=len(complete), claims_reviewed=len(claims), pairs_reviewed=len(pairs),
                    output_completion_rate=len(complete)/len(records) if records else None,
                    claim_completion_rate=len(claims)/total_claims if total_claims else None,
                    pair_completion_rate=len(pairs)/total_pairs if total_pairs else None,
                    primary_review_complete=bool(total_claims) and len(claims)==total_claims
                        and len(pairs)==total_pairs and len(complete)==len(records),
                    completed_answer_ids=complete, reviewed_claim_ids=sorted(reviewed),
                    outputs_without_frozen_claims=sum(not r['claims'] for r in records),
                    human_review_events=len(state['transactions']), reviewers=state['reviewers'])
    return progress, claims, pairs
