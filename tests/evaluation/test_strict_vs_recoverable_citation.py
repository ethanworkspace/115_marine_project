import unittest

from src.evaluation.generation.protocol_v2 import resolve_citations


class StrictRecoverableCitationTests(unittest.TestCase):
    def test_out_of_context_and_unknown_ids_are_not_recoverable(self):
        contexts = [{"context_id": "C1", "chunk_id": "in-corpus", "document_id": "d", "page": 1}]
        result = resolve_citations(["outside-corpus", "C9", "in-corpus"], contexts,
                                   corpus_chunk_ids={"in-corpus", "outside-corpus"}, status="answered")
        self.assertEqual(result["strict_valid_count"], 0)
        self.assertEqual(result["recoverable_valid_count"], 1)
        self.assertEqual(result["error_taxonomy_counts"]["out_of_context_chunk_id"], 1)
        self.assertEqual(result["error_taxonomy_counts"]["unknown_context_id"], 1)


if __name__ == "__main__":
    unittest.main()
