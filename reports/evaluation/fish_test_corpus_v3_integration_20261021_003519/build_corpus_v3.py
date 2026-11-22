from __future__ import annotations

import collections
import datetime as dt
import hashlib
import html
import json
import math
import re
import shutil
import sqlite3
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import numpy as np
import requests


ROOT = Path(__file__).resolve().parents[3]
WORK = Path(__file__).resolve().parent
CORPUS_DIR = WORK / "corpus"
RAW_DIR = CORPUS_DIR / "raw_snapshots"
DB_PATH = CORPUS_DIR / "marine_hybrid_rag_corpus_v3.sqlite3"
INPUT_DIR = ROOT / "research_staging" / "official_downloads" / "phase_ab_recovery_20261020_172529"
DGBAS_PATH = ROOT / "research_staging" / "_official_source_staging" / "phase20_1E_step3I" / "raw" / "DGBAS-AQUACULTURE-SPECIES-79395_2020.xml"
STEP3V_DIR = ROOT / "reports" / "evaluation" / "final_model_selection" / "phase20_1E_exec_r3" / "step3v_dgbas_formal_admission"
PHASE_A_QUESTIONS = ROOT / "reports" / "evaluation" / "fish_test_phase_a_20261012" / "fish_test_questions_normalized.jsonl"
PHASE_AA_DIR = ROOT / "reports" / "evaluation" / "fish_test_phase_aa_20261019_220906"
PHASE_Z_DIR = ROOT / "reports" / "evaluation" / "fish_test_phase_z_20261019_173013"

EXPECTED = {
    "tfrin_fishery_qa.json": (1_476_257, "66e1803c1bac11aef1dd887c798767773603e1c1274d274cafa153c36a318446", 956),
    "animal_drug_info.json": (8_727_437, "49cb8818b25dd8ec8ef7f2b9c5e86163f90d95ebeb80b3cc34c0408499228c4c", 9_999),
    "eel_stocking_by_county.json": (9_090, "919201c2605e70d01c1d46270e9740714883608dcf75f9ae9fab16838bb63528", 9),
}
SOURCE_META = {
    "MOA-TFRI-OPEN-114846": {
        "dataset_id": "114846", "title": "水產試驗所漁業問答", "publisher": "農業部水產試驗所",
        "dataset_url": "https://data.gov.tw/dataset/114846",
        "resource_url": "https://data.moa.gov.tw/Service/OpenData/TfrinRss/TfrinRss02.aspx?IsTransData=1&UnitId=B71",
        "file": "tfrin_fishery_qa.json", "license": "政府資料開放授權條款第1版",
        "attribution": "農業部水產試驗所，水產試驗所漁業問答，資料集114846，JSON資源快照2026-10-20。依政府資料開放授權條款第1版提供。https://data.gov.tw/license",
        "scope": "Exact official open-data JSON resource; factual Q&A fields title/description/pubdate and link; local isolated research retrieval with required attribution. Linked external pages are not included under this admission.",
        "license_page_metadata_updated": "2023-08-14", "update_frequency": "不定期更新",
    },
    "MOA-ANIMAL-DRUG-OPEN-7274": {
        "dataset_id": "7274", "title": "動物用藥資訊", "publisher": "農業部動植物防疫檢疫署",
        "dataset_url": "https://data.gov.tw/dataset/7274", "resource_url": "https://data.moa.gov.tw/Service/OpenData/FromM/ADProData.aspx",
        "file": "animal_drug_info.json", "license": "政府資料開放授權條款第1版",
        "attribution": "農業部動植物防疫檢疫署，動物用藥資訊，資料集7274，JSON資源快照2026-10-20。依政府資料開放授權條款第1版提供。https://data.gov.tw/license",
        "scope": "Original permit/product/ingredient/indication/validity fields only. No inference of dosage, frequency, withdrawal period, current therapeutic recommendation, or species use beyond exact source text.",
        "license_page_metadata_updated": "2026-03-13", "update_frequency": "每7天",
    },
    "MOA-EEL-STOCKING-OPEN-41845": {
        "dataset_id": "41845", "title": "縣市別養殖放養量彙整表（鰻魚）", "publisher": "農業部",
        "dataset_url": "https://data.gov.tw/dataset/41845", "resource_url": "https://data.moa.gov.tw/Service/OpenData/DataFileService.aspx?IsTransData=1&UnitId=B36",
        "file": "eel_stocking_by_county.json", "license": "政府資料開放授權條款第1版",
        "attribution": "農業部，縣市別養殖放養量彙整表（鰻魚），資料集41845，JSON資源快照2026-10-20。依政府資料開放授權條款第1版提供。https://data.gov.tw/license",
        "scope": "Native statistical fields only. No reference year is present; context-only. No trend, temperature, disease, or husbandry inference.",
        "license_page_metadata_updated": "2025-04-02", "update_frequency": "不定期更新",
    },
    "DGBAS-79395-2020": {
        "dataset_id": "79395", "title": "從事漁業之水產養繁殖面積（不含箱網）按主要養繁殖水產生物種類分", "publisher": "行政院主計總處",
        "dataset_url": "https://data.gov.tw/dataset/79395", "resource_url": "https://ws.dgbas.gov.tw/001/Upload/461/relfile/11525/232442/mp01206a109.xml",
        "file": "DGBAS-AQUACULTURE-SPECIES-79395_2020.xml", "license": "政府資料開放授權條款第1版",
        "attribution": "行政院主計總處，2020 從事漁業之水產養繁殖面積（不含箱網）按主要養繁殖水產生物種類分（民國109年 XML）；依政府資料開放授權條款第1版提供。https://data.gov.tw/license",
        "scope": "Previously admitted scope-limited: 2020 single-year descriptive Fact only; native statistical area/category/value/unit; no biological-species inference, trend, husbandry, disease, water-quality or medication inference.",
        "license_page_metadata_updated": "2026-10-12 verified in Step 3V", "update_frequency": "每5年",
    },
}

TARGET_SPECIES = ["虱目魚", "吳郭魚", "石斑魚", "鱸魚", "烏魚", "鰻魚"]
SPECIES_TERMS = ["虱目魚", "吳郭魚", "台灣鯛", "石斑魚", "鞍帶石斑", "龍膽石斑", "青斑", "龍虎斑", "鱸魚", "金目鱸", "七星鱸", "午仔魚", "烏魚", "鰻魚", "日本鰻", "白鰻"]
TOPIC_TERMS = {
    "Water Quality": ["水質", "溶氧", "酸鹼", "pH", "氨氮", "亞硝酸", "鹽度", "水溫"],
    "Disease": ["疾病", "病原", "感染", "病症", "症狀", "防治", "寄生蟲", "病毒", "細菌"],
    "Climate / Cold": ["寒害", "寒流", "低溫", "防寒", "氣候", "颱風"],
    "Medication / Law": ["藥", "用藥", "停藥", "藥品", "許可證", "法規", "規定", "劑量"],
    "Calculation": ["計算", "公式", "換算", "FCR", "SGR", "放養密度", "每公頃", "投餵率", "成長率"],
    "Fact": ["何時", "何地", "哪一", "多少", "比例", "面積", "放養量", "產量"],
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]


