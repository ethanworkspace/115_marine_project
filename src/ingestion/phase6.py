"""Phase 6 recovery, source verification, table triage, and eligibility reports.

This module consumes only the experimental parser v2 reports and source manifest.
It never writes to the production vector store or runs the production chunker.
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .gate import aggregate_document, apply_ingestion_status, evaluate_page
from .parsers.ocr import discover_ocr_backends, evaluate_ocr_quality
from .parsers.router import load_parser_config


ROOT = Path(__file__).resolve().parents[2]
_UNIT_RE = re.compile(r"(?<!\w)(?:mg\s*/\s*L|ppm|%|℃|°\s*C|deg\s*C|ppt|kg|g|mL|L)(?!\w)", re.I)
_NUMBER_RE = re.compile(r"(?<!\w)[+-]?(?:\d+(?:[.,]\d+)*|[.,]\d+)(?!\w)")

PRIORITY_TERMS = {
    1: ("法規", "法令", "用藥", "藥物", "動物用藥", "停藥期", "休藥", "withdrawal", "medication", "drug", "regulation", "legal", "water quality standard", "水質安全", "安全標準", "水質標準"),
    2: ("養殖", "手冊", "疾病", "病害", "水質", "管理", "sop", "aquaculture", "disease", "manual", "water quality"),
    3: ("研究", "論文", "大學", "研究所", "research", "journal", "university", "thesis", "paper"),
}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in records), encoding="utf-8", newline="\n")
    temporary.replace(path)


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    temporary.replace(path)


def classify_source_priority(document: dict[str, Any]) -> tuple[int, str]:
    metadata = document.get("document_metadata") or {}
    haystack = " ".join(str(value or "") for value in (
        document.get("title"), document.get("file_path"), document.get("document_type"),
        document.get("topics"), document.get("organization"), metadata.get("title"),
        metadata.get("document_type"), metadata.get("topics"), metadata.get("organization"),
    )).casefold()
    source_tier = document.get("source_tier", metadata.get("source_tier"))
    high_risk = [term for term in PRIORITY_TERMS[1] if term.casefold() in haystack]
    if high_risk:
        return 1, "high_risk_subject_keyword; verify source and legal currentness:" + ",".join(high_risk[:5])
    research = [term for term in PRIORITY_TERMS[3] if term.casefold() in haystack]
    if source_tier == 2 or research:
        basis = "existing_source_tier_2" if source_tier == 2 else "research_or_academic_keyword:" + ",".join(research[:5])
        return 3, basis
    official_manual = [term for term in PRIORITY_TERMS[2] if term.casefold() in haystack]
    if official_manual:
        authority_note = "source authority still unverified" if source_tier != 1 else "source tier 1 recorded"
        return 2, "official_manual_topic_candidate (" + authority_note + "):" + ",".join(official_manual[:5])
    return 4, "general_reference_or_topic_not_identifiable_from_current_metadata"


def _normalized_signature(table: dict[str, Any]) -> str:
    headers = " ".join(str(cell) for cell in table.get("headers", [])).casefold()
    caption = str(table.get("caption") or "").casefold()
    normalized = re.sub(r"[^\w\u3400-\u9fff]+", "", headers + caption)
    return normalized if len(normalized) >= 4 else ""


def classify_tables(pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return conservative classifications; every class includes its heuristic evidence."""
    page_by_key = {(page.get("document_id"), page.get("page_number")): page for page in pages}
    tables = [table for page in pages for table in page.get("tables", [])]
    tables.sort(key=lambda table: (str(table.get("document_id")), table.get("page_number") or 0, str(table.get("table_id"))))

    signatures: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for table in tables:
        signature = _normalized_signature(table)
        if signature:
            signatures[(str(table.get("document_id")), signature)].append(table)
    multipage_ids: set[str] = set()
    for group in signatures.values():
        group.sort(key=lambda item: item.get("page_number") or 0)
        for first, second in zip(group, group[1:]):
            p1, p2 = first.get("page_number"), second.get("page_number")
            if p1 is not None and p2 is not None and 0 < p2 - p1 <= 2:
                multipage_ids.update((str(first.get("table_id")), str(second.get("table_id"))))

    output: list[dict[str, Any]] = []
    for table in tables:
        page = page_by_key.get((table.get("document_id"), table.get("page_number")), {})
        headers = [str(value).strip() for value in table.get("headers", [])]
        rows = table.get("rows", [])
        row_count = int(table.get("row_count", len(rows)))
        columns = int(table.get("column_count", max([len(headers), *(len(row) for row in rows)], default=0)))
        populated = sum(bool(str(cell).strip()) for row in rows for cell in row)
        cells = sum(len(row) for row in rows)
        nonempty_ratio = populated / max(1, cells)
        warnings = [str(value) for value in table.get("warnings", [])]
        widths = {len(row) for row in rows if row}
        reasons: list[str] = []
        if str(table.get("table_id")) in multipage_ids:
            classification = "multi_page_table"
            reasons.append("same document has matching table signature on a nearby page; heuristic only")
        elif page.get("image_coverage", 0) >= 0.40 and len(str(page.get("native_text") or "").strip()) < 40:
            classification = "image_table"
            reasons.append("page has high image coverage and little native text")
        elif row_count == 0 or columns < 2 or cells == 0:
            classification = "false_positive"
            reasons.append("extractor returned no body rows, fewer than two columns, or no cells")
        elif "header_column_count_mismatch" in warnings and len(widths) > 1:
            classification = "merged_cell_table"
            reasons.append("row-width variation and header mismatch may indicate merged cells")
        elif columns >= 8 or not headers or nonempty_ratio < 0.60 or any("sparse_or_empty_cells" in warning for warning in warnings):
            classification = "complex_layout"
            if columns >= 8:
                reasons.append("wide table candidate (at least eight columns)")
            if not headers:
                reasons.append("headers were not reliably extracted")
            if nonempty_ratio < 0.60:
                reasons.append("sparse cell population suggests a complex or damaged layout")
        elif not table.get("needs_review") and len(headers) >= 2 and row_count >= 2:
            classification = "simple_table"
            reasons.append("parser reported a complete header and at least two body rows without review flags")
        else:
            classification = "unknown"
            reasons.append("available structure does not support a safer heuristic class")

        # Do not auto-reject a heuristic false-positive candidate.
        status = "accepted_with_warning" if classification == "simple_table" else "review"
        if status == "accepted_with_warning":
            reasons.append("structured table is parser-pass only; source verification remains separate")
        result = dict(table)
        result.update({
            "classification": classification,
            "classification_reason": reasons,
            "classification_is_heuristic": True,
            "ingestion_status": status,
            "review_reason": [] if status != "review" else reasons,
            "reviewed_by": None,
            "reviewed_at": None,
            "source_file_checksum": page.get("file_checksum"),
            "parser_version": page.get("parser_version"),
        })
        output.append(result)
    return output


