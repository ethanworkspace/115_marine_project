import unittest

from src.evaluation.source_mapping import _unmapped_reason


class UnmappedAnalysisTests(unittest.TestCase):
    def test_unmatched_named_source_is_source_not_in_corpus(self):
        q = {"expected_sources": [{"source_id": "S1"}], "expected_facts": [{"statement": "fact"}]}
        aliases = [{"mapping_confidence": "unmapped", "excel_source_title": "外部手冊"}]
        self.assertEqual(_unmapped_reason(q, [], aliases), "source_not_in_corpus")

    def test_missing_source_metadata_is_reported(self):
        self.assertEqual(_unmapped_reason({"expected_sources": [], "expected_facts": []}, [], []), "question_bank_source_missing")


if __name__ == "__main__":
    unittest.main()
