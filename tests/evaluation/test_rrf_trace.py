import unittest

from scripts.run_grounded_rrf import _trace_rows
from src.evaluation.grounded_baselines import _required_evidence
from src.evaluation.rrf import fuse_ranked_lists
from tests.evaluation.grounded_baseline_fixtures import hit, question


class RRFTraceTests(unittest.TestCase):
    def test_trace_records_both_ranks_contributions_and_matches(self):
        corpus = {
            "c0": {"chunk_id": "c0", "document_id": "d0", "page_start": 1, "page_end": 1, "text": "support"},
            "c1": {"chunk_id": "c1", "document_id": "d1", "page_start": 2, "page_end": 2, "text": "other"},
        }
        q = question(chunks=("c0",), pages=(("d0", 1),), docs=("d0",))
        fused = fuse_ranked_lists([hit(1, "c0", "d0", 1)], [hit(1, "c1", "d1", 2)], corpus, top_n=2)
        trace = _trace_rows(q, fused, _required_evidence(q, corpus))[0]
        self.assertEqual(trace["bm25_rank"], 1)
        self.assertEqual(trace["dense_rank"], None)
        self.assertEqual(trace["bm25_rrf_contribution"], 1 / 61)
        self.assertTrue(trace["is_required_evidence"])
        self.assertTrue(trace["chunk_match"])
        self.assertTrue(trace["page_match"])
        self.assertTrue(trace["document_match"])


if __name__ == "__main__":
    unittest.main()
