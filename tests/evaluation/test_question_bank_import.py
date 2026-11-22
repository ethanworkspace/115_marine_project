from __future__ import annotations

import tempfile
import unittest
import zipfile
from html import escape
from pathlib import Path

from src.evaluation.question_bank_import import (
    build_mapping_report,
    import_question_bank,
    make_draft_from_candidate,
    normalize_workbook,
)


def _column_name(index: int) -> str:
    result = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        result = chr(65 + remainder) + result
    return result


def _write_xlsx(path: Path, values: dict[str, str]) -> None:
    headers = [
        "題號", "問題", "主題", "難度", "基準答案", "來源網址",
        "評估類型", "題目形式", "必答重點", "資料性質", "來源ID",
    ]
    row = [values.get(header, "") for header in headers]
    cell_rows = []
    for row_number, values_row in ((4, headers), (5, row)):
        cells = []
        for index, value in enumerate(values_row, 1):
            if not value:
                continue
            ref = f"{_column_name(index)}{row_number}"
            cells.append(f'<c r="{ref}" t="inlineStr"><is><t>{escape(str(value))}</t></is></c>')
        cell_rows.append(f'<row r="{row_number}">' + "".join(cells) + "</row>")
    sheet = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<sheetData>' + "".join(cell_rows) + '</sheetData></worksheet>'
    )
    workbook = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets><sheet name="題目庫" sheetId="1" r:id="rId1"/></sheets></workbook>'
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
        'Target="worksheets/sheet1.xml"/></Relationships>'
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("xl/workbook.xml", workbook)
        archive.writestr("xl/_rels/workbook.xml.rels", rels)
        archive.writestr("xl/worksheets/sheet1.xml", sheet)


class QuestionBankImportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.workbook = self.root / "fish test" / "吳郭魚_題庫.xlsx"

    def _write_normal(self, **overrides: str) -> None:
        values = {
            "題號": "Q01",
            "問題": "水質檢測時如何觀察溶氧？",
            "主題": "水質管理",
            "難度": "中等",
            "基準答案": "依文件記錄的水質檢測流程觀察。",
            "來源網址": "",
            "評估類型": "事實題",
            "題目形式": "簡答題",
            "必答重點": "溶氧",
            "資料性質": "參考資料",
            "來源ID": "SRC1",
        }
        values.update(overrides)
        _write_xlsx(self.workbook, values)

    def test_import_never_creates_gold_fields_and_candidate_id_is_stable(self) -> None:
        self._write_normal()
        first = normalize_workbook(self.workbook, root=self.root)
        second = normalize_workbook(self.workbook, root=self.root)
        self.assertEqual(len(first), 1)
        self.assertEqual(first[0]["candidate_id"], second[0]["candidate_id"])
        self.assertEqual(first[0]["source_sheet"], "題目庫")
        self.assertEqual(first[0]["source_row"], 5)
        self.assertEqual(first[0]["question_candidate"], "水質檢測時如何觀察溶氧？")
        self.assertEqual(first[0]["answer_candidate"], "依文件記錄的水質檢測流程觀察。")
        for field in ("gold_answer", "required_chunks", "acceptable_chunks", "gold_chunks", "gold_evidence_snapshot"):
            self.assertNotIn(field, first[0])

    def test_excel_answer_and_evidence_suggestions_are_never_promoted_to_gold(self) -> None:
        self._write_normal()
        corpus = [{
            "chunk_id": "chunk-1", "document_id": "doc-1", "page_start": 1,
            "text": "水質檢測流程應記錄溶氧數值。", "retrieval_role": "retrieval",
            "benchmark_eligible": True, "risk_level": "normal", "duplicate_status": "canonical",
        }]
        candidate = normalize_workbook(self.workbook, root=self.root, corpus=corpus)[0]
        self.assertTrue(candidate["evidence_search_candidates"])
        draft = make_draft_from_candidate(candidate, corpus_sha256="a" * 64, created_at="2026-10-03T00:00:00Z")
        self.assertIsNone(draft["gold_answer"])
        self.assertIsNone(draft["species"])
        self.assertFalse(draft["species_verified"])
        self.assertEqual(draft["candidate_species"], "吳郭魚")
        self.assertEqual(draft["species_basis"], "workbook_filename_candidate_only")
        self.assertEqual(draft["required_chunks"], [])
        self.assertEqual(draft["acceptable_chunks"], [])
        self.assertEqual(draft["gold_evidence_snapshot"], [])
        self.assertEqual(draft["candidate_chunk_ids"], [])
        self.assertNotIn("reference_answer_candidate", draft)

    def test_high_risk_unverified_candidate_is_not_annotation_eligible(self) -> None:
        self._write_normal(
            **{"問題": "此魚使用藥物時應注意什麼停藥期？", "主題": "用藥與停藥期", "必答重點": "停藥期"}
        )
        candidate = normalize_workbook(self.workbook, root=self.root, corpus=[])[0]
        self.assertEqual(candidate["risk_level"], "high")
        self.assertFalse(candidate["annotation_eligible"])
        self.assertFalse(candidate["first_batch_eligible"])

    def test_legal_high_risk_requires_non_unknown_corpus_legal_status(self) -> None:
        self._write_normal(
            **{"問題": "依現行法規此項藥物是否核准？", "主題": "法規", "來源網址": "https://example.org/source"}
        )
        corpus = [{"source_url": "https://example.org/source", "source_verified": True, "legal_status": "unknown"}]
        candidate = normalize_workbook(self.workbook, root=self.root, corpus=corpus)[0]
        self.assertFalse(candidate["annotation_eligible"])
        self.assertFalse(candidate["first_batch_eligible"])

    def test_reviewed_count_requires_complete_manual_review_provenance(self) -> None:
        candidates = [{"candidate_id": "qbc-1", "category_candidate": "fact", "species": "吳郭魚", "risk_level": "normal", "first_batch_eligible": True}]
        incomplete = {"question_bank_candidate_id": "qbc-1", "annotation_status": "reviewed", "question_verified": True, "evidence_verified": True}
        complete = {
            **incomplete, "annotator": "A", "reviewer": "B", "review_notes": "已確認", "reviewed_at": "2026-10-03T00:00:00Z",
            "reviewer_confirmations": {key: True for key in (
                "question_supported", "gold_answer_supported", "required_chunks_reasonable",
                "acceptable_chunks_reasonable", "species_within_evidence", "category_reasonable", "difficulty_reasonable",
            )},
        }
        report_incomplete = build_mapping_report(candidates, [incomplete])
        report_complete = build_mapping_report(candidates, [complete])
        self.assertEqual(report_incomplete["reviewed"], 0)
        self.assertEqual(report_complete["reviewed"], 1)


if __name__ == "__main__":
    unittest.main()
