import unittest
from src.evaluation.edge.exec19b_r2 import valid_block

class Continuity(unittest.TestCase):
    def test_complete_valid_window(self):
        self.assertTrue(valid_block({'completed':True,'runtime_valid':True,'question_ids':list(range(60))},range(60)))
    def test_runtime_failure_invalidates_all(self):
        self.assertFalse(valid_block({'completed':True,'runtime_valid':False,'question_ids':list(range(60))},range(60)))
    def test_code_integrity_block_invalidates(self):
        self.assertFalse(valid_block({'completed':True,'runtime_valid':True,'question_ids':list(range(60)),'relevant_policy_blocks':1},range(60)))
    def test_order_cannot_change(self):
        self.assertFalse(valid_block({'completed':True,'runtime_valid':True,'question_ids':list(reversed(range(60)))},range(60)))
