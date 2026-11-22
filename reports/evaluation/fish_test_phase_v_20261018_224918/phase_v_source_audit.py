from __future__ import annotations

import csv
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
RUN = Path(__file__).resolve().parent
PHASE_U = ROOT / "reports/evaluation/fish_test_phase_u_20261018_195823"


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inspect_file(path: Path) -> dict:
    result = {"file_exists": path.is_file(), "file_size_bytes": path.stat().st_size if path.is_file() else None,
              "format": path.suffix.lower().lstrip(".") if path.suffix else "extensionless",
              "extracted_characters": None, "page_count": None, "empty_pages": None,
              "document_metadata": {}, "content_title_signals": [], "parser": None, "parser_error": None}
    if not path.is_file():
        return result
    suffix = path.suffix.lower()
    try:
        if suffix == ".pdf":
            import fitz
            doc = fitz.open(path)
            pages = [page.get_text("text") for page in doc]
            text = "\n".join(pages)
            result.update(page_count=len(doc), empty_pages=sum(not p.strip() for p in pages),
                          document_metadata=dict(doc.metadata or {}), parser="PyMuPDF text extraction diagnostic")
        elif suffix == ".docx":
            from docx import Document
            doc = Document(path)
            text = "\n".join(p.text for p in doc.paragraphs)
            text += "\n" + "\n".join(" | ".join(c.text for c in row.cells) for table in doc.tables for row in table.rows)
            result.update(parser="python-docx extraction diagnostic", page_count=None, empty_pages=None)
        elif suffix in {".html", ".htm", ".txt", ".md", ".xml", ".csv", ".json", ".jsonl"}:
            raw = path.read_bytes()
            for encoding in ("utf-8-sig", "utf-8", "cp950", "big5", "latin-1"):
                try:
                    text = raw.decode(encoding)
                    break
                except UnicodeDecodeError:
                    continue
            result["parser"] = "read-only text decoding diagnostic"
        elif suffix in {".xlsx", ".xlsm"}:
            from openpyxl import load_workbook
            book = load_workbook(path, read_only=True, data_only=True)
            cells = []
            for ws in book.worksheets:
                for row in ws.iter_rows(values_only=True):
                    cells.extend(str(x) for x in row if x is not None)
            text = "\n".join(cells)
            result.update(parser="openpyxl extraction diagnostic", page_count=len(book.worksheets), empty_pages=None)
        else:
            raw = path.read_bytes()
            text = raw[:2_000_000].decode("utf-8", errors="replace")
            result["parser"] = "best-effort UTF-8 preview only"
        result["extracted_characters"] = len(text)
        clean = re.sub(r"\s+", " ", text)
        result["content_title_signals"] = [clean[i:i + 180] for i in [0, max(0, clean.find("\n"))] if clean[i:i + 180]][:2]
    except Exception as exc:
        result["parser_error"] = f"{type(exc).__name__}: {exc}"
        result["parser"] = "failed"
    return result


owners = read_jsonl(PHASE_U / "source_owner_decision_update_57.jsonl")
audits = read_jsonl(PHASE_U / "source_rights_version_scope_audit_57_final.jsonl")
audit_by_record = {r["source_record_id"]: r for r in audits}
assert len(owners) == 57 and all(r.get("owner_decision") == "APPROVED" for r in owners)

