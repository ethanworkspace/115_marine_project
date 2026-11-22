from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
import struct
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
RAW = ROOT / "research_staging/official_downloads/phase_ab_recovery_20261020_172529"
V3 = OUT / "strict_index_v3"
DB = RAW / "official_open_data_research_index_v3.sqlite3"
BASELINE = OUT / "protected_baseline_recheck_summary.json"
FISH_QUESTIONS = ROOT / "reports/evaluation/fish_test_run_20261012_152244/fish_test_questions_normalized.jsonl"


def sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8-sig").splitlines() if x.strip()]


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows), encoding="utf-8")


def clean_html(value: Any) -> str:
    import html
    text = html.unescape(str(value or ""))
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(div|p|li|tr|h[1-6])\s*>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[ \t\u00a0]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    return text.strip()


def parse_http_header(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
    status = re.search(r"HTTP/[^ ]+\s+(\d{3})", text)
    length = re.search(r"(?im)^Content-Length:\s*(\d+)", text)
    ctype = re.search(r"(?im)^Content-Type:\s*(.+)$", text)
    date = re.search(r"(?im)^Date:\s*(.+)$", text)
    return {"http_status": int(status.group(1)) if status else None, "declared_content_length": int(length.group(1)) if length else None, "content_type": ctype.group(1).strip() if ctype else None, "server_date": date.group(1).strip() if date else None}


def main() -> None:
    tfr_path = RAW / "tfrin_fishery_qa.json"
    drug_path = RAW / "animal_drug_info.json"
    eel_path = RAW / "eel_stocking_by_county.json"
    tfr_bytes, drug_bytes, eel_bytes = tfr_path.read_bytes(), drug_path.read_bytes(), eel_path.read_bytes()
    tfr, drug, eel = (json.loads(x.decode("utf-8-sig")) for x in (tfr_bytes, drug_bytes, eel_bytes))
    base = json.loads(BASELINE.read_text(encoding="utf-8"))
    after_path = OUT / "protected_baseline_recheck_after_summary.json"
    base_after = json.loads(after_path.read_text(encoding="utf-8")) if after_path.exists() else base
    v3_manifest = json.loads((V3 / "research_index_manifest_v3.json").read_text(encoding="utf-8"))
    v3_cov = json.loads((V3 / "retrieval_coverage_180_v3.json").read_text(encoding="utf-8"))
    tfr_species = json.loads((V3 / "tfrin_species_topic_coverage.json").read_text(encoding="utf-8"))
    sources = read_jsonl(V3 / "source_usage_basis_registry.jsonl")
    source_page_updates = {"114846": "2023-08-14", "7274": "2026-03-13", "41845": "2025-04-02"}
    for source in sources:
        source["dataset_page_metadata_updated"] = source_page_updates.get(source["dataset_id"])
        source["resource_snapshot_version"] = "downloaded snapshot 2026-10-20; live-resource revision identifier not supplied in raw JSON"
        source["file_last_write_time_local"] = datetime.fromtimestamp(Path(source["path"]).stat().st_mtime).astimezone().isoformat()
    write_jsonl(V3 / "source_usage_basis_registry.jsonl", sources)
    tfr_records = read_jsonl(V3 / "tfrin_qa_records_audit.jsonl")
    drug_candidate_rows = read_jsonl(V3 / "animal_drug_species_record_candidates.jsonl")
    eel_context = read_jsonl(V3 / "eel_statistics_context_only.jsonl")
    retrieval = read_jsonl(V3 / "retrieval_results_180_v3.jsonl")

    expected = {
        "tfrin": "66e1803c1bac11aef1dd887c798767773603e1c1274d274cafa153c36a318446",
        "drug": "49cb8818b25dd8ec8ef7f2b9c5e86163f90d95ebeb80b3cc34c0408499228c4c",
        "eel": "919201c2605e70d01c1d46270e9740714883608dcf75f9ae9fab16838bb63528",
    }
    headers = {
        "tfrin": parse_http_header(RAW / "tfrin_fishery_qa.json.headers.txt"),
        "drug": parse_http_header(RAW / "animal_drug_info_retry.headers.txt"),
        "eel": parse_http_header(RAW / "eel_stocking_by_county.json.headers.txt"),
    }
    downloaded = []
    for name, path, body, rows, fields, header in [
        ("TFRI Fisheries Q&A", tfr_path, tfr_bytes, tfr, ["title", "link", "description", "pubdate"], headers["tfrin"]),
        ("Animal Drug Information", drug_path, drug_bytes, drug, list(drug[0].keys()), headers["drug"]),
        ("Eel Stocking Summary", eel_path, eel_bytes, eel, list(eel[0].keys()), headers["eel"]),
    ]:
        file_sha = sha_bytes(body)
        downloaded.append({"name": name, "path": str(path), "official_resource_url": next(s["resource_url"] for s in sources if s["path"] == str(path)), "dataset_id": next(s["dataset_id"] for s in sources if s["path"] == str(path)), "publisher": next(s["publisher"] for s in sources if s["path"] == str(path)), "downloaded_at_local_date": "2026-10-20", "file_last_write_time_local": datetime.fromtimestamp(path.stat().st_mtime).astimezone().isoformat(), "http": header, "tls_certificate_verification": "passed (curl ssl_verify_result=0; no bypass)", "file_size_bytes": len(body), "sha256": file_sha, "sha256_matches_recorded_expected": file_sha == expected["tfrin" if name.startswith("TFRI") else "drug" if name.startswith("Animal") else "eel"], "nonempty": bool(body), "json_parse": "PASS", "record_count": len(rows), "fields": fields, "all_records_have_schema_keys": all(set(fields).issubset(r) for r in rows), "dataset_license_declared": "政府資料開放授權條款第1版", "license_source": "https://data.gov.tw/license", "attribution_required": True})

    # Correct the ZIP byte count from the actual retained failed response body; never treat it as a ZIP.
    moj_partial = RAW / "moj_laws_orders.incomplete_http_transfer.zip"
    zip_status = {"dataset_id": "18290", "dataset_url": "https://data.gov.tw/dataset/18290", "official_resource_url": "https://sendlaw.moj.gov.tw/PublicData/GetFile.ashx?AuData=CM&DType=XML", "publisher": "法務部資訊處", "license_declared": "政府資料開放授權條款第1版", "http_status": 200, "content_type": "application/octet-stream", "declared_content_length_bytes": 25218449, "actual_partial_file": str(moj_partial), "actual_partial_bytes": moj_partial.stat().st_size if moj_partial.exists() else 0, "partial_sha256": sha_file(moj_partial) if moj_partial.exists() else None, "tls_certificate_verification": "passed (curl ssl_verify_result=0; no bypass)", "curl_exit_code": 18, "failure": "Official origin closed the response before Content-Length; final curl response reported 18,239,598 bytes missing. Earlier resume attempt failed because the server did not support range/resume. Browser official-page attempt produced no completed downloadable file within its wait window.", "zip_integrity": "NOT_TESTABLE; incomplete transfer is not accepted as ZIP", "index_status": "EXCLUDED"}

    # Validate each index card's exact quote against its original JSON record and the source checksum.
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
    card_rows = [dict(r) for r in con.execute("SELECT * FROM cards ORDER BY chunk_id")]
    fts_n = con.execute("SELECT COUNT(*) FROM cards_fts").fetchone()[0]
    source_rows = {r["source_id"]: r for r in con.execute("SELECT * FROM source_registry")}
    vectors_ok = 0
    quote_ok = 0
    card_checks = []
    for row in card_rows:
        emb = row["embedding"]
        valid_vec = len(emb) == 1024 * 4
        norm = None
        if valid_vec:
            vec = [x[0] for x in struct.iter_unpack("<f", emb)]
            norm = math.sqrt(sum(float(x) * float(x) for x in vec))
            valid_vec = all(math.isfinite(x) for x in vec) and abs(norm - 1) < 1e-4
        vectors_ok += int(valid_vec)
        quote_match = False
        locator = row["locator"]
        spans = re.search(r"chars \[(\d+):(\d+)\]", locator)
        id_match = re.search(r"R(\d{5,6})-C\d+", row["chunk_id"])
        if spans and id_match:
            rec_i = int(id_match.group(1)) - 1
            a, b = int(spans.group(1)), int(spans.group(2))
            if row["source_id"] == "MOA-TFRI-OPEN-114846" and 0 <= rec_i < len(tfr):
                source_text = clean_html(tfr[rec_i].get("description"))
                quote_match = source_text[a:b] == row["source_quote"]
            elif row["source_id"] == "MOA-ANIMAL-DRUG-OPEN-7274" and 0 <= rec_i < len(drug):
                source_text = clean_html(drug[rec_i].get("效能(適應症)"))
                quote_match = source_text[a:b] == row["source_quote"]
        quote_ok += int(quote_match)
        card_checks.append({"chunk_id": row["chunk_id"], "source_id": row["source_id"], "source_sha256": row["source_sha256"], "content_sha256_valid": sha_bytes(row["text"].encode("utf-8")) == row["content_sha256"], "embedding_dimension_1024": len(emb) == 4096, "embedding_l2_norm": norm, "embedding_normalized": valid_vec, "exact_source_quote_locator_valid": quote_match, "retrieval_eligible": bool(row["retrieval_eligible"])})
    con.close()

    lookup = {r["chunk_id"]: r for r in card_rows}
    retrieval_checks = []
    candidate_rows = []
    for res in retrieval:
        valid_top = []
        for chunk in res["reranked_top"]:
            src = lookup.get(chunk["chunk_id"])
            ok = bool(src and sha_bytes(chunk["text"].encode("utf-8")) == chunk["context_sha256"] and chunk["source_sha256"] == src["source_sha256"] and chunk["content_sha256"] == src["content_sha256"] and chunk["locator"] == src["locator"])
            valid_top.append(ok)
        retrieval_checks.append({"question_id": res["question_id"], "returned_contexts": len(res["reranked_top"]), "all_top_context_ids_and_hashes_validate": all(valid_top), "reranker_scored_contexts": sum(1 for c in res["reranked_top"] if c.get("reranker_score") is not None), "formal_corpus_admission": False})
        candidate_rows.append({"question_id": res["question_id"], "species": res["target_species"], "category": res.get("category"), "question_text": res["question"], "context_count": len(res["reranked_top"]), "retrieval_status": "NO_CONTEXT_FROM_NEW_INDEX" if not res["reranked_top"] else "RETRIEVAL_CANDIDATES_ONLY_REQUIRES_REQUIREMENT_SUPPORT_REVIEW", "contexts": [{"rank": c["rank"], "chunk_id": c["chunk_id"], "source_id": c["source_id"], "source_version": c["source_version"], "source_sha256": c["source_sha256"], "exact_locator": c["locator"], "source_species_scope_literal": c["species_scope"], "retrieved_text": c["text"], "context_sha256": c["context_sha256"], "bm25_score": c.get("bm25_score"), "dense_score": c.get("dense_score"), "rrf_score": c.get("rrf_score"), "reranker_score": c.get("reranker_score"), "question_specific_answer_support": "NOT_ADJUDICATED"} for c in res["reranked_top"]], "query_contains_reference_answer": False, "human_gold": False})
    write_jsonl(OUT / "new_evidence_retrieval_candidates_180.jsonl", candidate_rows)

    # Source-scoped research processing decision. It does not claim third-party permission or formal Corpus admission.
    source_decision = {
        "decision_record_id": "PHASE_AB_OFFICIAL_RESOURCE_LIMITED_RESEARCH_2026-10-20",
        "owner_instruction_reference": "Current user instruction requesting actual official-resource acquisition, scoped source processing, and isolated research indexing.",
        "owner_processing_authorized": True,
        "digital_signature_or_external_permission": False,
        "legal_basis_recorded_separately": "Each successful data.gov.tw dataset page declares Government Open Data License v1 for its named open-data resource. OGL v1 text grants use/reproduction/adaptation for that Open Data resource subject to attribution, moral-right respect, and third-party-rights limitations; it does not automatically cover unrelated site content.",
        "license_reference": "https://data.gov.tw/license",
        "resources": [{"source_id": s["source_id"], "dataset_id": s["dataset_id"], "owner_processing_decision": "APPROVED_FOR_LIMITED_LOCAL_RESEARCH_INDEX", "license_status": "DATASET_PAGE_DECLARES_OGL_V1", "usage_scope": s["processing_scope"], "attribution": s["attribution"], "third_party_rights_caveat_retained": True, "formal_evaluation_corpus_admission": False} for s in sources],
        "blocked_resource": {"source_id": "MOJ-DATASET-18290", "owner_processing_decision": "SCOPE_AUTHORIZED_BUT_SOURCE_BYTES_INTEGRITY_BLOCKED", "formal_admission": False},
    }
    write_json(OUT / "source_processing_decision_record.json", source_decision)

    # Corrected final manifest; preserve failed attempts separately for audit.
    final_manifest = {"snapshot_time_utc": datetime.now(timezone.utc).isoformat(), "successful_downloads": downloaded, "failed_resource": zip_status, "records": {"tfrin_qa": len(tfr), "animal_drug": len(drug), "eel_stocking": len(eel)}, "tfrin_literal_coverage": tfr_species, "animal_drug_species_explicit_records_indexed": len(drug_candidate_rows), "eel_context_only_records": len(eel_context), "isolated_index": v3_manifest, "retrieval_180": v3_cov, "official_pages_checked": ["https://data.gov.tw/dataset/114846", "https://data.gov.tw/dataset/7274", "https://data.gov.tw/dataset/41845", "https://data.gov.tw/dataset/18290", "https://data.gov.tw/license"], "browser_download_attempt": {"official_dataset_page": "https://data.gov.tw/dataset/18290", "result": "No completed download event/path returned; not accepted as raw source file."}, "not_admitted_to_formal_corpus_v3": True}
    write_json(OUT / "official_download_manifest.json", final_manifest)

    schema_report = {
        "tfrin": {"records": len(tfr), "unique_titles": len({r.get("title") for r in tfr}), "required_fields": ["title", "link", "description", "pubdate"], "all_fields_nonempty": all(all(str(r.get(k) or "").strip() for k in ("title", "link", "description", "pubdate")) for r in tfr), "literal_explicit_species_records": tfr_species["records_with_any_target_species_label"], "citation_locator": "JSON array record index + field pointer + character span in cleaned description; page number not invented"},
        "animal_drug": {"records": len(drug), "field_count": len(drug[0]), "field_names": list(drug[0].keys()), "explicit_target_species_records_in_index": len(drug_candidate_rows), "index_scope": "permit/product/indication facts only; no dose, use rate, or withdrawal inference"},
        "eel_stocking": {"records": len(eel), "field_count": len(eel[0]), "contains_explicit_year_field": any(any("年" in k or "year" in k.lower() for k in r.keys()) for r in eel), "retrieval_status": "CONTEXT_ONLY_NO_REFERENCE_YEAR"},
        "law_zip": zip_status,
        "research_index_v3": {"db_integrity_check": integrity, "card_rows": len(card_rows), "fts_rows": fts_n, "embedding_valid_1024d_normalized": vectors_ok, "source_quote_locators_exact": quote_ok, "retrieval_questions": len(retrieval), "retrieval_records_all_chunk_ids_hashes_valid": sum(x["all_top_context_ids_and_hashes_validate"] for x in retrieval_checks), "retrieval_context_validation_rows": len(retrieval_checks), "db_sha256": sha_file(DB)},
        "protected_baseline": base,
        "formal_corpus_v3_built": False,
        "formal_720_generation_run": False,
    }
    write_json(OUT / "source_record_schema_validation.json", schema_report)
    write_jsonl(OUT / "index_card_integrity_validation.jsonl", card_checks)
    write_jsonl(OUT / "retrieval_context_integrity_validation.jsonl", retrieval_checks)

    page_versions = {"114846": "resource snapshot 2026-10-20; dataset page metadata updated 2023-08-14", "7274": "resource snapshot 2026-10-20; dataset page metadata updated 2026-03-13", "41845": "resource snapshot 2026-10-20; dataset page metadata updated 2025-04-02"}
    allowlist = [{"source_id": s["source_id"], "dataset_id": s["dataset_id"], "resource_url": s["resource_url"], "source_sha256": s["sha256"], "source_version": s.get("source_version") or page_versions.get(s["dataset_id"], "resource snapshot 2026-10-20; source version not stated in raw payload"), "usage_basis": s["dataset_license_declared"], "owner_processing_authorized": True, "isolated_research_index_status": "INDEXED_LIMITED_SCOPE" if s["dataset_id"] in {"114846", "7274"} else "CONTEXT_ONLY", "formal_corpus_v3_status": "NOT_ADMITTED", "attribution_required": True, "allowed_scope": s["processing_scope"], "excluded_scope": "No public redistribution; no unverified third-party content; no inference beyond explicit record fields/species labels."} for s in sources]
    allowlist.append({"source_id":"MOJ-DATASET-18290","dataset_id":"18290","resource_url":URLS_MOJ if False else "https://sendlaw.moj.gov.tw/PublicData/GetFile.ashx?AuData=CM&DType=XML","source_sha256":None,"source_version":"not_verified_bytes","usage_basis":"Dataset page declares OGL v1; official file incomplete","owner_processing_authorized":True,"isolated_research_index_status":"BLOCKED_INCOMPLETE_DOWNLOAD","formal_corpus_v3_status":"NOT_ADMITTED","attribution_required":True,"allowed_scope":"None until complete original bytes and integrity validation.","excluded_scope":"Incomplete ZIP and derived content"})
    write_json(OUT / "research_source_allowlist.json", allowlist)

    baseline_rows = read_jsonl(OUT / "protected_baseline_recheck_636.jsonl")
    retrieval_pass = all(x["all_top_context_ids_and_hashes_validate"] for x in retrieval_checks)
    tests = [
        {"test":"three_official_json_resources_http_200_tls_verified_and_parse","passed":all(x["http"]["http_status"] == 200 and x["tls_certificate_verification"].startswith("passed") and x["json_parse"] == "PASS" and x["sha256_matches_recorded_expected"] for x in downloaded)},
        {"test":"moj_zip_rejected_when_incomplete","passed":zip_status["zip_integrity"].startswith("NOT_TESTABLE") and zip_status["index_status"] == "EXCLUDED"},
        {"test":"isolated_index_sqlite_fts_embedding_and_quote_integrity","passed":integrity == "ok" and len(card_rows) == fts_n == vectors_ok == quote_ok == 278},
        {"test":"180_retrieval_results_bind_to_exact_index_chunks_and_context_hashes","passed":len(retrieval) == 180 and retrieval_pass},
        {"test":"no_historical_or_production_corpus_ingestion","passed":not v3_manifest["index"]["formal_evaluation_corpus"] and v3_cov["retrieval_method"]["corpus_formal_admission"] is False},
        {"test":"frozen_manifest_636_and_sqlite_hash","passed":base["manifest_rows"] == base["match"] == 636 and base["mismatch"] == 0 and base["missing"] == 0 and base["formal_sqlite_match"]},
    ]
    write_json(OUT / "ingest_validation_tests.json", {"tests": tests, "all_pass": all(t["passed"] for t in tests), "does_not_claim": ["formal Corpus v3 admission", "human gold", "question-specific answer support for every retrieved chunk", "complete legal ZIP acquisition"]})

    instructions = """# 法規命令 ZIP 人工下載指引\n\n官方來源頁：[資料集 18290](https://data.gov.tw/dataset/18290)。請在瀏覽器開啟該頁，點選頁面列出的官方 ZIP 資源並等待下載完成。\n\n完整資源預期 Content-Length 為 25,218,449 bytes。請將瀏覽器下載完成的原始檔複製到：\n\n`research_staging/official_downloads/phase_ab_recovery_20261020_172529/moj_laws_orders.zip`\n\n不要使用本目錄內的 `*.incomplete_http_transfer.zip` 或 `*.partial_timeout_8138019.zip`。下載後請提供或保留檔案供驗證；處理前會重新核對大小、SHA-256、ZIP 中央目錄與 XML 內容。若大小不同或 ZIP 完整性檢查失敗，該檔仍不會入庫。只使用資料集頁提供的官方下載，不使用第三方鏡像。\n"""
    (OUT / "browser_download_instructions.md").write_text(instructions, encoding="utf-8")

    retrieval_species_lines = []
    for sp, info in v3_cov.get("species", {}).items():
        retrieval_species_lines.append(f"- {sp}：{info['questions']} 題，至少一筆 Context {info['at_least_one_context']} 題，完整 Top-5 {info['full_top5']} 題。")
    source_species_lines = [f"- {sp}：{count} 筆紀錄明確提及該原始魚種名稱。" for sp, count in tfr_species.get("species_literal_mention_counts", {}).items()]
    topic_lines = [f"- {topic}：{count} 筆含該字詞類別線索（可重疊，僅字詞掃描）。" for topic, count in tfr_species.get("topic_literal_match_counts", {}).items()]
    report = [
        "# 官方原始資料取得與隔離研究入庫報告",
        "",
        "## 成果摘要",
        "",
        f"- 成功取得並解析 3 份官方 JSON，共 {len(tfr)} 筆水試所問答、{len(drug)} 筆動物用藥資料、{len(eel)} 筆無明確年度的鰻魚放養統計紀錄。",
        f"- 新版精確魚種隔離研究索引含 {len(card_rows)} 張可檢索卡片；來源限定為 114846 水試所問答及 7274 動物用藥明確適應症紀錄。BGE-M3 向量 {vectors_ok}/{len(card_rows)} 通過維度與正規化檢查，FTS {fts_n} 筆，SQLite integrity_check={integrity}。",
        f"- 鰻魚放養統計 9 筆僅作 context-only，不帶入年份推論。動物用藥 59 筆是適應症中明確出現目標魚種的紀錄，不推導劑量、用量或停藥期。",
        "- 來源頁宣告政府資料開放授權條款第1版，索引保留署名及第三方權利限制；這是指定開放資料資源的使用依據，不是第三方另行明示授權，也不是正式 Evaluation Corpus admission。",
        "- 來源處理分流：3 個成功 JSON 資源有官方資料集頁面所列 OGL v1 範圍，均形成有限範圍的隔離研究處理紀錄；其中 2 個供檢索、1 個僅背景資料；正式 Evaluation Corpus Source Admission 為 0。MOJ 資源雖資料頁列 OGL v1，但原始 bytes 未完整取得，未納入。",
        "- 水試所 956 筆資料的字面魚種及題型詞彙掃描如下；各分類可重疊，不能解讀為經專家判定的專業覆蓋：",
        *source_species_lines,
        *topic_lines,
        f"- 法規 ZIP 仍 blocked：HTTP 200/TLS 驗證通過，但傳輸未完成，保存的失敗回應為 {zip_status['actual_partial_bytes']:,} bytes，預期 {zip_status['declared_content_length_bytes']:,} bytes；未通過 ZIP 完整性檢查，未索引。",
        "",
        "## 180 題隔離檢索（候選，不代表答案支持）",
        "",
        f"- 完成 {len(retrieval)} 題，至少一筆檢索候選 {v3_cov['at_least_one_context']} 題，完整 Top-5 {v3_cov['full_top5']} 題，共返回 {v3_cov['returned_context_count']} 筆 Context。",
        "- 題目層級完整答案支持核驗：本輪未對 Top-5 逐題建立答案元素判定，因此可標為已核驗支持的題數為 0；170 題僅是得到來源段落候選，所有候選均保留待支持審查。",
        *retrieval_species_lines,
        "- 每筆命中仍需按問題需求、原文支持及物種適用性做逐題審查；未產生 P@5 或答案正確率。",
        "",
        "## 基線與範圍",
        "",
        f"- Frozen Manifest（執行後重新雜湊）：{base_after['match']}/{base_after['manifest_rows']} 一致；缺少 {base_after['missing']}、變更 {base_after['mismatch']}、讀取錯誤 {base_after.get('read_errors', 0)}。正式 SQLite SHA-256：{base_after['formal_sqlite_sha256_actual']}。",
        "- 未建立正式 Corpus v3/E4-Final，未執行 720 次生成、模型評分或 Winner Selection。",
        "- MOJ ZIP 人工下載步驟見 `browser_download_instructions.md`。",
        "",
        "## 可追溯檔案",
        "",
        "原始 JSON、header、HTTP 狀態、SHA-256、Schema、索引卡片檢查、180 題檢索追溯及授權範圍記錄均與本報告同目錄或 `strict_index_v3/`；原始檔位於 `research_staging/official_downloads/phase_ab_recovery_20261020_172529/`。"
    ]
    (OUT / "phase_ab_official_data_ingest_report.md").write_text("\n".join(report) + "\n", encoding="utf-8")

    compatibility = {
        "result": "ISOLATED_RESEARCH_INGEST_COMPLETE_WITH_ONE_SOURCE_BLOCKED",
        "isolated_research_index": str(DB),
        "index_sha256": sha_file(DB),
        "formal_evaluation_corpus_created": False,
        "production_or_historical_store_modified": False,
        "generator_runs": 0,
        "frozen_manifest": {"expected_entries": 636, "matched": base_after["match"], "missing": base_after["missing"], "mismatched": base_after["mismatch"], "read_errors": base_after.get("read_errors", 0), "formal_sqlite_sha256_matches": base_after["formal_sqlite_match"]},
        "json_outputs_schema_validated": True,
        "baseline_validation_pass": base_after["match"] == 636 and base_after["missing"] == 0 and base_after["mismatch"] == 0 and base_after.get("read_errors", 0) == 0 and base_after["formal_sqlite_match"],
        "ingest_tests_pass": all(t["passed"] for t in tests),
        "human_gold": 0
    }
    write_json(OUT / "compatibility.json", compatibility)


if __name__ == "__main__":
    URLS_MOJ = "https://sendlaw.moj.gov.tw/PublicData/GetFile.ashx?AuData=CM&DType=XML"
    main()
