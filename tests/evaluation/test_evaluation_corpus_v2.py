import unittest

from src.evaluation.corpus import build_corpus


class EvaluationCorpusV2Tests(unittest.TestCase):
    def test_parent_child_and_review_roles_are_preserved(self):
        common = {"document_id": "d", "chunkable": True, "ingestion_status": "accepted",
                  "text": "source text", "source_span_ids": ["s"], "page_start": 1, "page_end": 1,
                  "source_verified": True, "legal_status": "unknown", "content_checksum": "hash"}
        chunks = [
            {**common, "chunk_id": "p", "chunk_type": "parent", "chunk_strategy": "manual", "parent_chunk_id": None},
            {**common, "chunk_id": "c", "chunk_type": "child", "chunk_strategy": "manual", "parent_chunk_id": "p"},
            {**common, "chunk_id": "x", "chunk_type": "child", "chunk_strategy": "manual", "ingestion_status": "review", "parent_chunk_id": "p"},
        ]
        manifest = [{"document_id": "d", "title": "source", "checksum": "x" * 64,
                     "source_verified": True, "legal_status": "unknown", "source_tier": 1}]
        spans = [{"source_span_id": "s", "document_id": "d", "page_number": 1, "file_checksum": "x" * 64}]
        corpus, _, summary = build_corpus(chunks, manifest, spans=spans)
        roles = {row["chunk_id"]: row["retrieval_role"] for row in corpus}
        self.assertEqual(roles, {"c": "retrieval", "p": "context_only", "x": "excluded"})
        self.assertEqual(summary["retrieval_chunks"], 1)


if __name__ == "__main__":
    unittest.main()
