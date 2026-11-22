import unittest
from src.evaluation.edge.recovery19b1 import exact_model_identity,MODEL_ID,REVISION
class ModelIdentityTest(unittest.TestCase):
    def data(self):return dict(model_id=MODEL_ID,revision=REVISION,files={'weights':{'sha256':'abc'}})
    def test_exact_identity(self):self.assertTrue(exact_model_identity(self.data(),{'weights':'abc'}))
    def test_revision_change_rejected(self):
        m=self.data();m['revision']='different';self.assertFalse(exact_model_identity(m,{'weights':'abc'}))
    def test_weights_change_rejected(self):self.assertFalse(exact_model_identity(self.data(),{'weights':'different'}))
