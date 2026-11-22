from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
RAG_DIR = Path(__file__).resolve().parents[1] / "rag_v2"
sys.path.insert(0, str(RAG_DIR))
import phase_s_rag as rag


class PhaseSRAGTests(unittest.TestCase):
    def test_species_names_are_not_cross_aliases(self):
        self.assertNotEqual("烏魚", "吳郭魚")
        self.assertNotIn("烏魚", ("吳郭魚", "虱目魚", "石斑魚", "鱸魚", "鰻魚"))
        self.assertNotIn("午仔魚", rag.SPECIES)

    def test_dgbas_fact_scope_does_not_promote_species_or_category(self):
        profile = {"question_category": "Water Quality", "requires_statistical_fact": False, "target_species": "吳郭魚"}
        chunk = {"species_scope": "STATISTICAL_CATEGORY_ONLY", "source_kind": "dgbas_statistic", "content": "吳郭魚統計分類"}
        ok, _ = rag.scope_filter(profile, chunk)
        self.assertFalse(ok)
        profile = {"question_category": "Fact", "requires_statistical_fact": True, "target_species": "吳郭魚"}
        ok, note = rag.scope_filter(profile, chunk)
        self.assertTrue(ok)
        self.assertIn("not an exact biological species assertion", note)

    def test_statute_does_not_support_nonlegal_category(self):
        chunk = {"species_scope": "GENERAL_REGULATION", "source_kind": "official_statute", "content": "法條"}
        for category in ("Disease", "Calculation", "Water Quality"):
            ok, _ = rag.scope_filter({"question_category": category, "requires_statistical_fact": False, "target_species": ""}, chunk)
            self.assertFalse(ok)
        ok, _ = rag.scope_filter({"question_category": "Medication / Law", "requires_statistical_fact": False, "target_species": "烏魚"}, chunk)
        self.assertTrue(ok)

    def test_exact_citation_and_wrong_chunk_are_rejected(self):
        chunk = {"chunk_id": "c1", "source_id": "s1", "page": 2, "content": "原文證據片段。"}
        base = {"status": "answered", "answer": "回答", "citations": [{"chunk_id": "c1", "source_id": "s1", "page": 2, "quote": "原文證據片段。"}], "insufficient_evidence_reason": None}
        self.assertEqual([], rag.validate_answer(base, [chunk]))
        wrong = {**base, "citations": [{**base["citations"][0], "quote": "不存在的引用"}]}
        self.assertTrue(any("exact substring" in e for e in rag.validate_answer(wrong, [chunk])))
        wrong_id = {**base, "citations": [{**base["citations"][0], "chunk_id": "c2"}]}
        self.assertTrue(any("outside final Top-5" in e for e in rag.validate_answer(wrong_id, [chunk])))

    def test_candidate_retrieval_returns_stages_and_scope_gate(self):
        chunks = [
            {"chunk_id": "c1", "source_id": "s1", "source_title": "statute", "page": 1, "locator": "a1", "content": "動物用藥品管理法規則", "lexical_tokens": "動物 用藥品 管理 法規則", "embedding": __import__("numpy").array([1.0, 0.0], dtype="float32"), "species_scope": "GENERAL_REGULATION", "source_kind": "official_statute", "category_scope": ["Medication / Law"]},
            {"chunk_id": "c2", "source_id": "s2", "source_title": "statistic", "page": None, "locator": "xml", "content": "吳郭魚分類統計", "lexical_tokens": "吳郭魚 分類 統計", "embedding": __import__("numpy").array([0.0, 1.0], dtype="float32"), "species_scope": "STATISTICAL_CATEGORY_ONLY", "source_kind": "dgbas_statistic", "category_scope": ["Fact"]},
        ]
        profile = {"question_category": "Medication / Law", "requires_statistical_fact": False, "target_species": "烏魚"}
        stages = rag.rrf_rank("動物用藥品法規", profile, chunks, __import__("numpy").array([1.0, 0.0], dtype="float32"), limit=5)
        self.assertEqual("c1", stages["rrf"][0]["chunk_id"])
        self.assertEqual(1, stages["eligible_chunk_count"])
        self.assertEqual(1, stages["scope_excluded_count"])

    def test_reranker_fails_closed_when_unavailable(self):
        import os
        previous = os.environ.pop("PHASE_S_BGE_RERANKER_PATH", None)
        try:
            with self.assertRaises(rag.RerankerUnavailable):
                rag.rerank([], "test")
        finally:
            if previous is not None:
                os.environ["PHASE_S_BGE_RERANKER_PATH"] = previous


if __name__ == "__main__":
    unittest.main(verbosity=2)
