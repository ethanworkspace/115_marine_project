import unittest
from src.evaluation.edge.inputs import load_target
class SharedTest(unittest.TestCase):
    def test_config_keeps_pools_separate(self):
        t=load_target();self.assertEqual(t['VRAM']['bytes'],8188*1024**2)
        self.assertIsNone(t['unified_memory']['bytes']);self.assertEqual(t['shared_GPU_memory']['capacity_GiB_approx'],15.9)
