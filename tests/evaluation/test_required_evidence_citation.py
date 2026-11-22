import unittest

from src.evaluation.generation.evaluation import evidence_citation_recall


class RequiredEvidenceCitationTests(unittest.TestCase):
    def test_recall_is_scored_only_for_required_chunks_available_in_context(self):
        contexts = [{"context_id": "C1", "chunk_id": "a", "document_id": "d", "page": 1},
                    {"context_id": "C2", "chunk_id": "b", "document_id": "d", "page": 2}]
        report = evidence_citation_recall({"citations": [{"context_id": "C1", "chunk_id": "a", "document_id": "d", "page": 1}]}, contexts, ["a", "b", "missing"])
        self.assertEqual(report["required_chunks_in_context"], 2)
        self.assertEqual(report["required_evidence_citation_recall"], 0.5)
        self.assertFalse(report["all_available_required_evidence_cited"])


if __name__ == "__main__":
    unittest.main()
