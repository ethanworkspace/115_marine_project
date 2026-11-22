import unittest
from src.evaluation.edge.core19b import residency_record

class ResidencyTest(unittest.TestCase):
    def test_five_required_nodes(self):
        for node in ('request_start','after_dense','after_reranker','before_generator','after_generator'):
            self.assertEqual(residency_record(node,{'loaded':[]})['node'],node)
    def test_does_not_infer_spill_or_fallback(self):
        r=residency_record('after_dense',{'shared_memory_bytes':123})
        self.assertIsNone(r['shared_memory_spill']);self.assertIsNone(r['cpu_fallback'])
    def test_copy_does_not_mutate_sensor_data(self):
        sensor={'loaded':['bge-m3']};r=residency_record('after_dense',sensor)
        r['observations']['loaded'].append('other');self.assertEqual(sensor['loaded'],['bge-m3'])
