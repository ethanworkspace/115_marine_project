import unittest

from src.evaluation.generation.protocol_v2 import resolve_citations


class CitationAliasResolverTests(unittest.TestCase):
    def test_context_id_is_strict_and_chunk_alias_is_recoverable_only(self):
        contexts = [{"context_id": "C1", "chunk_id": "chunk-a", "document_id": "doc-a", "page": 3}]
        strict = resolve_citations(["C1"], contexts, status="answered")
        alias = resolve_citations(["chunk-a"], contexts, status="answered")
        self.assertTrue(strict["citations"][0]["strict_valid"])
        self.assertTrue(alias["citations"][0]["recoverable_valid"])
        self.assertFalse(alias["citations"][0]["strict_valid"])
        self.assertEqual(alias["citations"][0]["recovered_context_id"], "C1")


if __name__ == "__main__":
    unittest.main()
