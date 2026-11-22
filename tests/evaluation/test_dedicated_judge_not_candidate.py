import unittest
from src.evaluation.phase20_1r_protocol import judge_is_independent

class DedicatedJudgeTests(unittest.TestCase):
    def test_judge_digest_must_differ_from_every_candidate(self):
        candidates=[{"artifact_digest":"a"*64}]
        self.assertTrue(judge_is_independent({"artifact_digest":"b"*64,"is_candidate":False}, candidates))
        self.assertFalse(judge_is_independent({"artifact_digest":"a"*64,"is_candidate":False}, candidates))
