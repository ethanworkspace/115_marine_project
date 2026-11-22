import unittest
from src.evaluation.edge.core import schedule,MODELS,hardware_status
from src.evaluation.edge.report import validate_results


class ColdWarmTest(unittest.TestCase):
    def test_three_full_rotating_blocks_every_model(self):
        blocks=schedule();self.assertEqual(len(blocks),12)
        for m in MODELS:self.assertEqual([r['repetition'] for r in blocks if r['model']==m],[1,2,3])

    def test_warmup_or_cold_cannot_be_formal_warm_result(self):
        for stage in ('warmup','cold'):
            with self.assertRaises(ValueError):validate_results([dict(model=MODELS[0],repetition=1,question_id='q',stage=stage)],[],['q'])

    def test_unverified_cold_start_not_complete(self):
        self.assertEqual(hardware_status(completed=180,required=180,cold_verified=False,
            failure_count=0,input_audited=True,limitations=False),'benchmark_incomplete')

    def test_changed_question_order_fails(self):
        rows=[dict(model=MODELS[0],repetition=1,question_id='q2',stage='warm')]
        with self.assertRaises(ValueError):validate_results(rows,[],['q1','q2'])
