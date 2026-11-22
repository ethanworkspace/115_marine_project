import unittest
from src.evaluation.edge.recovery19b1 import resume_gate
class CUDAGateTest(unittest.TestCase):
    def test_CUDA_required_no_CPU_fallback(self):
        gates={k:{'passed':True} for k in ('R0','R1','R2','R3','R4','R5','E4_60')}
        gates['R1']={'passed':False,'CPU_fallback':False};self.assertFalse(resume_gate(gates))
