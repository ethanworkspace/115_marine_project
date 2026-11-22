import unittest

from src.evaluation.generation.contexts import build_e4_top5_contexts


class E4Top5ContextTests(unittest.TestCase):
    def test_exact_five_retrieval_chunks_in_rank_order(self):
        rows = [{"rank": i, "chunk_id": f"c{i}", "document_id": "d", "page": i} for i in range(1, 6)]
        corpus = {f"c{i}": {"chunk_id": f"c{i}", "document_id": "d", "page_start": i, "page_end": i,
                            "pages": [i], "text": f"text{i}", "retrieval_role": "retrieval", "duplicate_status": "none"}
                  for i in range(1, 6)}
        contexts = build_e4_top5_contexts({"question_id": "q"}, rows, corpus)
        self.assertEqual([row["chunk_id"] for row in contexts], [f"c{i}" for i in range(1, 6)])

    def test_rejects_short_top5(self):
        with self.assertRaises(ValueError):
            build_e4_top5_contexts({"question_id": "q"}, [], {})


if __name__ == "__main__":
    unittest.main()
