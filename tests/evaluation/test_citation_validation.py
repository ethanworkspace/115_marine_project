import unittest

from src.evaluation.generation.evaluation import normalize_citations


class CitationValidationTests(unittest.TestCase):
    def test_validates_and_enriches_only_available_context(self):
        contexts = [{"context_id": "C1", "chunk_id": "c", "document_id": "d", "page": 7}]
        report = normalize_citations({"status": "answered", "citations": [
            {"context_id": "C1", "chunk_id": "c", "document_id": "d", "page": 7},
            {"context_id": "C9", "chunk_id": "z", "document_id": "x", "page": 2},
        ]}, contexts)
        self.assertEqual(report["citations"][0]["chunk_id"], "c")
        self.assertEqual(report["hallucinated_citation_count"], 1)
        self.assertEqual(report["out_of_context_citation_count"], 1)

    def test_answer_without_citation_is_missing(self):
        report = normalize_citations({"status": "answered", "citations": []}, [])
        self.assertTrue(report["missing_citation"])


if __name__ == "__main__":
    unittest.main()
