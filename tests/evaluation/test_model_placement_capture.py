import unittest
from unittest.mock import Mock
from src.evaluation.edge.execution19a import placement
class PlacementTest(unittest.TestCase):
    def test_does_not_guess_CPU_layers(self):
        a=Mock();a.allocations.return_value={'models':[{'name':'m','size_vram':123}]}
        s=Mock();s.latest.return_value={}
        r=placement(a,'m',s);self.assertEqual(r['GPU_allocation_bytes'],123)
        self.assertIsNone(r['CPU_allocation_bytes']);self.assertIsNone(r['GPU_offload_layers'])
