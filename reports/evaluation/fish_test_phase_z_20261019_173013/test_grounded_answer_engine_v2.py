from __future__ import annotations

import hashlib
import unittest

import phase_z_runtime as runtime


class GroundedAnswerEngineTests(unittest.TestCase):
    def test_exact_source_fact_extracts_without_question_specific_answer(self):
        for case_id in ("Z-IND-MULLET-AGE2-RATE", "Z-IND-GROUPER-TEMP-RANGE"):
            data = runtime.load_case(case_id)
            decision = runtime.ENGINE.assess_evidence(data["profile"], data["spans"])
            result = runtime.ENGINE.deterministic_extract(data["profile"], data["spans"], decision)
            self.assertEqual(decision["state"], "EVIDENCE_SUFFICIENT")
            self.assertEqual(result["answer_origin"], "DETERMINISTIC_EVIDENCE_EXTRACTION")
            self.assertTrue(result["evidence_span_ids"])
            self.assertIsNone(data["profile"]["pre_frozen_answer_text"])

    def test_empty_context_abstains(self):
        data = runtime.load_case("Z-NEG-EEL-WATER-QUALITY")
        result = runtime.ENGINE.deterministic_extract(data["profile"], data["spans"])
        self.assertEqual(result["answer_origin"], "ABSTAINED")
        self.assertEqual(result["support_validation"]["state"], "EVIDENCE_INSUFFICIENT")

    def test_wrong_species_is_blocked(self):
        data = runtime.load_case("Z-NEG-MULLET-EVIDENCE-FOR-TILAPIA")
        result = runtime.ENGINE.deterministic_extract(data["profile"], data["spans"])
        self.assertEqual(result["answer_origin"], "ABSTAINED")
        self.assertEqual(result["support_validation"]["state"], "SOURCE_INAPPLICABLE")

    def test_high_risk_without_authority_is_blocked(self):
        data = runtime.load_case("Z-NEG-SPECIFIC-DRUG-DOSE")
        result = runtime.ENGINE.deterministic_extract(data["profile"], data["spans"])
        self.assertEqual(result["answer_origin"], "ABSTAINED")
        self.assertEqual(result["support_validation"]["state"], "HIGH_RISK_SOURCE_UNVERIFIED")

    def test_invalid_citation_cannot_be_returned_as_model_answer(self):
        data = runtime.load_case("Z-IND-MULLET-AGE2-RATE")
        decision = runtime.ENGINE.assess_evidence(data["profile"], data["spans"])
        raw = '{"status":"answered","answer":"5,000–6,000 fish/ha","citations":[{"chunk_id":"other-rank","source_id":"TFRI-M17-MULLET"}],"evidence_sufficiency":"sufficient","abstention_reason":null}'
        result = runtime.ENGINE.finish_model_answer(data["profile"], data["spans"], raw, decision, {(data["spans"][0].chunk_id, data["spans"][0].source_id)})
        self.assertEqual(result["answer_origin"], "DETERMINISTIC_EVIDENCE_EXTRACTION")
        self.assertNotEqual(result["final_response"]["citations"][0]["chunk_id"], "other-rank")

    def test_model_citation_is_canonicalized_from_fixed_span(self):
        data = runtime.load_case("Z-IND-MULLET-AGE2-RATE")
        span = data["spans"][0]
        decision = runtime.ENGINE.assess_evidence(data["profile"], data["spans"])
        raw = '{"status":"answered","answer":"5,000–6,000尾/公頃","citations":[{"chunk_id":"%s","source_id":"%s"}],"evidence_sufficiency":"sufficient","abstention_reason":null}' % (span.chunk_id, span.source_id)
        result = runtime.ENGINE.finish_model_answer(data["profile"], data["spans"], raw, decision, {(span.chunk_id, span.source_id)})
        self.assertEqual(result["answer_origin"], "MODEL_GENERATED")
        self.assertEqual(result["final_response"]["citations"][0]["locator"], span.locator)
        self.assertEqual(result["evidence_span_ids"], [span.span_id])

    def test_decimal_calculation_is_generic_and_source_bounded(self):
        text = "The pond area is 3 ha; stocking density is 10000 fish/ha."
        quote = "3 ha; stocking density is 10000 fish/ha."
        start = text.index(quote)
        span = runtime.ENGINE.EvidenceSpan(
            span_id="s1", chunk_id="c1", source_id="SYNTHETIC-TEST", source_version="v1",
            source_sha256="a" * 64, expected_source_sha256="a" * 64, locator="page 1",
            quote=quote, source_page_text=text, start_char=start, end_char=start + len(quote),
            fact_card_text=text, species_scope=("species-a",), applicability_status="VERIFIED_EXACT",
            cross_species_basis=None, processing_scope="RESEARCH_FACT_CARD_NONPUBLIC", retrieval_eligible=True,
            formally_admitted_to_evaluation_corpus=False,
        )
        profile = {
            "question_text": "Compute fish count.", "target_species": "species-a", "risk_class": "DETERMINISTIC_CALCULATION",
            "species_applicability": {"status": "VERIFIED_EXACT", "basis": "synthetic test only"},
            "required_answer_elements": [{"element_id": "inputs", "required": True, "required_literals": ["3 ha", "10000 fish/ha"], "evidence_span_ids": ["s1"]}],
            "calculation_spec": {"verification_status": "VERIFIED", "source_id": "SYNTHETIC-TEST", "source_version": "v1", "operation": "multiply", "inputs": ["3", "10000"], "result_unit": "fish", "result_label": "Calculated count: "},
        }
        result = runtime.ENGINE.deterministic_extract(profile, [span])
        self.assertEqual(result["answer_origin"], "DETERMINISTIC_EVIDENCE_EXTRACTION")
        self.assertIn("30000 fish", result["final_response"]["answer"])

    def test_wrong_source_hash_fails_closed(self):
        data = runtime.load_case("Z-IND-MULLET-AGE2-RATE")
        bad = runtime.replace(data["spans"][0], source_sha256="0" * 64)
        result = runtime.ENGINE.deterministic_extract(data["profile"], [bad])
        self.assertEqual(result["answer_origin"], "ABSTAINED")
        self.assertIn("SOURCE_CHECKSUM_NOT_VERIFIED", result["support_validation"]["span_issues"][bad.span_id])


if __name__ == "__main__":
    unittest.main(verbosity=2)
