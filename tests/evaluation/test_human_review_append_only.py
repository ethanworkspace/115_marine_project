import json
import tempfile
import unittest
from pathlib import Path
from src.evaluation.human_support.history import ReviewStore, read_jsonl, append_row
from tests.evaluation.human_support_fixtures import record, submission, register


class HistoryTest(unittest.TestCase):
    def test_revision_keeps_previous_bytes_and_values(self):
        with tempfile.TemporaryDirectory() as td:
            r=record();s=ReviewStore(td,[r]);register(s)
            s.submit('A_test','K_test','R_test',submission(r))
            p=Path(td)/'human_claim_reviews.jsonl';before=p.read_bytes()
            s.submit('A_test','K_test','R_test',submission(r,'not_supported'))
            self.assertTrue(p.read_bytes().startswith(before))
            rows=read_jsonl(p)
            self.assertEqual(rows[1]['previous_value'],rows[0]['new_value'])
            self.assertEqual(rows[0]['new_value']['cited_set_support'],'fully_supported')
            self.assertEqual(rows[1]['new_value']['cited_set_support'],'not_supported')
            self.assertEqual(len(s.read()['transactions']),2)

    def test_corrupt_hash_chain_fails_explicitly(self):
        with tempfile.TemporaryDirectory() as td:
            s=ReviewStore(td,[record()]);register(s)
            s.submit('A_test','K_test','R_test',submission())
            path=Path(td)/'review_transactions.jsonl';row=read_jsonl(path)[0]
            row['submission']['notes']='tampered'
            path.write_text(json.dumps(row)+'\n',encoding='utf-8')
            with self.assertRaises(ValueError):s.read()

    def test_unknown_projection_event_fails(self):
        with tempfile.TemporaryDirectory() as td:
            s=ReviewStore(td,[record()])
            append_row(Path(td)/'human_claim_reviews.jsonl',{'event_id':'unknown'})
            with self.assertRaises(ValueError):s.read()

    def test_commit_projection_interruption_is_append_recoverable(self):
        with tempfile.TemporaryDirectory() as td:
            s=ReviewStore(td,[record()]);register(s)
            original=s._sync_projections
            def fail_after_commit(ts):
                if ts:raise OSError('synthetic projection interruption')
                return original(ts)
            s._sync_projections=fail_after_commit
            with self.assertRaises(OSError):s.submit('A_test','K_test','R_test',submission())
            self.assertEqual(len(read_jsonl(Path(td)/'review_transactions.jsonl')),1)
            s._sync_projections=original
            self.assertEqual(len(s.read()['claims']),1)
            self.assertEqual(len(read_jsonl(Path(td)/'human_claim_reviews.jsonl')),1)

    def test_ai_or_undecided_submission_not_committed(self):
        with tempfile.TemporaryDirectory() as td:
            s=ReviewStore(td,[record()]);register(s)
            x=submission();x['human_confirmed']=False
            with self.assertRaises(ValueError):s.submit('A_test','K_test','R_test',x)
            x=submission();x['citations'][0]['support']=None
            with self.assertRaises(ValueError):s.submit('A_test','K_test','R_test',x)
            self.assertEqual(s.read()['transactions'],[])

    def test_second_reviewer_different_identity_and_assigned_only(self):
        with tempfile.TemporaryDirectory() as td:
            s=ReviewStore(td,[record()],['K_test']);register(s)
            with self.assertRaises(ValueError):register(s,'R_test','second')
            register(s,'R_second','second')
            s.submit('A_test','K_test','R_second',submission())
            self.assertEqual(len(s.read()['claims']),1)