def _gold_candidates(pages: list[dict[str, Any]], limit: int = 50) -> list[dict[str, Any]]:
    quotas = [
        ("normal_text", 8, lambda p, blob: bool(str(p.get("native_text") or "").strip())),
        ("table", 7, lambda p, blob: bool(p.get("tables"))),
        ("numbers", 7, lambda p, blob: bool(_NUMBER_RE.search(blob))),
        ("units", 6, lambda p, blob: bool(_UNIT_RE.search(blob))),
        ("species", 6, lambda p, blob: any(term in blob for term in ("吳郭魚", "虱目魚", "石斑魚", "鱸魚", "烏魚", "鰻魚", "tilapia", "grouper"))),
        ("disease", 6, lambda p, blob: any(term in blob.casefold() for term in ("疾病", "病害", "白點病", "弧菌", "disease", "pathology"))),
        ("regulation", 6, lambda p, blob: any(term in blob.casefold() for term in ("法規", "用藥", "停藥期", "藥物", "regulation", "withdrawal"))),
        ("ocr_candidate", 4, lambda p, blob: p.get("classification") == "ocr_candidate"),
    ]
    keyed = []
    for page in pages:
        if page.get("page_number") is None:
            continue
        blob = " ".join(str(value or "") for value in (
            page.get("title"), page.get("file_path"), page.get("native_text"), page.get("text"),
            page.get("document_metadata", {}).get("topics"), page.get("document_metadata", {}).get("species"),
        ))
        keyed.append((page, blob))
    keyed.sort(key=lambda pair: (str(pair[0].get("document_id")), pair[0].get("page_number") or 0))
    selected: list[dict[str, Any]] = []
    used: set[tuple[str, int | None]] = set()
    for category, quota, predicate in quotas:
        matches = [(page, blob) for page, blob in keyed if predicate(page, blob) and (page.get("document_id"), page.get("page_number")) not in used]
        fallbacks = [(page, blob) for page, blob in keyed if (page.get("document_id"), page.get("page_number")) not in used]
        for index in range(quota):
            matched_stratum = bool(matches)
            pool = matches if matched_stratum else fallbacks
            if not pool or len(selected) >= limit:
                break
            page, _ = pool[0]
            key = (page.get("document_id"), page.get("page_number"))
            used.add(key)
            matches = [pair for pair in matches if (pair[0].get("document_id"), pair[0].get("page_number")) != key]
            fallbacks = [pair for pair in fallbacks if (pair[0].get("document_id"), pair[0].get("page_number")) != key]
            selected.append({
                "document_id": page.get("document_id"),
                "page_number": page.get("page_number"),
                "title": page.get("title"),
                "file_path": page.get("file_path"),
                "file_checksum": page.get("file_checksum"),
                "suggested_stratum": category,
                "selection_basis": "matching_existing_parser_metadata_or_text" if matched_stratum else "balanced_reserve; category requires human confirmation",
                "human_confirmation_required": True,
                "ground_truth_text": None,
            })
    return selected[:limit]