manifest = {
    "manifest_version": "phase_v_owner_approval_manifest_v1",
    "decision_source": "Phase U source_owner_decision_update_57.jsonl, derived from explicit user-provided research-owner decision dated 2026-10-18",
    "decision_scope": "owner decision for research RAG consideration only; not a third-party license, not proof that all sources pass rights/version/species checks",
    "approval_file_status": "source_admission_owner_approval_57.json was not present; Phase U's auditable decision records are used instead",
    "record_count": len(owners),
    "owner_approved_count": sum(r.get("owner_decision") == "APPROVED" for r in owners),
    "distinct_sha256_count": len({r.get("checksum_sha256") for r in owners}),
    "records": [
        {"source_record_id": r.get("source_record_id"), "source_id": r.get("source_id"),
         "owner_decision": r.get("owner_decision"), "owner_decision_date": r.get("owner_decision_date"),
         "owner_decision_source": r.get("owner_decision_source"), "original_path": r.get("original_path"),
         "sha256": r.get("checksum_sha256"), "phase_u_rights_status": audit_by_record.get(r.get("source_record_id"), {}).get("rights_status"),
         "phase_u_admission_status": audit_by_record.get(r.get("source_record_id"), {}).get("source_admission_status")}
        for r in owners
    ],
}
(RUN / "source_approval_manifest_v1.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

blockers = []
for r in owners:
    a = audit_by_record[r["source_record_id"]]
    if a.get("admission_execution_status") != "blocked_source_specific_rights_version_or_identity":
        continue
    source_path = ROOT / r["original_path"]
    info = inspect_file(source_path)
    actual_hash = sha256_file(source_path) if source_path.is_file() else None
    hash_match = actual_hash == r.get("checksum_sha256") if actual_hash else False
    rights = a.get("rights_status")
    blocker_codes = []
    if not source_path.is_file():
        blocker_codes.append("SOURCE_FILE_MISSING")
    elif not hash_match:
        blocker_codes.append("SOURCE_CHECKSUM_MISMATCH")
    if not r.get("publisher") or "UNVERIFIED" in str(r.get("publisher")):
        blocker_codes.append("PUBLISHER_UNVERIFIED")
    if not r.get("url"):
        blocker_codes.append("OFFICIAL_URL_MISSING")
    if not r.get("version") or "UNVERIFIED" in str(r.get("version")):
        blocker_codes.append("VERSION_UNVERIFIED")
    if "unverified" in str(rights).lower() or "copyright_notice_or_rights_scope_unverified" in str(rights).lower():
        blocker_codes.append("FULLTEXT_OR_INDEX_RIGHTS_UNVERIFIED")
    if r.get("parsing_quality") is None:
        blocker_codes.append("PARSER_QUALITY_UNASSESSED")
    elif info.get("parser_error"):
        blocker_codes.append("PARSER_ERROR")
    species_signals = r.get("species_content_signals") or {}
    expected = (r.get("expected_species_and_categories") or {}).get("species_candidates") or []
    if expected and not species_signals:
        blocker_codes.append("SPECIES_SCOPE_UNVERIFIED")
    if info.get("page_count") and info.get("empty_pages", 0):
        blocker_codes.append("PARSER_EMPTY_PAGES_REVIEW")
    blockers.append({
        "source_record_id": r["source_record_id"], "source_id": r.get("source_id"), "title": r.get("title"),
        "original_path": r.get("original_path"), "sha256_expected": r.get("checksum_sha256"),
        "sha256_actual": actual_hash, "checksum_match": hash_match,
        "publisher_recorded": r.get("publisher"), "official_url_recorded": r.get("url"),
        "version_recorded": r.get("version"), "rights_status": rights,
        "owner_decision": r.get("owner_decision"), "file_inspection": info,
        "blocker_codes": list(dict.fromkeys(blocker_codes)),
        "blocker_explanation_from_phase_u": a.get("blocker_reason"),
        "decision": "BLOCKED_FOR_FULLTEXT_CORPUS_ADMISSION" if "FULLTEXT_OR_INDEX_RIGHTS_UNVERIFIED" in blocker_codes or "VERSION_UNVERIFIED" in blocker_codes else "REVIEW_REQUIRED_BEFORE_ADMISSION",
        "next_action": "Use only exact verified facts under a documented, source-specific basis; do not add full text/embeddings until processing scope is substantiated. Resolve missing metadata from the publisher or document itself where possible.",
        "not_inferred": ["third-party permission", "species applicability from keyword-only signals", "current-version status from local filename", "technical accuracy from checksum alone"],
    })

out_path = RUN / "source_blocker_resolution_50.jsonl"
out_path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in blockers), encoding="utf-8")
by_code = Counter(code for row in blockers for code in row["blocker_codes"])
summary = {
    "phase_u_owner_records": len(owners), "owner_approved": manifest["owner_approved_count"],
    "distinct_sha256": manifest["distinct_sha256_count"], "blocked_source_records_reaudited": len(blockers),
    "file_missing": sum(not row["file_inspection"]["file_exists"] for row in blockers),
    "checksum_match_count": sum(row["checksum_match"] for row in blockers),
    "checksum_mismatch_or_missing": sum(not row["checksum_match"] for row in blockers),
    "formats": dict(Counter(row["file_inspection"]["format"] for row in blockers)),
    "blocker_code_counts_nonexclusive": dict(by_code),
    "fulltext_or_index_rights_unverified": sum("FULLTEXT_OR_INDEX_RIGHTS_UNVERIFIED" in row["blocker_codes"] for row in blockers),
    "files_with_parse_errors": sum(bool(row["file_inspection"]["parser_error"]) for row in blockers),
    "admission_promotions": 0,
    "note": "Owner approval was not treated as third-party permission; no Phase U blocked source was promoted by this audit alone.",
}
(RUN / "source_blocker_resolution_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(summary, ensure_ascii=False, indent=2))
