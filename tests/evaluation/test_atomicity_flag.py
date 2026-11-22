import unittest
from src.evaluation.human_support.core import make_events
from tests.evaluation.human_support_fixtures import record,submission


class AtomicityTest(unittest.TestCase):
    def test_compound_flag_preserves_frozen_claim(self):
        r=record();text=r['claims'][0]['claim_text']
        c,p=make_events(r,'K_test',submission(r,atomicity='compound'),
            {'reviewer_id':'R','reviewer_role':'test','review_source':'human'},'2026-10-06T00:00:00+00:00','H1')
        self.assertTrue(c['new_value']['atomicity_issue'])
        self.assertEqual(r['claims'][0]['claim_text'],text)
        self.assertEqual(len(r['claims']),1)

    def test_nonfactual_retained_not_silently_removed(self):
        r=record();c,p=make_events(r,'K_test',submission(r,atomicity='not_factual'),
            {'reviewer_id':'R','reviewer_role':'test','review_source':'human'},'2026-10-06T00:00:00+00:00','H1')
        self.assertFalse(c['new_value']['atomicity_issue'])
        self.assertEqual(c['new_value']['atomicity'],'not_factual')
