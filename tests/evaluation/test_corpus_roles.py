import unittest

from tests.evaluation.helpers import build, make_chunk, make_doc


class CorpusRoleTests(unittest.TestCase):
    def test_parent_context_child_retrieval_and_review_excluded(self):
        rows = build([
            make_chunk("parent", chunk_type="parent"),
            make_chunk("child", parent="parent", checksum="def"),
            make_chunk("review", status="review", checksum="ghi"),
        ], [make_doc()])
        roles = {row["chunk_id"]: row["retrieval_role"] for row in rows}
        self.assertEqual(roles, {"child": "retrieval", "parent": "context_only", "review": "excluded"})

    def test_parent_never_eligible_as_retrieval(self):
        row = build([make_chunk("parent", chunk_type="parent")], [make_doc()])[0]
        self.assertEqual(row["retrieval_role"], "context_only")
        self.assertFalse(row["benchmark_eligible"])


if __name__ == "__main__":
    unittest.main()
