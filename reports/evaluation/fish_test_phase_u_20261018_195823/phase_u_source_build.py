from __future__ import annotations

import csv
import hashlib
import json
import re
import sqlite3
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
BASE = ROOT / "reports/evaluation/fish_test_phase_u_20261018_171024"
MATRIX = BASE / "source_admission_approval_matrix.jsonl"
GOV = BASE / "government_data_source_records.jsonl"
OWNER_FILE = OUT / "source_admission_owner_approval_57.json"
UPDATED = OUT / "source_owner_decision_update_57.jsonl"
AUDIT = OUT / "source_rights_version_scope_audit_57.jsonl"
ADMISSION = OUT / "source_admission_registry_v3.jsonl"
CHUNKS_JSONL = OUT / "corpus_v3" / "corpus_chunks_v3.jsonl"
DB_PATH = OUT / "corpus_v3" / "corpus_v3.sqlite3"
CHUNK_MANIFEST = OUT / "corpus_v3" / "corpus_v3_manifest.json"

OGL_URL = "https://data.gov.tw/license"
DATASET_BASE = "https://data.gov.tw/dataset/"
APPROVAL_TEXT = (
    "研究負責人於使用者本輪指示中明確核准 Phase U 來源矩陣全部 57 筆 Owner Decision，"
    "供新版研究 RAG 評估使用；此為對話中的研究決策紀錄，不是數位簽章或第三方授權。"
)

