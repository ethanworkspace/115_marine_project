from __future__ import annotations

import hashlib
import html
import json
import re
import sqlite3
import struct
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import requests

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
RAW = ROOT / "research_staging/official_downloads/phase_ab_recovery_20261020_172529"
DB = RAW / "official_open_data_research_index_v2.sqlite3"
PY = ROOT / ".venv/Scripts/python.exe"
OLLAMA_TAGS = "http://127.0.0.1:11434/api/tags"
OLLAMA_EMBED = "http://127.0.0.1:11434/api/embed"
EMBED_MODEL = "bge-m3:latest"
EMBED_DIGEST = "7907646426070047a77226ac3e684fbbe8410524f7b4a74d02837e43f2146bab"

URLS = {
    "tfrin": "https://data.moa.gov.tw/Service/OpenData/TfrinRss/TfrinRss02.aspx?IsTransData=1&UnitId=B71",
    "drug": "https://data.moa.gov.tw/Service/OpenData/FromM/ADProData.aspx",
    "eel": "https://data.moa.gov.tw/Service/OpenData/DataFileService.aspx?IsTransData=1&UnitId=B36",
    "law_page": "https://data.gov.tw/dataset/18290",
    "law_zip": "https://sendlaw.moj.gov.tw/PublicData/GetFile.ashx?AuData=CM&DType=XML",
    "license": "https://data.gov.tw/license",
}

# Literal labels are kept separate. Specific seabass labels are not broadened to generic 鱸魚.
SPECIES_TERMS = {
    "虱目魚": ["虱目魚"],
    "吳郭魚": ["吳郭魚"],
    "台灣鯛": ["台灣鯛"],
    "石斑魚": ["石斑魚", "鞍帶石斑", "龍膽石斑", "青斑", "老虎斑"],
    "鱸魚": ["鱸魚"],
    "金目鱸": ["金目鱸"],
    "七星鱸": ["七星鱸"],
    "烏魚": ["烏魚", "烏仔魚"],
    "鰻魚": ["鰻魚"],
    "白鰻": ["白鰻"],
    "日本鰻": ["日本鰻"],
}
TOPICS = {
    "water_quality": ["溶氧", "水質", "酸鹼", "pH", "氨氮", "亞硝酸", "鹽度", "水溫"],
    "disease": ["疾病", "病原", "感染", "寄生蟲", "症狀", "防治", "病害"],
    "climate_cold": ["寒害", "低溫", "寒流", "防寒", "氣候", "颱風"],
    "culture_management": ["養殖", "放養", "投餵", "飼料", "魚塭", "繁殖", "成長", "管理"],
    "calculation": ["換肉率", "飼料轉換率", "成長率", "存活率", "密度", "計算", "公式", "百分比"],
    "medication_law": ["用藥", "藥物", "藥品", "許可證", "停藥", "法規", "劑量"],
}


def sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def write_json(path: Path, obj: Any) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows), encoding="utf-8")


def field_text(value: Any) -> str:
    text = html.unescape(str(value or ""))
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(div|p|li|tr|h[1-6])\s*>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[ \t\u00a0]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    return text.strip()


def detect_scopes(text: str) -> list[str]:
    found = []
    for label, terms in SPECIES_TERMS.items():
        if any(term in text for term in terms):
            found.append(label)
    return found or ["species_unknown"]


def detect_topics(text: str) -> list[str]:
    return [key for key, terms in TOPICS.items() if any(term.lower() in text.lower() for term in terms)] or ["fact"]


def split_text_spans(text: str, max_chars: int = 700) -> list[tuple[int, int]]:
    if not text:
        return [(0, 0)]
    spans: list[tuple[int, int]] = []
    start = 0
    n = len(text)
    boundary = re.compile(r"(?<=[。！？；\n])")
    while start < n:
        hard_end = min(start + max_chars, n)
        breaks = [m.end() for m in boundary.finditer(text, start, hard_end)] if hard_end < n else []
        end = breaks[-1] if breaks else hard_end
        if end <= start:
            end = hard_end
        spans.append((start, end))
        start = end
    return spans


