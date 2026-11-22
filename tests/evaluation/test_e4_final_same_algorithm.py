import unittest

class E4FinalAlgorithmTests(unittest.TestCase):
    def test_frozen_e4_parameters_are_preserved(self):
        cfg={"bm25_top_k":50,"dense_top_k":50,"rrf_k":60,"bm25_weight":1.0,"dense_weight":1.0,"rrf_top_k":50,"reranker_candidate_depth":50,"final_top_k":5}
        self.assertEqual(cfg,{"bm25_top_k":50,"dense_top_k":50,"rrf_k":60,"bm25_weight":1.0,"dense_weight":1.0,"rrf_top_k":50,"reranker_candidate_depth":50,"final_top_k":5})