# These are the exact local files for which a dataset-specific official page
# states Open Government Data License v1. The data and the license are scoped
# to these identified resources only.
DATASET_RULES: dict[str, dict[str, Any]] = {
    "DGBAS-AQUACULTURE-SPECIES-79395_2015.xml": {
        "source_id": "DGBAS-79395-2015",
        "dataset_id": "79395",
        "title": "從事漁業之水產養繁殖面積（不含箱網）按主要養繁殖水產生物種類分（2015 census）",
        "publisher": "行政院主計總處",
        "official_url": DATASET_BASE + "79395",
        "resource_url": "https://ws.dgbas.gov.tw/001/Upload/461/relfile/11525/231810/MP01206.xml",
        "version": "2015 census resource; local XML SHA-256 is the immutable file version",
        "usage_basis": "Dataset-specific Open Government Data License v1 on official data.gov.tw dataset page",
        "attribution": "行政院主計總處；資料集名稱；2015 census resource; 政府資料開放授權條款-第1版; https://data.gov.tw/license",
        "usage_scope": "Index exact 2015 single-period descriptive statistical rows and original category labels only.",
        "prohibitions": ["No 2015/2020 trend or direct comparison without harmonization", "No exact biological species inference from broad statistical labels", "No husbandry, disease, water-quality, medication, or climate claims"],
        "category_scope": ["Fact/statistics"],
        "species_scope": "Only original statistical category labels; not verified biological species-specific husbandry scope",
        "retrieval_default": True,
        "period": "2015",
        "existing_admission": False,
        "official_license_source": DATASET_BASE + "79395",
    },
    "DGBAS-AQUACULTURE-SPECIES-79395_2020.xml": {
        "source_id": "DGBAS-79395-2020",
        "dataset_id": "79395",
        "title": "從事漁業之水產養繁殖面積（不含箱網）按主要養繁殖水產生物種類分（2020 census）",
        "publisher": "行政院主計總處",
        "official_url": DATASET_BASE + "79395",
        "resource_url": "https://ws.dgbas.gov.tw/001/Upload/461/relfile/11525/232442/mp01206a109.xml",
        "version": "2020 resource label; XML itself has no year field; local SHA-256 is immutable file version",
        "usage_basis": "Dataset-specific Open Government Data License v1; existing Step 3V scope-limited owner admission preserved",
        "attribution": "行政院主計總處；資料集名稱；2020 resource label (year comes from resource metadata, not XML); 政府資料開放授權條款-第1版; https://data.gov.tw/license",
        "usage_scope": "Only 2020 single-period descriptive Fact rows with original statistical labels and units.",
        "prohibitions": ["No cross-year trend or direct comparison", "No exact biological species inference from broad statistical labels", "No husbandry, disease, water-quality, medication, or climate claims"],
        "category_scope": ["Fact/statistics"],
        "species_scope": "Only original statistical category labels; not verified biological species-specific husbandry scope",
        "retrieval_default": True,
        "period": "2020 resource label (not encoded in XML)",
        "existing_admission": True,
        "official_license_source": DATASET_BASE + "79395",
    },
    "FA-STOCKING-135670.csv": {
        "source_id": "FA-STOCKING-135670",
        "dataset_id": "135670",
        "title": "漁業署_養殖漁業放養量調查統計資料",
        "publisher": "農業部漁業署",
        "official_url": DATASET_BASE + "135670",
        "resource_url": "https://data.moa.gov.tw/Service/OpenData/FaRss/FaRSS139.aspx?FOTT=CSV&IsTransData=1&UnitId=G70",
        "version": "Exact local snapshot by SHA-256, retrieved 2026-10-10; statistical reference year is absent",
        "usage_basis": "Dataset-specific Open Government Data License v1 on official data.gov.tw dataset page",
        "attribution": "農業部漁業署；漁業署_養殖漁業放養量調查統計資料；snapshot 2026-10-10; 政府資料開放授權條款-第1版; https://data.gov.tw/license",
        "usage_scope": "Index exact raw rows as undated snapshot/context only; field descriptions may be indexed.",
        "prohibitions": ["Do not infer or add a statistical reference year", "Do not produce year-specific answers", "Do not infer exact biological species from group labels"],
        "category_scope": ["Fact/statistics; context-only for data-value rows"],
        "species_scope": "Original fish-name labels only; statistical category is not a biological taxonomy assertion",
        "retrieval_default": False,
        "period": None,
        "existing_admission": False,
        "official_license_source": DATASET_BASE + "135670",
    },
    "MOA-FISH-SPECIES-CODE-134250.csv": {
        "source_id": "MOA-FISH-SPECIES-CODE-134250",
        "dataset_id": "134250",
        "title": "Fish species code",
        "publisher": "Ministry of Agriculture / 農業部",
        "official_url": "https://data.gov.tw/en/datasets/134250",
        "resource_url": "https://data.moa.gov.tw/Service/OpenData/DataFileService.aspx?UnitId=H64&FOTT=CSV&IsTransData=1",
        "version": "Exact local snapshot by SHA-256, retrieved 2026-10-10; dataset page updated 2026-06-29",
        "usage_basis": "Dataset-specific Open Government Data License v1 on official data.gov.tw dataset page",
        "attribution": "Ministry of Agriculture; Fish species code; snapshot 2026-10-10; Open Government Data License v1.0; https://data.gov.tw/license",
        "usage_scope": "Index exact code/name/scientific-name rows as a dated source snapshot for label lookup only.",
        "prohibitions": ["Do not treat the snapshot as a current authoritative taxonomy beyond its version", "Do not infer husbandry applicability from a code/name match", "Keep broad/common-name categories distinct from scientific species"],
        "category_scope": ["Fact/taxonomy label lookup"],
        "species_scope": "Raw source labels and scientific-name field as provided; row-level taxonomy confidence may vary",
        "retrieval_default": True,
        "period": "snapshot as retrieved 2026-10-10; official dataset updated 2026-06-29",
        "existing_admission": False,
        "official_license_source": "https://data.gov.tw/en/datasets/134250",
    },
    "MOA-FISHERY-PRODUCTION-44084.csv": {
        "source_id": "MOA-FISHERY-PRODUCTION-44084",
        "dataset_id": "44084",
        "title": "漁業生產量─按漁業、漁種別分",
        "publisher": "農業部",
        "official_url": DATASET_BASE + "44084",
        "resource_url": "https://data.moa.gov.tw/service/opendata/agrstatUnit.aspx?item_code=CF0110&dimension_group_code_1=CF04&dimension_group_code_2=CF01&FOTT=CSV&IsTransData=1&UnitId=611",
        "version": "Exact local snapshot by SHA-256, retrieved 2026-10-10; preserve raw year codes, field names, values and units",
        "usage_basis": "Dataset-specific Open Government Data License v1 on official data.gov.tw dataset page",
        "attribution": "農業部；漁業生產量─按漁業、漁種別分；snapshot 2026-10-10; 政府資料開放授權條款-第1版; https://data.gov.tw/license",
        "usage_scope": "Index exact row-level production statistics with original fishery, year-code, value and unit fields.",
        "prohibitions": ["Do not convert raw year codes without a verified year-code mapping", "Do not combine fishery sectors", "Do not infer exact species from broad fish-name labels"],
        "category_scope": ["Fact/statistics: production only"],
        "species_scope": "Original dname1 fish label only; the dataset row is not a husbandry recommendation",
        "retrieval_default": True,
        "period": "year field retained as raw source value; exact year-code interpretation not normalized",
        "existing_admission": False,
        "official_license_source": DATASET_BASE + "44084",
    },
    "WRA-AQUACULTURE-WATER-58700.csv": {
        "source_id": "WRA-AQUACULTURE-WATER-58700",
        "dataset_id": "58700",
        "title": "水利署養殖面積與養殖用水量統計",
        "publisher": "經濟部水利署",
        "official_url": DATASET_BASE + "58700",
        "resource_url": "https://opendata.wra.gov.tw/api/v2/dfc12113-9e62-4185-a3e6-4a83042d0c71?sort=_importdate%20asc&format=CSV",
        "version": "Exact local snapshot by SHA-256, retrieved 2026-10-10; page reports a known update issue for data from 2020 onward",
        "usage_basis": "Dataset-specific Open Government Data License v1 on official data.gov.tw dataset page",
        "attribution": "經濟部水利署；水利署養殖面積與養殖用水量統計；snapshot 2026-10-10; 政府資料開放授權條款-第1版; https://data.gov.tw/license",
        "usage_scope": "Retain as context-only water-use statistics with original fields, year and status; do not use as water-quality evidence.",
        "prohibitions": ["Cannot support water-quality thresholds or management claims", "No species-specific claims from the aggregate data", "Do not claim records are current for 2020 onward given the published update warning"],
        "category_scope": ["Context-only: water-use statistics; excluded from Water Quality claims"],
        "species_scope": "Dataset codes may encode cultivation kind; this is not species-specific biological evidence",
        "retrieval_default": False,
        "period": "raw ROC year field retained; temporal quality warning applies since 2020",
        "existing_admission": False,
        "official_license_source": DATASET_BASE + "58700",
    },
}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def xml_text_rows(path: Path, rule: dict[str, Any]) -> list[dict[str, Any]]:
    root = ET.parse(path).getroot()
    result: list[dict[str, Any]] = []
    for rec_idx, record in enumerate(list(root), start=1):
        fields: dict[str, Any] = {}
        for elem in list(record):
            val = elem.text.strip() if elem.text and elem.text.strip() else None
            if val is None and list(elem):
                val = " | ".join((child.text or "").strip() for child in list(elem))
            fields[elem.tag] = val
        label = next((v for k, v in fields.items() if "項目別" in k and v), "")
        text = "；".join(f"{key}={value}" for key, value in fields.items() if value is not None)
        text = f"來源資料集：{rule['title']}；原始記錄標籤：{label}；原始欄位和值：{text}；單位依原始欄位名稱保留。"
        result.append({
            "record_locator": f"xml:/DataCollection/{record.tag}[{rec_idx}]",
            "raw_fields": fields,
            "text": text,
            "species_scope": rule["species_scope"],
            "category_scope": rule["category_scope"],
            "retrieval_eligible": bool(rule["retrieval_default"]),
            "chunk_type": "statistical_record",
        })
    return result