def load_json(path: Path) -> tuple[bytes, Any]:
    raw = path.read_bytes()
    if not raw:
        raise ValueError(f"empty file: {path.name}")
    data = json.loads(raw.decode("utf-8-sig"))
    if not isinstance(data, list):
        raise ValueError(f"expected top-level list: {path.name}")
    return raw, data


def field_completeness(rows: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    keys = sorted(set().union(*(r.keys() for r in rows))) if rows else []
    return {k: {"nonempty": sum(1 for r in rows if r.get(k) not in (None, "")), "total": len(rows)} for k in keys}


def validate_and_registry() -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    tfr_bytes, tfr = load_json(RAW / "tfrin_fishery_qa.json")
    drug_bytes, drug = load_json(RAW / "animal_drug_info.json")
    eel_bytes, eel = load_json(RAW / "eel_stocking_by_county.json")
    download_at = datetime.now(timezone.utc).isoformat()

    sources = [
        {"source_id": "MOA-TFRI-OPEN-114846", "dataset_id": "114846", "title": "水產試驗所漁業問答", "publisher": "農業部／水產試驗所", "official_dataset_url": "https://data.gov.tw/dataset/114846", "resource_url": URLS["tfrin"], "path": str(RAW / "tfrin_fishery_qa.json"), "sha256": sha_bytes(tfr_bytes), "file_size_bytes": len(tfr_bytes), "format": "JSON", "records": len(tfr), "field_completeness": field_completeness(tfr), "dataset_license_declared": "政府資料開放授權條款第1版", "license_evidence_url": URLS["license"], "attribution": "農業部／水產試驗所，水產試驗所漁業問答（資料集 114846，JSON 資源；快照 2026-10-20；SHA-256: " + sha_bytes(tfr_bytes) + "); 依政府資料開放授權條款第1版釋出；https://data.gov.tw/license", "attribution_required": True, "owner_decision": "Authorized by current user instruction for this exact official resource in a versioned, isolated research index; not a digital signature.", "processing_scope": "Exact downloaded JSON resource; local non-public search/indexing and factual verification, with attribution; no unrelated page/media or third-party material outside the resource.", "usage_status": "ADMITTED_LIMITED_RESEARCH_OGL_V1", "caveat": "OGL v1 dataset page declares this resource licensed; license retains third-party rights caveat. This is not a claim of human gold or formal Evaluation Corpus admission."},
        {"source_id": "MOA-ANIMAL-DRUG-OPEN-7274", "dataset_id": "7274", "title": "動物用藥資訊", "publisher": "農業部／動植物防疫檢疫署", "official_dataset_url": "https://data.gov.tw/dataset/7274", "resource_url": URLS["drug"], "path": str(RAW / "animal_drug_info.json"), "sha256": sha_bytes(drug_bytes), "file_size_bytes": len(drug_bytes), "format": "JSON", "records": len(drug), "field_completeness": field_completeness(drug), "dataset_license_declared": "政府資料開放授權條款第1版", "license_evidence_url": URLS["license"], "attribution": "農業部／動植物防疫檢疫署，動物用藥資訊（資料集 7274，JSON 快照 2026-10-20；SHA-256: " + sha_bytes(drug_bytes) + "); 依政府資料開放授權條款第1版釋出；https://data.gov.tw/license", "attribution_required": True, "owner_decision": "Authorized by current user instruction for this exact official resource in a versioned, isolated research index; not a digital signature.", "processing_scope": "Exact downloaded JSON resource; index factual permit fields only. Does not infer dose, aquaculture use, withdrawal period, treatment, or species applicability absent explicit source fields.", "usage_status": "ADMITTED_LIMITED_RESEARCH_OGL_V1", "caveat": "A permit record is not treatment advice; OGL v1 dataset page declares this resource licensed and preserves third-party rights caveat."},
        {"source_id": "MOA-EEL-STOCK-OPEN-41845", "dataset_id": "41845", "title": "縣市別養殖放養量彙整表（鰻魚）", "publisher": "農業部", "official_dataset_url": "https://data.gov.tw/dataset/41845", "resource_url": URLS["eel"], "path": str(RAW / "eel_stocking_by_county.json"), "sha256": sha_bytes(eel_bytes), "file_size_bytes": len(eel_bytes), "format": "JSON", "records": len(eel), "field_completeness": field_completeness(eel), "dataset_license_declared": "政府資料開放授權條款第1版", "license_evidence_url": URLS["license"], "attribution": "農業部，縣市別養殖放養量彙整表（鰻魚，資料集 41845，JSON 快照 2026-10-20；SHA-256: " + sha_bytes(eel_bytes) + "); 依政府資料開放授權條款第1版釋出；https://data.gov.tw/license", "attribution_required": True, "owner_decision": "Authorized by current user instruction for this exact official resource in a versioned, isolated research index; not a digital signature.", "processing_scope": "Exact downloaded JSON resource for bounded descriptive statistics only; no year is present in the downloaded record schema, so no year-specific assertion.", "usage_status": "ADMITTED_LIMITED_RESEARCH_OGL_V1_CONTEXT_ONLY", "caveat": "The file has no explicit year field. Record values must not be presented as belonging to an inferred year."},
    ]
    write_jsonl(OUT / "source_usage_basis_registry.jsonl", sources)

    tfr_records = []
    species_counts: Counter[str] = Counter()
    topic_counts: Counter[str] = Counter()
    species_topic_counts: Counter[tuple[str, str]] = Counter()
    for idx, row in enumerate(tfr, 1):
        title = field_text(row.get("title"))
        answer = field_text(row.get("description"))
        text = ("問題：" + title + "\n官方回答：" + answer).strip()
        labels = detect_scopes(text)
        topics = detect_topics(text)
        for label in labels:
            if label != "species_unknown":
                species_counts[label] += 1
                for topic in topics:
                    species_topic_counts[(label, topic)] += 1
        for topic in topics:
            topic_counts[topic] += 1
        raw_link = str(row.get("link") or "")
        record_basis = raw_link or (title + "\n" + str(row.get("pubdate") or "") + "\n" + answer)
        rid = "TFRI-114846-R" + f"{idx:06d}"
        tfr_records.append({"record_id": rid, "record_index": idx, "source_id": "MOA-TFRI-OPEN-114846", "source_sha256": sha_bytes(tfr_bytes), "source_version": "data.gov.tw metadata updated 2023-08-14; downloaded snapshot 2026-10-20", "source_record_url": raw_link or None, "exact_locator": f"JSON array record /{idx-1}; fields /title, /description, /pubdate, /link", "source_title": title, "answer_text": answer, "published_date": row.get("pubdate"), "source_species_label": labels, "species_scope": labels, "taxonomy_level": "literal_source_mentions_only; not expert taxonomy adjudication", "category_candidates": topics, "evidence_text": text, "exact_evidence_text": answer, "source_position": {"json_array_index_zero_based": idx-1, "field": "/description", "offset_start_in_extracted_field": 0, "offset_end_in_extracted_field": len(answer)}, "retrieval_eligibility": True, "verification_status": "OPEN_DATA_RECORD_BYTES_VERIFIED; factual relevance to any benchmark question requires exact record-level review", "annotation_status": "LITERAL_TOPIC_AND_SPECIES_SCAN_ONLY"})
    write_jsonl(OUT / "tfrin_qa_records_audit.jsonl", tfr_records)

    scan = {"source_id": "MOA-TFRI-OPEN-114846", "scan_method": "literal substring scan on cleaned title plus answer; overlapping labels/categories; not expert classification", "record_count": len(tfr), "distinct_question_texts": len(set(r["title"] for r in tfr)), "species_literal_mention_counts": dict(species_counts), "topic_literal_match_counts": dict(topic_counts), "species_topic_literal_match_counts": [{"species_source_label": s, "topic_candidate": t, "records": n} for (s,t),n in sorted(species_topic_counts.items())], "records_with_any_target_species_label": sum(1 for r in tfr_records if r["species_scope"] != ["species_unknown"]), "records_with_any_topic_candidate": sum(1 for r in tfr_records if r["category_candidates"] != ["fact"]), "limitations": ["Counts overlap where a record contains several labels.", "Literal terms do not establish expert accuracy or suitability to a benchmark answer.", "Source species label is preserved; 金目鱸 and 七星鱸 are not generalized to all 鱸魚."]}
    write_json(OUT / "tfrin_species_topic_coverage.json", scan)

    # Drug records become retrieval cards only when a target species is explicitly named in the indication.
    drug_rows = []
    drug_species_counter: Counter[str] = Counter()
    for idx, row in enumerate(drug, 1):
        indication = field_text(row.get("效能(適應症)"))
        product = field_text(row.get("動物用藥品中文名稱"))
        labels = detect_scopes(indication)
        exact = [x for x in labels if x != "species_unknown"]
        if not exact:
            continue
        # Keep exact permit metadata and indication; do not fabricate dosage/withdrawal guidance.
        text = "許可證字號：" + field_text(row.get("許可證字號")) + "\n藥品名稱：" + product + "\n效能（適應症）原始欄位：" + indication
        for label in exact:
            drug_species_counter[label] += 1
        drug_rows.append({"record_id": f"ANIMAL-DRUG-7274-R{idx:05d}", "record_index": idx, "source_id": "MOA-ANIMAL-DRUG-OPEN-7274", "source_sha256": sha_bytes(drug_bytes), "source_version": "data.gov.tw metadata updated 2026-03-13; downloaded snapshot 2026-10-20; dataset refresh frequency 7 days", "source_title": product, "published_date": row.get("核發日期"), "exact_locator": f"JSON array record /{idx-1}; fields /許可證字號, /動物用藥品中文名稱, /效能(適應症), /有效期間", "source_species_label": exact, "species_scope": exact, "category_candidates": ["medication_law"], "evidence_text": text, "exact_evidence_text": indication, "retrieval_eligibility": True, "permitted_claim_scope": "Only the recorded permit/product/indication and stated validity fields. No inferred dosage, species approval beyond explicit indication wording, treatment advice, or withdrawal period."})
    write_jsonl(OUT / "animal_drug_species_record_candidates.jsonl", drug_rows)

    eel_records = []
    for idx, row in enumerate(eel, 1):
        text = "；".join(f"{k}：{v}" for k,v in row.items())
        eel_records.append({"record_id": f"EEL-41845-R{idx:03d}", "record_index": idx, "source_id": "MOA-EEL-STOCK-OPEN-41845", "source_sha256": sha_bytes(eel_bytes), "source_version": "data.gov.tw metadata updated 2025-04-02; downloaded snapshot 2026-10-20", "source_species_label": "鰻魚（資料集標題分類）", "species_scope": ["鰻魚"], "exact_locator": f"JSON array record /{idx-1}; fields preserved by original names", "record": row, "evidence_text": text, "retrieval_eligibility": False, "context_only_reason": "No reference year/time-period field was present in this resource response; cannot support year-specific claims."})
    write_jsonl(OUT / "eel_statistics_context_only.jsonl", eel_records)

    # Validate the failed official ZIP transfer, preserving bytes as a failed artifact.
    zip_part = RAW / "moj_laws_orders.full.zip.part"
    zip_fail = RAW / "moj_laws_orders.incomplete_http_transfer.zip"
    zip_meta = {"official_url": URLS["law_zip"], "dataset_url": URLS["law_page"], "expected_content_length_bytes": 25218449, "received_bytes": zip_part.stat().st_size if zip_part.exists() else 0, "http_status_seen": 200, "content_type_seen": "application/octet-stream", "tls_verify_result": 0, "curl_exit_code": 18, "status": "FAILED_INCOMPLETE_TRANSFER", "failure_reason": "Official origin closed response before declared Content-Length; curl reported code 18 and 18,239,598 bytes missing on final attempt. Range resume had previously returned exit 33 because server did not support resume. Not a valid ZIP; not indexed."}
    if zip_part.exists() and not zip_fail.exists():
        zip_part.rename(zip_fail)

    overall = {"snapshot_time_utc": download_at, "sources": sources, "failed_resource": zip_meta, "records": {"tfrin_qa": len(tfr), "animal_drug": len(drug), "eel_stocking": len(eel)}, "tfrin_literal_coverage": scan, "animal_drug_explicit_target_species_records": len(drug_rows), "animal_drug_species_record_counts_overlapping": dict(drug_species_counter), "eel_records_context_only": len(eel_records), "admission_summary": {"owner_processing_authorized_resources": 3, "dataset_resources_with_OGL_v1_declared_and_integrity_verified": 3, "indexed_as_isolated_research_eligible_source_files": 2, "context_only_sources": 1, "blocked_sources": 1, "formal_corpus_v3_created": False, "production_changed": False}, "license_interpretation": "The official dataset pages declare OGL v1. Use is confined to those specific JSON resources, subject to attribution and third-party-rights/moral-right caveats in the license. The owner instruction authorizes scoped research processing but is not third-party permission or external legal opinion."}
    write_json(OUT / "official_download_manifest.json", overall)
    return tfr_records, drug_rows, eel_records, overall


def create_db(records: list[dict[str, Any]]) -> dict[str, Any]:
    if DB.exists():
        raise FileExistsError(f"Refusing to overwrite existing isolated index: {DB}")
    tags = requests.get(OLLAMA_TAGS, timeout=15).json().get("models", [])
    model = next((r for r in tags if r.get("name") == EMBED_MODEL), None)
    if not model or str(model.get("digest", "")).removeprefix("sha256:") != EMBED_DIGEST:
        raise RuntimeError("BGE-M3 model identity mismatch")
    DB.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB)
    con.execute("PRAGMA journal_mode=DELETE")
    con.execute("PRAGMA synchronous=FULL")
    con.execute("""CREATE TABLE cards(
      chunk_id TEXT PRIMARY KEY, source_id TEXT NOT NULL, source_sha256 TEXT NOT NULL, source_version TEXT NOT NULL,
      locator TEXT NOT NULL, text TEXT NOT NULL, content_sha256 TEXT NOT NULL, source_quote TEXT NOT NULL,
      species_scope TEXT NOT NULL, scientific_scope TEXT, taxonomy_level TEXT, category_scope TEXT NOT NULL,
      source_cluster_id TEXT NOT NULL, processing_scope TEXT NOT NULL, source_path TEXT NOT NULL, source_page INTEGER NOT NULL,
      quote_start INTEGER NOT NULL, quote_end INTEGER NOT NULL, retrieval_eligible INTEGER NOT NULL,
      human_gold INTEGER NOT NULL, formal_admission INTEGER NOT NULL, embedding BLOB NOT NULL)""")
    con.execute("CREATE VIRTUAL TABLE cards_fts USING fts5(chunk_id UNINDEXED, text, source_id UNINDEXED, species_scope UNINDEXED, category_scope UNINDEXED, tokenize='unicode61')")
    con.execute("""CREATE TABLE source_registry(source_id TEXT PRIMARY KEY, dataset_id TEXT, title TEXT, publisher TEXT, source_url TEXT,
      sha256 TEXT, license TEXT, attribution TEXT, usage_status TEXT, scope TEXT, metadata_json TEXT NOT NULL)""")
    con.execute("CREATE TABLE context_only_records(record_id TEXT PRIMARY KEY, source_id TEXT, locator TEXT, record_json TEXT, reason TEXT)")

    all_rows = []
    for row in records:
        text = row["chunk_text"]
        all_rows.append({"id": row["chunk_id"], "source_id": row["source_id"], "sha": row["source_sha256"], "ver": row["source_version"], "loc": row["exact_locator"], "text": text, "quote": row["exact_evidence_text"], "species": row["species_scope"], "tax": row.get("taxonomy_level", "literal_source_mentions_only"), "cats": row["category_candidates"], "scope": row.get("permitted_claim_scope", "OGL_V1 exact dataset resource; source record facts only"), "path": str(RAW / ("tfrin_fishery_qa.json" if row["source_id"] == "MOA-TFRI-OPEN-114846" else "animal_drug_info.json")), "qstart": row.get("source_position", {}).get("offset_start_in_extracted_field", 0), "qend": row.get("source_position", {}).get("offset_end_in_extracted_field", len(row["exact_evidence_text"])), "row": row})

    # Batch embeddings. Save checkpoints only in a separate jsonl to allow recovery.
    emb_checkpoint = OUT / "embedding_build_checkpoint_v2.jsonl"
    vectors: dict[str, np.ndarray] = {}
    if emb_checkpoint.exists():
        for line in emb_checkpoint.read_text(encoding="utf-8").splitlines():
            if line.strip():
                obj = json.loads(line)
                vec = np.asarray(obj["embedding"], dtype=np.float32)
                if len(vec) == 1024 and np.isfinite(vec).all():
                    vectors[obj["id"]] = vec / max(np.linalg.norm(vec), 1e-12)
    pending = [r for r in all_rows if r["id"] not in vectors]
    with emb_checkpoint.open("a", encoding="utf-8") as ck:
        for start in range(0, len(pending), 8):
            batch = pending[start:start+8]
            resp = requests.post(OLLAMA_EMBED, json={"model": EMBED_MODEL, "input": [r["text"] for r in batch], "truncate": True}, timeout=180)
            resp.raise_for_status()
            embs = resp.json().get("embeddings", [])
            if len(embs) != len(batch):
                raise RuntimeError(f"embedding count mismatch in batch: {len(embs)} != {len(batch)}")
            for row, raw_vec in zip(batch, embs, strict=True):
                vec = np.asarray(raw_vec, dtype=np.float32)
                if len(vec) != 1024 or not np.isfinite(vec).all():
                    raise RuntimeError(f"invalid embedding for {row['id']}")
                vec = vec / max(np.linalg.norm(vec), 1e-12)
                vectors[row["id"]] = vec
                ck.write(json.dumps({"id": row["id"], "embedding": vec.tolist()}, separators=(",", ":")) + "\n")
            ck.flush()
            print(f"embedded {min(start+8,len(pending))}/{len(pending)} pending; total {len(vectors)}/{len(all_rows)}", flush=True)

    source_map = {
        "MOA-TFRI-OPEN-114846": {"dataset_id":"114846","title":"水產試驗所漁業問答","publisher":"農業部／水產試驗所","source_url":URLS["tfrin"],"sha256":all_rows[0]["sha"],"license":"政府資料開放授權條款第1版 (dataset 114846 declares)","attribution":"農業部／水產試驗所；資料集114846；政府資料開放授權條款第1版","usage_status":"ADMITTED_LIMITED_RESEARCH_OGL_V1","scope":"Exact JSON open-data resource; non-public research indexing and factual verification with attribution"},
        "MOA-ANIMAL-DRUG-OPEN-7274": {"dataset_id":"7274","title":"動物用藥資訊","publisher":"農業部／動植物防疫檢疫署","source_url":URLS["drug"],"sha256":next((r["sha"] for r in all_rows if r["source_id"]=="MOA-ANIMAL-DRUG-OPEN-7274"), sha_file(RAW / "animal_drug_info.json")),"license":"政府資料開放授權條款第1版 (dataset 7274 declares)","attribution":"農業部／動植物防疫檢疫署；資料集7274；政府資料開放授權條款第1版","usage_status":"ADMITTED_LIMITED_RESEARCH_OGL_V1","scope":"Only exact species-explicit permit/indication fields; no dose, treatment or withdrawal inference"},
    }
    for sid, meta in source_map.items():
        con.execute("INSERT INTO source_registry VALUES(?,?,?,?,?,?,?,?,?,?,?)", (sid, meta["dataset_id"], meta["title"], meta["publisher"], meta["source_url"], meta["sha256"], meta["license"], meta["attribution"], meta["usage_status"], meta["scope"], json.dumps(meta,ensure_ascii=False)))
    for row in all_rows:
        vec = vectors[row["id"]].astype(np.float32).tobytes()
        cats = json.dumps(row["cats"], ensure_ascii=False)
        species = "|".join(row["species"])
        # In the runtime, each fish scope must match exactly. No unknown record is promoted to general.
        con.execute("INSERT INTO cards VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (row["id"],row["source_id"],row["sha"],row["ver"],row["loc"],row["text"],sha_bytes(row["text"].encode("utf-8")),row["quote"],species,"unknown",row["tax"],cats,"official-open-data-"+row["source_id"],row["scope"],row["path"],0,row["qstart"],row["qend"],1,0,0,vec))
        con.execute("INSERT INTO cards_fts(chunk_id,text,source_id,species_scope,category_scope) VALUES(?,?,?,?,?)", (row["id"],row["text"],row["source_id"],species,cats))
    con.commit()
    card_count = con.execute("SELECT COUNT(*) FROM cards").fetchone()[0]
    fts_count = con.execute("SELECT COUNT(*) FROM cards_fts").fetchone()[0]
    emb_count = con.execute("SELECT COUNT(*) FROM cards WHERE length(embedding)=4096").fetchone()[0]
    con.close()
    if card_count != len(all_rows) or fts_count != len(all_rows) or emb_count != len(all_rows):
        raise RuntimeError("index row/FTS/embedding count mismatch")
    return {"database_path": str(DB), "database_sha256": sha_file(DB), "cards": card_count, "fts_rows": fts_count, "valid_1024d_embeddings": emb_count, "embedding_model": EMBED_MODEL, "embedding_digest": EMBED_DIGEST, "normalized_l2": True, "context_only_eel_records": 9, "formal_evaluation_corpus": False, "index_scope": "isolated research index from two OGL v1 exact dataset resources; no historical source corpus copied"}


if __name__ == "__main__":
    tfr_records, drug_rows, eel_records, manifest = validate_and_registry()
    # Only explicit species labels enter search; long answers are split into exact, locatable spans.
    index_tfr = []
    for row in tfr_records:
        if row["species_scope"] == ["species_unknown"]:
            continue
        for ci, (a, b) in enumerate(split_text_spans(row["answer_text"]), 1):
            quote = row["answer_text"][a:b]
            index_tfr.append({**row, "chunk_id": f"{row['record_id']}-C{ci:03d}", "chunk_text": ("問題：" + row["source_title"] + "\n官方回答片段：" + quote).strip(), "exact_evidence_text": quote, "exact_locator": row["exact_locator"] + f"; /description chars [{a}:{b}]", "source_position": {**row["source_position"], "offset_start_in_extracted_field": a, "offset_end_in_extracted_field": b}})
    index_drug = []
    for row in drug_rows:
        indication = row["exact_evidence_text"]
        for ci, (a, b) in enumerate(split_text_spans(indication), 1):
            quote = indication[a:b]
            prefix = row["evidence_text"].split("\n效能（適應症）原始欄位：", 1)[0]
            index_drug.append({**row, "chunk_id": f"{row['record_id']}-C{ci:03d}", "chunk_text": prefix + "\n效能（適應症）片段：" + quote, "exact_evidence_text": quote, "exact_locator": row["exact_locator"] + f"; /效能(適應症) chars [{a}:{b}]", "source_position": {"offset_start_in_extracted_field": a, "offset_end_in_extracted_field": b}})
    index_records = index_tfr + index_drug
    print("index candidates", json.dumps({"tfrin_species_explicit_records":len({r['record_id'] for r in index_tfr}),"tfrin_chunks":len(index_tfr),"drug_species_explicit_records":len({r['record_id'] for r in index_drug}),"drug_chunks":len(index_drug),"total":len(index_records)},ensure_ascii=False), flush=True)
    index_report = create_db(index_records)
    write_json(OUT / "research_index_manifest.json", {"corpus_id":"official_open_data_research_index_v2","built_at_utc":datetime.now(timezone.utc).isoformat(),"sources":manifest["sources"][:2],"index":index_report,"index_rule":"Only TFRI Q&A records with literal target-species labels and animal-drug rows whose efficacy/indication explicitly names a target species are searchable. Long answer fields are segmented into exact contiguous spans with source offsets. Species-unknown Q&A remains audited but is not indexed. Eel data is context-only. Law ZIP failed integrity and is excluded.","caveats":["This isolated research index is not the frozen Evaluation Corpus v2 or formal Corpus v3.","Factual answer support still requires record-level validation; retrieval hit is not a verified answer.","Animal drug fields do not justify dose or withdrawal-period advice.","Species labels are literal source labels; no broad taxonomic inference was applied."]})
    print(json.dumps(index_report,ensure_ascii=False), flush=True)
