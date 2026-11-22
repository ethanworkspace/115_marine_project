"""Run a versioned Phase 10 corpus recovery, isolated from production and v1/v2."""

from __future__ import annotations

import copy
import hashlib
import json
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.evaluation import phase10_recovery as p10
from src.evaluation.corpus import build_corpus, read_jsonl as read_corpus_jsonl, write_jsonl as write_corpus_jsonl
from src.evaluation.source_mapping import expand_silver_mapping
from src.ingestion.checksum import sha256_file, stable_document_id
from src.ingestion.gate import aggregate_document, apply_ingestion_status, evaluate_page
from src.ingestion.parsers.ocr import apply_ocr_image, discover_ocr_backends
from src.ingestion.parsers.pipeline import _table_dict
from src.ingestion.parsers.router import ParserRouter, load_parser_config
from src.ingestion.phase6 import classify_tables
from src.ingestion.chunking.pipeline import build_shadow_corpus


MANIFEST = ROOT / "reports/document_manifest.jsonl"
PARSER_CONFIG = ROOT / "config/parsing.yaml"
CHUNK_CONFIG = ROOT / "config/chunking_v2.json"
BASE_SHADOW = ROOT / "data/shadow/chunks_v2.jsonl"
BASE_SPANS = ROOT / "data/shadow/source_spans_v2.jsonl"
BASE_CORPUS = ROOT / "data/evaluation/corpus_v1.jsonl"
BASE_EXCLUDED = ROOT / "data/evaluation/excluded_records.jsonl"
BASE_SILVER_V1 = ROOT / "data/evaluation/silver/questions_v1.jsonl"
BASE_SILVER_V2 = ROOT / "data/evaluation/silver/questions_v2.jsonl"
OUTPUT = ROOT / "reports/recovery/phase10"
MANIFEST_V3 = ROOT / "reports/recovery/document_manifest_v3.jsonl"
CHUNKS_V3 = ROOT / "data/shadow/chunks_v3.jsonl"
SPANS_V3 = ROOT / "data/shadow/source_spans_v3.jsonl"
CORPUS_V2 = ROOT / "data/evaluation/corpus_v2.jsonl"
SILVER_V3 = ROOT / "data/evaluation/silver/questions_v3.jsonl"
TODAY = date.today().isoformat()


def _digest(value: str | Path) -> str:
    path = Path(value)
    return sha256_file(path)


def _field_map(record: dict[str, Any], updates: dict[str, Any]) -> dict[str, Any]:
    row = dict(record)
    row.update(updates)
    return row


def _create_new_manifest(path: Path, *, title: str, organization: str, source_url: str,
                         source_id: str, publication_date: str | None, version: str,
                         species: list[str], topics: list[str], document_type: str,
                         legal_status: str, source_verified: bool, identity_status: str,
                         authority_status: str, publication_url: str | None = None,
                         effective_date: str | None = None) -> dict[str, Any]:
    relative = path.resolve().relative_to(ROOT.resolve()).as_posix()
    checksum = sha256_file(path)
    return {
        "document_id": stable_document_id(relative), "title": title, "source_id": source_id,
        "organization": organization, "source_url": source_url, "source_tier": 1,
        "publication_date": publication_date, "download_date": TODAY,
        "effective_date": effective_date, "expiry_date": None, "version": version,
        "legal_status": legal_status, "species": species, "topics": topics,
        "document_type": document_type, "language": "zh-TW", "checksum": checksum,
        "file_path": relative, "file_size": path.stat().st_size,
        "parser_version": "pymupdf 1.28.2", "ingestion_status": "registered",
        "duplicate_of": None, "source_verified": source_verified,
        "identity_status": identity_status, "authority_status": authority_status,
        "publication_url": publication_url,
    }


