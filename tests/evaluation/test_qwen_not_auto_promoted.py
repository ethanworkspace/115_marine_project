import unittest
from src.evaluation.human_support.report import update_shortlist
from tests.evaluation.human_support_fixtures import previous_shortlist,CRITERIA


class QwenPromotionTest(unittest.TestCase):
    def metrics(self):
        return {'qwen2.5-coder:7b':dict(n_reviewed_claims=19,outputs_reviewed=12,
            human_fully_supported_claim_rate=1,human_unsupported_by_context_rate=0,human_cannot_determine_rate=0)}

    def test_no_human_data_no_promotion(self):
        r=update_shortlist(previous_shortlist(),{},False,CRITERIA)
        self.assertEqual(r['models']['qwen2.5-coder:7b']['status'],'evaluation_unresolved')

    def test_partial_sample_even_perfect_not_promoted(self):
        r=update_shortlist(previous_shortlist(),self.metrics(),False,CRITERIA)
        self.assertEqual(r['models']['qwen2.5-coder:7b']['status'],'evaluation_unresolved')

    def test_supported_human_sample_only_conditional_not_strong(self):
        r=update_shortlist(previous_shortlist(),self.metrics(),True,CRITERIA)
        q=r['models']['qwen2.5-coder:7b']
        self.assertEqual(q['status'],'conditional_candidate')
        self.assertTrue(q['independent_generation_quality_unresolved'])

    def test_cannot_determine_gate_not_ignored(self):
        h=self.metrics();h['qwen2.5-coder:7b']['human_cannot_determine_rate']=.5
        r=update_shortlist(previous_shortlist(),h,True,CRITERIA)
        self.assertEqual(r['models']['qwen2.5-coder:7b']['status'],'evaluation_unresolved')
