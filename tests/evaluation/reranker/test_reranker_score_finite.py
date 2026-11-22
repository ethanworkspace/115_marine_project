from __future__ import annotations

import importlib.util
import math
import unittest

try:
    from .runtime_test_support import get_runtime
except ImportError:
    from runtime_test_support import get_runtime


@unittest.skipUnless(importlib.util.find_spec("torch"), "reranker runtime is installed only in .venv-reranker")
class RerankerFiniteScoreTests(unittest.TestCase):
    def test_scores_are_finite(self) -> None:
        runtime = get_runtime()
        values = runtime.score_pairs(
            "What should be checked in pond water?",
            ["Dissolved oxygen should be monitored.", "A fish disease can affect feeding."],
        )
        self.assertEqual(len(values), 2)
        self.assertTrue(all(math.isfinite(value) for value in values))


if __name__ == "__main__":
    unittest.main()
