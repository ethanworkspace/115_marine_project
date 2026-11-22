import unittest
from src.evaluation.edge.core19b import sustained_gate

class SustainedTest(unittest.TestCase):
    def complete(self):return [dict(repetition=r,question_position=q) for r in range(1,4) for q in range(60)]
    def test_three_full_runs_required(self):
        self.assertTrue(sustained_gate(self.complete()));self.assertFalse(sustained_gate(self.complete()[:-1]))
    def test_crash_or_OOM_blocks(self):
        for failure in ('OOM','runtime_crash'):
            rows=self.complete();rows[0][failure]=True;self.assertFalse(sustained_gate(rows))
    def test_duplicate_missing_request_not_completion(self):
        rows=self.complete();rows[-1]=rows[0];self.assertFalse(sustained_gate(rows))
