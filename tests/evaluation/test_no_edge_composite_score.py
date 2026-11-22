import unittest
from src.evaluation.edge.core import pareto,deployment_row


class NoCompositeTest(unittest.TestCase):
    def test_no_fictitious_pareto_frontier(self):
        rows=[deployment_row('gemma2:9b','benchmark_incomplete',{'TTFT':None,'RAM':None})]
        r=pareto(rows,{'TTFT':'min','RAM':'min'})
        self.assertEqual(r['non_dominated'],[]);self.assertIsNone(r['composite_score'])

    def test_only_axis_dominance_no_arbitrary_weights(self):
        rows=[dict(model='A',hardware_status='deployable_on_device',latency=1,memory=3),
              dict(model='B',hardware_status='deployable_on_device',latency=2,memory=2)]
        r=pareto(rows,{'latency':'min','memory':'min'})
        self.assertEqual(set(r['non_dominated']),{'A','B'})
        self.assertIsNone(r['composite_score'])
