import unittest

from src.evaluation.grounded_baselines import retrieval_corpus, stable_sha256
from tests.evaluation.grounded_baseline_fixtures import corpus_rows


class SameCorpusTests(unittest.TestCase):
    def test_only_retrieval_canonical_chunks_survive(self):
        rows = corpus_rows()
        rows += [
            {**rows[0], "chunk_id": "parent", "canonical_chunk_id": "parent", "retrieval_role": "context_only"},
            {**rows[0], "chunk_id": "dup", "canonical_chunk_id": "c0", "duplicate_status": "exact_duplicate"},
            {**rows[0], "chunk_id": "excluded", "canonical_chunk_id": "excluded", "retrieval_role": "excluded"},
        ]
        selected = retrieval_corpus(rows)
        ids = [row["chunk_id"] for row in selected]
        self.assertEqual(ids, ["c0", "c1", "c2", "c3"])
        self.assertEqual(stable_sha256(ids), stable_sha256([row["chunk_id"] for row in retrieval_corpus(rows)]))


if __name__ == "__main__":
    unittest.main()
