import unittest
from src.evaluation.generation_models.core import judge_conflict

class JudgeConflictTests(unittest.TestCase):
    def test_artifact_same_despite_alias(self): self.assertTrue(judge_conflict({'name':'alias','digest':'x'},{'model_digest':'x'}))
    def test_different_artifact(self): self.assertFalse(judge_conflict({'digest':'y'},{'model_digest':'x'}))
    def test_unknown_not_verified_same(self): self.assertFalse(judge_conflict({'digest':None},{'model_digest':None}))