def csv_text_rows(path: Path, rule: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        all_rows = list(reader)
    included: list[dict[str, Any]] = []
    excluded_status_counts: dict[str, int] = defaultdict(int)
    for rec_idx, raw in enumerate(all_rows, start=2):
        row = {str(k): (str(v).strip() if v is not None else "") for k, v in raw.items() if k is not None}
        eligible = bool(rule["retrieval_default"])
        note = None
        if rule["source_id"] == "WRA-AQUACULTURE-WATER-58700":
            # The published source identifies status codes and exposes a known
            # temporal update issue. Keep every raw record as context-only.
            eligible = False
            note = "context_only: source page warns of update-method/data errors from 2020 onward; not water-quality evidence"
            excluded_status_counts[row.get("status", "(blank)")] += 1
        elif rule["source_id"] == "FA-STOCKING-135670":
            eligible = False
            note = "context_only: statistical reference year absent; row may not support date-specific claims"
        elif rule["source_id"] == "MOA-FISH-SPECIES-CODE-134250":
            eligible = bool(row.get("代碼") and row.get("中文名稱"))
            note = "label/code lookup only; not husbandry applicability"
        elif rule["source_id"] == "MOA-FISHERY-PRODUCTION-44084":
            eligible = bool(row.get("dname1") and row.get("dname2") and row.get("year") and row.get("value") and row.get("unit"))
            note = "row-level statistical fact; raw year code and fishery sector preserved"
        text = "；".join(f"{key}={value}" for key, value in row.items() if value != "")
        text = f"來源資料集：{rule['title']}；原始欄位和值：{text}。"
        included.append({
            "record_locator": f"csv:record[{rec_idx}]",
            "raw_fields": row,
            "text": text,
            "species_scope": rule["species_scope"],
            "category_scope": rule["category_scope"],
            "retrieval_eligible": eligible,
            "chunk_type": "statistical_record",
            "eligibility_note": note,
        })
    return included, {"fieldnames": fieldnames, "row_count": len(all_rows), "context_only_by_status": dict(excluded_status_counts)}


def main() -> None:
    matrix_rows = [json.loads(line) for line in MATRIX.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(matrix_rows) != 57:
        raise SystemExit(f"Expected 57 Phase U source records; found {len(matrix_rows)}")
    matrix_files: dict[str, dict[str, Any]] = {}
    digest_to_records: dict[str, list[dict[str, Any]]] = defaultdict(list)
    errors: list[dict[str, Any]] = []
    for row in matrix_rows:
        path = (ROOT / row["original_path"]).resolve()
        if not path.is_file():
            errors.append({"source_record_id": row.get("source_record_id"), "path": row["original_path"], "error": "file_missing"})
            continue
        actual = sha256_file(path)
        expected = row.get("checksum_sha256")
        if expected and expected != actual:
            errors.append({"source_record_id": row.get("source_record_id"), "path": row["original_path"], "error": "sha256_mismatch", "expected": expected, "actual": actual})
        item = {**row, "absolute_path": str(path), "actual_sha256": actual, "expected_sha256": expected, "sha256_matches_matrix": (expected == actual if expected else None)}
        digest_to_records[actual].append(item)
        matrix_files[row["original_path"]] = item
    if errors:
        write_json(OUT / "source_integrity_blockers.json", {"status": "blocked", "errors": errors})
        raise SystemExit(f"Source integrity blocked for {len(errors)} records")
    if len(digest_to_records) != 55:
        raise SystemExit(f"Expected 55 unique source files by SHA-256; found {len(digest_to_records)}")

    owner_record = {
        "decision_id": "PHASE-U-SOURCE-MATRIX-57-OWNER-APPROVAL-20261018",
        "decision_date": "2026-10-18",
        "approver_role": "research_owner",
        "approval_source": "explicit_user_instruction_in_current_conversation",
        "approval_document_requested": "source_admission_owner_approval_57.json",
        "approval_document_found_in_project_or_phase_u_directory": False,
        "decision_text": APPROVAL_TEXT,
        "approved_source_matrix_record_count": 57,
        "approved_scope": "Phase U matrix sources may proceed to source-specific rights, version, publisher and applicability validation for isolated research RAG use; this does not create third-party permissions or override source-specific restrictions.",
        "digital_signature": False,
        "external_identity_verification": False,
        "third_party_license_granted": False,
        "admission_execution_status_before_validation": "not_started",
        "corpus_v3_build_approved_by_current_user": True,
        "e4_final_build_approved_by_current_user": False,
        "formal_model_scoring_approved": False,
        "winner_selection_approved": False,
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "note": "The named JSON was not found; this record transcribes the explicit owner decision in the user message and does not claim the missing file was read."
    }
    write_json(OWNER_FILE, owner_record)

    # Owner decision is updated for all 57 original records. Actual source
    # permissions and admission decisions remain separately assessed below.
    owner_updates = []
    source_reviews = []
    admissions = []
    unique_admitted: dict[str, dict[str, Any]] = {}
    for row in matrix_rows:
        path_key = row["original_path"]
        actual = matrix_files[path_key]["actual_sha256"]
        fname = Path(path_key).name
        rule = DATASET_RULES.get(fname)
        updated = {**row, "owner_decision": "APPROVED", "owner_decision_date": "2026-10-18", "owner_approval_reference": owner_record["decision_id"], "owner_decision_source": "explicit_user_instruction_in_current_conversation"}
        owner_updates.append(updated)
        if rule:
            record = {
                "source_id": rule["source_id"],
                "source_record_id": row.get("source_record_id"),
                "source_title": rule["title"],
                "publisher": rule["publisher"],
                "local_file": row["original_path"],
                "source_sha256": actual,
                "matrix_sha256_matches": matrix_files[path_key]["sha256_matches_matrix"],
                "official_dataset_url": rule["official_url"],
                "resource_url": rule["resource_url"],
                "license": "政府資料開放授權條款-第1版 / Open Government Data License v1.0",
                "license_url": OGL_URL,
                "license_scope_verified_for_this_dataset": True,
                "attribution_required": True,
                "attribution_text": rule["attribution"],
                "publication_version": rule["version"],
                "owner_decision": "APPROVED",
                "owner_approval_reference": owner_record["decision_id"],
                "source_admission_status": "already_admitted_scope_limited" if rule["existing_admission"] else "admitted_scope_limited",
                "admission_execution_status": "admitted_scope_limited",
                "corpus_v3_inclusion_status": "included" if rule["retrieval_default"] else "included_context_only",
                "approved_usage_scope": rule["usage_scope"],
                "prohibited_usage_scope": rule["prohibitions"],
                "category_scope": rule["category_scope"],
                "species_scope": rule["species_scope"],
                "statistical_period": rule["period"],
                "source_cluster_id": rule["source_id"].split("-")[0] + "-open-data",
                "retrieval_default": rule["retrieval_default"],
                "official_license_source_url": rule["official_license_source"],
                "source_page_checked": "2026-10-18 via official data.gov.tw dataset page",
                "version_limitations": rule["version"],
                "limitations": rule["prohibitions"],
            }
            source_reviews.append(record)
            unique_admitted.setdefault(actual, record)
        else:
            title = str(row.get("title") or Path(path_key).name)
            pub = str(row.get("publisher") or "UNVERIFIED")
            if "tfrin" in path_key.lower() or "水產試驗所" in title or "水試所" in title:
                rights_status = "copyright_notice_or_rights_scope_unverified_for_full_text_indexing"
                reason = "Official TFRI site footer says copyright reserved; no document-specific open-license evidence was located. Owner approval is not third-party authorization. Full-text parsing/embedding is not admitted."
            elif any(term in title for term in ("法", "條例", "規則", "準則")):
                rights_status = "statutory_text_candidate_but_local_version_or_source_identity_unverified"
                reason = "Some legal texts are excluded from copyright protection under Taiwan Copyright Act Article 9, but this local file's official identity/current version and any non-statutory explanatory material were not verified for this build."
            else:
                rights_status = "source_identity_version_or_usage_basis_unverified"
                reason = "Owner decision is approved, but a file-specific publisher/version/usage basis and/or applicability was not independently established."
            source_reviews.append({
                "source_id": row.get("source_id"),
                "source_record_id": row.get("source_record_id"),
                "source_title": title,
                "publisher": pub,
                "local_file": path_key,
                "source_sha256": actual,
                "matrix_sha256_matches": matrix_files[path_key]["sha256_matches_matrix"],
                "owner_decision": "APPROVED",
                "owner_approval_reference": owner_record["decision_id"],
                "source_admission_status": "not_admitted",
                "admission_execution_status": "blocked_source_specific_rights_version_or_identity",
                "corpus_v3_inclusion_status": "excluded_from_index_pending_verification",
                "rights_status": rights_status,
                "blocker_reason": reason,
                "source_url": row.get("url"),
                "source_version": row.get("version"),
                "scope_signals_not_verified": row.get("expected_species_and_categories"),
            })
    write_jsonl(UPDATED, owner_updates)
    write_jsonl(AUDIT, source_reviews)
    write_jsonl(ADMISSION, list(unique_admitted.values()))

    chunks: list[dict[str, Any]] = []
    raw_schema: dict[str, Any] = {}
    for fname, rule in DATASET_RULES.items():
        match = next((x for x in matrix_files.values() if Path(x["original_path"]).name == fname), None)
        if not match:
            raise SystemExit(f"Approved dataset file missing from 57 source matrix: {fname}")
        path = Path(match["absolute_path"])
        if path.suffix.lower() == ".xml":
            records = xml_text_rows(path, rule)
            raw_schema[rule["source_id"]] = {"format": "XML", "record_count": len(records), "xml_root": ET.parse(path).getroot().tag, "reference_period_from_resource_metadata": rule["period"]}
        else:
            records, schema = csv_text_rows(path, rule)
            raw_schema[rule["source_id"]] = {"format": "CSV", **schema}
        for rec in records:
            text = rec["text"]
            chunk_id = "u3-" + sha256_text(rule["source_id"] + "\n" + match["actual_sha256"] + "\n" + rec["record_locator"] + "\n" + text)[:24]
            chunks.append({
                "chunk_id": chunk_id,
                "source_id": rule["source_id"],
                "source_title": rule["title"],
                "publisher": rule["publisher"],
                "source_url": rule["official_url"],
                "resource_url": rule["resource_url"],
                "source_sha256": match["actual_sha256"],
                "source_version": rule["version"],
                "license": "政府資料開放授權條款-第1版",
                "attribution": rule["attribution"],
                "corpus_version": "research_corpus_v3_phase_u_20261018",
                "record_locator": rec["record_locator"],
                "raw_fields": rec["raw_fields"],
                "text": text,
                "content_sha256": sha256_text(text),
                "category_scope": rule["category_scope"],
                "species_scope": rule["species_scope"],
                "retrieval_eligible": bool(rec["retrieval_eligible"]),
                "chunk_role": "retrieval" if rec["retrieval_eligible"] else "context_only",
                "eligibility_note": rec.get("eligibility_note"),
                "source_cluster_id": rule["source_id"].split("-")[0] + "-open-data",
                "period": rule["period"],
            })

    chunks.sort(key=lambda x: (x["source_id"], x["record_locator"], x["chunk_id"]))
    write_jsonl(CHUNKS_JSONL, chunks)
    chunk_hash = sha256_file(CHUNKS_JSONL)
    # Retain only source rows that passed source-specific OGL/admission checks.
    db = sqlite3.connect(DB_PATH)
    try:
        db.execute("PRAGMA journal_mode=DELETE")
        db.execute("PRAGMA synchronous=FULL")
        db.executescript("""
        CREATE TABLE sources (
          source_id TEXT PRIMARY KEY, title TEXT NOT NULL, publisher TEXT NOT NULL,
          local_file TEXT NOT NULL, sha256 TEXT NOT NULL, source_url TEXT NOT NULL,
          resource_url TEXT NOT NULL, license TEXT NOT NULL, attribution TEXT NOT NULL,
          version TEXT NOT NULL, usage_scope TEXT NOT NULL, retrieval_default INTEGER NOT NULL
        );
        CREATE TABLE chunks (
          chunk_id TEXT PRIMARY KEY, source_id TEXT NOT NULL, source_sha256 TEXT NOT NULL,
          source_version TEXT NOT NULL, record_locator TEXT NOT NULL, content_sha256 TEXT NOT NULL,
          text TEXT NOT NULL, metadata_json TEXT NOT NULL, retrieval_eligible INTEGER NOT NULL,
          chunk_role TEXT NOT NULL, FOREIGN KEY(source_id) REFERENCES sources(source_id)
        );
        CREATE INDEX idx_chunks_source ON chunks(source_id);
        CREATE INDEX idx_chunks_retrieval ON chunks(retrieval_eligible);
        """)
        for sha, record in unique_admitted.items():
            rule = next(r for r in DATASET_RULES.values() if r["source_id"] == record["source_id"])
            matrix_match = next(x for x in matrix_files.values() if Path(x["original_path"]).name in DATASET_RULES and DATASET_RULES[Path(x["original_path"]).name]["source_id"] == rule["source_id"])
            db.execute("INSERT INTO sources VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (
                rule["source_id"], rule["title"], rule["publisher"], matrix_match["original_path"], sha,
                rule["official_url"], rule["resource_url"], "OGDL-v1", rule["attribution"], rule["version"],
                rule["usage_scope"], int(rule["retrieval_default"]),
            ))
        for c in chunks:
            metadata = {k: v for k, v in c.items() if k not in {"text", "raw_fields"}}
            db.execute("INSERT INTO chunks VALUES (?,?,?,?,?,?,?,?,?,?)", (
                c["chunk_id"], c["source_id"], c["source_sha256"], c["source_version"], c["record_locator"],
                c["content_sha256"], c["text"], canonical_json({**metadata, "raw_fields": c["raw_fields"]}),
                int(c["retrieval_eligible"]), c["chunk_role"],
            ))
        db.commit()
        try:
            db.execute("CREATE VIRTUAL TABLE chunks_fts USING fts5(chunk_id UNINDEXED, token_text, content='')")
            from_phase = ROOT / "src/evaluation/retrievers/bm25.py"
            # Exact tokenizer name/algorithm is implemented here to keep the
            # isolated index self-contained and auditable.
            token_re = re.compile(r"[a-z0-9]+(?:[./_%+\-][a-z0-9]+)*|[\u3400-\u9fff]+", re.I)
            def tokenize(text: str) -> list[str]:
                out = []
                for m in token_re.finditer(text.casefold()):
                    t = m.group(0)
                    if re.fullmatch(r"[\u3400-\u9fff]+", t):
                        out.extend([t] if len(t) == 1 else [t[i:i+2] for i in range(len(t)-1)])
                    else:
                        out.append(t)
                return out
            db.executemany("INSERT INTO chunks_fts(chunk_id, token_text) VALUES (?,?)", ((c["chunk_id"], " ".join(tokenize(c["text"]))) for c in chunks if c["retrieval_eligible"]))
            db.commit()
            fts_status = "built"
        except sqlite3.OperationalError as exc:
            fts_status = "blocked: " + str(exc)
            raise
    finally:
        db.close()

    duplicate_groups = [{"sha256": sha, "source_records": [x["source_record_id"] for x in items], "paths": [x["original_path"] for x in items]} for sha, items in digest_to_records.items() if len(items) > 1]
    manifest = {
        "corpus_version": "research_corpus_v3_phase_u_20261018",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "build_status": "BUILT_ISOLATED_LIMITED_SCOPE",
        "formal_production_corpus": False,
        "owner_approval_reference": owner_record["decision_id"],
        "source_matrix_record_count": 57,
        "unique_source_files_by_sha256": 55,
        "duplicate_hash_group_count": len(duplicate_groups),
        "duplicate_hash_groups": duplicate_groups,
        "eligible_source_artifact_count": len(unique_admitted),
        "new_source_admission_count": sum(not x["existing_admission"] for x in DATASET_RULES.values()),
        "preserved_existing_admission_count": sum(x["existing_admission"] for x in DATASET_RULES.values()),
        "source_ids": sorted(unique_admitted[r["source_sha256"]]["source_id"] for r in unique_admitted.values()),
        "source_sha256s": sorted(unique_admitted.keys()),
        "retrieval_eligible_chunk_count": sum(1 for c in chunks if c["retrieval_eligible"]),
        "context_only_chunk_count": sum(1 for c in chunks if not c["retrieval_eligible"]),
        "total_chunk_count": len(chunks),
        "chunk_jsonl_sha256": chunk_hash,
        "sqlite_path": str(DB_PATH.relative_to(ROOT)).replace("\\", "/"),
        "sqlite_sha256": sha256_file(DB_PATH),
        "sqlite_chunk_count": len(chunks),
        "embedding_model": "bge-m3:latest",
        "embedding_model_digest_expected_from_phase_t": "7907646426070047a77226ac3e684fbbe8410524f7b4a74d02837e43f2146bab",
        "bm25": {"status": fts_status, "sqlite_fts5": True, "tokenizer": "traditional_chinese_bigrams_latin_terms_v1", "k1": 1.5, "b": 0.75},
        "rrf": {"k": 60, "weights": {"bm25": 1.0, "dense": 1.0}, "candidate_depth": 100},
        "reranker": {"model_id": "BAAI/bge-reranker-v2-m3", "revision": "953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e", "status": "pinned_phase_t_verified; new run pending retrieval smoke test"},
        "top_k": 5,
        "file_schema_diagnostics": raw_schema,
        "not_included": "All remaining owner-approved matrix sources are excluded from retrieval/indexing until source-specific rights, file identity/version and applicability are verified. Owner approval alone is not a third-party license.",
        "protected_corpus_v2_and_production_modified": False,
    }
    write_json(CHUNK_MANIFEST, manifest)
    print(json.dumps({"status": "prepared", "sources": len(unique_admitted), "new_admissions": manifest["new_source_admission_count"], "chunks": len(chunks), "retrieval_eligible": manifest["retrieval_eligible_chunk_count"], "context_only": manifest["context_only_chunk_count"], "sqlite_sha256": manifest["sqlite_sha256"], "chunk_sha256": chunk_hash}, ensure_ascii=False))


if __name__ == "__main__":
    main()
