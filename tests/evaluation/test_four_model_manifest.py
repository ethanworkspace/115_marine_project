import unittest

from src.evaluation.phase20_protocol import PHASE20_CANDIDATES


class FourModelManifestTests(unittest.TestCase):
    def test_exact_four_frozen_candidates(self):
        self.assertEqual(len(PHASE20_CANDIDATES), 4)
        self.assertEqual([m["runtime_name"] for m in PHASE20_CANDIDATES], [
            "deepseek-r1:7b", "qwen2.5-coder:7b", "deepseek-r1:8b", "gemma2:9b"
        ])


if __name__ == "__main__":
    unittest.main()
