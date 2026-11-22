import unittest
from src.evaluation.phase20_1r_protocol import phase20_2_readiness

class Phase202RReadinessTests(unittest.TestCase):
    def test_every_gate_is_required_and_no_winner_is_created(self):
        gates={k:True for k in ("four_models_ready","independent_judge_ready","normal_evidence_ready","high_risk_ready","calculation_ready","final_corpus_ready","e4_final_ready")}
        result=phase20_2_readiness(gates)
        self.assertTrue(result["phase20_2_benchmark_construction_ready"])
        self.assertIsNone(result["winner"])
        gates["e4_final_ready"]=False
        self.assertFalse(phase20_2_readiness(gates)["phase20_2_benchmark_construction_ready"])
