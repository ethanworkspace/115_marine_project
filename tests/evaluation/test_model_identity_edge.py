import copy
import json
import unittest
from src.evaluation.edge.core import validate_model_identity,MODELS
from src.evaluation.edge.inputs import OUT


class ModelIdentityTest(unittest.TestCase):
    def test_full_artifact_id_size_native_and_experimental_context(self):
        for model in MODELS:
            r=json.loads((OUT/'model_manifests'/(model.replace(':','_')+'.json')).read_text(encoding='utf-8'))
            self.assertEqual(len(r['digest']),64);self.assertGreater(r['artifact_size_bytes'],0)
            self.assertEqual(r['experimental_context_length'],8192)
            self.assertTrue(validate_model_identity(r,r))

    def test_changed_quantization_or_digest_fails(self):
        r=dict(name='test',digest='a'*64,quantization='Q4_0',parameter_count=10,native_context_length=8192)
        x=copy.deepcopy(r);x['quantization']='Q8'
        with self.assertRaises(ValueError):validate_model_identity(r,x)
        x=copy.deepcopy(r);x['digest']='b'*64
        with self.assertRaises(ValueError):validate_model_identity(r,x)
