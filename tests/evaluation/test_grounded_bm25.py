import unittest

from src.evaluation.retrievers.bm25 import BM25_CONFIG, TOKENIZER, EvaluationBM25
from tests.evaluation.grounded_baseline_fixtures import corpus_rows


class GroundedBM25Tests(unittest.TestCase):
    def test_fixed_phase9_config_and_evaluation_only_rank(self):
        rows = corpus_rows()
        retriever = EvaluationBM25(rows, corpus_sha256="frozen", git_commit="test")
        hits = retriever.retrieve("水質管理", top_k=3)
        self.assertEqual(BM25_CONFIG["k1"], 1.5)
        self.assertEqual(BM25_CONFIG["b"], 0.75)
        self.assertEqual(TOKENIZER, "traditional_chinese_bigrams_latin_terms_v1")
        self.assertEqual(len(hits), 3)
        self.assertEqual(hits, retriever.retrieve("水質管理", top_k=3))
        self.assertEqual(retriever.index_manifest["index_storage"], "in_memory_experimental_only")


if __name__ == "__main__":
    unittest.main()
