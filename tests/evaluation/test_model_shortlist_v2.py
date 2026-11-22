import unittest
from src.evaluation.human_support.report import update_shortlist
from tests.evaluation.human_support_fixtures import previous_shortlist,CRITERIA


class ShortlistTest(unittest.TestCase):
    def test_no_review_carries_prior_without_relabeling_ai(self):
        old=previous_shortlist();new=update_shortlist(old,{},False,CRITERIA)
        self.assertEqual({m:r['status'] for m,r in old['models'].items()},
                         {m:r['status'] for m,r in new['models'].items()})
        self.assertIsNone(new['models']['gemma2:9b']['human_claim_citation_audit'])
        self.assertNotIn('citation_audit',new['models']['gemma2:9b'])
        self.assertFalse(new['final_edge_model_selected'])

    def test_no_composite_score(self):
        new=update_shortlist(previous_shortlist(),{},False,CRITERIA)
        self.assertTrue(new['no_composite_score'])
        self.assertTrue(all(r['reference_alignment_bias_possible'] for r in new['models'].values()))
