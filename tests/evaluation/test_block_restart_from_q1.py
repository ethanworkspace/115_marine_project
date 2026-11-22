import unittest
from src.evaluation.edge.exec19b_r2 import restart_plan

class Restart(unittest.TestCase):
    def test_fresh_q1_new_id(self):
        p=restart_plan('old',True)
        self.assertEqual(p['start_question_position'],0);self.assertTrue(p['new_run_id_required'])
        self.assertFalse(p['partial_primary_data_reused'])
    def test_preflight_required(self):
        self.assertFalse(restart_plan('old',False)['allowed'])
        self.assertIsNone(restart_plan('old',False)['start_question_position'])
