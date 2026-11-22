import unittest

from src.evaluation.phase20_protocol import independent_judge_independent


class IndependentJudgeTests(unittest.TestCase):
    def test_judge_must_not_match_any_candidate_digest(self):
        models = [{"digest": "m1"}, {"digest": "m2"}, {"digest": "m3"}, {"digest": "m4"}]
        self.assertTrue(independent_judge_independent("judge", models))
        self.assertFalse(independent_judge_independent("m2", models))
        self.assertFalse(independent_judge_independent(None, models))


if __name__ == "__main__":
    unittest.main()
