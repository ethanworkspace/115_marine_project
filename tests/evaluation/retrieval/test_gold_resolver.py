import unittest

from src.evaluation.retrieval.gold_resolver import GoldResolutionError, resolve_gold


class GoldResolverTests(unittest.TestCase):
    def setUp(self):
        self.corpus = {
            "c1": {"chunk_id": "c1", "document_id": "d1", "page_start": 2, "page_end": 2, "retrieval_role": "retrieval", "duplicate_status": "canonical"},
            "ctx": {"chunk_id": "ctx", "document_id": "d1", "page_start": 2, "retrieval_role": "context_only", "duplicate_status": "canonical"},
            "dup": {"chunk_id": "dup", "document_id": "d1", "page_start": 2, "retrieval_role": "retrieval", "duplicate_status": "exact_duplicate"},
            "excluded": {"chunk_id": "excluded", "document_id": "d1", "page_start": 2, "retrieval_role": "excluded", "duplicate_status": "none"},
        }

    def test_resolves_required_and_acceptable(self):
        gold = resolve_gold({"question_id": "q", "answerable": True, "required_chunks": ["c1"], "acceptable_chunks": ["ctx"]}, self.corpus)
        self.assertEqual(gold.required[0].page, 2)
        self.assertEqual(gold.acceptable[0].relation, "acceptable")

    def test_missing_gold_fails_explicitly(self):
        with self.assertRaisesRegex(GoldResolutionError, "cannot resolve"):
            resolve_gold({"question_id": "q", "answerable": True, "required_chunks": ["missing"]}, self.corpus)

    def test_excluded_and_duplicate_gold_fail(self):
        for chunk in ("excluded", "dup"):
            with self.subTest(chunk=chunk), self.assertRaises(GoldResolutionError):
                resolve_gold({"question_id": "q", "required_chunks": [chunk]}, self.corpus)

    def test_answerable_requires_evidence(self):
        with self.assertRaisesRegex(GoldResolutionError, "no required/acceptable"):
            resolve_gold({"question_id": "q", "answerable": True}, self.corpus)
