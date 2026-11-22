from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from src.evaluation.silver import build_silver_questions, validate_silver_question
from src.evaluation.retrievers.bm25 import EvaluationBM25
from src.evaluation.silver_benchmark import run_e1_bm25_silver


def corpus_row(chunk_id: str, text: str, *, role: str = "retrieval", duplicate: str = "canonical", eligible: bool = False) -> dict:
    return {
        "chunk_id": chunk_id, "canonical_chunk_id": chunk_id,
        "document_id": "doc-" + chunk_id, "canonical_document_id": "doc-" + chunk_id,
        "page_start": 1, "page_end": 1, "text": text,
        "retrieval_role": role, "duplicate_status": duplicate,
        "benchmark_eligible": eligible,
    }


def silver_row(question_id: str, mapping_status: str, chunk_id: str | None) -> dict:
    mapped = [] if not chunk_id else [{"chunk_id": chunk_id, "document_id": "doc-" + chunk_id, "page": 1, "page_end": 1}]
    return {
        "question_id": question_id, "species_candidate": "吳郭魚", "question": "水溫最佳生長範圍為何？",
        "reference_answer": "AI-generated candidate answer", "category": "water_quality",
        "question_type": "問答題", "risk_level": "normal", "source_workbook": "book.xlsx",
        "source_sheet": "題目庫", "source_row": 5, "expected_sources": [], "expected_facts": [],
        "benchmark_type": "silver", "generation_source": "ai_question_bank", "mapping_backend": "lexical_only",
        "question_origin": "ai_generated", "evidence_mapping_type": "auto_mapped",
        "evidence_mapping_status": mapping_status, "mapping_method": ["synthetic_fixture"],
        "mapping_score": 0.9 if chunk_id else None, "fact_mapping": [],
        "mapped_chunks": mapped,
        "mapped_pages": [{"document_id": "doc-" + chunk_id, "page": 1}] if chunk_id else [],
        "mapped_documents": ["doc-" + chunk_id] if chunk_id else [],
    }


class SilverMappingTests(unittest.TestCase):
    def test_builder_uses_real_fact_identifier_only_when_present_in_corpus(self) -> None:
        candidate = {
            "candidate_id": "qbc_1", "species": "吳郭魚", "question_candidate": "溫度如何？",
            "answer_candidate": "25 至 30 度", "category_candidate": "water_quality", "question_type": "問答題",
            "risk_level": "normal", "source_workbook": "missing.xlsx", "source_sheet": "題目庫", "source_row": 5,
            "original_metadata": {"事實ID": "F001", "來源ID": "S01", "問題": "溫度如何？", "基準答案": "25 至 30 度"},
        }
        corpus = [corpus_row("c1", "最佳水溫為25至30度。")]
        row = build_silver_questions([candidate], corpus, root=Path(tempfile.gettempdir()))[0]
        self.assertEqual(row["benchmark_type"], "silver")
        self.assertEqual(row["generation_source"], "ai_question_bank")
        self.assertIn(row["evidence_mapping_status"], {"low_confidence", "unmapped"})
        self.assertNotIn("gold_answer", row)
        self.assertNotIn("required_chunks", row)

    def test_real_corpus_fact_identifier_can_map_exactly(self) -> None:
        candidate = {
            "candidate_id": "qbc_2", "species": "吳郭魚", "question_candidate": "溫度如何？",
            "answer_candidate": "25 至 30 度", "category_candidate": "fact", "question_type": "問答題",
            "risk_level": "normal", "source_workbook": "missing.xlsx", "source_sheet": "題目庫", "source_row": 5,
            "original_metadata": {"事實ID": "F001", "來源ID": "S01", "問題": "溫度如何？", "基準答案": "25 至 30 度"},
        }
        row = corpus_row("c2", "相關事實")
        row["fact_ids"] = ["F001"]
        built = build_silver_questions([candidate], [row], root=Path(tempfile.gettempdir()))[0]
        self.assertEqual(built["evidence_mapping_status"], "exact")
        self.assertEqual([item["chunk_id"] for item in built["mapped_chunks"]], ["c2"])

    def test_silver_schema_requires_mapping_status_and_never_calls_it_gold(self) -> None:
        row = silver_row("q1", "unmapped", None)
        self.assertEqual(validate_silver_question(row), [])
        row["benchmark_type"] = "gold"
        self.assertTrue(any("benchmark_type" in issue for issue in validate_silver_question(row)))


class EvaluationBM25Tests(unittest.TestCase):
    def test_filter_is_retrieval_canonical_and_ignores_gold_eligibility(self) -> None:
        rows = [
            corpus_row("keep", "水溫 最佳 生長", eligible=False),
            corpus_row("parent", "水溫 最佳 生長", role="context_only"),
            corpus_row("duplicate", "水溫 最佳 生長", duplicate="exact_duplicate"),
        ]
        retriever = EvaluationBM25(rows, corpus_sha256="a" * 64)
        self.assertEqual([hit.chunk_id for hit in retriever.retrieve("水溫 最佳")], ["keep"])
        self.assertFalse(retriever.index_manifest["eligibility_filter"]["human_gold_benchmark_eligible_filter"])

    def test_ranking_is_deterministic_and_does_not_use_expected_evidence(self) -> None:
        rows = [corpus_row("b", "吳郭魚 水溫 最佳生長 25至30度"), corpus_row("a", "吳郭魚 水溫 最佳生長 25至30度")]
        first = EvaluationBM25(rows, corpus_sha256="b" * 64)
        second_rows = json.loads(json.dumps(rows))
        second_rows[0]["expected_gold"] = True
        second_rows[1]["expected_gold"] = False
        second = EvaluationBM25(second_rows, corpus_sha256="b" * 64)
        self.assertEqual([hit.chunk_id for hit in first.retrieve("吳郭魚水溫", top_k=2)], ["a", "b"])
        self.assertEqual([hit.chunk_id for hit in first.retrieve("吳郭魚水溫", top_k=2)], [hit.chunk_id for hit in second.retrieve("吳郭魚水溫", top_k=2)])


class SilverE1RunnerTests(unittest.TestCase):
    def test_only_exact_high_are_primary_and_unmapped_not_errors(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "data/evaluation/silver").mkdir(parents=True)
            (root / "data/evaluation").mkdir(parents=True, exist_ok=True)
            corpus = [
                corpus_row("hit", "吳郭魚水溫最佳生長範圍 25至30度"),
                corpus_row("other", "疾病養殖管理內容"),
            ]
            corpus_path = root / "data/evaluation/corpus_v1.jsonl"
            corpus_path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in corpus), encoding="utf-8")
            digest = hashlib.sha256(corpus_path.read_bytes()).hexdigest()
            (root / "data/evaluation/corpus_manifest.json").write_text(json.dumps({"corpus_sha256": digest}), encoding="utf-8")
            questions = [silver_row("q-exact", "exact", "hit"), silver_row("q-low", "low_confidence", "other"), silver_row("q-none", "unmapped", None)]
            qpath = root / "data/evaluation/silver/questions_v1.jsonl"
            qpath.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in questions), encoding="utf-8")
            result = run_e1_bm25_silver(root)
            self.assertEqual(result["overall"]["scored_question_count"], 1)
            self.assertEqual(result["overall"]["retrieved_question_count"], 1)
            self.assertEqual(result["coverage"]["unmapped"], 1)
            self.assertFalse(any(row["question_id"] == "q-none" for row in result["errors"]))
            self.assertTrue(result["validation"]["corpus_sha256_unchanged"])
            self.assertTrue(result["validation"]["silver_sha256_unchanged"])


if __name__ == "__main__":
    unittest.main()
