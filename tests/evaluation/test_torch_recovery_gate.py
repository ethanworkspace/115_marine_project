import unittest
from src.evaluation.edge.recovery19b1 import resume_gate
class TorchGateTest(unittest.TestCase):
    def test_import_failure_cannot_resume(self):
        gates={k:{'passed':True} for k in ('R0','R1','R2','R3','R4','R5','E4_60')};gates['R0']['passed']=False
        self.assertFalse(resume_gate(gates))
    def test_missing_import_evidence_cannot_resume(self):self.assertFalse(resume_gate({}))
