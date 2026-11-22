import unittest
from src.evaluation.edge.core import token_metrics


class TokenTest(unittest.TestCase):
    def test_reasoning_counts_not_invented(self):
        r=token_metrics(dict(eval_count=20,eval_duration=2_000_000_000),thinking_capable=True,thinking_observed=True)
        self.assertFalse(r['reasoning_token_separation_available'])
        self.assertIsNone(r['visible_output_token_count']);self.assertIsNone(r['visible_answer_tps'])
        self.assertEqual(r['runtime_tps'],10)

    def test_content_only_model_can_report_visible_decode_rate(self):
        r=token_metrics(dict(eval_count=20,eval_duration=2_000_000_000),thinking_capable=False,thinking_observed=False)
        self.assertEqual(r['reasoning_token_count'],0);self.assertEqual(r['visible_answer_tps'],10)

    def test_known_count_without_separate_duration_not_visible_TPS(self):
        r=token_metrics(dict(eval_count=20,thinking_eval_count=8,eval_duration=2_000_000_000),thinking_capable=True,thinking_observed=True)
        self.assertEqual(r['visible_output_token_count'],12);self.assertIsNone(r['visible_answer_tps'])
