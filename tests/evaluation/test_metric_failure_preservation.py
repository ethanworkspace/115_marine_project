import unittest
from src.evaluation.ragas_eval.core import summarize, error_labels
from .ragas_fixtures import row


class FailurePreservationTests(unittest.TestCase):
    def test_failed_score_counted_not_silently_dropped(self):
        a, b = row(), row('q2')
        b['metrics']['faithfulness'] = dict(status='failed', score=None, failure_reason='parse')
        s = summarize([a, b], ci=False)['metrics']['faithfulness']
        self.assertEqual((s['n_total'], s['n_valid'], s['n_failed']), (2, 1, 1))
        self.assertEqual(s['failure_reasons'], {'parse': 1})
        self.assertIn('judge_evaluation_failure', error_labels(b))

    def test_pending_not_disguised_as_failure(self):
        a = row()
        a['metrics'] = {}
        s = summarize([a], ci=False)['metrics']['faithfulness']
        self.assertEqual((s['n_pending'], s['n_failed'], s['n_valid']), (1, 0, 0))
