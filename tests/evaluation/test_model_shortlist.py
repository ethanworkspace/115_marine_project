import unittest
from src.evaluation.validity.core import shortlist_status


class ShortlistTest(unittest.TestCase):
    def test_conflict_unresolved(self):
        self.assertEqual(shortlist_status('qwen',1,judge_conflict=True),'evaluation_unresolved')

    def test_no_strong_without_independence(self):
        self.assertEqual(shortlist_status('gemma',1,judge_conflict=False,faithfulness=.9),'conditional_candidate')

    def test_reliability_low_priority(self):
        self.assertEqual(shortlist_status('deepseek',.94,judge_conflict=False),'low_priority')

    def test_strong_gate(self):
        self.assertEqual(shortlist_status('g',1,judge_conflict=False,independent_ready=True,
            human_claim_reviews=48,human_completed_outputs=48,faithfulness=.9),'strong_candidate')

    def test_one_human_claim_not_enough(self):
        self.assertEqual(shortlist_status('g',1,judge_conflict=False,independent_ready=True,
            human_claim_reviews=1,faithfulness=.9),'conditional_candidate')
