import unittest

from src.evaluation.corpus_gaps import classify_fact_gap


class FactGapAnalysisTests(unittest.TestCase):
    def test_priority_reasons_are_explicit(self):
        self.assertEqual(classify_fact_gap({"ocr_candidate": True}), "ocr_missing")
        self.assertEqual(classify_fact_gap({"review_table": True}), "table_unparsed")
        self.assertEqual(classify_fact_gap({"review_page": True}), "review_page")
        self.assertEqual(classify_fact_gap({"accepted_page_match": True}), "chunking_loss")

    def test_unknown_when_no_local_support(self):
        self.assertEqual(classify_fact_gap({}), "unknown")


if __name__ == "__main__":
    unittest.main()
