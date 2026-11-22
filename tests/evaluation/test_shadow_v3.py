import unittest

from src.evaluation.phase10_recovery import merge_versioned_rows


class ShadowV3Tests(unittest.TestCase):
    def test_reparse_replaces_only_selected_documents(self):
        base = [{"chunk_id": "old-a", "document_id": "a"}, {"chunk_id": "keep-b", "document_id": "b"}]
        new = [{"chunk_id": "new-a", "document_id": "a"}]
        result = merge_versioned_rows(base, new, replace_document_ids={"a"}, id_key="chunk_id")
        self.assertEqual(result, [{"chunk_id": "keep-b", "document_id": "b"}, {"chunk_id": "new-a", "document_id": "a"}])

    def test_stable_id_conflict_fails(self):
        with self.assertRaises(ValueError):
            merge_versioned_rows([], [{"chunk_id": "c", "document_id": "a"}, {"chunk_id": "c", "document_id": "b"}],
                                 replace_document_ids=set(), id_key="chunk_id")


if __name__ == "__main__":
    unittest.main()
