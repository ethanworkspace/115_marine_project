import unittest
from src.evaluation.edge.recovery19b1 import classify
class BaselineTest(unittest.TestCase):
    def test_hash_unchanged_does_not_prove_policy_unchanged(self):
        rows=[dict(event_id=3077,blocked_path='.venv-reranker/torch/lib/shm.dll')]
        r=classify(rows,runtime_drift=False);self.assertIn('application_policy_block',r)
        self.assertNotIn('OS_policy_state_change',r);self.assertNotIn('runtime_artifact_drift',r)
    def test_real_drift_separate(self):self.assertIn('runtime_artifact_drift',classify([],runtime_drift=True))
