import unittest
from src.evaluation.edge.analysis19a import cold_release_reanalysis
from src.evaluation.edge.report19a import hardware_samples_summary


class EdgeMemoryCoverageTest(unittest.TestCase):
    def test_parent_memory_is_not_reported_as_runner_peak(self):
        row=hardware_samples_summary([])
        self.assertFalse(row['runner_process_working_set_available'])
        self.assertIsNone(row['model_process_specific_RAM_peak'])
        self.assertIsNone(row['model_process_specific_VRAM_peak'])

    def test_parent_zero_does_not_override_device_proxy_failure(self):
        rows=[dict(model='fixture',repetition=1,runtime_allocations={'models':[]},
            cold_verification={'verified':True,'sample':{'gpu':{'dedicated_used_bytes':1000+65*1024**2}}})]
        result=cold_release_reanalysis(rows,1000)
        self.assertFalse(result['all_device_proxies_pass'])
        self.assertTrue(result['records'][0]['original_verified'])
        self.assertFalse(result['records'][0]['original_record_modified'])
