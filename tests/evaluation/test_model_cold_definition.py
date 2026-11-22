import unittest
from src.evaluation.edge.execution19a import unloaded_gpu_check
class ColdTest(unittest.TestCase):
    def test_unloaded_and_gpu_released(self):
        r=unloaded_gpu_check({'unloaded':True},{'GPU_process_memory':{'dedicated_process':[{'value_bytes':0}]}},100)
        self.assertTrue(r['verified']);self.assertFalse(r['OS_filesystem_cache_cleared'])
    def test_gpu_allocation_still_present(self):
        self.assertFalse(unloaded_gpu_check({'unloaded':True},{'GPU_process_memory':{'dedicated_process':[{'value_bytes':1024**3}]}},100)['verified'])