def clean_html(value: str) -> str:
    value = re.sub(r"(?i)<br\s*/?>", "\n", str(value or ""))
    value = re.sub(r"(?i)</(?:p|div|li)\s*>", "\n", value)
    value = re.sub(r"<[^>]+>", " ", value)
    value = html.unescape(value).replace("\xa0", " ")
    return re.sub(r"[ \t]+", " ", re.sub(r"\n\s*\n+", "\n", value)).strip()


def content_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def species_mentions(text: str) -> list[str]:
    return sorted({term for term in SPECIES_TERMS if term in text}, key=lambda x: (len(x), x))


def topic_labels(text: str) -> list[str]:
    return [category for category, terms in TOPIC_TERMS.items() if any(t.lower() in text.lower() for t in terms)] or ["Fact"]


def cjk_tokens(text: str) -> list[str]:
    text = str(text or "").lower()
    out: list[str] = []
    for run in re.findall(r"[\u3400-\u9fff]+", text):
        if len(run) == 1:
            out.append(run)
        else:
            out.extend(run[i:i + 2] for i in range(len(run) - 1))
    out.extend(re.findall(r"[a-z0-9]+(?:[._/-][a-z0-9]+)*", text))
    return list(dict.fromkeys(out))


def split_answer(text: str, max_chars: int = 760) -> list[tuple[str, int, int]]:
    text = clean_html(text)
    if not text:
        return []
    units = []
    for para in text.splitlines():
        para = para.strip()
        if not para:
            continue
        if len(para) <= max_chars:
            units.append(para)
            continue
        sentences = re.split(r"(?<=[。！？!?；;])", para)
        current = ""
        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue
            if current and len(current) + len(sentence) > max_chars:
                units.append(current)
                current = sentence
            else:
                current += sentence
        if current:
            units.append(current)
    # Recover stable normalized-text spans in the rendered answer field.
    spans = []
    cursor = 0
    for unit in units:
        start = text.find(unit, cursor)
        if start < 0:
            start = text.find(unit)
        if start < 0:
            start, end = 0, len(unit)
        else:
            end = start + len(unit)
            cursor = end
        spans.append((unit, start, end))
    return spans


def exact_scope_matches(target: str, scopes: list[str], question: str) -> tuple[bool, str]:
    if target in scopes:
        return True, "EXACT_LITERAL_TARGET_SPECIES"
    specific = {"金目鱸", "七星鱸", "午仔魚", "日本鰻", "白鰻", "鞍帶石斑", "龍膽石斑", "青斑", "龍虎斑", "台灣鯛"}
    matched_specific_in_question = [s for s in specific if s in question]
    for alias in matched_specific_in_question:
        if alias in scopes:
            return True, "EXACT_LITERAL_SPECIFIC_SPECIES_IN_QUESTION"
    if "GENERAL_AQUACULTURE_EXPLICIT" in scopes or "GENERAL_REGULATION_EXPLICIT" in scopes:
        return True, "SOURCE_EXPLICITLY_GENERAL"
    return False, "NO_EXPLICIT_TARGET_SCOPE_MATCH"


def schema_init(con: sqlite3.Connection) -> None:
    con.executescript("""
    PRAGMA journal_mode=WAL;
    PRAGMA foreign_keys=ON;
    CREATE TABLE corpus_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
    CREATE TABLE sources(
      source_id TEXT PRIMARY KEY, dataset_id TEXT NOT NULL, title TEXT NOT NULL, publisher TEXT NOT NULL,
      dataset_url TEXT NOT NULL, resource_url TEXT NOT NULL, source_sha256 TEXT NOT NULL, file_size_bytes INTEGER NOT NULL,
      source_file TEXT NOT NULL, license TEXT NOT NULL, license_url TEXT NOT NULL, attribution TEXT NOT NULL,
      owner_admission_status TEXT NOT NULL, license_scope_status TEXT NOT NULL, identity_status TEXT NOT NULL,
      version_status TEXT NOT NULL, applicability_status TEXT NOT NULL, completeness_status TEXT NOT NULL,
      processing_scope TEXT NOT NULL, source_cluster_id TEXT NOT NULL, metadata_json TEXT NOT NULL
    );
    CREATE TABLE source_records(
      source_record_id TEXT PRIMARY KEY, source_id TEXT NOT NULL, source_record_locator TEXT NOT NULL,
      source_record_sha256 TEXT NOT NULL, eligibility_status TEXT NOT NULL, eligibility_reason TEXT NOT NULL,
      original_record_json TEXT NOT NULL, duplicate_group_id TEXT, FOREIGN KEY(source_id) REFERENCES sources(source_id)
    );
    CREATE TABLE chunks(
      chunk_id TEXT PRIMARY KEY, source_id TEXT NOT NULL, source_record_id TEXT NOT NULL,
      source_sha256 TEXT NOT NULL, source_version TEXT NOT NULL, locator TEXT NOT NULL, text TEXT NOT NULL,
      content_sha256 TEXT NOT NULL, source_quote TEXT NOT NULL, raw_field_pointer TEXT NOT NULL,
      quote_start INTEGER, quote_end INTEGER, species_scope TEXT NOT NULL, scientific_scope TEXT,
      taxonomy_level TEXT, category_scope TEXT NOT NULL, source_cluster_id TEXT NOT NULL,
      processing_scope TEXT NOT NULL, source_path TEXT NOT NULL, source_page INTEGER,
      retrieval_status TEXT NOT NULL, retrieval_eligible INTEGER NOT NULL, human_gold INTEGER NOT NULL DEFAULT 0,
      formal_admission INTEGER NOT NULL, embedding BLOB, embedding_model TEXT, embedding_digest TEXT,
      embedding_dimension INTEGER, transform_rule TEXT NOT NULL, restrictions_json TEXT NOT NULL,
      FOREIGN KEY(source_id) REFERENCES sources(source_id), FOREIGN KEY(source_record_id) REFERENCES source_records(source_record_id)
    );
    CREATE VIRTUAL TABLE chunks_fts USING fts5(chunk_id UNINDEXED, fts_text, source_id UNINDEXED, tokenize='unicode61');
    CREATE INDEX idx_chunks_source ON chunks(source_id);
    CREATE INDEX idx_chunks_status ON chunks(retrieval_status);
    """)


