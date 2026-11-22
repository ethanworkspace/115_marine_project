import unittest
import json
import tempfile
from pathlib import Path

from src.ingestion.chunking.common import ChunkFactory, TextUnit
from src.ingestion.chunking.pipeline import build_shadow_corpus
from src.ingestion.gate import can_index
from tests.ingestion.chunking.helpers import CONFIG, document, page


class ChunkEligibilityTests(unittest.TestCase):
    def test_review_page_is_not_ingestion_eligible(self):
        self.assertFalse(can_index(page("待審頁面", status="review")))

    def test_unverified_high_risk_source_is_chunkable_but_not_indexable(self):
        source = page("第一條 用藥規範。")
        doc = document(title="動物用藥法規", document_type="law", source_verified=False, legal_status="unknown")
        factory = ChunkFactory(config=CONFIG, span_registry={})
        record = factory.add_text(document=doc, unit=TextUnit([source]), start=0, end=len(source["text"]),
                                  strategy="regulation", chunk_type="parent", article="第一條")
        self.assertTrue(record["chunkable"])
        self.assertFalse(record["indexable"])

    def test_source_verification_and_current_legal_state_are_both_required_for_high_risk(self):
        source = page("第一條 規定。")
        doc = document(title="法規", document_type="law", source_verified=True, legal_status="unknown")
        factory = ChunkFactory(config=CONFIG, span_registry={})
        record = factory.add_text(document=doc, unit=TextUnit([source]), start=0, end=len(source["text"]),
                                  strategy="regulation", chunk_type="parent", article="第一條")
        self.assertFalse(record["indexable"])

    def test_pipeline_excludes_review_pages_and_keeps_accepted_pages(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "config").mkdir()
            (root / "reports" / "parsing").mkdir(parents=True)
            (root / "reports").mkdir(exist_ok=True)
            (root / "config" / "chunking_v2.json").write_text(json.dumps(CONFIG), encoding="utf-8")
            doc = document()
            doc["title"] = "一般養殖參考"
            doc["topics"] = []
            (root / "reports" / "parsing" / "document_eligibility.jsonl").write_text(
                json.dumps(doc, ensure_ascii=False) + "\n", encoding="utf-8")
            accepted = page("這是可以使用的原生文字。", 1, status="accepted_with_warning")
            review = page("這段必須隔離的審查文字。", 2, status="review")
            (root / "reports" / "parsing" / "page_inventory.jsonl").write_text(
                "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in (accepted, review)), encoding="utf-8")
            baseline = {"metrics": {"chunks": {"count": 0, "under_20_chars": 0, "under_100_chars": 0},
                                    "metadata": {"missing_page": 0, "missing_species": 0, "missing_topic": 0},
                                    "duplicate_chunks": {"extra_rows": 0}}}
            (root / "reports" / "data_quality.json").write_text(json.dumps(baseline), encoding="utf-8")
            result = build_shadow_corpus(root)
            chunks = [json.loads(line) for line in (root / "data" / "shadow" / "chunks_v2.jsonl").read_text(encoding="utf-8").splitlines()]
            excluded = [json.loads(line) for line in (root / "reports" / "chunking" / "excluded_pages.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertTrue(chunks)
            self.assertEqual({chunk["page_start"] for chunk in chunks}, {1})
            self.assertEqual(result["eligible_pages"], 1)
            self.assertEqual(result["excluded_pages"], 1)
            self.assertEqual(excluded[0]["ingestion_status"], "review")


if __name__ == "__main__":
    unittest.main()
