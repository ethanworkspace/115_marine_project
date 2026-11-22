import unittest
from src.evaluation.phase20_1r_protocol import evidence_matrix

class NoDuplicateFactPaddingTests(unittest.TestCase):
    def test_duplicate_fact_never_counts_as_distinct_units(self):
        from src.evaluation.phase20_1r_protocol import SPECIES,CATEGORIES
        unit={"evidence_unit_id":"u1","species":SPECIES[0],"category":CATEGORIES[0],"fact_or_rule":"same fact","support_span":"span","chunk_id":"c1","document_id":"d1","page":1,"source_title":"s","source_status":"verified","date_version":"v1","checksum":"a"*64,"risk_level":"normal","readiness_status":"silver_ready","human_reviewed":False,"source_in_evaluation_corpus":True,"provenance_complete":True,"species_mapping_valid":True,"category_mapping_valid":True}
        rows=evidence_matrix([unit,dict(unit,evidence_unit_id="u2",chunk_id="c2")],[])
        self.assertEqual(1,rows[0]["ready_unit_count"])
