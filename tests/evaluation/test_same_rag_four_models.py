import unittest

from src.evaluation.phase20_protocol import PHASE20_CANDIDATES


class SameRAGTests(unittest.TestCase):
    def test_all_four_models_share_one_candidate_set(self):
        self.assertEqual(len({m["runtime_name"] for m in PHASE20_CANDIDATES}), 4)
        self.assertEqual([m["model_id"] for m in PHASE20_CANDIDATES], ["M1", "M2", "M3", "M4"])


if __name__ == "__main__":
    unittest.main()
