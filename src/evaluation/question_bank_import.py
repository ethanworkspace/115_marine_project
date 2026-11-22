"""Import six-species Excel question banks as non-Gold annotation candidates."""

from __future__ import annotations

import hashlib
import json
import posixpath
import re
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit
from xml.etree import ElementTree as ET

from .annotation import atomic_write_jsonl, sha256_file, utc_now
from .corpus import read_jsonl, write_json


ROOT = Path(__file__).resolve().parents[2]
SPECIES = ("虱目魚", "吳郭魚", "石斑魚", "鱸魚", "烏魚", "鰻魚")
FIRST_BATCH_TARGETS = {
    "fact": 5,
    "water_quality": 5,
    "disease": 5,
    "climate": 3,
    "sop": 3,
    "multi_document": 3,
}
HIGH_RISK_CATEGORIES = {"regulation", "drug", "withdrawal_period", "dosage", "legal_status", "safety_boundary"}
LEGAL_TERMS = re.compile(r"法規|法令|合法|核准|禁用|殘留|停藥|休藥|withdrawal|法定|法律|regulation", re.IGNORECASE)
DOSAGE_TERMS = re.compile(r"劑量|用藥|投藥|藥浴|藥物|mg\s*/\s*kg|休藥|停藥|dosage|\bdose\b", re.IGNORECASE)
SAFETY_TERMS = re.compile(r"安全界線|安全範圍|不可超過|不得|毒性|禁用|緊急措施|安全應答", re.IGNORECASE)
TOPIC_TERMS = {
    "disease": re.compile(r"疾病|魚病|病原|病害|症狀|診斷|治療|防治|寄生蟲|病毒|細菌|感染|疫病"),
    "climate": re.compile(r"寒流|寒害|防寒|越冬|氣候|天候|颱風|暴雨|低溫|高溫|冷氣團"),
    "water_quality": re.compile(r"水質|水溫|溫度|溶氧|鹽度|pH|氨氮|亞硝酸|透明度|濁度|ppm|psu"),
    "sop": re.compile(r"管理|飼養|養殖|投餌|飼料|放養|密度|水車|換水|池塘|收成|越冬溝|操作"),
}

NS_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
NS_REL_DOC = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS_REL_PKG = "http://schemas.openxmlformats.org/package/2006/relationships"


def _cell_column(reference: str) -> int:
    letters = re.match(r"[A-Z]+", reference or "")
    if not letters:
        return 0
    value = 0
    for char in letters.group(0):
        value = value * 26 + ord(char) - ord("A") + 1
    return value - 1


def _shared_strings(archive: zipfile.ZipFile) -> list[str]:
    try:
        root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    except KeyError:
        return []
    return ["".join(item.itertext()) for item in root.findall(f"{{{NS_MAIN}}}si")]


def _cell_value(cell: ET.Element, shared: list[str]) -> Any:
    cell_type = cell.get("t")
    if cell_type == "inlineStr":
        inline = cell.find(f"{{{NS_MAIN}}}is")
        return "".join(inline.itertext()) if inline is not None else ""
    value_node = cell.find(f"{{{NS_MAIN}}}v")
    if value_node is None or value_node.text is None:
        return None
    value = value_node.text
    if cell_type == "s":
        try:
            return shared[int(value)]
        except (ValueError, IndexError):
            return value
    if cell_type == "b":
        return value == "1"
    if cell_type in {"str", "e"}:
        return value
    try:
        numeric = float(value)
        return int(numeric) if numeric.is_integer() else numeric
    except ValueError:
        return value


def read_xlsx_sheets(path: str | Path) -> dict[str, list[tuple[int, list[Any]]]]:
    """Read cell values and 1-based Excel row numbers using stdlib OOXML."""
    path = Path(path)
    with zipfile.ZipFile(path) as archive:
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        relations = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        rel_map = {rel.get("Id"): rel.get("Target") for rel in relations.findall(f"{{{NS_REL_PKG}}}Relationship")}
        shared = _shared_strings(archive)
        sheets: dict[str, list[tuple[int, list[Any]]]] = {}
        sheet_nodes = workbook.findall(f".//{{{NS_MAIN}}}sheet")
        for sheet in sheet_nodes:
            name = str(sheet.get("name") or "")
            target = rel_map.get(sheet.get(f"{{{NS_REL_DOC}}}id"))
            if not target:
                continue
            sheet_path = target.lstrip("/") if target.startswith("/") else posixpath.normpath(posixpath.join("xl", target))
            xml = ET.fromstring(archive.read(sheet_path))
            rows: list[tuple[int, list[Any]]] = []
            for row_node in xml.findall(f".//{{{NS_MAIN}}}sheetData/{{{NS_MAIN}}}row"):
                row_number = int(row_node.get("r") or len(rows) + 1)
                values: list[Any] = []
                for cell in row_node.findall(f"{{{NS_MAIN}}}c"):
                    col = _cell_column(str(cell.get("r") or ""))
                    if col >= len(values):
                        values.extend([None] * (col + 1 - len(values)))
                    values[col] = _cell_value(cell, shared)
                rows.append((row_number, values))
            sheets[name] = rows
    return sheets


