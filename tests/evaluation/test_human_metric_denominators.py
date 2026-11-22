import tempfile
import unittest
from src.evaluation.human_support.core import support_summary, latest_events
from src.evaluation.human_support.history import ReviewStore, primary_state
from tests.evaluation.human_support_fixtures import record,submission,register


class DenominatorTest(unittest.TestCase):
    def test_no_reviews_rates_unavailable_not_zero(self):
        s=support_summary([],[])
        self.assertIsNone(s['human_fully_supported_claim_rate'])
        self.assertIsNone(s['human_provenance_validity'])
        self.assertEqual(s['n_reviewed_claims'],0)

    def test_revisions_not_double_counted(self):
        with tempfile.TemporaryDirectory() as td:
            r=record();store=ReviewStore(td,[r]);register(store)
            store.submit('A_test','K_test','R_test',submission(r))
            store.submit('A_test','K_test','R_test',submission(r,'not_supported','compound'))
            progress,cs,ps=primary_state([r],store.read());s=support_summary(cs,ps)
            self.assertEqual(s['n_reviewed_claims'],1)
            self.assertEqual(s['atomicity_issue_count'],1)
            self.assertEqual(s['human_unsupported_by_context_rate'],1)
            self.assertEqual(progress['human_review_events'],2)
            self.assertEqual(progress['claims_reviewed'],1)

    def test_no_claim_output_requires_human_inspection(self):
        with tempfile.TemporaryDirectory() as td:
            r=record();r['claims']=[];store=ReviewStore(td,[r]);register(store)
            self.assertEqual(primary_state([r],store.read())[0]['outputs_reviewed'],0)
            store.submit_no_claim_output('A_test','R_test','synthetic inspection',True)
            p,cs,ps=primary_state([r],store.read())
            self.assertEqual(p['outputs_reviewed'],1)
            self.assertEqual(p['claims_reviewed'],0)
            self.assertFalse(p['primary_review_complete'])
