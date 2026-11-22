import unittest
from tests.evaluation.edge19a_fixtures import complete
from src.evaluation.edge.analysis19a import run_stability
class StabilityTest(unittest.TestCase):
    def test_zero_jitter_and_per_run_IFR(self):
        r=run_stability(complete());self.assertEqual(r['latency_run_median_CV'],0)
        self.assertEqual([x['IFR']['n_total'] for x in r['runs']],[60]*3)
