import unittest
from src.evaluation.edge.recovery19b1 import remediation_allowed,FORBIDDEN_ACTIONS
class SafetyTest(unittest.TestCase):
    def test_read_only_actions_allowed(self):self.assertTrue(remediation_allowed(['read_events','capture_hashes']))
    def test_security_and_runtime_bypass_rejected(self):
        for action in FORBIDDEN_ACTIONS:self.assertFalse(remediation_allowed([action]))
    def test_unknown_mutation_not_authorized(self):self.assertFalse(remediation_allowed(['unknown_command']))
