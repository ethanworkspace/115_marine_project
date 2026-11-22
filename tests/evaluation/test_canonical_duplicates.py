import unittest

from tests.evaluation.helpers import build, make_chunk, make_doc


class CanonicalDuplicateTests(unittest.TestCase):
    def test_document_duplicate_of_is_respected_and_copy_excluded(self):
        docs = [make_doc("doc-copy", checksum="same-file", duplicate_of="doc-canonical"),
                make_doc("doc-canonical", checksum="same-file")]
        rows = build([
            make_chunk("copy-chunk", document_id="doc-copy"),
            make_chunk("canonical-chunk", document_id="doc-canonical"),
        ], docs)
        by_id = {row["chunk_id"]: row for row in rows}
        self.assertEqual(by_id["copy-chunk"]["canonical_document_id"], "doc-canonical")
        self.assertEqual(by_id["copy-chunk"]["duplicate_status"], "duplicate_source")
        self.assertEqual(by_id["copy-chunk"]["retrieval_role"], "excluded")
        self.assertEqual(by_id["canonical-chunk"]["retrieval_role"], "retrieval")

    def test_exact_duplicate_canonicalization_is_deterministic(self):
        chunks = [make_chunk("chunk-z"), make_chunk("chunk-a")]
        first = {row["chunk_id"]: row for row in build(chunks, [make_doc()])}
        second = {row["chunk_id"]: row for row in build(list(reversed(chunks)), [make_doc()])}
        self.assertEqual(first["chunk-a"]["duplicate_status"], "canonical")
        self.assertEqual(first["chunk-z"]["duplicate_status"], "exact_duplicate")
        self.assertEqual(first["chunk-z"]["canonical_chunk_id"], "chunk-a")
        self.assertFalse(first["chunk-z"]["benchmark_eligible"])
        self.assertEqual(first["chunk-z"]["retrieval_role"], "excluded")
        self.assertEqual(first, second)

    def test_parent_child_same_checksum_are_not_deduplicated(self):
        rows = build([make_chunk("parent", chunk_type="parent"), make_chunk("child", parent="parent")], [make_doc()])
        self.assertEqual({row["duplicate_status"] for row in rows}, {"none"})


if __name__ == "__main__":
    unittest.main()
