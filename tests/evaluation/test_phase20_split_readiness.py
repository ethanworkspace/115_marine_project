import unittest
from src.evaluation.edge.core19b import split_readiness

class ReadinessTest(unittest.TestCase):
    def test_runtime_block_means_both_false(self):
        r=split_readiness({'gemma2:9b':'benchmark_incomplete'})
        self.assertFalse(r['phase20_research_integration_ready']);self.assertFalse(r['final_model_selection_ready'])
    def test_hardware_success_does_not_resolve_quality(self):
        r=split_readiness({'qwen2.5-coder:7b':'deployable_on_device'})
        self.assertTrue(r['phase20_research_integration_ready']);self.assertFalse(r['final_model_selection_ready'])
    def test_final_readiness_requires_validity(self):
        r=split_readiness({'gemma2:9b':'deployable_on_device'},independent_judge_ready=True,
                         human_review_complete=True,qwen_quality_unresolved=False)
        self.assertTrue(r['final_model_selection_ready'])