def verify_sources() -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]], dict[str, Any]]:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {"checked_at_local": dt.datetime.now().astimezone().isoformat(), "sources": [], "overall_status": "PASS"}
    loaded: dict[str, list[dict[str, Any]]] = {}
    copied: dict[str, Any] = {}
    for filename, (expected_size, expected_sha, expected_count) in EXPECTED.items():
        src = INPUT_DIR / filename
        dst = RAW_DIR / filename
        if not src.is_file():
            report["overall_status"] = "BLOCKED"
            report["sources"].append({"file": filename, "status": "SOURCE_MISSING", "path": str(src)})
            continue
        actual_size = src.stat().st_size
        actual_sha = sha256(src)
        try:
            rows = json.loads(src.read_text(encoding="utf-8-sig"))
            parse_status = "PASS" if isinstance(rows, list) else "FAIL_NOT_ARRAY"
            if not isinstance(rows, list):
                rows = []
        except Exception as exc:
            rows, parse_status = [], f"FAIL:{type(exc).__name__}:{exc}"
        schema_keys = list(rows[0].keys()) if rows and isinstance(rows[0], dict) else []
        missing_required = [i for i, row in enumerate(rows) if not isinstance(row, dict) or any(k not in row for k in schema_keys)]
        if actual_size != expected_size or actual_sha != expected_sha or len(rows) != expected_count or parse_status != "PASS":
            report["overall_status"] = "BLOCKED"
            status = "BLOCKED_INTEGRITY_MISMATCH"
        else:
            status = "PASS"
            if dst.exists():
                if dst.stat().st_size != expected_size or sha256(dst) != expected_sha:
                    raise RuntimeError(f"Existing immutable snapshot differs; refusing overwrite: {dst}")
            else:
                shutil.copyfile(src, dst)
            if dst.stat().st_size != expected_size or sha256(dst) != expected_sha:
                report["overall_status"] = "BLOCKED"
                status = "BLOCKED_COPY_MISMATCH"
        exact_json_counts = collections.Counter(json.dumps(r, ensure_ascii=False, sort_keys=True, separators=(",", ":")) for r in rows)
        if filename == "tfrin_fishery_qa.json":
            identity_counts = collections.Counter((str(r.get("title", "")).strip(), str(r.get("link", "")).strip()) for r in rows)
        elif filename == "animal_drug_info.json":
            identity_counts = collections.Counter(str(r.get("許可證字號", "")).strip() for r in rows)
        else:
            identity_counts = collections.Counter(str(r.get("所屬縣市", "")).strip() for r in rows)
        record = {
            "file": filename, "path": str(src), "immutable_copy": str(dst) if dst.exists() else None,
            "expected_size_bytes": expected_size, "actual_size_bytes": actual_size,
            "expected_sha256": expected_sha, "actual_sha256": actual_sha,
            "sha256_matches": actual_sha == expected_sha, "json_parse_status": parse_status,
            "expected_records": expected_count, "actual_records": len(rows),
            "field_count": len(schema_keys), "field_names": schema_keys,
            "rows_missing_schema_keys": len(missing_required),
            "exact_duplicate_record_excess": sum(n - 1 for n in exact_json_counts.values() if n > 1),
            "identity_duplicate_excess": sum(n - 1 for n in identity_counts.values() if n > 1),
            "identity_unique_count": len(identity_counts), "status": status,
        }
        report["sources"].append(record)
        copied[filename] = record
        loaded[filename] = rows
    return report, loaded, copied


def verify_dgbas() -> tuple[dict[str, Any], list[dict[str, Any]], Path | None]:
    integrity_file = STEP3V_DIR / "dgbas_2020_source_integrity.json"
    admission_file = STEP3V_DIR / "dgbas_2020_formal_admission_record.json"
    prov_file = STEP3V_DIR / "dgbas_2020_record_provenance.jsonl"
    card_file = STEP3V_DIR / "dgbas_six_evidence_cards_review.jsonl"
    result: dict[str, Any] = {"source_id": "DGBAS-79395-2020", "status": "NOT_INCLUDED", "reason": ""}
    if not DGBAS_PATH.is_file() or not all(p.is_file() for p in (integrity_file, admission_file, prov_file, card_file)):
        result["status"] = "BLOCKED_MISSING_ADMISSION_EVIDENCE"
        result["reason"] = "Step 3V source bytes or formal admission trace not found."
        return result, [], None
    admission = json.loads(admission_file.read_text(encoding="utf-8-sig"))
    integrity = json.loads(integrity_file.read_text(encoding="utf-8-sig"))
    actual = sha256(DGBAS_PATH)
    expected = "31c4cdb6fc3cdcd58abc4a5ba8a1cde908f1ca12f9f338fb39da4d4bf494dd31"
    raw = DGBAS_PATH.read_bytes()
    has_doctype = bool(re.search(br"<!\s*(DOCTYPE|ENTITY)", raw, re.I))
    try:
        root = ET.fromstring(raw)
        parse_status = "PASS"
    except Exception as exc:
        root, parse_status = None, f"FAIL:{type(exc).__name__}:{exc}"
    if actual != expected or not integrity.get("sha256_match") or admission.get("admission_execution_status") != "admitted_scope_limited" or parse_status != "PASS" or has_doctype:
        result.update({"status": "BLOCKED", "reason": "DGBAS hash/admission/XML precondition failed", "sha256_actual": actual, "sha256_expected": expected, "parse_status": parse_status, "doctype_or_entity": has_doctype})
        return result, [], None
    dgbas_snapshot = RAW_DIR / DGBAS_PATH.name
    if dgbas_snapshot.exists():
        if sha256(dgbas_snapshot) != expected:
            raise RuntimeError("Existing DGBAS immutable snapshot differs; refusing overwrite")
    else:
        shutil.copyfile(DGBAS_PATH, dgbas_snapshot)
    provenance = read_jsonl(prov_file)
    facts = []
    children = list(root)
    failures = []
    for row in provenance:
        loc = row["xml_record_locator"].rstrip("/").split("/")[-1]
        field = row["xml_field_locator"].rstrip("/").split("/")[-1]
        match = re.search(r"\[(\d+)\]$", loc)
        index_1based = int(match.group(1)) if match else None
        if not index_1based or index_1based > len(children):
            failures.append({"fact_id": row.get("derived_fact_id"), "reason": "xml_record_index_out_of_range", "locator": loc})
            continue
        rec = children[index_1based]
        node = next((x for x in list(rec) if x.tag == field), None)
        raw_value = (node.text or "").strip() if node is not None else None
        if raw_value != str(row.get("raw_value", "")).strip():
            failures.append({"fact_id": row.get("derived_fact_id"), "reason": "xml_value_mismatch", "expected": row.get("raw_value"), "actual": raw_value, "locator": row.get("xml_field_locator")})
            continue
        facts.append({**row, "xml_node_tag": field, "xml_raw_value_rechecked": raw_value, "derived_fact_id": row["derived_fact_id"]})
    result.update({
        "status": "PASS" if len(facts) == len(provenance) and not failures else "PARTIAL_BLOCKED",
        "path": str(DGBAS_PATH), "immutable_copy": str(RAW_DIR / DGBAS_PATH.name),
        "sha256_expected": expected, "sha256_actual": actual, "file_size_bytes": len(raw),
        "xml_parse_status": parse_status, "xml_root": root.tag if root is not None else None,
        "doctype_or_entity_declaration_present": has_doctype, "owner_admission_status": admission.get("admission_execution_status"),
        "reference_year": 2020, "reference_year_basis": admission.get("reference_year_basis"),
        "provenance_rows": len(provenance), "exact_xml_value_matches": len(facts), "mismatches": failures[:30],
        "retrieval_scope": "Fact only; native statistic labels, area, raw values and unit; never biological species inference",
    })
    return result, facts, RAW_DIR / DGBAS_PATH.name


