import unittest
from src.evaluation.validity.core import independent_candidates


class IndependentJudgeTest(unittest.TestCase):
    def test_generator_digest_rejected_even_alias(self):
        r=independent_candidates([{'name':'alias','digest':'same','capabilities':['completion']}],['same'])
        self.assertFalse(r[0]['independent_eligible'])

    def test_embedding_not_judge(self):
        r=independent_candidates([{'digest':'new','capabilities':['embedding']}],['same'])
        self.assertFalse(r[0]['independent_eligible'])

    def test_distinct_completion_eligible(self):
        r=independent_candidates([{'digest':'new','capabilities':['completion']}],['same'])
        self.assertTrue(r[0]['independent_eligible'])
