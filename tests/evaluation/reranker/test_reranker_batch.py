from __future__ import annotations

import importlib.util
import math
import unittest

try:
    from .runtime_test_support import get_runtime
except ImportError:
    from runtime_test_support import get_runtime


@unittest.skipUnless(importlib.util.find_spec("torch"), "reranker runtime is installed only in .venv-reranker")
class RerankerBatchTests(unittest.TestCase):
    def test_batch_larger_than_configured_batch_size_scores_every_pair(self) -> None:
        runtime = get_runtime()
        passages = [f"Pond management record {index}: monitor water quality and fish behavior." for index in range(7)]
        values = runtime.score_pairs("What should an operator monitor?", passages)
        self.assertEqual(len(values), len(passages))
        self.assertTrue(all(math.isfinite(value) for value in values))


if __name__ == "__main__":
    unittest.main()