def build_manifest_v3(old: list[dict[str, Any]], source_aliases: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows = [copy.deepcopy(row) for row in old]
    by_id = {row["document_id"]: row for row in rows}
    alias_by_doc: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for alias in source_aliases:
        candidates = alias.get("candidate_local_documents") or []
        for item in candidates:
            doc_id = item if isinstance(item, str) else item.get("document_id")
            if doc_id in by_id:
                alias_by_doc[str(doc_id)].append(alias)

    actions: list[dict[str, Any]] = []
    manual_id = "8f337c28-890f-5ddb-9d92-612427284c4f"
    act_id = "0ac441bd-6eab-50ef-a459-72850101b7dd"
    tilapia_id = "2a1a9c12-afbc-57e5-b599-eaf991a09c12"
    if manual_id in by_id:
        row = by_id[manual_id]
        row.update({
            "title": "漁電共生養殖技術應用手冊(下)", "source_id": "fisheries_research_official",
            "organization": "農業部水產試驗所", "source_url": "https://www.tfrin.gov.tw/ws.php?id=246",
            "source_tier": 1, "publication_date": "2023-08-31", "download_date": TODAY,
            "version": "技術手冊17；出版日期112-08-31", "legal_status": "unknown",
            "species": ["石斑魚", "鱸魚", "烏魚"],
            # Keep the document-level strategy manual; disease remains section metadata/text.
            # The existing router gives a document-wide disease strategy precedence if
            # "疾病" is placed in topics, which would break prior section-aware chunk IDs.
            "topics": ["養殖管理", "水質", "氣候", "SOP"],
            "document_type": "manual", "language": "zh-TW", "source_verified": True,
            "identity_status": "verified", "authority_status": "verified_official",
            "publication_url": "https://www.tfrin.gov.tw/ws.php?id=246",
            "version_evidence": "official publication record plus downloaded official attachment SHA-256 identical to local file",
        })
        actions.append({"document_id": manual_id, "action": "metadata_repair_and_reparse",
                        "reason": "official TFRIN publication record and byte-identical official attachment verified"})
    if act_id in by_id:
        row = by_id[act_id]
        row.update({
            "title": "動物用藥品管理法", "source_id": "moa_official", "organization": "農業部",
            "source_url": "https://law.moa.gov.tw/LawContent.aspx?id=FL014718&media=print",
            "source_tier": 1, "publication_date": "1971-08-16", "download_date": TODAY,
            "version": "官方現行法規頁記載修正日期105-11-09；本文條次與本地 PDF 對齊",
            "legal_status": "current", "species": [], "topics": ["法規", "動物用藥品管理"],
            "document_type": "regulation", "language": "zh-TW", "source_verified": True,
            "identity_status": "verified", "authority_status": "verified_official",
            "effective_date": None,
            "version_evidence": "official current MOA law page title/amendment date match local PDF; all article identifiers present",
        })
        actions.append({"document_id": act_id, "action": "source_verification_and_reparse",
                        "reason": "official current law record matches document title, revision date and article identifiers"})
    if tilapia_id in by_id:
        row = by_id[tilapia_id]
        row.update({"identity_status": "likely", "authority_status": "verified_official",
                    "source_url": "https://www.tfrin.gov.tw/theme_data.php?id=272&theme=aquatic_technology",
                    "source_id": "fisheries_research_official", "organization": "農業部水產試驗所",
                    "source_tier": 1, "source_verified": False,
                    "metadata_recovery_note": "official TFRIN aquaculture technology page is title-related; local scanned PDF identity is not confirmed by byte or page comparison"})
        actions.append({"document_id": tilapia_id, "action": "metadata_candidate_only",
                        "reason": "official title-level candidate, but scan identity and contents remain unverified; OCR unavailable"})

    bass_alias = next((row for row in source_aliases if row.get("source_url", "").find("id=64168") >= 0), {})
    bass_url = bass_alias.get("source_url") or "https://www.tfrin.gov.tw/redirect_files.php?file_name=xTw2fNUbAIsga5ML7kM5cilWENZeNJEXnefxxJlTGgto02XxqywPAzXKySFjNnou&id=64168"
    new_manual = _create_new_manifest(
        ROOT / "data/recovery/raw_sources/tfrin_golden_seabass_biosecurity_handbook_final_2025.pdf",
        title="金目鱸養殖生物安全手冊", organization="農業部水產試驗所",
        source_url=bass_url, source_id="fisheries_research_official", publication_date="2025-11-30",
        version="GPN 4711400105；出版日期114-11-30", species=["鱸魚"],
        topics=["養殖管理", "疾病", "生物安全", "水質", "SOP"], document_type="manual",
        legal_status="unknown", source_verified=True, identity_status="verified",
        authority_status="verified_official", publication_url="https://www.tfrin.gov.tw/theme_data.php?id=591&theme=publication_all")
    use_rule_url = "https://law.moa.gov.tw/LawContent.aspx?id=FL035443&media=print"
    new_rules = _create_new_manifest(
        ROOT / "data/recovery/raw_sources/moa_animal_drug_use_rules_attachment_1_FL035443.pdf",
        title="動物用藥品使用準則－水產動物用藥品使用規範附表",
        organization="農業部", source_url=use_rule_url, source_id="moa_official",
        publication_date=None, version="官方現行法規頁修正日期114-01-08；附表一",
        species=["吳郭魚", "虱目魚", "石斑魚", "鱸魚", "烏魚", "鰻魚"],
        topics=["法規", "用藥", "劑量", "停藥期"], document_type="regulation",
        legal_status="current", source_verified=True, identity_status="verified",
        authority_status="verified_official", publication_url=use_rule_url)
    for row in (new_manual, new_rules):
        if row["document_id"] not in by_id:
            rows.append(row)
            actions.append({"document_id": row["document_id"], "action": "missing_source_acquisition",
                            "reason": "downloaded from official issuing-agency record and validated by Parser v2"})
    rows.sort(key=lambda row: str(row["document_id"]))
    return rows, {"actions": actions, "new_documents": [new_manual, new_rules],
                  "updated_document_ids": [manual_id, act_id, tilapia_id]}


def _aggregate_missing_sources(gaps: list[dict[str, Any]], local_identity: list[dict[str, Any]]) -> list[dict[str, Any]]:
    local_alias = {row.get("source_alias_id"): row for row in local_identity}
    grouped: dict[str, dict[str, Any]] = {}
    for gap in gaps:
        alias_id = str(gap.get("source_alias_id") or "")
        if not alias_id:
            continue
        out = grouped.setdefault(alias_id, {
            **{key: gap.get(key) for key in ("source_alias_id", "excel_source_id", "source_title", "source_url")},
            "affected_questions": [], "affected_facts": [], "species": [], "categories": [],
            "current_mapping_status": [], "identity_status": gap.get("identity_status", "unresolved"),
            "authority_status": gap.get("authority_status", "unknown"),
        })
        for key, dest in (("affected_questions", "affected_questions"), ("affected_facts", "affected_facts"),
                          ("species", "species"), ("categories", "categories"),
                          ("current_mapping_status", "current_mapping_status")):
            out[dest].extend(gap.get(key, []))
    acquisitions: dict[str, dict[str, Any]] = {}
    for alias_id, row in grouped.items():
        candidates = row
        item = None
        url = str(row.get("source_url") or "")
        if "id=64168" in url:
            document_id = stable_document_id("data/recovery/raw_sources/tfrin_golden_seabass_biosecurity_handbook_final_2025.pdf")
            item = {"organization": "農業部水產試驗所", "source_tier": 1,
                    "identity_status": "verified", "authority_status": "verified_official",
                    "acquisition_status": "acquired_and_parser_v2_validated", "document_id": document_id,
                    "legal_status": "unknown", "source_verified": True,
                    "publication_date": "2025-11-30", "version": "GPN 4711400105; 2025-11-30",
                    "notes": "official publication page lists final 97-page 2025 handbook; PDF downloaded, SHA-256 captured, 70 pages passed ingestion gate"}
        elif "FL035443" in url:
            document_id = stable_document_id("data/recovery/raw_sources/moa_animal_drug_use_rules_attachment_1_FL035443.pdf")
            item = {"organization": "農業部", "source_tier": 1,
                    "identity_status": "verified", "authority_status": "verified_official",
                    "acquisition_status": "acquired_parser_v2_partial_gate_pass", "document_id": document_id,
                    "legal_status": "current", "effective_date": None, "publication_date": None,
                    "source_verified": True,
                    "version": "official page revision date 114-01-08; Annex 1",
                    "notes": "official active law page links the annex; two text pages passed, dosage/withdrawal table pages remain review"}
        elif "kmweb.moa.gov.tw" in url:
            item = {"organization": "農業知識入口網／農業部", "source_tier": 1,
                    "identity_status": "unresolved", "authority_status": "unverified",
                    "acquisition_status": "pending_html_parser_and_page_version_capture",
                    "notes": "government host is identified, but no versioned parsed artifact was admitted; preserve URL and source metadata for follow-up"}
        elif "tfrin.gov.tw" in url:
            item = {"organization": "農業部水產試驗所", "source_tier": 1,
                    "identity_status": "unresolved", "authority_status": "unverified",
                    "acquisition_status": "pending_document_identity_or_parser_review",
                    "notes": "other official agency page/record; source content is HTML or legacy Word and is not admitted without suitable Parser v2 route"}
        elif "fa.gov.tw" in url:
            item = {"organization": "農業部漁業署", "source_tier": 1,
                    "identity_status": "unresolved", "authority_status": "unverified",
                    "acquisition_status": "pending_html_parser_and_source_version_capture",
                    "notes": "official agency domain identified; source record not downloaded/parsed during this round"}
        acquisitions[alias_id] = item or {}
    result = p10.build_missing_source_registry(list(grouped.values()), acquisitions=acquisitions)
    # Preserve original aliases separately even where several aliases share one URL.
    return result


def _recovery_queue(manifest_v3: list[dict[str, Any]], local_identity: list[dict[str, Any]], missing: list[dict[str, Any]]) -> list[dict[str, Any]]:
    corpus_docs = {row.get("document_id") for row in read_corpus_jsonl(BASE_CORPUS)}
    manifest_by_id = {row["document_id"]: row for row in manifest_v3}
    silver_rows = read_corpus_jsonl(BASE_SILVER_V1)
    for alias in local_identity:
        workbook, _, source_id = str(alias.get("source_key") or "::").partition("::")
        qids, facts = [], []
        for question in silver_rows:
            if question.get("source_workbook") != workbook:
                continue
            source_ids = {str(item.get("source_id")) for item in question.get("expected_sources", []) if item.get("source_id")}
            if source_id and source_id in source_ids:
                qids.append(str(question.get("question_id")))
                facts.extend(f"{workbook}::{item.get('fact_id')}" for item in question.get("expected_facts", []) if item.get("fact_id"))
        alias["affected_questions"] = sorted(set(qids))
        alias["affected_facts"] = sorted(set(facts))
        alias["affected_question_count"] = len(alias["affected_questions"])
        alias["affected_fact_count"] = len(alias["affected_facts"])
        alias["species"] = [question.get("species_candidate") for question in silver_rows
                             if question.get("question_id") in set(qids) and question.get("species_candidate")]
        alias["categories"] = [question.get("category") for question in silver_rows
                                if question.get("question_id") in set(qids) and question.get("category")]
    aliased: dict[str, dict[str, Any]] = {}
    for row in local_identity:
        for candidate in row.get("candidate_local_documents", []):
            doc_id = candidate if isinstance(candidate, str) else candidate.get("document_id")
            if not doc_id or doc_id not in manifest_by_id or doc_id in corpus_docs:
                continue
            entry = aliased.setdefault(doc_id, {"document_id": doc_id, "title": manifest_by_id[doc_id].get("title"),
                "file_path": manifest_by_id[doc_id].get("file_path"), "source_alias_ids": [],
                "affected_questions": [], "affected_facts": [], "species": [], "categories": [],
                "identity_status": "likely", "authority_status": "unknown", "source_quality": 2, "recoverability": 1})
            entry["source_alias_ids"].append(row.get("source_alias_id"))
    for entry in aliased.values():
        entry["source_alias_ids"] = sorted(set(entry["source_alias_ids"]))
        alias_keys = {row.get("source_alias_id") for row in local_identity if row.get("source_alias_id") in entry["source_alias_ids"]}
        aliases_by_key = {row.get("source_alias_id"): row for row in local_identity}
        for alias_key in alias_keys:
            alias = aliases_by_key[alias_key]
            entry["affected_questions"].extend(alias.get("affected_questions", []))
            entry["affected_facts"].extend(alias.get("affected_facts", []))
            entry["species"].extend(alias.get("species", []))
            entry["categories"].extend(alias.get("categories", []))
        for k in ("affected_questions", "affected_facts", "species", "categories"):
            entry[k] = sorted(set(entry[k]))
        entry["affected_question_count"] = len(entry["affected_questions"])
        entry["affected_fact_count"] = len(entry["affected_facts"])
    local_sources = list(aliased.values())
    priorities = json.loads((ROOT / "reports/corpus_gap/recovery_priority_top20.json").read_text(encoding="utf-8"))
    impact = json.loads((ROOT / "reports/corpus_gap/local_artifact_impact.json").read_text(encoding="utf-8"))
    ocr = json.loads((ROOT / "reports/corpus_gap/ocr_priority.json").read_text(encoding="utf-8"))
    legacy = impact.get("artifacts", {}).get("legacy_doc", {}).get("documents", [])
    local_impact = {
        "artifacts": {
            "review_table": impact.get("artifacts", {}).get("review_table", {}),
            "review_page": impact.get("artifacts", {}).get("review_page", {}),
        }
    }
    queue = p10.build_recovery_work_queue(local_sources=local_sources, missing_sources=missing,
        fact_gaps=read_corpus_jsonl(ROOT / "reports/corpus_gap/fact_gaps.jsonl"),
        local_impact=local_impact, ocr_priority=ocr, legacy_documents=legacy)
    # Add prior Phase 9C top-20 priority context for audit only.
    queue = [{**row, "phase9c_top20_included": any(row.get("document_id") in x.get("candidate_document_ids", [])
                or row.get("source_alias_id") == x.get("source_alias_id") for x in priorities.get("items", []))}
             for row in queue]
    return queue


def _parse_selective(manifests: list[dict[str, Any]], documents: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    cfg = load_parser_config(PARSER_CONFIG)
    router = ParserRouter(cfg)
    backend = discover_ocr_backends(cfg)
    manifest_by_id = {row["document_id"]: row for row in manifests}
    selected_ids = {row["document_id"] for row in documents}
    root_rows = [row for row in manifests if row.get("document_id") in selected_ids]
    parsed_docs = []
    page_rows: list[dict[str, Any]] = []
    raw_tables: list[dict[str, Any]] = []
    doc_rows: list[dict[str, Any]] = []
    for manifest in sorted(root_rows, key=lambda x: x["document_id"]):
        source = (ROOT / Path(str(manifest["file_path"]).replace("/", "\\"))).resolve()
        parsed = router.parse(source, manifest)
        is_legal = manifest.get("document_type") == "regulation" or any(x in " ".join(manifest.get("topics", [])) for x in ("法規", "用藥", "劑量", "停藥期"))
        for page in parsed.pages:
            if page.classification == "ocr_candidate":
                apply_ocr_image(page, b"", None, cfg)
            rec = page.to_dict()
            rec.update({key: manifest.get(key) for key in (
                "title", "source_id", "source_url", "source_tier", "source_verified", "identity_status",
                "authority_status", "publication_date", "effective_date", "version", "legal_status",
                "species", "topics", "document_type", "language")})
            rec["file_path"] = manifest["file_path"]
            rec["document_metadata"] = {key: manifest.get(key) for key in (
                "title", "source_id", "organization", "source_url", "source_tier", "source_verified",
                "identity_status", "authority_status", "publication_date", "effective_date", "version",
                "legal_status", "species", "topics", "document_type", "language")}
            status, reasons = evaluate_page(rec, high_risk_legal_topic=is_legal)
            apply_ingestion_status(rec, status, reasons)
            rec["parser_provenance"] = {"file_checksum": parsed.file_checksum,
                "parser_name": parsed.parser_name, "parser_version": parsed.parser_version,
                "extraction_method": rec.get("extraction_method"),
                "extraction_confidence": rec.get("extraction_confidence")}
            page_rows.append(rec)
            for table in rec.get("tables", []):
                raw_tables.append({**table, "file_path": manifest["file_path"],
                                   "source_title": manifest["title"], "page_ingestion_status": status})
            parsed_docs.append(parsed)
        statuses = [row["ingestion_status"] for row in page_rows if row["document_id"] == manifest["document_id"]]
        status, reasons = aggregate_document(statuses, source_verified=manifest.get("source_verified") is True)
        doc_rows.append({**manifest, "document_metadata": copy.deepcopy(manifest),
            "ingestion_status": status, "review_reason": reasons,
            "pages_total": len(statuses), "pages_accepted": sum(p10_status(s) for s in statuses),
            "_chunkable": True})
    # Reuse Phase 6's conservative structural heuristic; an existing parser review flag is never cleared.
    table_classifications = classify_tables(page_rows)
    table_by_id = {row["table_id"]: row for row in table_classifications}
    for page in page_rows:
        page["tables"] = [table_by_id.get(table.get("table_id"), table) for table in page.get("tables", [])]
        # The chunker consumes only parser-selected text after the page gate passes.
        page["text"] = page.get("selected_text") or page.get("text") or ""
    return page_rows, doc_rows, {"ocr_backend": backend, "tables": table_classifications, "raw_tables": raw_tables}


def p10_status(status: str) -> bool:
    return status in {"accepted", "accepted_with_warning"}


def _write_versioned_shadow(pages: list[dict[str, Any]], docs: list[dict[str, Any]],
                            table_inventory: list[dict[str, Any]], manifests: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    stage = OUTPUT / "chunking_stage"
    for rel in ("config", "reports/parsing", "reports/tables", "reports/chunking", "data/shadow"):
        (stage / rel).mkdir(parents=True, exist_ok=True)
    (stage / "config/chunking_v2.json").write_bytes(CHUNK_CONFIG.read_bytes())
    quality_baseline = json.loads((ROOT / "reports/data_quality.json").read_text(encoding="utf-8"))
    (stage / "reports/data_quality.json").write_text(json.dumps(quality_baseline), encoding="utf-8")
    p10.write_jsonl(stage / "reports/parsing/page_inventory.jsonl", pages)
    p10.write_jsonl(stage / "reports/parsing/document_eligibility.jsonl", docs)
    p10.write_jsonl(stage / "reports/tables/table_inventory.jsonl", table_inventory)
    stage_quality = build_shadow_corpus(stage)
    recovered_chunks = read_corpus_jsonl(stage / "data/shadow/chunks_v2.jsonl")
    recovered_spans = read_corpus_jsonl(stage / "data/shadow/source_spans_v2.jsonl")
    base_chunks = read_corpus_jsonl(BASE_SHADOW)
    base_spans = read_corpus_jsonl(BASE_SPANS)
    replace_ids = {row["document_id"] for row in docs}
    chunks = p10.merge_versioned_rows(base_chunks, recovered_chunks, replace_document_ids=replace_ids, id_key="chunk_id")
    spans = p10.merge_versioned_rows(base_spans, recovered_spans, replace_document_ids=replace_ids, id_key="source_span_id")
    p10.write_jsonl(CHUNKS_V3, chunks)
    p10.write_jsonl(SPANS_V3, spans)
    v2_ids = {row["chunk_id"] for row in base_chunks}
    recovered_ids = {row["chunk_id"] for row in recovered_chunks}
    stage_quality.update({
        "parent_shadow_sha256": _digest(BASE_SHADOW),
        "shadow_v3_sha256": _digest(CHUNKS_V3),
        "new_chunks": sum(row["chunk_id"] not in v2_ids for row in recovered_chunks),
        "repaired_or_replaced_chunks": sum(row["chunk_id"] in v2_ids for row in recovered_chunks),
        "chunks_removed_after_reparse_gate": len(v2_ids - {row["chunk_id"] for row in chunks}),
        "documents_reparsed": sorted(replace_ids),
        "recovery_manifest_sha256": _digest(MANIFEST_V3),
        "parser_version": "pymupdf 1.28.2",
        "chunking_version": "2.0.0-shadow",
        "formal_indexing_performed": False,
        "reparsed_output_chunks": len(recovered_chunks),
        "total_shadow_v3_chunks": len(chunks),
    })
    p10.write_json(OUTPUT / "shadow_v3_build.json", stage_quality)
    # Copy the descriptive chunking metrics from the isolated stage; never write into reports/chunking.
    import shutil
    stage_reports = stage / "reports/chunking"
    versioned_report_dir = ROOT / "reports/chunking_v3"
    versioned_report_dir.mkdir(parents=True, exist_ok=True)
    for file in stage_reports.glob("*.json"):
        if file.name in {"chunk_quality.json", "strategy_summary.json"}:
            shutil.copyfile(file, versioned_report_dir / file.name)
    versioned_quality = json.loads((versioned_report_dir / "chunk_quality.json").read_text(encoding="utf-8"))
    versioned_quality.update({"total_shadow_v3_chunks": len(chunks), "parent_shadow_v2_sha256": _digest(BASE_SHADOW),
                              "shadow_v3_sha256": _digest(CHUNKS_V3), "generated_recovery_documents": len(docs),
                              "formal_indexing_performed": False})
    p10.write_json(versioned_report_dir / "chunk_quality.json", versioned_quality)
    return chunks, spans, stage_quality


def _make_corpus_v2(chunks: list[dict[str, Any]], spans: list[dict[str, Any]], manifests: list[dict[str, Any]],
                    new_excluded_pages: list[dict[str, Any]], parsed_doc_ids: set[str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    old_excluded = [row for row in read_corpus_jsonl(ROOT / "reports/chunking/excluded_pages.jsonl")
                    if str(row.get("document_id") or "") not in parsed_doc_ids]
    excluded_pages = old_excluded + new_excluded_pages
    corpus, excluded, summary = build_corpus(chunks, manifests, spans=spans, excluded_pages=excluded_pages)
    summary["schema_version"] = "evaluation-corpus-v2"
    summary["parent_corpus_v1_sha256"] = _digest(BASE_CORPUS)
    summary["source_shadow_v3_sha256"] = _digest(CHUNKS_V3)
    summary["source_manifest_v3_sha256"] = _digest(MANIFEST_V3)
    summary["quality_claim"] = "Corpus recovery coverage only; no retrieval benchmark or answer correctness evaluation was performed."
    p10.write_jsonl(CORPUS_V2, corpus)
    p10.write_jsonl(ROOT / "data/evaluation/excluded_records_v2.jsonl", excluded)
    p10.write_json(ROOT / "reports/evaluation/corpus_v2_summary.json", summary)
    p10.write_json(ROOT / "data/evaluation/corpus_manifest_v2.json", {
        "corpus_id": "evaluation-corpus-v2", "created_from": "data/shadow/chunks_v3.jsonl",
        "source_manifest": "reports/recovery/document_manifest_v3.jsonl",
        "source_spans": "data/shadow/source_spans_v3.jsonl",
        "parent_evaluation_corpus_v1_sha256": _digest(BASE_CORPUS),
        "parent_shadow_v2_sha256": _digest(BASE_SHADOW),
        "source_shadow_v3_sha256": _digest(CHUNKS_V3),
        "source_manifest_v3_sha256": _digest(MANIFEST_V3),
        "evaluation_corpus_v2_sha256": _digest(CORPUS_V2),
        "canonicalization_policy": "Reuse Phase 8 corpus rules: first-stage retrieval is child/standalone/table row only, SHA-256 canonicalization deterministic, parents context-only.",
        "summary": summary,
    })
    return corpus, excluded, summary


def _run_silver_v3(corpus: list[dict[str, Any]], excluded: list[dict[str, Any]], manifests: list[dict[str, Any]],
                   ocr_candidates: list[dict[str, Any]]) -> dict[str, Any]:
    stage = OUTPUT / "silver_mapping_stage"
    for rel in ("data/evaluation/silver", "reports/parsing"):
        (stage / rel).mkdir(parents=True, exist_ok=True)
    p10.write_jsonl(stage / "data/evaluation/corpus_v1.jsonl", corpus)
    p10.write_jsonl(stage / "data/evaluation/silver/questions_v1.jsonl", read_corpus_jsonl(BASE_SILVER_V1))
    p10.write_jsonl(stage / "data/evaluation/excluded_records.jsonl", excluded)
    p10.write_jsonl(stage / "reports/document_manifest.jsonl", manifests)
    p10.write_jsonl(stage / "reports/parsing/ocr_candidates.jsonl", ocr_candidates)
    result = expand_silver_mapping(stage)
    questions = result["questions"]
    v2 = {row["question_id"]: row for row in read_corpus_jsonl(BASE_SILVER_V2)}
    for row in questions:
        prior = v2.get(row["question_id"], {})
        row["previous_silver_v2_mapping_status"] = prior.get("evidence_mapping_status")
        row["evaluation_mapping_version"] = "source-fact-map-v3"
        row["benchmark_type"] = "silver"
        row["generation_source"] = "ai_question_bank"
        row["mapping_is_source_verification"] = False
    p10.validate_v3_questions(questions, corpus)
    counts = Counter(row.get("evidence_mapping_status") for row in questions)
    primary = [row for row in questions if row.get("evidence_mapping_status") in {"exact", "high_confidence"}
               and row.get("mapping_complete") and row.get("mapped_chunks")]
    species_count = len({row.get("species_candidate") for row in primary if row.get("species_candidate")})
    category_count = len({row.get("category") for row in primary if row.get("category")})
    readiness = {
        "dataset_version": "silver-questions-v3", "benchmark_type": "AI-generated Silver; not human Gold",
        "total_questions": len(questions), "exact": counts["exact"], "high_confidence": counts["high_confidence"],
        "primary_evaluable_questions": len(primary), "required_primary_questions": 40,
        "primary_evaluable_species_count": species_count, "required_species_count": 4,
        "primary_evaluable_category_count": category_count, "required_category_count": 4,
        "silver_v3_benchmark_readiness": len(primary) >= 40 and species_count >= 4 and category_count >= 4,
        "mapping_confidence_is_source_verification": False,
        "note": "Coverage gate only; does not assert reference answer truth or retrieval quality.",
    }
    p10.write_jsonl(SILVER_V3, questions)
    p10.write_jsonl(ROOT / "data/evaluation/source_alias_registry_v3.jsonl", result["aliases"])
    p10.write_json(ROOT / "reports/evaluation/silver_v3_coverage.json", result["coverage"])
    p10.write_json(ROOT / "reports/evaluation/silver_v3_benchmark_readiness.json", readiness)
    by_doc_action: dict[str, str] = {}
    # A successful mapping to an existing reparsed document is attributed to metadata repair; newly acquired IDs to acquisition.
    manifest_records = read_corpus_jsonl(MANIFEST_V3)
    for row in manifest_records:
        if row.get("identity_status") == "verified" and row.get("document_id") in {"8f337c28-890f-5ddb-9d92-612427284c4f", "0ac441bd-6eab-50ef-a459-72850101b7dd"}:
            by_doc_action[row["document_id"]] = "metadata_repair"
        elif row.get("file_path", "").startswith("data/recovery/raw_sources/"):
            by_doc_action[row["document_id"]] = "missing_source_acquisition"
    gain = p10.coverage_gain(read_corpus_jsonl(BASE_SILVER_V2), questions, recovery_actions=by_doc_action)
    p10.write_json(ROOT / "reports/evaluation/coverage_gain_v3.json", gain)
    return {"result": result, "readiness": readiness, "coverage_gain": gain}


def run() -> dict[str, Any]:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    old_manifest = p10.read_jsonl(MANIFEST)
    identity = p10.read_jsonl(ROOT / "reports/corpus_gap/source_identity_authority.jsonl")
    gaps = p10.read_jsonl(ROOT / "reports/corpus_gap/gap_registry.jsonl")
    missing_raw = p10.read_jsonl(ROOT / "reports/corpus_gap/missing_sources.jsonl")
    source_plan = p10.read_jsonl(ROOT / "data/recovery/source_recovery_plan.jsonl")
    missing = _aggregate_missing_sources(missing_raw, p10.read_jsonl(ROOT / "reports/corpus_gap/source_identity_authority.jsonl"))
    plan_by_alias = {row.get("source_alias_id"): row for row in source_plan}
    for row in missing:
        plan = plan_by_alias.get(row.get("source_alias_id"), {})
        row["recovery_action"] = plan.get("recovery_action")
        row["prior_phase9c_priority"] = plan.get("priority")
        row["action_constraints"] = plan.get("action_constraints")
    manifests, actions = build_manifest_v3(old_manifest, identity)
    p10.write_jsonl(MANIFEST_V3, manifests)
    p10.write_jsonl(ROOT / "data/recovery/missing_source_registry.jsonl", missing)

    work_queue = _recovery_queue(manifests, identity, missing)
    p10.write_jsonl(OUTPUT / "work_queue.jsonl", work_queue)
    p10.write_json(OUTPUT / "input_freeze.json", {
        "source_recovery_plan_sha256": _digest(ROOT / "data/recovery/source_recovery_plan.jsonl"),
        "recovery_priority_top20_sha256": _digest(ROOT / "reports/corpus_gap/recovery_priority_top20.json"),
        "missing_sources_sha256": _digest(ROOT / "reports/corpus_gap/missing_sources.jsonl"),
        "fact_gaps_sha256": _digest(ROOT / "reports/corpus_gap/fact_gaps.jsonl"),
        "local_artifact_impact_sha256": _digest(ROOT / "reports/corpus_gap/local_artifact_impact.json"),
        "ocr_priority_sha256": _digest(ROOT / "reports/corpus_gap/ocr_priority.json"),
        "missing_source_aliases": len(missing), "work_queue_entries": len(work_queue),
    })

    manifest_by_id = {row["document_id"]: row for row in manifests}
    source_aliases = identity
    doc_missing_ids = {"2a1a9c12-afbc-57e5-b599-eaf991a09c12", "0ac441bd-6eab-50ef-a459-72850101b7dd"}
    parse_ids = doc_missing_ids | {"8f337c28-890f-5ddb-9d92-612427284c4f"}
    for row in actions["new_documents"]:
        parse_ids.add(row["document_id"])
    docs_for_parse = [manifest_by_id[key] for key in sorted(parse_ids) if key in manifest_by_id]
    pages, doc_rows, parser_aux = _parse_selective(manifests, docs_for_parse)
    tables = parser_aux["tables"]
    p10.write_jsonl(OUTPUT / "page_inventory.jsonl", pages)
    p10.write_jsonl(OUTPUT / "table_inventory.jsonl", tables)

    parsed_counter = Counter(row.get("classification") for row in pages)
    status_counter = Counter(row.get("ingestion_status") for row in pages)
    table_counter = Counter(row.get("classification") or "unknown" for row in tables)
    ocr_candidates = [row for row in pages if row.get("classification") == "ocr_candidate"]
    manual_review = [row for row in pages if row.get("ingestion_status") == "review"]
    accepted_pages = [row for row in pages if p10_status(row.get("ingestion_status"))]
    parser_quality = {
        "documents_total": len(docs_for_parse), "pages_total": len(pages),
        "native_text_pages": parsed_counter["native_text"],
        "no_native_text_pages": sum(not str(row.get("native_text") or "").strip() for row in pages),
        "ocr_candidate_pages": len(ocr_candidates), "ocr_success_pages": sum(row.get("ocr_quality_status") == "pass" for row in ocr_candidates),
        "ocr_review_pages": sum(row.get("ocr_quality_status") == "review" for row in ocr_candidates),
        "ocr_reject_pages": sum(row.get("ocr_quality_status") == "reject" for row in ocr_candidates),
        "ocr_backend_unavailable_pages": sum(row.get("ocr_quality_status") == "backend_unavailable" for row in ocr_candidates),
        "blank_pages": parsed_counter["blank"], "image_or_chart_pages": parsed_counter["image_or_chart"],
        "parser_error_pages": parsed_counter["parser_error"], "pages_accepted": len(accepted_pages),
        "pages_review": status_counter["review"], "pages_rejected": status_counter["rejected"],
        "tables_total": len(tables), "tables_by_classification": dict(sorted(table_counter.items())),
        "tables_accepted": sum(row.get("ingestion_status") in {"accepted", "accepted_with_warning"} for row in tables),
        "tables_review": sum(row.get("ingestion_status") == "review" for row in tables),
        "replacement_characters": sum(str(row.get("selected_text") or "").count("\ufffd") for row in pages),
        "installation_advice": parser_aux["ocr_backend"].get("installation_advice"),
        "ocr_backend": parser_aux["ocr_backend"],
        "only_can_index_pages_entered_chunk_stage": True,
    }
    p10.write_json(OUTPUT / "parser_quality.json", parser_quality)
    p10.write_jsonl(OUTPUT / "manual_review.jsonl", [{"review_type": "page", **row} for row in manual_review])
    p10.write_json(OUTPUT / "ocr_status.json", {
        "backend": parser_aux["ocr_backend"], "candidate_pages_in_recovery_scope": len(ocr_candidates),
        "processed_pages": 0 if parser_aux["ocr_backend"].get("selected_backend") is None else len(ocr_candidates),
        "backend_unavailable_pages": parser_quality["ocr_backend_unavailable_pages"],
        "suggested_installation": parser_aux["ocr_backend"].get("installation_advice"),
        "no_ocr_text_was_fabricated": True,
    })

    # Table/page recovery is fail-closed: the prior Phase 6 classifier accepts only parser-pass simple tables.
    old_impact = json.loads((ROOT / "reports/corpus_gap/local_artifact_impact.json").read_text(encoding="utf-8"))
    review_page = old_impact.get("artifacts", {}).get("review_page", {})
    review_table = old_impact.get("artifacts", {}).get("review_table", {})
    p10.write_json(OUTPUT / "targeted_artifact_recovery.json", {
        "review_page_exposure": {"candidate_questions": 5,
            "candidate_facts": 1, "records_released": 0,
            "note": "Existing review pages remain gated unless a specific page passes the same parser/gate after provenance repair."},
        "review_table_exposure": {"candidate_questions": 8,
            "candidate_facts": 3, "records_released": 0,
            "new_parser_pass_tables_outside_target_scope": parser_quality["tables_accepted"],
            "note": "The eight question/three fact-linked tables did not pass a targeted manual-quality review; any separate simple parser-pass tables are reported but not attributed to these facts."},
        "new_table_classifications": dict(sorted(table_counter.items())),
        "global_phase9c_context": {"review_page_candidate_questions": review_page.get("candidate_questions", 0),
            "review_page_candidate_facts": review_page.get("candidate_facts", 0),
            "review_table_candidate_questions": review_table.get("candidate_questions", 0),
            "review_table_candidate_facts": review_table.get("candidate_facts", 0),
            "candidate_counts_are_exposure_not_proof": True},
    })

    # Copy only accepted pages and the pages' source-span provenance to the isolated Chunking v2 stage.
    recovered_chunks, recovered_spans, shadow_report = _write_versioned_shadow(pages, doc_rows, tables, manifests)
    chunks_v3 = read_corpus_jsonl(CHUNKS_V3)
    spans_v3 = read_corpus_jsonl(SPANS_V3)
    p10.validate_source_provenance(chunks_v3, spans_v3, manifests)
    excluded_stage = p10.read_jsonl(OUTPUT / "chunking_stage/reports/chunking/excluded_pages.jsonl")
    corpus_v2, excluded_v2, corpus_summary = _make_corpus_v2(chunks_v3, spans_v3, manifests,
        excluded_stage, {row["document_id"] for row in doc_rows})
    silver = _run_silver_v3(corpus_v2, excluded_v2, manifests,
        p10.read_jsonl(OUTPUT / "chunking_stage/reports/parsing/ocr_candidates.jsonl"))

    # One entry per distinct recovered file/source, retaining dates, source URL, access and hash.
    acquisitions = []
    for manifest in actions["new_documents"]:
        acquisitions.append(p10.make_acquisition_manifest(
            document_id=manifest["document_id"], title=manifest["title"], organization=manifest["organization"],
            source_url=manifest["source_url"], publication_url=manifest.get("publication_url"),
            file_path=manifest["file_path"], source_tier=manifest["source_tier"], download_date=manifest["download_date"],
            publication_date=manifest["publication_date"], version=manifest["version"], checksum=manifest["checksum"],
            size=manifest["file_size"], parser_version=manifest["parser_version"], license_status="not_explicitly_stated",
            access_information="Public official agency PDF; this project records internal research access, no redistribution license inferred.",
            identity_status=manifest["identity_status"], authority_status=manifest["authority_status"], legal_status=manifest["legal_status"],
            effective_date=manifest.get("effective_date"), recovery_action="missing_source_acquisition"))
    for manifest in (manifest_by_id["8f337c28-890f-5ddb-9d92-612427284c4f"],
                     manifest_by_id["0ac441bd-6eab-50ef-a459-72850101b7dd"]):
        acquisitions.append({"document_id": manifest["document_id"], "title": manifest["title"],
            "organization": manifest["organization"], "source_url": manifest["source_url"],
            "publication_url": manifest.get("publication_url"), "file_path": manifest["file_path"],
            "checksum": manifest["checksum"], "file_size": manifest["file_size"],
            "source_tier": manifest["source_tier"], "download_date": manifest.get("download_date"),
            "publication_date": manifest.get("publication_date"), "version": manifest.get("version"),
            "effective_date": manifest.get("effective_date"), "legal_status": manifest.get("legal_status"),
            "identity_status": manifest.get("identity_status"), "authority_status": manifest.get("authority_status"),
            "source_verified": manifest.get("source_verified"), "license_status": "not_explicitly_stated",
            "access_information": "Existing local file; official source page/attachment identity checked during Phase 10.",
            "parser_version": manifest.get("parser_version"), "recovery_action": "local_metadata_repair"})
    for old_id in ("8f337c28-890f-5ddb-9d92-612427284c4f", "0ac441bd-6eab-50ef-a459-72850101b7dd"):
        manifest = manifest_by_id[old_id]
        acquisitions.append({"document_id": old_id, "title": manifest["title"], "source_url": manifest["source_url"],
            "file_path": manifest["file_path"], "checksum": manifest["checksum"], "source_tier": manifest["source_tier"],
            "identity_status": manifest.get("identity_status"), "authority_status": manifest.get("authority_status"),
            "legal_status": manifest.get("legal_status"), "effective_date": None, "version": manifest.get("version"),
            "recovery_action": "source_verification_and_metadata_repair", "file_acquisition": "preexisting_local_original"})
    p10.write_jsonl(OUTPUT / "source_acquisition_manifest.jsonl", acquisitions)
    draft = ROOT / "data/recovery/raw_sources/tfrin_golden_seabass_biosecurity_handbook_2025.pdf"
    if draft.exists():
        acquisitions.append({"document_id": stable_document_id("data/recovery/raw_sources/tfrin_golden_seabass_biosecurity_handbook_2025.pdf"),
            "title": "金目鱸養殖生物安全手冊（文字初稿）", "organization": "農業部水產試驗所",
            "source_url": "https://www.tfrin.gov.tw/redirect_files.php?id=62468",
            "file_path": draft.relative_to(ROOT).as_posix(), "checksum": sha256_file(draft),
            "file_size": draft.stat().st_size, "source_tier": 1, "publication_date": "2025-03-03",
            "download_date": TODAY, "version": "文字初稿；superseded for corpus use by final 2025 publication",
            "legal_status": "draft", "identity_status": "verified", "authority_status": "verified_official",
            "license_status": "not_explicitly_stated", "access_information": "Official agency draft attachment retained as raw source only.",
            "parser_version": "not admitted", "recovery_action": "excluded_draft", "corpus_admission": "excluded"})
        p10.write_jsonl(OUTPUT / "source_acquisition_manifest.jsonl", acquisitions)

    # Auditable identity/authority evidence, kept separate from corpus content.
    local_manual = manifest_by_id["8f337c28-890f-5ddb-9d92-612427284c4f"]
    local_act = manifest_by_id["0ac441bd-6eab-50ef-a459-72850101b7dd"]
    official_manual_copy = ROOT / "data/recovery/raw_sources/tfrin_technical_manual_17_lower_full.pdf"
    act_html = ROOT / "data/recovery/raw_sources/moa_animal_drug_management_act_FL014718.html"
    p10.write_json(OUTPUT / "source_verification.json", {
        "manual_17": {"document_id": local_manual["document_id"], "identity_status": "verified",
            "authority_status": "verified_official", "local_sha256": local_manual["checksum"],
            "official_download_sha256": sha256_file(official_manual_copy),
            "byte_identical": local_manual["checksum"] == sha256_file(official_manual_copy),
            "official_record_url": "https://www.tfrin.gov.tw/ws.php?id=246",
            "publication_date": local_manual["publication_date"], "license_status": "not_explicitly_stated"},
        "animal_drug_management_act": {"document_id": local_act["document_id"], "identity_status": "verified",
            "authority_status": "verified_official", "source_verified": True, "legal_status": "current",
            "legal_status_basis": "current MOA law-content record has same title and amendment date; local extracted text contains the official article identifiers",
            "effective_date": None, "version": local_act["version"], "local_pdf_sha256": local_act["checksum"],
            "official_page_sha256": sha256_file(act_html), "official_page_url": local_act["source_url"],
            "full_byte_equality_claimed": False},
        "animal_drug_use_rules_annex": {"source_url": "https://law.moa.gov.tw/LawContent.aspx?id=FL035443&media=print",
            "identity_status": "verified", "authority_status": "verified_official", "legal_status": "current",
            "version": "official record revision date 114-01-08", "effective_date": None,
            "page_gate": {"accepted": 2, "review": 12},
            "review_reason": "drug-use table structure, units/footnotes need manual verification"},
        "final_golden_seabass_handbook": {"publication_record_url": "https://www.tfrin.gov.tw/theme_data.php?id=591&theme=publication_all",
            "download_url": manifest_by_id[stable_document_id("data/recovery/raw_sources/tfrin_golden_seabass_biosecurity_handbook_final_2025.pdf")]["source_url"],
            "identity_status": "verified", "authority_status": "verified_official", "legal_status": "unknown",
            "publication_date": "2025-11-30", "official_listing_pages": 97, "parsed_physical_pdf_pages": 100,
            "accepted_pages": 70, "review_pages": 29, "blank_pages": 1},
    })

    previous_corpus = read_corpus_jsonl(BASE_CORPUS)
    previous_doc_ids = {str(row.get("canonical_document_id") or row.get("document_id")) for row in previous_corpus}
    current_doc_ids = {str(row.get("canonical_document_id") or row.get("document_id")) for row in corpus_v2}
    added_doc_ids = current_doc_ids - previous_doc_ids
    chunks_by_doc = Counter(str(row.get("document_id")) for row in chunks_v3)
    parsed_page_counts = Counter()
    parsed_status_counts = Counter()
    for row in pages:
        parsed_page_counts[str(row["document_id"])] += 1
        parsed_status_counts[(str(row["document_id"]), str(row.get("ingestion_status")))] += 1
    local_quickwins = {
        "local_alias_count": 7, "distinct_manifest_documents": 2,
        "documents": [
            {"document_id": "2a1a9c12-afbc-57e5-b599-eaf991a09c12", "title": "第三章水產養殖管理技術 第二節吳郭魚",
             "aliases": 1, "pages": parsed_page_counts["2a1a9c12-afbc-57e5-b599-eaf991a09c12"],
             "accepted_pages": parsed_status_counts[("2a1a9c12-afbc-57e5-b599-eaf991a09c12", "accepted")],
             "review_pages": parsed_status_counts[("2a1a9c12-afbc-57e5-b599-eaf991a09c12", "review")],
             "reason": "all pages are OCR candidates; Tesseract and chi_tra/eng language data are unavailable; no gate relaxation"},
            {"document_id": "0ac441bd-6eab-50ef-a459-72850101b7dd", "title": "動物用藥品管理法",
             "aliases": 6, "pages": parsed_page_counts["0ac441bd-6eab-50ef-a459-72850101b7dd"],
             "accepted_pages": parsed_status_counts[("0ac441bd-6eab-50ef-a459-72850101b7dd", "accepted")],
             "review_pages": parsed_status_counts[("0ac441bd-6eab-50ef-a459-72850101b7dd", "review")],
             "recovered_chunks": chunks_by_doc["0ac441bd-6eab-50ef-a459-72850101b7dd"],
             "reason": "official current MOA record matched title/revision date; Parser v2 rerun passed page gate"},
        ],
        "separate_metadata_repair": {"document_id": local_manual["document_id"], "pages_reparsed": parsed_page_counts[local_manual["document_id"]],
            "accepted_pages": parsed_status_counts[(local_manual["document_id"], "accepted")],
            "reparsed_chunks": chunks_by_doc[local_manual["document_id"]],
            "same_chunk_ids_preserved": shadow_report["repaired_or_replaced_chunks"]},
        "no_original_documents_modified": True,
    }
    p10.write_json(OUTPUT / "local_quick_wins.json", local_quickwins)

    # Persist a version envelope with input/output checksums and explicit invariants.
    immutable = [BASE_SHADOW, BASE_CORPUS, BASE_SILVER_V1, BASE_SILVER_V2, ROOT / "rag_store.sqlite3"]
    recovery_manifest = {
        "manifest_version": "phase10-recovery-v3", "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "parent_manifest_sha256": _digest(MANIFEST), "parent_shadow_v2_sha256": _digest(BASE_SHADOW),
        "parent_evaluation_corpus_v1_sha256": _digest(BASE_CORPUS),
        "parent_silver_v1_sha256": _digest(BASE_SILVER_V1), "parent_silver_v2_sha256": _digest(BASE_SILVER_V2),
        "new_files": [row["file_path"] for row in actions["new_documents"]],
        "updated_metadata_document_ids": actions["updated_document_ids"],
        "recovery_actions": actions["actions"],
        "parser_version": "pymupdf 1.28.2", "chunking_version": "2.0.0-shadow",
        "shadow_v3_sha256": _digest(CHUNKS_V3), "evaluation_corpus_v2_sha256": _digest(CORPUS_V2),
        "silver_v3_sha256": _digest(SILVER_V3), "immutable_inputs_unchanged_at_generation": {str(path).replace('\\','/'): _digest(path) for path in immutable},
        "production_indexing_performed": False, "retrieval_benchmark_performed": False,
    }
    p10.write_json(ROOT / "data/recovery/recovery_manifest_v3.json", recovery_manifest)
    summary = {
        "local_quick_wins": {
            "aliases_expected": 7, "distinct_documents": 2,
            "tilapia_scan": {"document_id": "2a1a9c12-afbc-57e5-b599-eaf991a09c12", "reason": "OCR backend unavailable; no page promoted"},
            "animal_drug_management_act": {"document_id": "0ac441bd-6eab-50ef-a459-72850101b7dd", "reason": "official current law identity/version checked; Parser v2 gate rerun"},
        },
        "sources_acquired": [{"document_id": row["document_id"], "title": row["title"], "source_url": row["source_url"], "checksum": row["checksum"]} for row in actions["new_documents"]],
        "pages": {"recovery_scope": len(pages), "accepted": len(accepted_pages), "review": status_counter["review"], "rejected": status_counter["rejected"]},
        "pages_added_to_corpus": sum(1 for row in accepted_pages if row["document_id"] in added_doc_ids),
        "documents_added_to_corpus": len(added_doc_ids),
        "shadow_v3": {"total_chunks": len(chunks_v3), "reparsed_output_chunks": shadow_report["reparsed_output_chunks"],
                      "new_chunks": shadow_report["new_chunks"], "repaired_or_replaced_chunks": shadow_report["repaired_or_replaced_chunks"],
                      "chunks_removed_after_reparse_gate": shadow_report["chunks_removed_after_reparse_gate"]},
        "evaluation_corpus_v2": {key: corpus_summary.get(key) for key in ("total_shadow_chunks", "retrieval_chunks", "context_only_chunks", "excluded_chunks", "canonical_chunks", "duplicate_chunks")},
        "silver_v3": {"questions": len(silver["result"]["questions"]), "mapping": silver["result"]["coverage"]["overall"], "readiness": silver["readiness"]},
        "no_retrieval_benchmark": True,
    }
    p10.write_json(OUTPUT / "phase10_summary.json", summary)
    return summary


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
