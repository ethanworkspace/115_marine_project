import unittest
from src.evaluation.ragas_eval.core import summarize
from .ragas_fixtures import row


class AnsweredOnlyTests(unittest.TestCase):
    def test_abstention_is_not_regular_answer(self):
        s = summarize([row(), row('q2', status='insufficient_evidence', score=0)], ci=False)
        self.assertEqual(s['metrics']['faithfulness']['mean'], .8)
        self.assertEqual(s['metrics']['faithfulness']['n_total'], 1)
        self.assertEqual(s['metrics']['faithfulness']['n_abstained_excluded'], 1)
        self.assertEqual(s['abstention_rate'], .5)
