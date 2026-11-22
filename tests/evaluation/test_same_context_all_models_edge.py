import copy
import json
import unittest
from src.evaluation.edge.core import MODELS,digest,OPTIONS
from src.evaluation.edge.inputs import load_bundle


class SameContextTest(unittest.TestCase):
    def test_all_models_receive_same_contexts(self):
        rows,m=load_bundle()
        copies={model:copy.deepcopy(rows) for model in MODELS}
        for r in rows:
            cid=r['question']['question_id'];h=r['subset_row']['context_sha256']
            self.assertEqual(digest(json.dumps([x['text'] for x in r['contexts']],ensure_ascii=False)),h)
            self.assertEqual([x['context_id'] for x in r['contexts']],['C1','C2','C3','C4','C5'])
        self.assertTrue(all(copies[model]==rows for model in MODELS))

    def test_common_config_no_per_model_budget(self):
        self.assertEqual(OPTIONS,dict(temperature=0,top_p=1.0,seed=15015,num_predict=1024,num_ctx=8192))
