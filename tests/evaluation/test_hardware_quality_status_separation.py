import unittest
from src.evaluation.edge.core import deployment_row,hardware_status


class HardwareQualityTest(unittest.TestCase):
    def test_fast_qwen_does_not_resolve_quality(self):
        r=deployment_row('qwen2.5-coder:7b','deployable_on_device',dict(TPS=999,TTFT=.01))
        self.assertEqual(r['quality_status'],'evaluation_unresolved')
        self.assertTrue(r['judge_conflict']);self.assertFalse(r['quality_status_changed_by_speed'])

    def test_incomplete_run_not_deployable(self):
        self.assertEqual(hardware_status(completed=60,required=180,cold_verified=True,
            failure_count=0,input_audited=True,limitations=False),'benchmark_incomplete')

    def test_all_failures_not_removed_from_feasibility(self):
        self.assertEqual(hardware_status(completed=180,required=180,cold_verified=True,
            failure_count=180,input_audited=False,limitations=True),'not_feasible')
