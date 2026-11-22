import unittest
import json
from unittest.mock import patch
from .phase17_fixtures import manifest
from src.evaluation.generation_models.core import validate_manifest, COMMON_OPTIONS

class SameGenerationConfigTests(unittest.TestCase):
    def test_common_options(self): self.assertEqual(COMMON_OPTIONS,dict(temperature=0,top_p=1.0,seed=15015,num_predict=1024,num_ctx=8192))
    def test_model_specific_budget_rejected(self):
        m=manifest(); m['generation_options']['num_predict']=2048
        with self.assertRaises(ValueError): validate_manifest(m)

    def test_identical_native_payload_and_full_stream_capture(self):
        from src.evaluation.generation_models.runner import call_generation
        class Response:
            encoding = None
            def __enter__(self): return self
            def __exit__(self,*args): return False
            def raise_for_status(self): pass
            def iter_lines(self,decode_unicode):
                assert decode_unicode
                assert self.encoding == 'utf-8'
                yield json.dumps({'message':{'thinking':'native additional output'},'done':False})
                yield json.dumps({'message':{'content':'{"question_id":"q","status":"answered","answer":"A","citations":["C1"]}'},'done':False})
                yield json.dumps({'done':True,'done_reason':'stop','prompt_eval_count':100,'eval_count':10,'eval_duration':1000000000})
        with patch('src.evaluation.generation_models.runner.requests.post',return_value=Response()) as request:
            r=call_generation(model='m',system_prompt='fixed',user_prompt='fixed')
        body=request.call_args.kwargs['json']
        self.assertEqual(body['options'],COMMON_OPTIONS)
        self.assertNotIn('think',body)
        self.assertEqual(r['raw_thinking'],'native additional output')
        self.assertIsInstance(r['raw_stream_events'][0],str)
        self.assertEqual(r['parsed']['answer'],'A')
        self.assertEqual(len(r['raw_stream_events']),3)
