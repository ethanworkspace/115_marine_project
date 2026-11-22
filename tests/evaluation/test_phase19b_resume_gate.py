import unittest
from src.evaluation.edge.recovery19b1 import resume_gate
class ResumeTest(unittest.TestCase):
    def gates(self):return {k:{'passed':True} for k in ('R0','R1','R2','R3','R4','R5','E4_60')}
    def test_requires_every_gate(self):
        self.assertTrue(resume_gate(self.gates()))
        for key in self.gates():
            r=self.gates();r[key]['passed']=False;self.assertFalse(resume_gate(r))
    def test_technical_ready_not_full_benchmark_completed(self):
        self.assertTrue(resume_gate(self.gates()))
        self.assertNotIn('formal_requests_completed',self.gates())