def build_phase6_reports(repo_root: str | Path = ROOT) -> dict[str, Any]:
    root = Path(repo_root)
    manifest_path = root / "reports" / "document_manifest.jsonl"
    inventory_path = root / "reports" / "parsing" / "page_inventory.jsonl"
    parser_report_path = root / "reports" / "parsing" / "parser_quality.json"
    manifest = read_jsonl(manifest_path)
    pages = read_jsonl(inventory_path)
    physical_pdf_pages = [page for page in pages if page.get("page_number") is not None and str(page.get("file_path", "")).lower().endswith(".pdf")]
    parser_report = json.loads(parser_report_path.read_text(encoding="utf-8"))
    config = load_parser_config(root / "config" / "parsing.yaml")
    backend_status = discover_ocr_backends(config)
    manifest_by_id = {str(item["document_id"]): item for item in manifest}

    # Table classification and page/document gate states are added only to parser-v2 reports.
    tables = classify_tables(pages)
    tables_by_page: dict[tuple[str, int | None], list[dict[str, Any]]] = defaultdict(list)
    for table in tables:
        tables_by_page[(str(table.get("document_id")), table.get("page_number"))].append(table)
    tables_by_id = {str(table.get("table_id")): table for table in tables}
    page_statuses: dict[str, list[str]] = defaultdict(list)
    for page in pages:
        document = manifest_by_id.get(str(page.get("document_id")), {})
        metadata = page.get("document_metadata") or {}
        topic_priority, _ = classify_source_priority({**document, "document_metadata": metadata})
        high_risk = topic_priority == 1
        page["selected_text"] = str(page.get("selected_text") or page.get("text") or "")
        page["ocr_languages"] = page.get("ocr_languages") or []
        status, reasons = evaluate_page({**page, **{
            "legal_status": document.get("legal_status", metadata.get("legal_status")),
            "source_id": document.get("source_id", page.get("source_id")),
            "source_url": document.get("source_url", page.get("source_url")),
        }}, high_risk_legal_topic=high_risk)
        if high_risk and document.get("legal_status", "unknown") != "current":
            status = "review"
            reasons = list(dict.fromkeys([*reasons, "priority_1_source_requires_human_legal_currentness_verification"]))
        apply_ingestion_status(page, status, reasons)
        page["tables"] = [tables_by_id.get(str(table.get("table_id")), table) for table in page.get("tables", [])]
        page_statuses[str(page.get("document_id"))].append(status)

    document_eligibility: list[dict[str, Any]] = []
    source_candidates: list[dict[str, Any]] = []
    verified_ids: set[str] = set()
    for document in manifest:
        doc_id = str(document["document_id"])
        source_id = document.get("source_id")
        source_url = document.get("source_url")
        # Presence is not proof: only an explicit, human-recorded verification marker counts.
        source_verified = bool(
            document.get("source_verification_status") == "verified"
            and source_id and source_id != "unverified" and source_url
            and document.get("organization") and document.get("source_tier")
        )
        if source_verified:
            verified_ids.add(doc_id)
        priority, basis = classify_source_priority(document)
        missing = []
        for field, value in (
            ("source_id", None if source_id == "unverified" else source_id),
            ("source_url", source_url), ("organization", document.get("organization")),
            ("source_tier", document.get("source_tier")), ("publication_date", document.get("publication_date")),
            ("download_date", document.get("download_date")),
            ("source_verification_status", document.get("source_verification_status")),
            ("legal_status", None if document.get("legal_status") == "unknown" else document.get("legal_status")),
            ("species", document.get("species")), ("topics", document.get("topics")),
        ):
            if not value:
                missing.append(field)
        if priority == 1:
            for field in ("effective_date", "expiry_date", "version"):
                if not document.get(field):
                    missing.append(field)
        candidate = {
            "document_id": doc_id,
            "title": document.get("title"),
            "file_path": document.get("file_path"),
            "current_source_metadata": {
                "source_id": source_id, "source_url": source_url,
                "organization": document.get("organization"), "source_tier": document.get("source_tier"),
                "legal_status": document.get("legal_status"), "publication_date": document.get("publication_date"),
                "effective_date": document.get("effective_date"), "expiry_date": document.get("expiry_date"),
                "version": document.get("version"), "species": document.get("species"),
                "topics": document.get("topics"), "document_type": document.get("document_type"),
                "language": document.get("language"),
            },
            "missing_fields": missing,
            "verification_priority": priority,
            "priority_basis": basis,
            "source_verified": source_verified,
        }
        source_candidates.append(candidate)
        status, reasons = aggregate_document(
            page_statuses.get(doc_id, []),
            conversion_status="unavailable" if Path(document.get("file_path", "")).suffix.lower() == ".doc" else "not_required",
            source_verified=source_verified,
        )
        document_eligibility.append({
            **document,
            "ingestion_status": status,
            "review_reason": reasons,
            "reviewed_by": None,
            "reviewed_at": None,
            "source_verified": source_verified,
            "verification_priority": priority,
            "page_status_counts": dict(Counter(page_statuses.get(doc_id, []))),
        })
    source_candidates.sort(key=lambda item: (item["verification_priority"], str(item["title"] or "").casefold(), item["document_id"]))

    root_reports = root / "reports"
    write_jsonl(root / "reports" / "parsing" / "page_inventory.jsonl", pages)
    write_jsonl(root / "reports" / "parsing" / "document_eligibility.jsonl", document_eligibility)
    write_jsonl(root_reports / "source_verification_candidates.jsonl", source_candidates)
    write_jsonl(root_reports / "tables" / "table_inventory.jsonl", tables)

    table_classes = Counter(item["classification"] for item in tables)
    table_reasons = Counter(reason for item in tables for reason in item["classification_reason"])
    parser_table_warnings = Counter(
        str(warning)
        for page in pages for table in page.get("tables", []) for warning in table.get("warnings", [])
    )
    table_summary = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "tables_total": len(tables),
        "classification_counts": dict(sorted(table_classes.items())),
        "ingestion_status_counts": dict(sorted(Counter(item["ingestion_status"] for item in tables).items())),
        "classification_reason_counts": dict(sorted(table_reasons.items())),
        "parser_warning_counts": dict(sorted(parser_table_warnings.items())),
        "prior_parser_counts": {
            "pass": int(parser_report.get("table_parse_success", 0)),
            "review": int(parser_report.get("table_parse_review", 0)),
        },
        "notes": [
            "Classifications are heuristics; false_positive is a review candidate and is not automatically rejected.",
            "The original six parser-pass tables are retained as simple-table candidates only when their structural evidence is complete.",
        ],
    }
    write_json(root / "reports" / "tables" / "table_summary.json", table_summary)

    # OCR quality statistics do not alter OCR text and never promote text through this report step.
    ocr_pages = [page for page in pages if page.get("classification") == "ocr_candidate" or page.get("ocr_text")]
    quality_rows = []
    ocr_counts: Counter[str] = Counter()
    number_total = unit_total = domain_total = 0
    for page in ocr_pages:
        text = str(page.get("ocr_text") or "")
        if text:
            report = evaluate_ocr_quality(text, page.get("ocr_confidence"), config)
            values = report.to_dict()
            status = page.get("ocr_quality_status") if page.get("ocr_quality_status") not in {None, "not_run"} else report.status
        else:
            status = page.get("ocr_quality_status", "not_run")
            values = {"status": status, "text_length": 0, "number_token_count": 0, "unit_token_count": 0, "domain_term_matches": 0, "domain_terms_found": [], "reasons": ["no_ocr_text_available"]}
        ocr_counts[str(status)] += 1
        number_total += int(values.get("number_token_count", 0))
        unit_total += int(values.get("unit_token_count", 0))
        domain_total += int(values.get("domain_term_matches", 0))
        quality_rows.append({
            "document_id": page.get("document_id"), "file_checksum": page.get("file_checksum"),
            "page_number": page.get("page_number"), "classification": page.get("classification"),
            "ocr_backend": page.get("ocr_backend"), "ocr_backend_version": page.get("ocr_backend_version"),
            "ocr_languages": page.get("ocr_languages", []), "ocr_confidence": page.get("ocr_confidence"),
            "ocr_status": status, **values,
        })
    quality_report = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "backend_discovery": backend_status,
        "default_languages": config.get("ocr", {}).get("tesseract_language", "chi_tra+eng"),
        "ocr_candidate_or_result_pages": len(ocr_pages),
        "pdf_pages_without_native_text": int(parser_report.get("no_native_text_pages", 0)),
        "ocr_candidates_with_some_native_text": sum(
            page.get("classification") == "ocr_candidate" and bool(str(page.get("native_text") or "").strip())
            for page in physical_pdf_pages
        ),
        "status_counts": dict(sorted(ocr_counts.items())),
        "number_token_count": number_total,
        "unit_token_count": unit_total,
        "domain_term_matches": domain_total,
        "per_page": quality_rows,
        "thresholds": config.get("ocr", {}),
        "note": "OCR quality statistics are descriptive. OCR text is never corrected or promoted by this report generator.",
    }
    write_json(root / "reports" / "ocr" / "ocr_quality.json", quality_report)

    # Create an empty gold file by design: only human-entered ground truth belongs there.
    gold_dir = root / "data" / "gold" / "ocr"
    gold_dir.mkdir(parents=True, exist_ok=True)
    gold_file = gold_dir / "ocr_gold_sample.jsonl"
    if not gold_file.exists():
        gold_file.write_text("", encoding="utf-8")
    gold_candidates = _gold_candidates(pages, 50)
    gold_strata = dict(sorted(Counter(item["suggested_stratum"] for item in gold_candidates).items()))
    write_jsonl(root / "reports" / "ocr" / "gold_sample_candidates.jsonl", gold_candidates)

    legacy_docs = [item for item in manifest if Path(item.get("file_path", "")).suffix.lower() == ".doc"]
    conversion_status = parser_report.get("legacy_doc_conversion_backend", {})
    legacy_rows = []
    for document in legacy_docs:
        doc_pages = [page for page in pages if page.get("document_id") == document.get("document_id")]
        page_warnings = [warning for page in doc_pages for warning in page.get("warnings", [])]
        page_record = doc_pages[0] if doc_pages else {}
        conversion_status_value = page_record.get("conversion_status", "unavailable")
        converted = conversion_status_value == "success"
        legacy_rows.append({
            "document_id": document.get("document_id"),
            "file_path": document.get("file_path"),
            "conversion_backend": page_record.get("conversion_backend"),
            "backend_probe": conversion_status,
            "conversion_status": conversion_status_value if converted else "manual_conversion_required",
            "conversion_attempts": page_record.get("conversion_attempts", []),
            "output_path": page_record.get("conversion_output_path"),
            "warnings": list(dict.fromkeys(page_warnings + ([] if converted else ["No conversion backend completed; original DOC remains unchanged."]))),
            "ingestion_status": page_record.get("ingestion_status", "review") if converted else "review",
            "file_checksum": document.get("checksum"),
        })
    write_json(root / "reports" / "recovery" / "legacy_doc.json", {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "documents_total": len(legacy_rows),
        "conversion_order": ["word-com", "libreoffice-headless"],
        "backend_probe": conversion_status,
        "documents": legacy_rows,
        "raw_documents_modified": False,
    })

    # Summary counts are intentionally explicit; the detailed JSONL records carry the provenance.
    document_counts = Counter(item["ingestion_status"] for item in document_eligibility)
    page_counts = Counter(page["ingestion_status"] for page in physical_pdf_pages)
    ocr_candidate_total = sum(page.get("classification") == "ocr_candidate" for page in physical_pdf_pages)
    ocr_processed = sum(bool(page.get("ocr_backend") and page.get("ocr_quality_status") in {"pass", "review", "reject", "failed"}) for page in physical_pdf_pages)
    page_accepted_native = sum(page.get("ingestion_status") in {"accepted", "accepted_with_warning"} and page.get("extraction_method") == "native" for page in physical_pdf_pages)
    page_accepted_ocr = sum(page.get("ingestion_status") in {"accepted", "accepted_with_warning"} and page.get("extraction_method") == "ocr" for page in physical_pdf_pages)
    source_verified_count = len(verified_ids)
    legal_current_count = sum(item.get("legal_status") == "current" and item.get("document_id") in verified_ids for item in document_eligibility)
    eligibility = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "indexing_performed": False,
        "documents_total": len(document_eligibility),
        "documents_accepted": document_counts["accepted"],
        "documents_warning": document_counts["accepted_with_warning"],
        "documents_review": document_counts["review"],
        "documents_rejected": document_counts["rejected"],
        "pages_total": len(physical_pdf_pages),
        "pages_accepted_native": page_accepted_native,
        "pages_accepted_ocr": page_accepted_ocr,
        "pages_warning": page_counts["accepted_with_warning"],
        "pages_review": page_counts["review"],
        "pages_rejected": page_counts["rejected"],
        "ocr_candidate_total": ocr_candidate_total,
        "ocr_processed": ocr_processed,
        "ocr_pass": ocr_counts["pass"],
        "ocr_review": ocr_counts["review"],
        "ocr_reject": ocr_counts["reject"],
        "ocr_backend_unavailable": ocr_counts["backend_unavailable"],
        "legacy_doc_total": len(legacy_rows),
        "legacy_doc_recovered": sum(row["conversion_status"] == "success" for row in legacy_rows),
        "legacy_doc_review": sum(row["ingestion_status"] == "review" for row in legacy_rows),
        "tables_total": len(tables),
        "tables_structured_accepted": sum(table["ingestion_status"] in {"accepted", "accepted_with_warning"} for table in tables),
        "tables_review": sum(table["ingestion_status"] == "review" for table in tables),
        "tables_rejected": sum(table["ingestion_status"] == "rejected" for table in tables),
        "source_verified_documents": source_verified_count,
        "source_unverified_documents": len(document_eligibility) - source_verified_count,
        "current_legal_documents": legal_current_count,
        "unknown_legal_documents": sum(item.get("legal_status") == "unknown" for item in document_eligibility),
        "gold_sample_candidates": len(gold_candidates),
        "gold_sample_strata": gold_strata,
        "gold_ground_truth_records": sum(1 for line in gold_file.read_text(encoding="utf-8").splitlines() if line.strip()),
        "notes": [
            "Page totals count physical PDF pages; Office/text flow records are represented in document-level recovery/eligibility reports.",
            "Accepted native/OCR page counts include accepted_with_warning; pages_warning is a status subtotal and overlaps those method counts.",
            "Source verification is based only on existing registry metadata plus a recorded URL and organization; no URL is inferred from filenames.",
            "Unknown legal status remains unknown and is never promoted to current by this report generator.",
        ],
    }
    write_json(root_reports / "corpus_eligibility.json", eligibility)
    return {
        "eligibility": eligibility,
        "table_summary": table_summary,
        "ocr_quality": quality_report,
        "legacy_doc": {"documents_total": len(legacy_rows), "backend_probe": conversion_status},
        "source_priority_counts": dict(sorted(Counter(str(item["verification_priority"]) for item in source_candidates).items())),
        "gold_sample_candidates": len(gold_candidates),
        "gold_sample_strata": gold_strata,
    }


def main() -> None:
    result = build_phase6_reports()
    print(json.dumps({
        "eligibility": {key: value for key, value in result["eligibility"].items() if key != "notes"},
        "table_classification_counts": result["table_summary"]["classification_counts"],
        "ocr_status_counts": result["ocr_quality"]["status_counts"],
        "legacy_doc_total": result["legacy_doc"]["documents_total"],
        "source_priority_counts": result["source_priority_counts"],
        "gold_sample_candidates": result["gold_sample_candidates"],
        "gold_sample_strata": result["gold_sample_strata"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
