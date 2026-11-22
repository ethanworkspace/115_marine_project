import unittest

from src.evaluation.phase20_1_protocol import judge_is_independent


class JudgeConflictTests(unittest.TestCase):
    def test_candidate_digest_is_not_independent(self):
        digest = "d" * 64
        self.assertFalse(judge_is_independent(digest, ["a" * 64, digest]))


if __name__ == "__main__":
    unittest.main()
