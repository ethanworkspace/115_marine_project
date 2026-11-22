import unittest
from src.evaluation.edge.core19b import STAGES,StageTimers

class StageTimerTest(unittest.TestCase):
    def test_monotonic_sum_excludes_generation(self):
        clock=iter(range(12));timer=StageTimers(lambda:next(clock))
        for name in STAGES:
            with timer.stage(name):pass
        self.assertEqual(timer.retrieval_to_context_ms(),6000)
        with self.assertRaises(ValueError):
            with timer.stage('generation_ms'):pass
    def test_incomplete_stages_are_not_zero(self):
        with self.assertRaises(ValueError):StageTimers().retrieval_to_context_ms()
