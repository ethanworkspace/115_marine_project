from __future__ import annotations

import importlib.util
import unittest

try:
    from .runtime_test_support import get_runtime
except ImportError:
    from runtime_test_support import get_runtime


@unittest.skipUnless(importlib.util.find_spec("torch"), "reranker runtime is installed only in .venv-reranker")
class RerankerCandidateIdentityTests(unittest.TestCase):
    def test_reranking_preserves_candidate_ids(self) -> None:
        runtime = get_runtime()
        candidates = [
            {"chunk_id": "c2", "rank": 2, "text": "Dissolved oxygen affects fish health."},
            {"chunk_id": "c1", "rank": 1, "text": "The fish pond has water."},
        ]
        reranked = runtime.rerank("How does oxygen affect fish?", candidates)
        self.assertEqual({row["chunk_id"] for row in reranked}, {"c1", "c2"})
        self.assertEqual(len(reranked), len(candidates))
        self.assertEqual([row["reranker_rank"] for row in reranked], [1, 2])


if __name__ == "__main__":
    unittest.main()
