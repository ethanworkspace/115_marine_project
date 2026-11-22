import unittest
from src.evaluation.phase20_1r_protocol import evidence_unit_ready

class SilverReadyDefinitionTests(unittest.TestCase):
    def test_normal_risk_does_not_require_human_review(self):
        unit={"evidence_unit_id":"u1","species":"吳郭魚","category":"Fact","fact_or_rule":"fact","support_span":"span","chunk_id":"c1","document_id":"d1","page":1,"source_title":"s","source_status":"verified","date_version":"v1","checksum":"a"*64,"risk_level":"normal","readiness_status":"silver_ready","human_reviewed":False,"source_in_evaluation_corpus":True,"provenance_complete":True,"species_mapping_valid":True,"category_mapping_valid":True}
        self.assertTrue(evidence_unit_ready(unit))
