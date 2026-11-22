import unittest

from src.evaluation.grounded.pipeline import (
    distribution_report,
    select_multidocument_pairs,
    select_single_evidence,
)
from tests.evaluation.grounded_fixtures import make_evidence, make_corpus_record


class GroundedSamplingTests(unittest.TestCase):
    def setUp(self):
        self.rows = []
        for species in ("吳郭魚", "鰻魚", "鱸魚", "烏魚"):
            for doc_index in range(3):
                record = make_corpus_record(
                    f"{species}-{doc_index}", f"doc-{species}-{doc_index}", species,
                    f"{species}養殖資料說明水質管理與池塘操作，並記錄可觀察的養殖管理要點和現象。",
                )
                evidence = make_evidence(record)
                evidence["category"] = "fact"
                evidence["evidence_quality_status"] = "accepted"
                self.rows.append(evidence)

    def test_sampling_is_deterministic_and_document_balanced(self):
        first = select_single_evidence(self.rows, 8, max_per_document=1)
        second = select_single_evidence(self.rows, 8, max_per_document=1)
        self.assertEqual([row["chunk_id"] for row in first], [row["chunk_id"] for row in second])
        self.assertEqual(len({row["document_id"] for row in first}), 8)

    def test_multidocument_pair_uses_same_species_category_and_different_documents(self):
        pairs = select_multidocument_pairs(self.rows, 4)
        self.assertEqual(len(pairs), 4)
        for left, right in pairs:
            self.assertNotEqual(left["document_id"], right["document_id"])
            self.assertEqual(left["species"], right["species"])
            self.assertEqual(left["category"], right["category"])

    def test_distribution_keeps_all_six_species_visible(self):
        report = distribution_report([], self.rows, "a" * 64)
        self.assertEqual(list(report["by_species"])[:6],
                         ["虱目魚", "吳郭魚", "石斑魚", "鱸魚", "烏魚", "鰻魚"])
        self.assertEqual(report["by_species"]["虱目魚"], 0)
        self.assertEqual(report["by_species"]["unknown"], 0)


if __name__ == "__main__":
    unittest.main()
