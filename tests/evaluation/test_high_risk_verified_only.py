import unittest
from src.evaluation.phase20_1r_protocol import high_risk_unit_ready

class HighRiskVerifiedTests(unittest.TestCase):
    def test_official_current_applicability_is_mandatory(self):
        unit={"category":"Safe Medication / Law","readiness_status":"verified_ready","official_source":True,"source_status":"verified","current_applicability_verified":True,"authority":"MOA","document_title":"Act","page":1,"date_version":"2026-01","applicability":"aquaculture","checksum":"a"*64}
        self.assertTrue(high_risk_unit_ready(unit))
        unit["current_applicability_verified"]=False
        self.assertFalse(high_risk_unit_ready(unit))
