import unittest
from src.evaluation.edge.exec19b_r2 import residency_changes

class Residency(unittest.TestCase):
    def test_observed_load_and_disappearance(self):
        value=residency_changes({'models':[{'name':'a'}]},{'models':[{'name':'b'}]},set())
        self.assertEqual(value['model_load'],['b']);self.assertEqual(value['model_eviction'],['a'])
        self.assertIsNone(value['CPU_fallback']);self.assertIsNone(value['shared_memory_spill'])
    def test_reload_requires_previous_observation(self):
        self.assertEqual(residency_changes({'models':[]},{'models':[{'name':'b'}]},{'b'})['model_reload'],['b'])
    def test_offload_change_observed(self):
        a={'models':[{'name':'a','size_vram':1}]};b={'models':[{'name':'a','size_vram':2}]}
        self.assertEqual(residency_changes(a,b,set())['GPU_offload_change'],['a'])
