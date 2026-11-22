from __future__ import annotations

import importlib.util
import unittest

try:
    from .runtime_test_support import get_runtime
except ImportError:
    from runtime_test_support import get_runtime


@unittest.skipUnless(importlib.util.find_spec("torch"), "reranker runtime is installed only in .venv-reranker")
class RerankerDeterminismTests(unittest.TestCase):
    def test_repeated_scores_and_order_are_stable(self) -> None:
        runtime = get_runtime()
        candidates = [
            {"chunk_id": f"c{index}", "rank": index + 1, "text": f"Fish culture evidence record {index}."}
            for index in range(5)
        ]
        first_scores = runtime.score_pairs("Fish culture evidence", [row["text"] for row in candidates])
        second_scores = runtime.score_pairs("Fish culture evidence", [row["text"] for row in candidates])
        first = runtime.rerank("Fish culture evidence", candidates)
        second = runtime.rerank("Fish culture evidence", candidates)
        self.assertEqual(first_scores, second_scores)
        self.assertEqual([row["chunk_id"] for row in first], [row["chunk_id"] for row in second])


if __name__ == "__main__":
    unittest.main()
