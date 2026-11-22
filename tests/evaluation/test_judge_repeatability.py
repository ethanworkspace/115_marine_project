import unittest
from src.evaluation.ragas_eval.core import repeatability, select_repeat_subset
from .ragas_fixtures import row


class JudgeRepeatabilityTests(unittest.TestCase):
    def test_continuous_repeat_metrics(self):
        a, b = [row(score=.8), row('q2', score=.4)], [row(score=.8), row('q2', score=.6)]
        s = repeatability(a, b)['faithfulness']
        self.assertEqual(s['exact_agreement'], .5)
        self.assertAlmostEqual(s['mean_absolute_difference'], .1)
        self.assertAlmostEqual(s['pearson_correlation'], 1)
        self.assertIsNone(s['categorical_agreement'])

    def test_subset_deterministic_and_balanced(self):
        r = [row('q' + str(i), c) for c in ('oracle', 'e4_top5') for i in range(20)]
        a, b = select_repeat_subset(r), select_repeat_subset(list(reversed(r)))
        self.assertEqual([(x['question_id'], x['condition']) for x in a], [(x['question_id'], x['condition']) for x in b])
        self.assertEqual(len(a), 30)

    def test_mismatched_ids_fail_explicitly(self):
        with self.assertRaises(ValueError):
            repeatability([row()], [row('other')])
