import unittest
import json
from pathlib import Path
from unittest.mock import Mock
from src.evaluation.edge.core import target_gate
from src.evaluation.edge.inputs import load_target,validate_target_schema
from src.evaluation.edge.runner import execute
from src.evaluation.edge.runtime import TargetBlocked,require_target
from tests.evaluation.edge_fixtures import target


class TargetTest(unittest.TestCase):
    def test_pending_template_schema_valid_but_execution_blocked(self):
        t=json.loads(Path('reports/evaluation/edge/phase19/target_device_manifest.json').read_text(encoding='utf-8'))['target_device'];self.assertEqual(validate_target_schema(t),[])
        self.assertFalse(target_gate(t)['edge_execution_ready'])
        self.assertIsNone(t['device_name'])

    def test_no_runtime_call_before_target_gate(self):
        factory=Mock()
        from unittest.mock import patch
        t=json.loads(Path('reports/evaluation/edge/phase19/target_device_manifest.json').read_text(encoding='utf-8'))['target_device']
        with patch('src.evaluation.edge.runner.load_target',return_value=t):
            with self.assertRaises(TargetBlocked):execute(adapter_factory=factory)
        factory.assert_not_called()

    def test_explicit_synthetic_target_not_research_default(self):
        self.assertTrue(target_gate(target())['edge_execution_ready'])
        with self.assertRaises(TargetBlocked):require_target(target(),node='wrong-physical-node')

    def test_no_acceptance_threshold_invented(self):
        t=target();g=target_gate(t)
        self.assertFalse(g['acceptance_thresholds_defined'])
        self.assertEqual(g['benchmark_mode'],'descriptive_feasibility')
        t['acceptance_thresholds']={'TPS_min':2}
        self.assertIn('acceptance_threshold_provenance_missing',target_gate(t)['errors'])
