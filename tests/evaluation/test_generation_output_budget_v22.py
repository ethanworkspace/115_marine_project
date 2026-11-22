from __future__ import annotations

import unittest

from src.evaluation.generation.ollama import GENERATION_OPTIONS
from src.evaluation.generation.protocol_v22 import MAX_OUTPUT_TOKENS, generation_options_v22


class GenerationOutputBudgetV22Tests(unittest.TestCase):
    def test_only_num_predict_changes_to_1024(self) -> None:
        actual = generation_options_v22()
        expected = dict(GENERATION_OPTIONS)
        expected["num_predict"] = 1024
        self.assertEqual(MAX_OUTPUT_TOKENS, 1024)
        self.assertEqual(actual, expected)
        self.assertEqual(GENERATION_OPTIONS["num_predict"], 768)


if __name__ == "__main__":
    unittest.main()
