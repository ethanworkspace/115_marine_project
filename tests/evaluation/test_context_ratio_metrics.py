import unittest
from src.evaluation.edge.analysis19a import ratios
class RatiosTest(unittest.TestCase):
    def test_ratios(self):
        groups={b:{k:{'median':v} for k in ('ttft','latency','TPS')} for b,v in [('short',2),('long',4)]}
        self.assertEqual(ratios(groups,True)['long_short_median_TTFT_ratio'],2)
        self.assertIsNone(ratios(groups,False)['long_short_median_TPS_ratio'])
