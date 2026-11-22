import unittest

class JudgeNoCotTests(unittest.TestCase):
    def test_frozen_protocol_must_not_request_private_reasoning(self):
        protocol={"requires_chain_of_thought":False,"requires_private_reasoning":False,"output_schema":"structured"}
        self.assertFalse(protocol["requires_chain_of_thought"])
        self.assertFalse(protocol["requires_private_reasoning"])
