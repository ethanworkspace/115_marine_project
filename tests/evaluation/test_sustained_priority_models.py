import unittest
from src.evaluation.edge.analysis19a import SUSTAINED_MODELS,SUSTAINED_SECONDS,INTERVAL_SECONDS
class SustainedTest(unittest.TestCase):
    def test_only_predeclared_priority_models(self):
        self.assertEqual(SUSTAINED_MODELS,('gemma2:9b','qwen2.5-coder:7b'))
        self.assertEqual(SUSTAINED_SECONDS,1800);self.assertEqual(INTERVAL_SECONDS,300)
