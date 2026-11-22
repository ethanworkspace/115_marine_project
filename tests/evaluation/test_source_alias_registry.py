import unittest

from src.evaluation.source_mapping import CONFIDENCE, match_source_identity


class SourceAliasRegistryTests(unittest.TestCase):
    def setUp(self):
        self.documents = [{
            "document_id": "doc-a", "document_title": "測試手冊", "title_aliases": ["測試手冊"],
            "source_id": "S-EXPLICIT", "source_url": "https://example.test/doc", "organization": "測試機關",
            "checksum": "abc", "publication_date": "2025-01-01", "duplicate_of": None,
            "source_verified": False,
        }]

    def test_registry_confidence_enum_and_verification_preserved(self):
        result = match_source_identity({"來源ID": "S-EXPLICIT", "文件／頁面": "其它標題"}, self.documents)
        self.assertIn(result["mapping_confidence"], CONFIDENCE)
        self.assertEqual(result["mapping_confidence"], "exact")
        self.assertIs(result["source_verified"], False)
        self.assertTrue(result["identity_match_trace"])

    def test_alias_mapping_is_deterministic(self):
        source = {"來源ID": "S-EXPLICIT", "文件／頁面": "其它標題"}
        first = match_source_identity(source, self.documents)
        second = match_source_identity(source, self.documents)
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
