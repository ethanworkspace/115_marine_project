from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
for entry in (HERE, ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))
import phase_aa_runtime as runtime


class PhaseAAIsolatedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases = [json.loads(x) for x in (HERE / "independent_test_set.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
        cls.case = next(x for x in cls.cases if x.get("test_id") == "AA-NEW-EEL-TEMP-01")
        cls.trace = runtime.retrieve(cls.case["question_text"], cls.case["target_species"], 5)
        cls.spans = runtime.spans_from_retrieval(cls.trace)

    def test_retrieval_returns_traceable_eel_card(self):
        wanted = self.case["source_card_chunk_id"]
        self.assertIn(wanted, [x["chunk_id"] for x in self.trace["reranked_top"]])
        row = next(x for x in self.trace["reranked_top"] if x["chunk_id"] == wanted)
        self.assertTrue(row["locator"])
        self.assertEqual(row["source_sha256"], self.case["source_sha256"])
        self.assertEqual(row["formal_corpus_admission"], False)

    def test_evidence_profile_is_sufficient_for_linked_species_card(self):
        profile = runtime.profile_for_case(self.case, self.spans)
        result = runtime.ENGINE.assess_evidence(profile, self.spans)
        self.assertEqual(result["state"], "EVIDENCE_SUFFICIENT")

    def test_wrong_species_linked_span_fails_closed(self):
        eel_span = next(x for x in self.spans if x.chunk_id == self.case["source_card_chunk_id"])
        profile = {
            "question_id": "AA-NEG-SPECIES-CONFLICT-01",
            "question_text": "將白鰻20–30°C套用至吳郭魚。",
            "target_species": "吳郭魚",
            "category": "Water Quality",
            "risk_class": "LOW_RISK_FACT",
            "species_applicability": {"status": "VERIFIED_EXACT", "basis": "test"},
            "required_answer_elements": [{"element_id": "temp", "required": True, "required_literals": ["20", "30"], "evidence_span_ids": [eel_span.span_id]}],
        }
        result = runtime.ENGINE.assess_evidence(profile, [eel_span])
        self.assertEqual(result["state"], "SOURCE_INAPPLICABLE")
        self.assertEqual(result["reason"], "REQUIRED_EVIDENCE_SPAN_OUTSIDE_VERIFIED_TARGET_SPECIES_SCOPE")

    def test_nonmatching_species_context_is_removed_before_prompt(self):
        eel_span = next(x for x in self.spans if x.chunk_id == self.case["source_card_chunk_id"])
        profile = {"target_species": "吳郭魚", "species_applicability": {"status": "VERIFIED_EXACT"}, "required_answer_elements": [{"element_id": "temp", "evidence_span_ids": [eel_span.span_id]}]}
        kept, excluded = runtime.species_filter_spans(profile, self.spans)
        self.assertNotIn(eel_span, kept)
        self.assertTrue(any(item["span_id"] == eel_span.span_id for item in excluded))
        result = runtime.ENGINE.assess_evidence(profile, kept)
        self.assertEqual(result["state"], "SOURCE_INAPPLICABLE")

    def test_no_context_high_risk_fails_closed(self):
        profile = {"question_text": "給我未核驗藥物劑量", "target_species": "未指定", "risk_class": "MEDICATION", "high_risk_authority_verified": False, "required_answer_elements": []}
        result = runtime.ENGINE.assess_evidence(profile, [])
        self.assertEqual(result["state"], "HIGH_RISK_SOURCE_UNVERIFIED")

    def test_deterministic_extraction_is_generic_and_cited(self):
        profile = runtime.profile_for_case(self.case, self.spans)
        decision = runtime.ENGINE.assess_evidence(profile, self.spans)
        result = runtime.ENGINE.deterministic_extract(profile, self.spans, decision)
        self.assertEqual(result["answer_origin"], "DETERMINISTIC_EVIDENCE_EXTRACTION")
        self.assertTrue(result["final_response"]["citations"])
        self.assertIn("20–30°C", result["final_response"]["answer"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
