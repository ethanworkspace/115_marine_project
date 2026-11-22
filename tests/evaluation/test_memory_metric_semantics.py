import unittest
from src.evaluation.edge.core import validate_memory,pareto
from src.evaluation.edge.runtime import energy_from_samples


class MemoryTest(unittest.TestCase):
    def test_whole_device_not_process_peak(self):
        r=dict(kind='RAM',scope='whole_device',phase='inference',value_bytes=1024,sensor='synthetic',timestamp=1)
        self.assertTrue(validate_memory(r))
        r['scope']='unspecified'
        with self.assertRaises(ValueError):validate_memory(r)

    def test_scopes_not_merged_for_pareto(self):
        rows=[dict(model='A',hardware_status='deployable_on_device',latency=1,RAM=10,scope='whole_device'),
              dict(model='B',hardware_status='deployable_on_device',latency=.5,RAM=5,scope='process_specific')]
        r=pareto(rows,{'latency':'min','RAM':'min'},('scope',))
        self.assertEqual(r['non_dominated'],['A']);self.assertEqual(r['excluded'][0]['reason'],'measurement_semantics_differ')

    def test_power_missing_cannot_estimate_energy(self):
        self.assertIsNone(energy_from_samples([dict(timestamp=1,power_watts=None),dict(timestamp=2,power_watts=20)]))
        self.assertEqual(energy_from_samples([dict(timestamp=1,power_watts=10,power_scope='GPU_board'),
            dict(timestamp=3,power_watts=20,power_scope='GPU_board')]),30)
