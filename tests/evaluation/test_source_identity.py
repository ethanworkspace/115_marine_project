import unittest

from src.evaluation.source_mapping import match_source_identity


class SourceIdentityTests(unittest.TestCase):
    def test_exact_normalized_url_matches_but_does_not_verify(self):
        docs = [{
            "document_id": "doc", "document_title": "D", "title_aliases": ["D"], "source_id": "unverified",
            "source_url": "HTTPS://example.test/a/", "organization": None, "checksum": None,
            "publication_date": None, "duplicate_of": None, "source_verified": False,
        }]
        row = {"來源ID": "S01", "文件／頁面": "different", "URL": "https://example.test/a"}
        result = match_source_identity(row, docs)
        self.assertEqual(result["mapping_method"], "exact_normalized_url")
        self.assertEqual(result["mapping_confidence"], "exact")
        self.assertIs(result["source_verified"], False)

    def test_identity_trace_records_ordered_steps(self):
        result = match_source_identity({"來源ID": "S99", "文件／頁面": "Missing"}, [])
        self.assertEqual([item["step"] for item in result["identity_match_trace"]], [
            "checksum_identity", "known_duplicate_mapping", "exact_source_id_alias", "exact_normalized_url",
            "exact_normalized_title", "title_plus_organization", "title_plus_year", "strong_lexical_title",
        ])
        self.assertEqual(result["mapping_confidence"], "unmapped")

    def test_known_duplicate_resolves_to_canonical_document(self):
        docs = [
            {"document_id": "canonical", "document_title": "Canonical", "title_aliases": ["Canonical"], "source_id": None, "source_url": None, "organization": None, "checksum": None, "publication_date": None, "duplicate_of": None, "source_verified": False},
            {"document_id": "duplicate", "document_title": "Duplicate", "title_aliases": ["Duplicate"], "source_id": None, "source_url": None, "organization": None, "checksum": None, "publication_date": None, "duplicate_of": "canonical", "source_verified": False},
        ]
        result = match_source_identity({"document_id": "duplicate", "來源ID": "S01"}, docs, {"duplicate": "canonical"})
        self.assertEqual(result["mapping_method"], "known_duplicate_mapping")
        self.assertEqual(result["document_id"], "canonical")


if __name__ == "__main__":
    unittest.main()