def build_records_and_chunks(loaded: dict[str, list[dict[str, Any]]], copied: dict[str, Any], dgbas_facts: list[dict[str, Any]], dgbas_copy: Path | None) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    sources: list[dict[str, Any]] = []
    records: list[dict[str, Any]] = []
    chunks: list[dict[str, Any]] = []
    count_by_source: dict[str, dict[str, int]] = collections.defaultdict(lambda: collections.Counter())
    for source_id, meta in SOURCE_META.items():
        if source_id.startswith("DGBAS"):
            path = dgbas_copy
            if path is None:
                continue
            sz, h = path.stat().st_size, sha256(path)
            snap_date = "2020-reference-resource-reused-from-Step-3V"
            completeness = "FULL_RESOURCE_INTEGRITY_VERIFIED; 1511 provenance records mapped to XML fields"
        else:
            fname = meta["file"]
            check = copied.get(fname)
            path = RAW_DIR / fname
            if not check or check.get("status") != "PASS":
                continue
            sz, h = check["actual_size_bytes"], check["actual_sha256"]
            snap_date = "2026-10-20 API resource snapshot; publisher does not expose immutable release ID in downloaded JSON"
            completeness = "DATASET_COMPLETENESS_UNKNOWN" if source_id == "MOA-ANIMAL-DRUG-OPEN-7274" else "SNAPSHOT_RECORD_COUNT_VERIFIED; resource is periodically updated"
        sources.append({
            "source_id": source_id, "dataset_id": meta["dataset_id"], "title": meta["title"], "publisher": meta["publisher"],
            "dataset_url": meta["dataset_url"], "resource_url": meta["resource_url"], "source_sha256": h, "file_size_bytes": sz,
            "source_file": str(path), "license": meta["license"], "license_url": "https://data.gov.tw/license",
            "attribution": meta["attribution"], "owner_admission_status": "APPROVED_SCOPE_LIMITED" if not source_id.startswith("DGBAS") else "ALREADY_ADMITTED_SCOPE_LIMITED_STEP3V",
            "license_scope_status": "OGL_V1_DATASET_RESOURCE_SCOPE_CONFIRMED_WITH_THIRD_PARTY_CAVEAT",
            "identity_status": "SOURCE_BYTES_HASH_AND_OFFICIAL_RESOURCE_URL_MATCH",
            "version_status": "SNAPSHOT_VERSIONED; PUBLISHER_RELEASE_ID_NOT_AVAILABLE" if not source_id.startswith("DGBAS") else "RESOURCE_VERSION_2020_REFERENCE_YEAR_VERIFIED_FROM_OFFICIAL_RESOURCE_LABEL",
            "applicability_status": "RECORD_LEVEL_LITERAL_SCOPE_ONLY; NO_UNSUPPORTED_ALIAS_EXPANSION",
            "completeness_status": completeness, "processing_scope": meta["scope"],
            "source_cluster_id": "SC-MOA-TFRI-OPEN-114846" if source_id.startswith("MOA-TFRI") else "SC-MOA-DRUG-OPEN-7274" if source_id.startswith("MOA-ANIMAL") else "SC-MOA-EEL-STOCKING-41845" if source_id.startswith("MOA-EEL") else "SC-DGBAS-79395",
            "metadata": {k: v for k, v in meta.items() if k not in {"file"}},
        })

    def add_record_chunk(source_id: str, record_id: str, locator: str, payload: dict[str, Any], status: str, reason: str, chunk_specs: list[dict[str, Any]]) -> None:
        rec_hash = content_hash(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        records.append({"source_record_id": record_id, "source_id": source_id, "source_record_locator": locator, "source_record_sha256": rec_hash, "eligibility_status": status, "eligibility_reason": reason, "original_record_json": payload})
        count_by_source[source_id][status] += 1
        for spec in chunk_specs:
            chunks.append({**spec, "source_id": source_id, "source_record_id": record_id, "source_record_locator": locator, "raw_record": payload,
                           "retrieval_status": spec.get("retrieval_status", status), "eligibility_reason": spec.get("eligibility_reason", reason)})

    tfrin = loaded.get("tfrin_fishery_qa.json", [])
    tfrin_copy = RAW_DIR / "tfrin_fishery_qa.json"
    source_id = "MOA-TFRI-OPEN-114846"
    for idx, row in enumerate(tfrin):
        record_id = f"114846-ROW-{idx+1:04d}"
        title = str(row.get("title", ""))
        answer = clean_html(str(row.get("description", "")))
        full = title + "\n" + answer
        mentions = species_mentions(full)
        target_mentions = [x for x in mentions if x in TARGET_SPECIES]
        category = topic_labels(full)
        locator = f"JSON array /[{idx}]; fields /title, /description, /pubdate; source link={row.get('link','')}"
        payload = dict(row)
        spec_list: list[dict[str, Any]] = []
        if target_mentions:
            parts = split_answer(answer)
            # Keep a single source-record cluster; each evidence chunk retains its exact JSON field span.
            for pno, (part, start, end) in enumerate(parts or [(answer, 0, len(answer))], 1):
                cid = f"TFRI-114846-{idx+1:04d}-C{pno:02d}"
                text_value = f"原始標題：{title}\n原始回答片段：{part}\n公布日期：{row.get('pubdate','')}"
                spec_list.append({
                    "chunk_id": cid, "source_sha256": EXPECTED["tfrin_fishery_qa.json"][1], "source_version": f"official JSON snapshot 2026-10-20; record pubdate={row.get('pubdate','')}",
                    "locator": f"JSON array /[{idx}]/description; normalized-rendered-character-span [{start}:{end}); title=/[{idx}]/title",
                    "text": text_value, "content_sha256": content_hash(text_value), "source_quote": part,
                    "raw_field_pointer": f"/[{idx}]/description", "quote_start": start, "quote_end": end,
                    "species_scope_list": mentions, "scientific_scope": None, "taxonomy_level": "literal_common_name_mentions_only",
                    "category_scope_list": category, "source_cluster_id": "SC-MOA-TFRI-OPEN-114846", "processing_scope": "OGL_V1_EXACT_RESOURCE_LOCAL_RESEARCH_INDEX_WITH_ATTRIBUTION",
                    "source_path": str(tfrin_copy), "source_page": None, "retrieval_status": "RETRIEVAL_ELIGIBLE", "retrieval_eligible": 1,
                    "transform_rule": "HTML br tags to newline; strip tags; HTML entity decode; exact raw JSON is retained in source_records; no page number inferred.",
                    "restrictions": {"direct_source_answer_only": True, "external_linked_page_not_included": True, "scope_basis": "literal species names in this record only", "source_date": row.get("pubdate")},
                })
            status, reason = "RETRIEVAL_ELIGIBLE", "Exact target fish term occurs in original title/answer; record-scoped Q&A; species is not broadened."
        else:
            status, reason = "EXCLUDED", "No literal target-species scope in this record; no general cross-species scope inferred. Raw row retained for audit but not indexed."
        add_record_chunk(source_id, record_id, locator, payload, status, reason, spec_list)

    drug_rows = loaded.get("animal_drug_info.json", [])
    drug_path = RAW_DIR / "animal_drug_info.json"
    source_id = "MOA-ANIMAL-DRUG-OPEN-7274"
    permit_seen = collections.Counter(str(r.get("許可證字號", "")).strip() for r in drug_rows)
    for idx, row in enumerate(drug_rows):
        permit = str(row.get("許可證字號", "")).strip()
        indication = str(row.get("效能(適應症)", ""))
        mentions = species_mentions(indication)
        target_mentions = [x for x in mentions if x in TARGET_SPECIES]
        rid = f"7274-{permit or 'NO-PERMIT'}-ROW-{idx+1:05d}"
        locator = f"JSON array /[{idx}]; fields /許可證字號, /動物用藥品中文名稱, /效能(適應症), /成分, /核發日期, /有效期間"
        specs = []
        if target_mentions:
            displayed = [f"{k}：{row.get(k, '')}" for k in ["許可證字號", "動物用藥品中文名稱", "動物用藥品英文名稱", "劑型", "效能(適應症)", "成分", "核發日期", "有效期間", "外銷專用"] if row.get(k)]
            text_value = "\n".join(displayed)
            cid = f"DRUG-7274-{idx+1:05d}"
            specs.append({
                "chunk_id": cid, "source_sha256": EXPECTED["animal_drug_info.json"][1], "source_version": "official JSON snapshot 2026-10-20; API release/version identifier unavailable; dataset completeness unknown",
                "locator": locator, "text": text_value, "content_sha256": content_hash(text_value), "source_quote": text_value,
                "raw_field_pointer": f"/[{idx}]/*selected_original_fields", "quote_start": 0, "quote_end": len(text_value),
                "species_scope_list": mentions, "scientific_scope": None, "taxonomy_level": "literal_species_in_indication_field_only",
                "category_scope_list": ["Medication / Law"], "source_cluster_id": "SC-MOA-DRUG-OPEN-7274",
                "processing_scope": "OGL_V1_EXACT_RESOURCE_PERMIT_FACTS_ONLY_NO_DOSAGE_OR_WITHDRAWAL_INFERENCE",
                "source_path": str(drug_path), "source_page": None, "retrieval_status": "RETRIEVAL_ELIGIBLE", "retrieval_eligible": 1,
                "transform_rule": "Selected original JSON field values joined with field labels; HTML formatting retained in source record; no fields inferred.",
                "restrictions": {"record_is_not_treatment_advice": True, "no_dose_frequency_withdrawal_inference": True, "no_current_validity_claim": True,
                                 "dataset_completeness": "DATASET_COMPLETENESS_UNKNOWN; downloaded API snapshot contains 9999 rows", "permit_number": permit,
                                 "validity_field_is_reported_not_interpreted": row.get("有效期間", "")},
            })
            status, reason = "RETRIEVAL_ELIGIBLE", "Exact target-species term occurs in original indication field; factual permit fields only; not a treatment recommendation."
        else:
            status, reason = "EXCLUDED", "No literal target-species term in indication field; excluded from fish-specific retrieval; raw row retained."
        add_record_chunk(source_id, rid, locator, dict(row), status, reason, specs)

    eel_rows = loaded.get("eel_stocking_by_county.json", [])
    eel_path = RAW_DIR / "eel_stocking_by_county.json"
    source_id = "MOA-EEL-STOCKING-OPEN-41845"
    for idx, row in enumerate(eel_rows):
        record_id = f"41845-ROW-{idx+1:03d}"
        text_value = "\n".join(f"{k}：{v}" for k, v in row.items() if v not in (None, ""))
        locator = f"JSON array /[{idx}]; native county and statistic fields; no reference-year field in source schema"
        spec = {"chunk_id": f"EEL-STOCKING-41845-{idx+1:03d}", "source_sha256": EXPECTED["eel_stocking_by_county.json"][1],
                "source_version": "official JSON snapshot 2026-10-20; no statistical reference year identified", "locator": locator,
                "text": text_value, "content_sha256": content_hash(text_value), "source_quote": text_value,
                "raw_field_pointer": f"/[{idx}]", "quote_start": 0, "quote_end": len(text_value), "species_scope_list": ["STATISTICAL_DATASET_LABEL_EEL_ONLY"],
                "scientific_scope": None, "taxonomy_level": "dataset_label_only_no_biological_species_assertion", "category_scope_list": ["Fact"],
                "source_cluster_id": "SC-MOA-EEL-STOCKING-41845", "processing_scope": "OGL_V1_EXACT_RESOURCE_CONTEXT_ONLY_NO_REFERENCE_YEAR",
                "source_path": str(eel_path), "source_page": None, "retrieval_status": "CONTEXT_ONLY", "retrieval_eligible": 0,
                "transform_rule": "Original JSON row serialized as field labels and values; no year or unit added.",
                "restrictions": {"reference_year": None, "no_trend_or_husbandry_inference": True}}
        add_record_chunk(source_id, record_id, locator, dict(row), "CONTEXT_ONLY", "Year absent; background only; not searchable for benchmark retrieval.", [spec])

    source_id = "DGBAS-79395-2020"
    for row in dgbas_facts:
        raw_fact_id = row.get("derived_fact_id")
        if raw_fact_id:
            fact_id = str(raw_fact_id)
        else:
            stable_key = "|".join([str(row.get("xml_record_locator", "")), str(row.get("xml_field_locator", "")), str(row.get("raw_value", ""))])
            fact_id = "DGBAS-F-" + hashlib.sha256(stable_key.encode("utf-8")).hexdigest()[:20]
        payload = dict(row)
        area = str(row.get("statistical_area", ""))
        cat = str(row.get("original_category_label", ""))
        raw_value = str(row.get("xml_raw_value_rechecked", ""))
        unit = str(row.get("original_unit", ""))
        display = f"資料資源標籤：民國109年（2020）；統計地域：{area}；原始統計分類名稱：{cat}；原始欄位：{row.get('xml_node_tag') or row.get('xml_field_locator','').split('/')[-1]}；原始值：{raw_value}；原始單位：{unit}。"
        locator = f"XML {row['xml_record_locator']} / field {row['xml_field_locator']}"
        status = "RETRIEVAL_ELIGIBLE"
        spec = {"chunk_id": f"DGBAS-79395-2020-{fact_id}", "source_sha256": "31c4cdb6fc3cdcd58abc4a5ba8a1cde908f1ca12f9f338fb39da4d4bf494dd31",
                "source_version": "resource label 民國109年; reference year 2020; XML has no explicit year field", "locator": locator,
                "text": display, "content_sha256": content_hash(display), "source_quote": display, "raw_field_pointer": row["xml_field_locator"],
                "quote_start": 0, "quote_end": len(display), "species_scope_list": ["DGBAS_NATIVE_STATISTICAL_CATEGORY_ONLY"],
                "scientific_scope": None, "taxonomy_level": "statistical_category_not_species", "category_scope_list": ["Fact"],
                "source_cluster_id": "SC-DGBAS-79395", "processing_scope": "ADMITTED_SCOPE_LIMITED_2020_SINGLE_YEAR_DESCRIPTIVE_FACT",
                "source_path": str(dgbas_copy), "source_page": None, "retrieval_status": status, "retrieval_eligible": 1,
                "transform_rule": "Field labels plus original XML lexical value; Decimal validation; retain native category and unit; no inferred species or trend.",
                "restrictions": {"reference_year": 2020, "year_basis": "official resource label only", "native_statistical_category": cat,
                                 "no_exact_biological_species_inference": True, "query_gate": "Only when user explicitly asks for 2020/DGBAS native statistical data; never species husbandry advice."}}
        add_record_chunk(source_id, fact_id, locator, payload, status, "Formal Step 3V limited Admission; one-year descriptive Fact only.", [spec])

    for item in sources:
        item["record_counts"] = dict(count_by_source.get(item["source_id"], {}))
        item["record_counts"]["total_source_records"] = sum(count_by_source.get(item["source_id"], {}).values())
    counts = {source_id: dict(counter) for source_id, counter in count_by_source.items()}
    return sources, records, chunks, counts


def embed_all(chunks: list[dict[str, Any]]) -> dict[str, np.ndarray]:
    tags = requests.get("http://127.0.0.1:11434/api/tags", timeout=10).json().get("models", [])
    model = next((x for x in tags if x.get("name") == "bge-m3:latest"), None)
    expected = "7907646426070047a77226ac3e684fbbe8410524f7b4a74d02837e43f2146bab"
    if not model or str(model.get("digest", "")).removeprefix("sha256:") != expected:
        raise RuntimeError("BGE-M3 identity mismatch or missing")
    eligible = [c for c in chunks if c["retrieval_eligible"]]
    out: dict[str, np.ndarray] = {}
    checkpoint = WORK / "embedding_checkpoint_v2.jsonl"
    if checkpoint.exists():
        for row in read_jsonl(checkpoint):
            vec = np.asarray(row.get("embedding", []), dtype=np.float32)
            if vec.shape == (1024,) and row.get("chunk_id") in {c["chunk_id"] for c in eligible}:
                out[row["chunk_id"]] = vec
    with checkpoint.open("a", encoding="utf-8", newline="\n") as f:
        for start in range(0, len(eligible), 24):
            batch = [c for c in eligible[start:start+24] if c["chunk_id"] not in out]
            if not batch:
                continue
            resp = requests.post("http://127.0.0.1:11434/api/embed", json={"model": "bge-m3:latest", "input": [c["text"] for c in batch], "truncate": True}, timeout=240)
            resp.raise_for_status()
            vectors = resp.json().get("embeddings", [])
            if len(vectors) != len(batch):
                raise RuntimeError(f"embedding count mismatch batch={len(batch)} response={len(vectors)}")
            for chunk, vector in zip(batch, vectors, strict=True):
                arr = np.asarray(vector, dtype=np.float32)
                if arr.shape != (1024,) or not np.isfinite(arr).all():
                    raise RuntimeError(f"invalid embedding for {chunk['chunk_id']}: {arr.shape}")
                norm = float(np.linalg.norm(arr))
                if norm <= 0:
                    raise RuntimeError("zero embedding")
                arr /= norm
                out[chunk["chunk_id"]] = arr
                f.write(json.dumps({"chunk_id": chunk["chunk_id"], "embedding": arr.tolist()}, separators=(",", ":")) + "\n")
            f.flush()
    if len(out) != len(eligible):
        raise RuntimeError(f"embedding coverage {len(out)}/{len(eligible)}")
    return out


def create_db(sources: list[dict[str, Any]], records: list[dict[str, Any]], chunks: list[dict[str, Any]], embeddings: dict[str, np.ndarray]) -> dict[str, Any]:
    if DB_PATH.exists():
        raise RuntimeError(f"Refusing to overwrite corpus DB: {DB_PATH}")
    con = sqlite3.connect(DB_PATH)
    try:
        schema_init(con)
        manifest = {"corpus_id": "marine_hybrid_rag_corpus_v3_research_isolated", "corpus_version": "3.0.0", "build_scope": "Three current owner-approved official OGL v1 data resources plus pre-existing DGBAS-79395 2020 limited admission; no other historic candidates.", "human_gold": False}
        con.executemany("INSERT INTO corpus_meta(key,value) VALUES (?,?)", [(k, json.dumps(v, ensure_ascii=False)) for k,v in manifest.items()])
        for s in sources:
            meta = s.copy()
            for key in ["source_id", "dataset_id", "title", "publisher", "dataset_url", "resource_url", "source_sha256", "file_size_bytes", "source_file", "license", "license_url", "attribution", "owner_admission_status", "license_scope_status", "identity_status", "version_status", "applicability_status", "completeness_status", "processing_scope", "source_cluster_id"]:
                pass
            con.execute("""INSERT INTO sources VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
                s["source_id"], s["dataset_id"], s["title"], s["publisher"], s["dataset_url"], s["resource_url"], s["source_sha256"], s["file_size_bytes"], s["source_file"], s["license"], s["license_url"], s["attribution"], s["owner_admission_status"], s["license_scope_status"], s["identity_status"], s["version_status"], s["applicability_status"], s["completeness_status"], s["processing_scope"], s["source_cluster_id"], json.dumps(s, ensure_ascii=False, sort_keys=True)))
        for r in records:
            con.execute("INSERT INTO source_records VALUES (?,?,?,?,?,?,?,?)", (
                r["source_record_id"], r["source_id"], r["source_record_locator"], r["source_record_sha256"],
                r["eligibility_status"], r["eligibility_reason"], json.dumps(r["original_record_json"], ensure_ascii=False, sort_keys=True), r.get("duplicate_group_id")))
        for c in chunks:
            vector = embeddings.get(c["chunk_id"])
            vector_blob = vector.astype(np.float32).tobytes() if vector is not None else None
            scope = c["species_scope_list"]
            categories = c["category_scope_list"]
            con.execute("INSERT INTO chunks VALUES (" + ",".join("?" for _ in range(30)) + ")", (
                c["chunk_id"], c["source_id"], c["source_record_id"], c["source_sha256"], c["source_version"], c["locator"], c["text"], c["content_sha256"], c["source_quote"], c["raw_field_pointer"], c.get("quote_start"), c.get("quote_end"),
                "|".join(scope), c.get("scientific_scope"), c.get("taxonomy_level"), json.dumps(categories, ensure_ascii=False), c["source_cluster_id"], c["processing_scope"], c["source_path"], c.get("source_page"), c["retrieval_status"], int(c["retrieval_eligible"]), 0, 1,
                vector_blob, "bge-m3:latest" if vector is not None else None, "7907646426070047a77226ac3e684fbbe8410524f7b4a74d02837e43f2146bab" if vector is not None else None, 1024 if vector is not None else None,
                c["transform_rule"], json.dumps(c["restrictions"], ensure_ascii=False, sort_keys=True)))
            if int(c["retrieval_eligible"]):
                con.execute("INSERT INTO chunks_fts(chunk_id,fts_text,source_id) VALUES (?,?,?)", (c["chunk_id"], " ".join(cjk_tokens(c["text"])), c["source_id"]))
        con.commit()
        integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
        fts_count = con.execute("SELECT count(*) FROM chunks_fts").fetchone()[0]
        chunk_count = con.execute("SELECT count(*) FROM chunks").fetchone()[0]
        embed_count = con.execute("SELECT count(*) FROM chunks WHERE embedding IS NOT NULL").fetchone()[0]
        eligible_count = con.execute("SELECT count(*) FROM chunks WHERE retrieval_eligible=1").fetchone()[0]
        source_count = con.execute("SELECT count(*) FROM sources").fetchone()[0]
        record_count = con.execute("SELECT count(*) FROM source_records").fetchone()[0]
        if integrity != "ok" or fts_count != eligible_count or embed_count != eligible_count:
            raise RuntimeError(f"DB validation failed integrity={integrity}, fts={fts_count}, eligible={eligible_count}, embeddings={embed_count}")
        return {"database": str(DB_PATH), "database_sha256": sha256(DB_PATH), "integrity_check": integrity, "source_count": source_count,
                "source_record_count": record_count, "chunk_count": chunk_count, "fts_row_count": fts_count, "embedding_count": embed_count,
                "retrieval_eligible_chunk_count": eligible_count, "context_only_chunk_count": chunk_count-eligible_count,
                "embedding_dimension": 1024, "embedding_model": "bge-m3:latest", "embedding_digest": "7907646426070047a77226ac3e684fbbe8410524f7b4a74d02837e43f2146bab", "normalized_l2": True}
    finally:
        con.close()


def assign_duplicate_groups(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep source-record identity while grouping exact or stable-identity duplicates."""
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = collections.defaultdict(list)
    for row in records:
        payload = row["original_record_json"]
        source_id = row["source_id"]
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        exact_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        if source_id == "MOA-TFRI-OPEN-114846":
            identity = json.dumps([payload.get("title"), payload.get("link")], ensure_ascii=False, separators=(",", ":"))
            identity_basis = "source title + link"
        elif source_id == "MOA-ANIMAL-DRUG-OPEN-7274":
            identity = str(payload.get("許可證字號", "")).strip()
            identity_basis = "許可證字號"
        elif source_id == "MOA-EEL-STOCKING-OPEN-41845":
            identity = str(payload.get("所屬縣市", "")).strip()
            identity_basis = "所屬縣市"
        else:
            identity = exact_hash
            identity_basis = "canonical raw record hash"
        groups[(source_id, identity, identity_basis)].append(row)
        row["_exact_raw_hash"] = exact_hash
    output = []
    for (source_id, identity, basis), members in groups.items():
        if len(members) < 2:
            continue
        group_hash = hashlib.sha256((source_id + "\0" + identity).encode("utf-8")).hexdigest()[:16]
        group_id = "DUP-" + group_hash
        exact = len({m["_exact_raw_hash"] for m in members}) == 1
        for member in members:
            member["duplicate_group_id"] = group_id
        output.append({"duplicate_group_id": group_id, "source_id": source_id, "identity_basis": basis,
                       "member_source_record_ids": [m["source_record_id"] for m in members], "member_count": len(members),
                       "all_raw_records_identical": exact, "relationship_status": "EXACT_DUPLICATE" if exact else "SAME_SOURCE_IDENTITY_NEEDS_CONTENT_REVIEW"})
    for row in records:
        row.pop("_exact_raw_hash", None)
    return output


def main() -> None:
    integrity, loaded, copied = verify_sources()
    write_json(WORK / "official_raw_data_integrity_report.json", integrity)
    if integrity["overall_status"] != "PASS":
        raise SystemExit("Official source integrity failed; stop before Corpus build.")
    dgbas_report, dgbas_facts, dgbas_copy = verify_dgbas()
    write_json(WORK / "dgbas_admission_revalidation.json", dgbas_report)
    if dgbas_report["status"] not in {"PASS", "PARTIAL_BLOCKED"}:
        dgbas_facts, dgbas_copy = [], None
    sources, records, chunks, status_counts = build_records_and_chunks(loaded, copied, dgbas_facts, dgbas_copy)
    duplicate_groups = assign_duplicate_groups(records)
    write_jsonl(WORK / "source_record_duplicate_groups.jsonl", duplicate_groups)
    write_json(WORK / "approved_official_sources_v3.json", {
        "new_owner_approved_sources": [s for s in sources if s["source_id"] != "DGBAS-79395-2020"],
        "preexisting_admitted_source": next((s for s in sources if s["source_id"] == "DGBAS-79395-2020"), None),
        "owner_admission_and_license_are_separate": True,
        "license": {"name": "政府資料開放授權條款第1版", "url": "https://data.gov.tw/license", "requirements": ["explicit attribution as provider/agency, year, distinguishing dataset and version", "respect third-party moral rights", "license excludes patents and trademarks", "official dataset pages must identify actual resource under license"], "third_party_scope_caveat": "This admission is limited to the named official JSON/XML resources; it does not extend to linked pages, third-party attachments, or external documents."},
        "owner_approval_reference": "Explicit current-conversation owner decision approving the three exact resources for isolated research Corpus v3; not a digital signature or blanket authorization for unrelated materials."
    })
    write_json(WORK / "source_admission_v3.json", {"registry_version": "source_admission_v3.0.0", "sources": sources, "not_included": ["Phase AA 27 candidate cards with no full-text admission", "50 restricted/unverified technical files", "S08/S10 unresolved crosswalks", "MOJ dataset 18290 partial ZIP"], "statuses_are_independent": ["owner_admission_status", "license_scope_status", "identity_status", "version_status", "applicability_status", "completeness_status", "retrieval_eligibility"]})
    write_jsonl(WORK / "source_record_status_registry.jsonl", [{"source_record_id":r["source_record_id"],"source_id":r["source_id"],"source_record_locator":r["source_record_locator"],"source_record_sha256":r["source_record_sha256"],"eligibility_status":r["eligibility_status"],"eligibility_reason":r["eligibility_reason"],"duplicate_group_id":r.get("duplicate_group_id")} for r in records])
    write_jsonl(WORK / "corpus_chunk_source_registry.jsonl", [{k:c.get(k) for k in ["chunk_id","source_id","source_record_id","source_sha256","source_version","locator","source_quote","raw_field_pointer","quote_start","quote_end","species_scope_list","category_scope_list","source_cluster_id","retrieval_status","retrieval_eligible","eligibility_reason","restrictions"]} for c in chunks])
    embeddings = embed_all(chunks)
    db_info = create_db(sources, records, chunks, embeddings)
    write_json(WORK / "corpus_build_db_validation.json", db_info)
    source_count_counts = {}
    for source_id, stat in status_counts.items():
        source_count_counts[source_id] = {"source_records_by_status": stat, "chunks_by_status": dict(collections.Counter(c["retrieval_status"] for c in chunks if c["source_id"] == source_id))}
    unique_checksums = sorted({s["source_sha256"] for s in sources})
    manifest = {"corpus_id":"marine_hybrid_rag_corpus_v3_research_isolated","corpus_version":"3.0.0","built_at_local":dt.datetime.now().astimezone().isoformat(),
        "status":"ISOLATED_RESEARCH_CORPUS_V3_BUILT; NOT_PRODUCTION; NOT_EVALUATION_CORPUS_V2", "source_ids":[s["source_id"] for s in sources], "source_count":len(sources),
        "different_original_sha256_count":len(unique_checksums), "original_sha256":unique_checksums, "source_records":len(records), "chunks":len(chunks),
        "retrieval_eligible_chunks":sum(int(c["retrieval_eligible"]) for c in chunks), "context_only_chunks":sum(c["retrieval_status"]=="CONTEXT_ONLY" for c in chunks),
        "excluded_source_records":sum(r["eligibility_status"]=="EXCLUDED" for r in records), "source_counts":source_count_counts, "sqlite":db_info,
        "bm25":{"implementation":"SQLite FTS5 unicode61 over CJK bigram-tokenized derived text","row_count":db_info["fts_row_count"]},
        "dense":{"model":"bge-m3:latest","digest":"7907646426070047a77226ac3e684fbbe8410524f7b4a74d02837e43f2146bab","dimension":1024,"normalized_l2":True,"count":db_info["embedding_count"]},
        "fusion":{"algorithm":"Reciprocal Rank Fusion","k":60},"reranker":{"model":"BAAI/bge-reranker-v2-m3","snapshot":"953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e"},
        "scope_controls":{"drug_data":"factual permit fields only; no dosage/withdrawal inference; 9999-row completeness unknown","eel_stocking":"context only; no year in source data","dgbas":"2020 one-year descriptive Fact only; native statistic category; no species inference"},
        "record_count_by_source_status":status_counts}
    write_json(WORK / "corpus_v3_manifest.json", manifest)
    coverage = {"corpus_id":manifest["corpus_id"],"method":"literal source scope and topic scans; not expert validation; overlapping categories","by_species":{},"by_category":{},"record_counts":source_count_counts}
    for fish in TARGET_SPECIES:
        eligible = [c for c in chunks if c["retrieval_eligible"] and fish in c["species_scope_list"]]
        coverage["by_species"][fish] = {"retrieval_eligible_chunks":len(eligible),"unique_source_records":len({c["source_record_id"] for c in eligible}),"source_ids":sorted({c["source_id"] for c in eligible}),"categories":dict(collections.Counter(cat for c in eligible for cat in c["category_scope_list"])),"note":"Exact literal source scope only; no alias expansion. DGBAS statistical categories and eel stocking rows excluded from biological species-specific coverage."}
    for category in ["Water Quality","Disease","Climate / Cold","Medication / Law","Calculation","Fact"]:
        subset = [c for c in chunks if c["retrieval_eligible"] and category in c["category_scope_list"]]
        coverage["by_category"][category] = {"retrieval_eligible_chunks":len(subset),"unique_source_records":len({c["source_record_id"] for c in subset}),"species_scope_counts":dict(collections.Counter(sp for c in subset for sp in c["species_scope_list"])),"note":"Keyword-based topic classification is a retrieval hint, not a verified benchmark answer label."}
    write_json(WORK / "corpus_v3_source_coverage.json", coverage)
    quality = [
        "# Corpus v3 品質與整合報告", "", f"- Corpus：`{manifest['corpus_id']}`，版本 `{manifest['corpus_version']}`。",
        f"- 來源數：{len(sources)}；不同原始 SHA-256：{len(unique_checksums)}；原始來源紀錄：{len(records)}。",
        f"- Chunk 數：{len(chunks)}；Retrieval eligible：{manifest['retrieval_eligible_chunks']}；Context only：{manifest['context_only_chunks']}；排除原始紀錄：{manifest['excluded_source_records']}。",
        f"- SQLite integrity：`{db_info['integrity_check']}`；FTS5：{db_info['fts_row_count']} 列；BGE-M3：{db_info['embedding_count']} 個 1024 維 L2 正規化向量。", "",
        "## 來源邊界", "", "只納入三份本輪明確核准、且政府資料開放平台列示 OGL v1 的指定官方資源，另納入 Step 3V 已有限准入的 DGBAS 2020 XML。Owner Admission、授權範圍、來源身分、版本、適用性及 Retrieval Eligibility 分欄保存。",
        "", "DGBAS 以原始 XML 的 1,511 筆 record/field provenance 重驗並建立 Fact 原子記錄；其統計分類僅是原始統計類別，不是精確生物物種。檢索側僅能在明確統計問題時用。鰻魚放養量 JSON 未見年度，9 列均為 Context only。動物用藥 API 快照有 9,999 列但完整性未能證實，故標記 `DATASET_COMPLETENESS_UNKNOWN`；索引僅保留適應症欄明確出現六目標魚種的許可事實，不提供劑量、頻率、停藥期或現行治療建議。",
        "", "## 解析與切塊", "", "水試所 JSON 以原始 Record 為來源群組，長答案按原始段落/句界切成多個 Chunk；所有 Chunk 保留同一 source_record_id，故不視為獨立來源。只將標題/回答中出現目標魚種字串的記錄放入檢索索引；其餘原始列保留在 `source_records` 並標記 EXCLUDED（語料範圍排除，不等同無權使用）。引文位置為 JSON Pointer 加正規化顯示文字的字元區間，無虛構頁碼。",
        "", "Phase AA 的 27 張研究事實卡、50 份使用依據未完成的文件、S08/S10 未核實來源、MOJ 不完整 ZIP 均未匯入。未以舊候選索引重新命名；此 SQLite 係從原始 JSON/XML bytes 重新建立。", "",
        "## 限制", "", "來源內容及標題文字命中是來源覆蓋線索，不是專家適用性或題目答案驗證。所有 AI/程式標註不是 Human Gold。新增 Open Data 來源授權僅涵蓋指定資源，不涵蓋外連頁面或第三方附件。"
    ]
    (WORK / "corpus_v3_quality_report.md").write_text("\n".join(quality) + "\n", encoding="utf-8")
    print(json.dumps({"workspace":str(WORK),"sources":len(sources),"records":len(records),"chunks":len(chunks),"retrieval_eligible":manifest["retrieval_eligible_chunks"],"context_only":manifest["context_only_chunks"],"excluded_records":manifest["excluded_source_records"],"db":db_info},ensure_ascii=False))


if __name__ == "__main__":
    main()