def _clean(value: Any) -> Any:
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


def _normal_url(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    parts = urlsplit(value.strip())
    return urlunsplit((parts.scheme.casefold(), parts.netloc.casefold(), parts.path.rstrip("/"), parts.query, ""))


def _canonical_category(raw: dict[str, Any]) -> str | None:
    text = " ".join(str(raw.get(key) or "") for key in ("評估類型", "主題", "問題", "必答重點"))
    source_ids = [part.strip() for part in re.split(r"[;,，；]", str(raw.get("來源ID") or "")) if part.strip()]
    if len(set(source_ids)) > 1:
        return "multi_document"
    if "計算" in text or str(raw.get("題目形式") or "") == "計算題":
        return "calculation"
    if "安全應答" in text:
        return "safety_boundary"
    for category in ("disease", "climate", "water_quality", "sop"):
        if TOPIC_TERMS[category].search(text):
            return category
    return "fact" if raw.get("問題") else None


def _difficulty(value: Any) -> str | None:
    return {"基礎": "easy", "入門": "easy", "中等": "medium", "進階": "hard", "困難": "hard"}.get(str(value or "").strip())


def _risk(category: str | None, raw: dict[str, Any]) -> tuple[str, str | None]:
    text = " ".join(str(raw.get(key) or "") for key in ("評估類型", "主題", "問題", "基準答案", "必答重點", "資料性質"))
    if category in HIGH_RISK_CATEGORIES or LEGAL_TERMS.search(text) or SAFETY_TERMS.search(text):
        requirement = "legal_status" if LEGAL_TERMS.search(text) or category in {"regulation", "drug", "withdrawal_period", "legal_status"} else "source_verified"
        return "high", requirement
    if DOSAGE_TERMS.search(text):
        return "high", "source_verified"
    return "normal", None


def _corpus_source_gate(source_url: Any, corpus: list[dict[str, Any]], legal_required: bool) -> tuple[str, list[dict[str, Any]]]:
    normalized = _normal_url(source_url)
    if not normalized:
        return "no_source_url", []
    matches = [row for row in corpus if _normal_url(row.get("source_url")) == normalized]
    if not matches:
        return "no_corpus_url_match", []
    verified = [row for row in matches if row.get("source_verified") is True]
    if not verified:
        return "matched_but_not_verified_in_corpus", matches
    if legal_required and not any(row.get("legal_status") not in {None, "", "unknown"} for row in verified):
        return "verified_match_but_legal_status_unknown_in_corpus", verified
    return "verified_match_in_corpus_metadata", verified


def _terms(text: str) -> set[str]:
    terms: set[str] = set()
    for match in re.finditer(r"[A-Za-z0-9]+(?:[./_%+-][A-Za-z0-9]+)*|[\u3400-\u9fff]+", text.casefold()):
        token = match.group(0)
        if re.fullmatch(r"[\u3400-\u9fff]+", token):
            if len(token) == 1:
                terms.add(token)
            else:
                terms.update(token[i:i + 2] for i in range(len(token) - 1))
        else:
            terms.add(token)
    return terms


def search_corpus_candidates(question: str, corpus: list[dict[str, Any]], limit: int = 20) -> list[dict[str, Any]]:
    """Return lexical browsing suggestions only; these are never Gold evidence."""
    if not question.strip():
        return []
    query_terms = _terms(question)
    candidates = []
    for row in corpus:
        if row.get("retrieval_role") not in {"retrieval", "context_only"}:
            continue
        if row.get("duplicate_status") in {"exact_duplicate", "duplicate_source"}:
            continue
        if row.get("benchmark_eligible") is not True or row.get("risk_level") != "normal":
            continue
        text = str(row.get("text") or "")
        overlap = query_terms & _terms(text)
        if not overlap:
            continue
        candidates.append({
            "chunk_id": row.get("chunk_id"),
            "document_id": row.get("document_id"),
            "page": row.get("page_start"),
            "retrieval_role": row.get("retrieval_role"),
            "overlap_score": round(len(overlap) / max(len(query_terms), 1), 6),
        })
    candidates.sort(key=lambda item: (-item["overlap_score"], str(item.get("document_id") or ""), int(item.get("page") or 0), str(item.get("chunk_id") or "")))
    return candidates[:limit]


def _candidate_id(workbook_relative: str, sheet: str, source_row: int) -> str:
    source_key = f"{workbook_relative.replace(chr(92), '/')}\n{sheet}\n{source_row}".encode("utf-8")
    return "qbc_" + hashlib.sha256(source_key).hexdigest()[:20]


def normalize_workbook(path: str | Path, *, root: str | Path = ROOT, corpus: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    path, root = Path(path), Path(root)
    corpus = corpus or []
    relative_path = path.resolve().relative_to(root.resolve()).as_posix()
    species_candidate = next((species for species in SPECIES if species in path.name), None)
    sheets = read_xlsx_sheets(path)
    imported: list[dict[str, Any]] = []
    workbook_checksum = sha256_file(path)
    for sheet_name, rows in sheets.items():
        if "題目庫" not in sheet_name:
            continue
        header_index = next((index for index, (_, values) in enumerate(rows[:12]) if "題號" in values and "問題" in values), None)
        if header_index is None:
            continue
        header_row_number, header_values = rows[header_index]
        headers = [str(value).strip() if value is not None else "" for value in header_values]
        for source_row, cells in rows[header_index + 1:]:
            raw = {header: _clean(cells[index] if index < len(cells) else None) for index, header in enumerate(headers) if header}
            question = raw.get("問題")
            if not isinstance(question, str) or not question.strip():
                continue
            category = _canonical_category(raw)
            risk, verification_requirement = _risk(category, raw)
            legal_required = verification_requirement == "legal_status"
            source_gate, source_matches = _corpus_source_gate(raw.get("來源網址"), corpus, legal_required)
            gate_pass = source_gate == "verified_match_in_corpus_metadata"
            annotation_eligible = risk == "normal" or gate_pass
            suggestion_rows = search_corpus_candidates(question, corpus)
            required_fields_present = bool(raw.get("題號")) and bool(raw.get("基準答案"))
            import_status = "candidate" if required_fields_present else "needs_review"
            imported.append({
                "candidate_id": _candidate_id(relative_path, sheet_name, source_row),
                "species": species_candidate,
                "species_basis": "workbook_filename_candidate_only" if species_candidate else "unknown",
                "question_candidate": question.strip(),
                "answer_candidate": str(raw.get("基準答案")).strip() if raw.get("基準答案") is not None else None,
                "category_candidate": category,
                "difficulty_candidate": _difficulty(raw.get("難度")),
                "question_type": raw.get("題目形式"),
                "source_workbook": relative_path,
                "source_workbook_sha256": workbook_checksum,
                "source_sheet": sheet_name,
                "source_row": source_row,
                "import_status": import_status,
                "risk_level": risk,
                "verification_requirement": verification_requirement,
                "corpus_source_gate": source_gate,
                "corpus_source_match_count": len(source_matches),
                "annotation_eligible": annotation_eligible,
                "first_batch_eligible": annotation_eligible and risk == "normal",
                "evidence_search_candidate_chunk_ids": [row["chunk_id"] for row in suggestion_rows],
                "evidence_search_candidates": suggestion_rows,
                "evidence_search_status": "potential_chunks_found" if suggestion_rows else "no_keyword_match",
                "unsupported_reason": None,
                "original_metadata": raw,
            })
    return imported


def import_question_bank(directory: str | Path = ROOT / "fish test", *, root: str | Path = ROOT, corpus: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    directory, root = Path(directory), Path(root)
    corpus = corpus if corpus is not None else read_jsonl(root / "data" / "evaluation" / "corpus_v1.jsonl")
    records: list[dict[str, Any]] = []
    for path in sorted(directory.glob("*.xlsx")):
        if any(species in path.name for species in SPECIES):
            records.extend(normalize_workbook(path, root=root, corpus=corpus))
    return records


def make_draft_from_candidate(candidate: dict[str, Any], *, corpus_sha256: str, created_at: str | None = None) -> dict[str, Any]:
    """Create a draft only; workbook answers/evidence remain unpromoted."""
    return {
        "question_id": f"dev_{candidate['candidate_id']}",
        "split": "development",
        "created_at": created_at or utc_now(),
        "question": candidate.get("question_candidate"),
        "gold_answer": None,
        "question_bank_candidate_id": candidate.get("candidate_id"),
        "answerable": None,
        "expected_abstention": None,
        "category": candidate.get("category_candidate") or "fact",
        "target_category": candidate.get("category_candidate") or "fact",
        "category_candidate": candidate.get("category_candidate"),
        "category_verified": False,
        "difficulty": candidate.get("difficulty_candidate"),
        "difficulty_candidate": candidate.get("difficulty_candidate"),
        "difficulty_verified": False,
        "species": None,
        "candidate_species": candidate.get("species"),
        "provisional_species": candidate.get("species"),
        "species_basis": candidate.get("species_basis"),
        "species_verified": False,
        "topic": candidate.get("original_metadata", {}).get("主題"),
        "question_type": candidate.get("question_type"),
        "document_scope": "single-document",
        "gold_documents": [], "gold_pages": [], "gold_chunks": [],
        "required_chunks": [], "acceptable_chunks": [], "conflicting_chunks": [],
        "gold_evidence_snapshot": [], "supporting_claims": [],
        "candidate_ids": [candidate.get("candidate_id")],
        "candidate_chunk_ids": [],
        "evidence_search_candidate_chunk_ids": [],
        "source_verification_required": candidate.get("risk_level") == "high",
        "source_verification_status": "pending",
        "risk_level": candidate.get("risk_level", "normal"),
        "annotation_status": "draft",
        "annotator": None, "reviewer": None,
        "annotation_version": "0.1.0",
        "evaluation_corpus_version": "evaluation-corpus-v1",
        "evaluation_corpus_sha256": corpus_sha256,
        "question_verified": False, "evidence_verified": False,
        "notes": "由 Excel Question Bank 轉入的人工標註草稿。Excel 答案僅為 reference candidate；Gold Answer 與 evidence 必須由人工根據 Evaluation Corpus 建立。",
    }


def mark_unsupported(candidate: dict[str, Any], reason: str) -> dict[str, Any]:
    if not reason.strip():
        raise ValueError("unsupported candidate requires a human review reason")
    updated = dict(candidate)
    updated["import_status"] = "unsupported"
    updated["evidence_search_status"] = "unsupported_candidate"
    updated["unsupported_reason"] = reason.strip()
    return updated


def _reviewed_complete(row: dict[str, Any]) -> bool:
    checks = row.get("reviewer_confirmations") or {}
    required_checks = (
        "question_supported", "gold_answer_supported", "required_chunks_reasonable",
        "acceptable_chunks_reasonable", "species_within_evidence", "category_reasonable",
        "difficulty_reasonable",
    )
    return (
        row.get("annotation_status") == "reviewed"
        and row.get("question_verified") is True
        and row.get("evidence_verified") is True
        and bool(row.get("reviewer"))
        and row.get("reviewer") != row.get("annotator")
        and bool(row.get("review_notes"))
        and bool(row.get("reviewed_at"))
        and all(checks.get(key) is True for key in required_checks)
    )


def build_first_batch_priority_queue(candidates: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, dict[str, int]]]:
    """Return a deterministic review queue of candidate IDs, not Gold records."""
    selected: list[dict[str, Any]] = []
    fulfillment: dict[str, dict[str, int]] = {}
    used: set[str] = set()
    for category, target in FIRST_BATCH_TARGETS.items():
        pool = [
            row for row in candidates
            if row.get("category_candidate") == category
            and row.get("risk_level") == "normal"
            and row.get("first_batch_eligible") is True
            and row.get("import_status") != "unsupported"
            and row.get("candidate_id") not in used
        ]
        pool.sort(key=lambda row: (
            str(row.get("source_workbook") or ""),
            int(row.get("source_row") or 0),
            str(row.get("candidate_id") or ""),
        ))
        chosen = pool[:target]
        for row in chosen:
            used.add(str(row.get("candidate_id")))
            selected.append({
                "candidate_id": row.get("candidate_id"),
                "category_candidate": category,
                "species_candidate": row.get("species"),
                "source_workbook": row.get("source_workbook"),
                "source_sheet": row.get("source_sheet"),
                "source_row": row.get("source_row"),
                "question_candidate": row.get("question_candidate"),
            })
        fulfillment[category] = {"target": target, "available": len(pool), "selected": len(chosen)}
    return selected, fulfillment


def build_mapping_report(candidates: list[dict[str, Any]], questions: list[dict[str, Any]]) -> dict[str, Any]:
    questions_by_candidate: dict[str, list[dict[str, Any]]] = {}
    for row in questions:
        candidate_id = row.get("question_bank_candidate_id")
        if candidate_id:
            questions_by_candidate.setdefault(str(candidate_id), []).append(row)
    candidate_statuses: dict[str, str] = {}
    for candidate in candidates:
        linked = questions_by_candidate.get(str(candidate.get("candidate_id")), [])
        candidate_statuses[str(candidate.get("candidate_id"))] = (
            "reviewed" if any(_reviewed_complete(row) for row in linked)
            else "annotated" if any(row.get("annotation_status") == "annotated" for row in linked)
            else "used_as_gold_draft" if linked
            else "unused"
        )
    statuses = Counter(candidate_statuses.values())
    priority_queue, priority_fulfillment = build_first_batch_priority_queue(candidates)
    return {
        "source_directory": "fish test",
        "imported_candidates": len(candidates),
        "species_count_basis": "candidate labels from workbook filenames only; not Gold species and not corpus evidence",
        "by_species": dict(sorted(Counter(str(row.get("species") or "unknown") for row in candidates).items())),
        "by_category": dict(sorted(Counter(str(row.get("category_candidate") or "unknown") for row in candidates).items())),
        "normal_risk": sum(row.get("risk_level") == "normal" for row in candidates),
        "high_risk": sum(row.get("risk_level") == "high" for row in candidates),
        "evidence_found_candidates": sum(bool(row.get("evidence_search_candidates")) for row in candidates),
        "evidence_not_found_candidates": sum(not row.get("evidence_search_candidates") for row in candidates),
        "candidates_with_corpus_suggestions": sum(bool(row.get("evidence_search_candidates")) for row in candidates),
        "candidates_without_corpus_suggestions": sum(not row.get("evidence_search_candidates") for row in candidates),
        "corpus_suggestion_chunk_count": sum(len(row.get("evidence_search_candidates") or []) for row in candidates),
        "evidence_search_note": "evidence_found_candidates counts only lexical corpus suggestions, not direct evidence support. Suggestions are never Gold evidence until manually selected and verified.",
        "annotation_eligible": sum(row.get("annotation_eligible") is True and row.get("import_status") != "unsupported" for row in candidates),
        "annotation_ineligible": sum(row.get("annotation_eligible") is not True or row.get("import_status") == "unsupported" for row in candidates),
        "first_batch_targets": FIRST_BATCH_TARGETS,
        "first_batch_eligible_candidates": sum(row.get("first_batch_eligible") is True and row.get("import_status") != "unsupported" for row in candidates),
        "first_batch_priority_queue": priority_queue,
        "first_batch_target_fulfillment": priority_fulfillment,
        "used_as_gold_draft": statuses["used_as_gold_draft"],
        "annotated": statuses["annotated"],
        "reviewed": statuses["reviewed"],
        "candidate_annotation_states": dict(sorted(statuses.items())),
        "note": "Candidate import never increments annotation_status on its own. reviewed counts require the recorded independent reviewer checks and provenance.",
    }


def refresh_mapping_report(root: str | Path = ROOT) -> dict[str, Any]:
    root = Path(root)
    candidates_path = root / "data" / "gold" / "question_bank_candidates.jsonl"
    questions_path = root / "data" / "gold" / "development" / "questions.jsonl"
    candidates = read_jsonl(candidates_path) if candidates_path.exists() else []
    questions = read_jsonl(questions_path)
    report = build_mapping_report(candidates, questions)
    write_json(root / "reports" / "evaluation" / "question_bank_mapping.json", report)
    return report


def save_import(directory: str | Path = ROOT / "fish test", *, root: str | Path = ROOT) -> dict[str, Any]:
    root = Path(root)
    records = import_question_bank(directory, root=root)
    atomic_write_jsonl(root / "data" / "gold" / "question_bank_candidates.jsonl", records)
    report = refresh_mapping_report(root)
    from .development import refresh_reports
    sprint_reports = refresh_reports(root)
    return {"records": len(records), "report": report, "sprint": sprint_reports["sprint"]}
