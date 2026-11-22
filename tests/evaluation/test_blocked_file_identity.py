import unittest
from src.evaluation.edge.recovery19b1 import classify,relevant_block_events
class BlockIdentityTest(unittest.TestCase):
    def test_unrelated_DLL_not_attributed(self):
        rows=[dict(event_id=3077,blocked_path='Chrome/x.dll')]
        self.assertEqual(relevant_block_events(rows),[]);self.assertEqual(classify(rows),['unknown'])
    def test_unsigned_direct_block_is_not_dependency_guess(self):
        rows=[dict(event_id=3077,blocked_path='.venv-reranker/torch/lib/shm.dll')]
        self.assertIn('application_policy_block',classify(rows,signature_status='NotSigned'))
    def test_Zone_presence_does_not_prove_cause(self):self.assertEqual(classify([],zone_present=True),['unknown'])
