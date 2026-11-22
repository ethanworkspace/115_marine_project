import unittest
from src.evaluation.edge.core19b import runtime_gate

class RuntimeGateTest(unittest.TestCase):
    def good(self):
        return dict(torch_import=True,cuda_available=True,model_loaded=True,single_pair_finite=True,
                    ten_query_count=10,pairs_scored=500,all_scores_finite=True,candidate_ids_preserved=True)
    def test_requires_full_CUDA_gate(self):
        self.assertTrue(runtime_gate(self.good()))
    def test_import_block_stops(self):
        p=self.good();p['torch_import']=False;self.assertFalse(runtime_gate(p))
    def test_no_CPU_fallback(self):
        p=self.good();p['cuda_available']=False;self.assertFalse(runtime_gate(p))
    def test_missing_pairs_stops(self):
        p=self.good();p['pairs_scored']=499;self.assertFalse(runtime_gate(p))
