import unittest

from src.evaluation.corpus_gaps import classify_missing_source


class MissingSourceAnalysisTests(unittest.TestCase):
    def test_explicit_local_duplicate_is_classified_first(self):
        self.assertEqual(classify_missing_source({"known_duplicate": True}), "duplicate_document")

    def test_local_but_review_only_document(self):
        self.assertEqual(classify_missing_source({"review_only": True, "source_title": "title"}), "review_only_document")

    def test_missing_identity_fields_are_not_called_missing_source(self):
        self.assertEqual(classify_missing_source({}), "source_identifier_missing")

    def test_source_with_no_local_identity_match_is_truly_missing_candidate(self):
        self.assertEqual(classify_missing_source({"source_identifier": "S1", "source_title": "title", "identity_fields_present": True}), "truly_missing")


if __name__ == "__main__":
    unittest.main()
