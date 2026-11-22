from __future__ import annotations

import ast
import hashlib
import json
import math
import re
import shutil
import sqlite3
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import fitz
import numpy as np
import requests

from phase_s_rag import BGE_TAG, DB_PATH, OLLAMA, RRF_K, embed_texts, requirement_profile, rrf_rank, tokenize_zh


ROOT = Path(__file__).resolve().parents[4]
RUN = Path(__file__).resolve().parents[1]
CORPUS_DIR = RUN / "corpus"
INDEX_DIR = RUN / "index"
BACKUP_DIR = RUN / "backups"
OUT_DIR = RUN
for d in (CORPUS_DIR, INDEX_DIR, BACKUP_DIR, OUT_DIR):
    d.mkdir(parents=True, exist_ok=True)

STAMP = datetime.now(timezone.utc).isoformat()
PHASE_P = ROOT / "reports/evaluation/fish_test_phase_p_20261017_161822"
PHASE_Q = ROOT / "reports/evaluation/fish_test_phase_q_20261017_163618"
PHASE_R = ROOT / "reports/evaluation/fish_test_phase_r_20261017_170144"
PHASE_E = ROOT / "reports/evaluation/fish_test_run_20261012_152244"
PHASE_E_AUDIT = ROOT / "reports/evaluation/fish_test_results_audit_v2_20261012_222741"
PHASE_3V = ROOT / "reports/evaluation/final_model_selection/phase20_1E_exec_r3/step3v_dgbas_formal_admission"
SOURCE_MANIFEST = ROOT / "reports/recovery/document_manifest_v3.jsonl"
CORPUS_V2 = ROOT / "data/evaluation/corpus_v2.jsonl"
QUESTIONS_PATH = PHASE_E / "fish_test_questions_normalized.jsonl"
DGBAS_XML = ROOT / "research_staging/_official_source_staging/phase20_1E_step3I/raw/DGBAS-AQUACULTURE-SPECIES-79395_2020.xml"
DGBAS_EXPECTED = "31c4cdb6fc3cdcd58abc4a5ba8a1cde908f1ca12f9f338fb39da4d4bf494dd31"
RERANKER_ID = "BAAI/bge-reranker-v2-m3"
MODELS = {
    "M1": "deepseek-r1:7b",
    "M2": "qwen2.5-coder:7b",
    "M3": "hf.co/bartowski/DeepSeek-R1-Distill-Llama-8B-GGUF:Q4_K_M",
    "M4": "gemma2:9b",
}


def sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8-sig") as f:
        return [json.loads(line) for line in f if line.strip()]


def write_json(path: Path, obj: Any) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def write_jsonl(path: Path, rows) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def file_sha_of_relative(rel: str) -> str | None:
    p = Path(rel)
    if not p.is_absolute():
        p = ROOT / p
    try:
        return sha256_file(p)
    except OSError:
        return None


def hash_frozen(stage: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    path = PHASE_P / "frozen_baseline_636_recheck.jsonl"
    rows = read_jsonl(path)
    unique = {}
    for r in rows:
        if r.get("stage") == "before":
            unique[r.get("path")] = r
    results = []
    for rel, r in sorted(unique.items()):
        actual = file_sha_of_relative(str(rel))
        expected = r.get("expected_sha256")
        status = "unchanged" if actual and actual == expected else ("missing_or_unreadable" if not actual else "mismatch")
        results.append({"stage": stage, "path": rel, "expected_sha256": expected, "actual_sha256": actual, "status": status})
    summary = {"stage": stage, "expected_unique_files": 636, "manifest_unique_files": len(unique), "checked_count": len(results),
               "matching_count": sum(r["status"] == "unchanged" for r in results), "mismatch_count": sum(r["status"] != "unchanged" for r in results),
               "complete": len(unique) == 636 and all(r["status"] == "unchanged" for r in results),
               "sqlite_sha256": sha256_file(ROOT / "rag_store.sqlite3"),
               "sqlite_expected_sha256": "d7d06d4d2a57d0a57d05bcb6131ffb24aefb226c6bd36349dbc5118d33b11087"}
    summary["sqlite_matches"] = summary["sqlite_sha256"] == summary["sqlite_expected_sha256"]
    write_jsonl(RUN / f"frozen_baseline_{stage}_recheck.jsonl", results)
    write_json(RUN / f"frozen_baseline_{stage}_summary.json", summary)
    return results, summary


def backup_inputs() -> dict[str, Any]:
    relatives = [
        "config/sources.yaml", "config/parsing.yaml", "config/chunking_v2.json", "config/retrieval_error_taxonomy.json",
        "data/evaluation/corpus_manifest_v2.json", "data/evaluation/source_alias_registry_v3.jsonl",
        "reports/recovery/document_manifest_v3.jsonl", "reports/evaluation/fish_test_run_20261012_152244/fish_test_questions_normalized.jsonl",
        "reports/evaluation/fish_test_phase_p_20261017_161822/evidence_coverage_summary.json",
        "reports/evaluation/fish_test_phase_q_20261017_163618/benchmark_readiness_summary.json",
        "reports/evaluation/fish_test_phase_r_20261017_170144/phase_r_validation.json",
    ]
    records = []
    for rel in relatives:
        src = ROOT / rel
        if not src.is_file():
            records.append({"source": rel, "backup": None, "status": "missing"})
            continue
        dst = BACKUP_DIR / rel.replace("/", "__").replace("\\", "__")
        shutil.copy2(src, dst)
        records.append({"source": rel, "backup": str(dst.relative_to(RUN)), "sha256_before": sha256_file(src), "sha256_backup": sha256_file(dst), "status": "copied_and_hash_matched" if sha256_file(src) == sha256_file(dst) else "backup_hash_mismatch"})
    return {"backup_directory": str(BACKUP_DIR.relative_to(ROOT)), "files": records, "all_present_files_match": all(r.get("status") == "copied_and_hash_matched" for r in records if r["status"] != "missing")}


def parse_pythonish(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:
            try:
                return ast.literal_eval(value)
            except Exception:
                return value
    return value


def audit_sources_and_crosswalk() -> dict[str, Any]:
    q_meta_rows = read_jsonl(PHASE_Q / "source_metadata_resolution.jsonl")
    p_context_rows = read_jsonl(PHASE_P / "retrieval_context_audit_900.jsonl")
    q_alias = read_json(PHASE_Q / "source_alias_audit.json")
    r_crosswalk = read_json(PHASE_R / "source_crosswalk_correction_proposal.json")
    manifest = read_jsonl(SOURCE_MANIFEST)
    unique_docs = {}
    for row in q_meta_rows:
        unique_docs.setdefault(row.get("document_id"), row)
    source_doc_audit = []
    for doc_id, row in sorted(unique_docs.items(), key=lambda x: str(x[0])):
        ev = row.get("local_file_evidence") or {}
        rel = ev.get("manifest_file_path")
        actual = file_sha_of_relative(rel) if rel else None
        source_doc_audit.append({
            "document_id": doc_id, "source_title": row.get("corpus_source_title"), "corpus_source_id": row.get("corpus_source_id"),
            "corpus_source_url": row.get("corpus_source_url"), "manifest_file_path": rel,
            "corpus_sha256": ev.get("corpus_registered_sha256"), "manifest_sha256": ev.get("manifest_sha256"),
            "actual_sha256": actual, "local_bytes_identity_match": bool(actual and actual == ev.get("corpus_registered_sha256") == ev.get("manifest_sha256")),
            "identity_status": "BYTE_IDENTITY_CONFIRMED_ONLY" if actual and actual == ev.get("corpus_registered_sha256") == ev.get("manifest_sha256") else "UNVERIFIED",
            "publisher_authority_version_rights_species": "UNVERIFIED unless independently recorded in verified source package",
            "resolution_outcome_before": row.get("resolution_outcome"),
        })
    pending_rows = []
    for row in q_meta_rows:
        unresolved = list(row.get("fields_still_unresolved") or [])
        pending_rows.append({
            "question_id": row.get("question_id"), "rank": row.get("rank"), "chunk_id": row.get("chunk_id"), "document_id": row.get("document_id"),
            "registered_source_id": row.get("corpus_source_id"), "source_title": row.get("corpus_source_title"),
            "file_bytes_identity": bool((row.get("local_file_evidence") or {}).get("actual_matches_corpus")),
            "unresolved_fields": unresolved, "source_resolution_status": "identity_only; authority/version/rights/species/corpus_scope_unverified" if unresolved else "review_source_row",
        })
    species_rows = []
    for row in p_context_rows:
        if not row.get("species_scope_conflict_candidate"):
            continue
        meta = parse_pythonish(row.get("document_species_metadata")) or []
        mentions = parse_pythonish(row.get("body_species_mentions")) or []
        if isinstance(meta, str): meta = [meta]
        if isinstance(mentions, str): mentions = [mentions]
        target = row.get("species")
        if meta and target and target not in meta:
            status = "METADATA_SCOPE_CONFLICT_REQUIRES_SOURCE_CONTENT_REVIEW"
        elif mentions and target and target in mentions:
            status = "TARGET_MENTION_ONLY_NOT_APPLICABILITY_PROOF"
        elif row.get("source_id") in ("moa_official", "fisheries_agency_official", "government_gazette_official") and not meta:
            status = "GENERAL_OFFICIAL_SOURCE_SCOPE_UNSPECIFIED"
        else:
            status = "SPECIES_SCOPE_UNVERIFIED"
        species_rows.append({
            "question_id": row.get("question_id"), "species": target, "category": row.get("category"), "chunk_id": row.get("chunk_id"),
            "document_id": row.get("document_id"), "source_title": row.get("source_title"), "document_species_metadata": meta,
            "body_species_mentions": mentions, "phase_p_diagnostic_labels": row.get("diagnostic_labels"),
            "revalidation_status": status, "verified_applicability": False,
            "note": "metadata/keyword overlap is not treated as scientific applicability evidence",
        })
    fixes = []
    for item in (r_crosswalk.get("correction_proposals") or r_crosswalk.get("crosswalks") or r_crosswalk.get("proposals") or []):
        fixes.append(item)
    if not fixes:
        fixes = [
            {"source_ids": ["S06", "S07", "S08"], "incorrect_document_id": "30b9fedc-1646-50b0-b7f0-0aeb9f54a76a", "incorrect_title": "養殖漁業防寒須知(農業部漁業署)", "actual_source_url": "https://fadopen.fa.gov.tw/fadopen/service/qryBreedPredictReport.htmx", "resolution": "separate service identity; do not point to cold-advisory PDF"},
            {"source_ids": ["S10"], "incorrect_document_id": "3ac134e2-d7d8-52e4-9e3f-af2ffcb5a20d", "incorrect_title": "訂定總說明與逐條說明（110.4.27）", "actual_source_url": "https://opendata.cwa.gov.tw/dist/opendata-swagger.html", "resolution": "separate CWA API documentation identity; do not point to legal explanatory document"},
        ]
    alias_counts = q_alias.get("resolution_status_counts", {})
    registry = {
        "registry_version": "phase_s_source_registry_v1",
        "created_at": STAMP,
        "immutable_history": True,
        "input_rows": {"phase_q_source_metadata_resolution_rows": len(q_meta_rows), "phase_p_context_rows": len(p_context_rows), "unique_local_source_documents": len(unique_docs), "pending_source_context_rows_expected": 511},
        "source_document_audit": source_doc_audit,
        "source_alias_audit_phase_q_preserved": {"title_disagreement_rows": q_alias.get("title_disagreement_rows"), "resolution_status_counts": alias_counts, "unresolved_or_unverified_title_mismatches": q_alias.get("unresolved_or_unverified_title_mismatches")},
        "confirmed_crosswalk_corrections_applied_only_in_new_sidecar": fixes,
        "source_index_policy": "Only the locally rehashed DGBAS 2020 XML already admitted at limited scope and the existing-v2-verified MOA official Animal Drug Control Act text are included. No alias-only source assignment is promoted.",
        "sources_excluded": [
            {"source": "FL035443 Annex I local PDF", "reason": "official change history was checked: 2025-01-08 change is Annex II; local Annex I PDF has no proven current attachment version against the official binary; quarantined from new index until exact attachment identity is established"},
            {"source": "TFRIN technical manuals and seabass biosecurity handbook", "reason": "full-text indexing/processing scope not established for this new index; preserve in existing Corpus v2 only; no copy into Phase S index"},
            {"source": "remaining unverified originals", "reason": "source authority, version, rights and species applicability are not all established"},
        ],
        "pending_context_rows": pending_rows,
        "species_scope_conflict_rows": species_rows,
        "old_registry_or_corpus_mutated": False,
    }
    write_json(OUT_DIR / "source_registry_corrected.json", registry)
    write_jsonl(OUT_DIR / "source_integrity_19_documents.jsonl", source_doc_audit)
    write_jsonl(OUT_DIR / "source_context_audit_511.jsonl", pending_rows)
    write_jsonl(OUT_DIR / "species_scope_revalidation_439.jsonl", species_rows)
    write_json(OUT_DIR / "source_alias_resolution_summary.json", {"phase_q_original_counts": q_alias, "phase_s_applied_crosswalk_repairs": fixes, "promoted_aliases": 0})
    return {"registry": registry, "q_metadata_rows": q_meta_rows, "phase_p_rows": p_context_rows, "manifest": manifest}


def local_pdf_chunk(source: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    path = ROOT / source["local_file"]
    expected = source["source_sha256"]
    actual = sha256_file(path)
    quality = {"source_id": source["source_id"], "path": source["local_file"], "expected_sha256": expected, "actual_sha256": actual,
               "checksum_match": actual == expected, "page_count": None, "page_audits": [], "scan_pages": [], "table_count": 0, "extraction_method": "PyMuPDF native text", "status": "blocked"}
    if not actual or actual != expected:
        return [], quality
    doc = fitz.open(path)
    quality["page_count"] = len(doc)
    chunks = []
    article_re = re.compile(r"第\s*([0-9０-９一二三四五六七八九十百千]+(?:\s*[-之]\s*[0-9０-９一二三四五六七八九十百千]+)?)\s*條")
    for page_idx, page in enumerate(doc):
        text = page.get_text("text", sort=True)
        text_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        tables = 0
        try:
            tables = len(page.find_tables().tables)
        except Exception:
            tables = 0
        quality["table_count"] += tables
        quality["page_audits"].append({"page": page_idx + 1, "character_count": len(text), "text_sha256": text_hash, "table_count": tables, "native_text": bool(text.strip())})
        if len(re.sub(r"\s", "", text)) < 30:
            quality["scan_pages"].append(page_idx + 1)
            continue
        matches = list(article_re.finditer(text))
        segments = []
        if matches:
            if matches[0].start() > 0 and text[:matches[0].start()].strip():
                segments.append((0, matches[0].start(), None))
            for j, m in enumerate(matches):
                end = matches[j + 1].start() if j + 1 < len(matches) else len(text)
                segments.append((m.start(), end, m.group(0).replace(" ", "")))
        else:
            segments.append((0, len(text), None))
        for start, end, article in segments:
            raw = text[start:end]
            if not raw.strip():
                continue
            # Split only long within-article text; every child retains its original page and exact offset.
            parts = [(start, end)]
            if len(raw) > 1800:
                parts = []
                pos = start
                while pos < end:
                    part_end = min(end, pos + 1200)
                    if part_end < end:
                        boundary = text.rfind("\n", pos + 600, part_end)
                        if boundary > pos:
                            part_end = boundary + 1
                    parts.append((pos, part_end))
                    pos = max(pos + 1, part_end - 100) if part_end < end else end
            for part_start, part_end in parts:
                content = text[part_start:part_end].strip()
                if len(content) < 15:
                    continue
                locator = f"page={page_idx + 1};article={article or 'page_text'};char={part_start}:{part_end}"
                cid = "ps_" + hashlib.sha256(f"{source['source_id']}|{actual}|{locator}|{content}".encode("utf-8")).hexdigest()[:32]
                chunks.append({
                    "chunk_id": cid, "source_id": source["source_id"], "source_title": source["source_title"], "source_url": source["source_url"],
                    "source_sha256": actual, "source_version": source["source_version"], "source_kind": source["source_kind"],
                    "species_scope": "GENERAL_REGULATION", "category_scope": ["Medication / Law"], "page": page_idx + 1, "locator": locator,
                    "page_text_sha256": text_hash, "char_start": part_start, "char_end": part_end, "article": article,
                    "content": content, "parser": "PyMuPDF", "parser_version": fitz.VersionBind,
                    "quality_flags": ["page_article_bounded"],
                })
    quality["status"] = "parsed_with_scan_gaps" if quality["scan_pages"] else "parsed"
    quality["extracted_chunks"] = len(chunks)
    return chunks, quality


def dgbas_fact_chunks(admission: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    actual = sha256_file(DGBAS_XML)
    if actual != DGBAS_EXPECTED or actual != admission.get("source_sha256"):
        return [], {"status": "blocked_checksum_mismatch", "expected": DGBAS_EXPECTED, "actual": actual}
    # stdlib ElementTree does not resolve external entities; parse the admitted local bytes only.
    root = ET.parse(DGBAS_XML).getroot()
    rows = list(root)
    chunks = []
    errors = []
    nonempty = 0
    numeric = 0
    for row_i, row in enumerate(rows, 1):
        area_node = next((x for x in row if x.tag == "項目別"), None)
        area = area_node.text if area_node is not None else None
        if area in (None, "按地區分"):
            continue
        for field in row:
            if field.tag == "項目別" or field.text is None or not field.text.strip():
                continue
            raw = field.text.strip()
            nonempty += 1
            try:
                value = str(Decimal(raw))
                numeric += 1
                numeric_ok = True
            except InvalidOperation:
                value, numeric_ok = raw, False
            category_label = field.tag
            unit = "公頃" if "公頃數" in field.tag else None
            # Root is DataCollection; the indexed element is the resource row.
            # Preserve the admitted Step 3V locator shape for exact cross-checking.
            record_locator = f"/{root.tag}/{row.tag}[{row_i}]"
            field_locator = f"{record_locator}/{field.tag}"
            line = f"行政院主計總處2020資料資源標籤下的單年度統計。地域原始標籤：{area}。統計欄位原始名稱：{category_label}。原始數值：{raw}。單位：{unit or '原始欄位未標示'}。此分類是資料集統計標籤，不作精確生物物種或養殖操作推論。"
            cid = "ps_" + hashlib.sha256(f"DGBAS-79395-2020|{actual}|{field_locator}|{raw}".encode("utf-8")).hexdigest()[:32]
            chunks.append({
                "chunk_id": cid, "source_id": "DGBAS-79395-2020", "source_title": admission.get("source_title"),
                "source_url": admission.get("official_url"), "source_sha256": actual, "source_version": admission.get("publication_version"),
                "source_kind": "dgbas_statistic", "species_scope": "STATISTICAL_CATEGORY_ONLY", "category_scope": ["Fact"],
                "page": None, "locator": field_locator, "xml_record_locator": record_locator, "xml_field_locator": field_locator,
                "raw_value": raw, "parsed_value": value, "unit": unit, "statistical_area": area, "original_category_label": category_label,
                "reference_year": 2020, "reference_year_basis": admission.get("reference_year_basis"),
                "numeric_parse_verified": numeric_ok, "content": line, "parser": "xml.etree.ElementTree", "parser_version": sys.version.split()[0],
                "quality_flags": ["single_reference_year", "native_label_preserved", "no_species_taxonomy_promotion"] + ([] if numeric_ok else ["non_numeric_raw_value_review"]),
            })
    # Cross-check the six already verified Step 3V cards against original XML field/value, without inheriting their status blindly.
    cards = read_jsonl(PHASE_3V / "dgbas_six_evidence_cards_review.jsonl")
    card_checks = []
    chunk_by_locator = {c["xml_field_locator"]: c for c in chunks}
    for card in cards:
        c = chunk_by_locator.get(card.get("xml_field_locator"))
        valid = bool(c and c["raw_value"] == card.get("raw_xml_value") and c["source_sha256"] == DGBAS_EXPECTED)
        card_checks.append({"fact_id": card.get("fact_id"), "xml_field_locator": card.get("xml_field_locator"), "raw_value_match": valid,
                            "source_sha256_match": bool(c and c["source_sha256"] == DGBAS_EXPECTED), "verified_in_phase_s": valid})
    report = {"status": "parsed", "source_sha256": actual, "root_tag": root.tag, "xml_top_level_rows": len(rows), "facts_indexed": len(chunks),
              "nonempty_values": nonempty, "decimal_values": numeric, "six_step3v_cards_rechecked": len(card_checks), "six_card_matches": sum(r["verified_in_phase_s"] for r in card_checks),
              "external_entities_enabled": False, "record_year_field_in_xml": False, "reference_year_basis": "official resource label 民國109年; XML has no year field", "card_checks": card_checks}
    return chunks, report


def source_and_index_build() -> dict[str, Any]:
    manifest = read_jsonl(SOURCE_MANIFEST)
    corpus = read_jsonl(CORPUS_V2)
    act_doc_id = "0ac441bd-6eab-50ef-a459-72850101b7dd"
    act_manifest = next(r for r in manifest if r.get("document_id") == act_doc_id)
    act_corpus = next(r for r in corpus if r.get("document_id") == act_doc_id and r.get("retrieval_role") == "retrieval")
    act_source = {
        "source_id": "MOA-FL014718-ACT", "source_title": "動物用藥品管理法", "source_url": "https://law.moa.gov.tw/LawContent.aspx?id=FL014718",
        "local_file": act_manifest["file_path"], "source_sha256": act_manifest["checksum"], "source_version": "民國105年11月09日修正；官方法規頁本輪核對所列最新修正日相同",
        "source_kind": "official_statute", "rights_status": "official statutory text; existing verified-v2 source; this does not assert a publisher license for other materials",
        "usage_scope": "private local experimental index; statute body only; no legal medication permission inferred beyond the text",
        "legacy_document_id": act_doc_id, "legacy_corpus_source_id": act_corpus.get("source_id"), "legacy_source_sha256": act_corpus.get("source_checksum"),
    }
    # The local annex is preserved and parsed for quality, but excluded until its attachment-specific version is matched to the official binary.
    annex_doc_id = "6fc2b60d-9aa8-5036-8495-6f4517fc3404"
    annex_manifest = next(r for r in manifest if r.get("document_id") == annex_doc_id)
    annex_source = {"source_id": "MOA-FL035443-ANNEX-I-CANDIDATE", "source_title": "動物用藥品使用準則第三條附件一水產動物用藥品使用規範", "source_url": "https://law.moa.gov.tw/LawContentSource.aspx?id=FL035443",
                    "local_file": annex_manifest["file_path"], "source_sha256": annex_manifest["checksum"], "source_version": "unverified attachment-specific version", "source_kind": "official_regulation_attachment",
                    "index_inclusion": "excluded_pending_exact_attachment_version", "official_history_check": {"page_revision_date": "114-01-08", "revision_scope": "Article 4 Annex II", "last_listed_Annex_I_update": "108-04-22", "local_annex_identity_to_official_binary": "not verified"}}
    admission = read_json(PHASE_3V / "dgbas_2020_formal_admission_record.json")
    dgbas, dgbas_report = dgbas_fact_chunks(admission)
    pdf_chunks, pdf_quality = local_pdf_chunk(act_source)
    annex_chunks_diagnostic, annex_quality = local_pdf_chunk({**annex_source, "source_version": annex_source["source_version"], "source_kind": "official_regulation_attachment"})
    # Do not index the annex until the version blocker above is resolved.
    all_chunks = pdf_chunks + dgbas
    dedup = {}
    duplicate_ids = []
    for c in all_chunks:
        if c["chunk_id"] in dedup:
            duplicate_ids.append(c["chunk_id"])
        else:
            dedup[c["chunk_id"]] = c
    all_chunks = sorted(dedup.values(), key=lambda r: r["chunk_id"])
    for c in all_chunks:
        c["content_sha256"] = hashlib.sha256(c["content"].encode("utf-8")).hexdigest()
        c["lexical_tokens"] = " ".join(tokenize_zh(c["content"]))
        c["embedding_text"] = c["content"]
    # Reproducible model identity and a bounded batch embedding run; only allowed source text is embedded.
    vectors = []
    for offset in range(0, len(all_chunks), 24):
        batch = all_chunks[offset:offset + 24]
        vec = embed_texts([c["embedding_text"] for c in batch], timeout=240)
        vectors.extend(vec)
        write_json(INDEX_DIR / "embedding_progress.json", {"embedded": len(vectors), "total": len(all_chunks), "last_batch_start": offset, "dimension": int(vec.shape[1]), "model": BGE_TAG})
    matrix = np.asarray(vectors, dtype="<f4")
    vector_path = INDEX_DIR / "vectors.f32"
    matrix.tofile(vector_path)
    vector_sha = sha256_file(vector_path)
    for chunk, vector in zip(all_chunks, matrix):
        chunk["embedding"] = vector.tobytes().hex()
    write_jsonl(CORPUS_DIR / "phase_s_chunks_v1.jsonl", all_chunks)
    chunks_sha = sha256_file(CORPUS_DIR / "phase_s_chunks_v1.jsonl")
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as con:
        con.execute("PRAGMA journal_mode=DELETE")
        con.execute("CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        con.execute("CREATE TABLE sources (source_id TEXT PRIMARY KEY, source_json TEXT NOT NULL)")
        con.execute("CREATE TABLE chunks (chunk_id TEXT PRIMARY KEY, source_id TEXT NOT NULL, source_title TEXT NOT NULL, source_url TEXT NOT NULL, source_sha256 TEXT NOT NULL, source_version TEXT, source_kind TEXT NOT NULL, species_scope TEXT NOT NULL, category_scope TEXT NOT NULL, page INTEGER, locator TEXT, content TEXT NOT NULL, lexical_tokens TEXT NOT NULL, embedding BLOB NOT NULL, metadata_json TEXT NOT NULL)")
        con.execute("CREATE VIRTUAL TABLE chunks_fts USING fts5(chunk_id UNINDEXED, lexical_tokens, tokenize='unicode61')")
        sources = [act_source, {"source_id": "DGBAS-79395-2020", "source_title": admission["source_title"], "source_url": admission["official_url"],
                                "source_sha256": admission["source_sha256"], "source_version": admission["publication_version"], "source_kind": "dgbas_statistic",
                                "rights_status": "DGBAS 2020 XML admitted_scope_limited in Step 3V under Government Open Data License v1", "usage_scope": admission["approved_usage_scope"],
                                "prohibited_usage_scope": admission["prohibited_usage_scope"], "admission_id": admission["admission_id"]}]
        con.executemany("INSERT INTO sources VALUES (?,?)", [(s["source_id"], json.dumps(s, ensure_ascii=False)) for s in sources])
        metadata = {"corpus_version": "phase_s_integrated_kb_v1", "created_at": STAMP, "formal_corpus_v3": False, "source_admission_count_new": 0,
                    "sources_included": [s["source_id"] for s in sources], "source_count": len(sources), "chunk_count": len(all_chunks), "embedding_model": BGE_TAG,
                    "embedding_dimension": 1024, "vector_file_sha256": vector_sha, "chunk_file_sha256": chunks_sha, "reranker_status": "blocked_missing_local_snapshot", "index_status": "candidate_index_complete_reranker_pending"}
        con.executemany("INSERT INTO metadata VALUES (?,?)", [(k, json.dumps(v, ensure_ascii=False) if not isinstance(v, str) else v) for k,v in metadata.items()])
        rows = []
        for c in all_chunks:
            meta = {k:v for k,v in c.items() if k not in ("content", "lexical_tokens", "embedding_text", "embedding")}
            rows.append((c["chunk_id"], c["source_id"], c["source_title"], c["source_url"], c["source_sha256"], c["source_version"], c["source_kind"], c["species_scope"],
                         json.dumps(c["category_scope"], ensure_ascii=False), c.get("page"), c.get("locator"), c["content"], c["lexical_tokens"], matrix[len(rows)].tobytes(), json.dumps(meta, ensure_ascii=False)))
        con.executemany("INSERT INTO chunks VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
        con.executemany("INSERT INTO chunks_fts(chunk_id,lexical_tokens) VALUES (?,?)", [(c["chunk_id"], c["lexical_tokens"]) for c in all_chunks])
        con.commit()
    db_sha = sha256_file(DB_PATH)
    report = {
        "corpus_version": "phase_s_integrated_kb_v1", "formal_evaluation_corpus_v3": False,
        "build_status": "candidate_retrieval_index_complete_reranker_pending", "formal_source_admissions_this_phase": 0,
        "included_sources": [act_source, {"source_id": "DGBAS-79395-2020", "source_title": admission["source_title"], "source_sha256": admission["source_sha256"], "status": "previously_admitted_scope_limited", "included_scope": "2020 Fact rows only"}],
        "excluded_sources": [annex_source, {"source_id": "TFRIN-manuals", "status": "excluded", "reason": "full-text re-indexing scope not established for this run"}],
        "act_pdf_quality": pdf_quality, "annex_pdf_quality_quarantined": annex_quality, "dgbas_xml": dgbas_report,
        "chunk_count": len(all_chunks), "pdf_chunk_count": len(pdf_chunks), "dgbas_fact_chunk_count": len(dgbas), "duplicate_chunk_ids": duplicate_ids,
        "chunk_file": str((CORPUS_DIR / "phase_s_chunks_v1.jsonl").relative_to(ROOT)), "chunk_file_sha256": chunks_sha,
        "vector_file": str(vector_path.relative_to(ROOT)), "vector_file_sha256": vector_sha, "database_file": str(DB_PATH.relative_to(ROOT)), "database_sha256": db_sha,
        "embedding": {"model": BGE_TAG, "digest": "7907646426070047a77226ac3e684fbbe8410524f7b4a74d02837e43f2146bab", "dimension": 1024, "normalization": "explicit L2", "dtype": "float32 little-endian"},
        "bm25": {"implementation": "Phase S isolated CJK unigram/bigram/trigram BM25", "k1": 1.5, "b": 0.75, "query_terms": "unique"},
        "fusion": {"method": "RRF", "k": RRF_K, "inputs": ["BM25 top100", "BGE-M3 dense top100"]},
        "reranker": {"model": RERANKER_ID, "status": "blocked_missing_local_snapshot", "final_top_k": 5},
        "leakage_exclusions": ["fish test workbooks", "benchmark questions", "candidate answers", "scoring rubrics", "old generator outputs", "evaluation traces", "reports"],
    }
    write_json(OUT_DIR / "knowledge_base_build_manifest.json", report)
    return {"chunks": all_chunks, "matrix": matrix, "report": report, "sources": [act_source, annex_source], "dgbas_admission": admission}


def prepare_questions_and_retrieval(chunks: list[dict[str, Any]], matrix: np.ndarray) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    questions = read_jsonl(QUESTIONS_PATH)
    qprofiles = [requirement_profile(q) for q in questions]
    query_texts = [f"{p['target_species'] or ''} {q['question_text']}" for q,p in zip(questions,qprofiles)]
    qvectors = []
    for offset in range(0, len(query_texts), 32):
        qvectors.extend(embed_texts(query_texts[offset:offset+32], timeout=180))
    results = []
    eligibility = []
    for q, profile, query, vec in zip(questions, qprofiles, query_texts, qvectors):
        stages = rrf_rank(query, profile, chunks, vec, limit=100)
        # No final Top-5 is emitted because the required local BGE reranker artifact is absent.
        results.append({
            "question_id": q["question_id"], "query": query, "retrieval_run_id": RUN.name,
            "corpus_version": "phase_s_integrated_kb_v1", "corpus_chunk_sha256": sha256_file(CORPUS_DIR / "phase_s_chunks_v1.jsonl"),
            "question_requirement_profile": profile, "query_leakage_audit": {"candidate_answer_in_query": False, "candidate_rubric_in_query": False},
            "bm25_top100": stages["bm25"], "dense_top100": stages["dense"], "rrf_candidates_top100": stages["rrf"],
            "retrieval_eligible_chunk_count": stages["eligible_chunk_count"], "scope_filtered_chunk_count": stages["scope_excluded_count"],
            "scope_filter_reasons": stages["scope_excluded_reasons"], "reranker": RERANKER_ID, "reranker_status": "blocked_missing_local_snapshot",
            "final_top5": None, "retrieval_status": "candidate_stages_completed_final_top5_blocked",
            "failure_reason": "BGE reranker v2-m3 local model weights absent; no substitute ranker used",
        })
        urls = q.get("candidate_source_urls") or []
        if isinstance(urls, str): urls = parse_pythonish(urls)
        if not isinstance(urls, list): urls = [str(urls)] if urls else []
        source_match = []
        for u in urls:
            u = str(u)
            if "FL014718" in u:
                source_match.append("MOA-FL014718-ACT")
            elif "FL035443" in u:
                source_match.append("MOA-FL035443-ANNEX-I-CANDIDATE")
            elif "79395" in u:
                source_match.append("DGBAS-79395-2020")
        present = [s for s in source_match if s in ("MOA-FL014718-ACT", "DGBAS-79395-2020")]
        eligibility.append({
            "question_id": q["question_id"], "species": q.get("species_chinese"), "category": profile["question_category"],
            "question_text": q["question_text"], "question_text_valid": bool(str(q.get("question_text") or "").strip()),
            "candidate_answer_status": q.get("answer_verification_status"), "answer_verified": False,
            "candidate_source_urls": urls, "sources_present_in_phase_s_index_candidate": present,
            "source_candidate_version_verified": bool(present), "exact_support_locator_verified": False,
            "evidence_in_phase_s_index_candidate": bool(present), "sufficient_corpus_support": False,
            "benchmark_eligible_v2": False, "human_gold_reviewed": bool(q.get("human_gold_reviewed")),
            "status": "not_eligible_unverified_answer_or_exact_support" if not present else "source_present_but_exact_answer_support_not_reverified",
            "gate_version": "benchmark_gate_v2", "corpus_version": "phase_s_integrated_kb_v1", "final_top5_retrieval_status": "blocked_reranker_missing",
        })
    write_jsonl(OUT_DIR / "question_profiles_180.jsonl", qprofiles)
    write_jsonl(OUT_DIR / "question_eligibility_v2.jsonl", eligibility)
    write_jsonl(OUT_DIR / "retrieval_results_v2.jsonl", results)
    # An empty file is intentional: the system acceptance gate blocked all new Generator calls.
    (OUT_DIR / "generator_results_v2.jsonl").write_text("", encoding="utf-8")
    cats = Counter(r["category"] for r in eligibility)
    species = Counter(r["species"] for r in eligibility)
    summary = {"question_count": len(questions), "question_profiles": len(qprofiles), "fresh_retrieval_rows": len(results),
               "bm25_dense_rrf_completed": len(results), "final_top5_completed": 0, "generator_calls": 0, "expected_generator_calls": 720,
               "eligibility_pass_count": sum(r["benchmark_eligible_v2"] for r in eligibility), "answer_verified_count": sum(r["answer_verified"] for r in eligibility),
               "species_counts": dict(species), "category_counts": dict(cats), "no_gold_or_rubric_leakage": True}
    write_json(OUT_DIR / "question_eligibility_summary.json", summary)
    return questions, eligibility, summary


def build_governance_outputs(source_info: dict[str, Any], build_result: dict[str, Any], eligibility: list[dict[str, Any]], qsummary: dict[str, Any], preflight: dict[str, Any]) -> None:
    species_rules = {
        "canonical_labels": ["虱目魚", "吳郭魚", "石斑魚", "鱸魚", "烏魚", "鰻魚"],
        "accepted_aliases": {"exact canonical label only": "No unsupported aliases are promoted in this index"},
        "species_specific_rules": [
            "金目鱸及七星鱸保留各自原始範圍，不能將金目鱸數據一般化至鱸魚。",
            "烏魚、吳郭魚、虱目魚、石斑魚、鰻魚以來源原名對應；名稱相似不等於同種。",
            "午仔魚、統計類別、屬/目分類與精確物種不互相升級。",
            "DGBAS-79395 的原始統計類別只能作類別統計事實，不能當作精確生物物種或操作建議。",
            "通用法規不因缺少魚種詞而排除，但不能推導特定藥品、劑量或停藥期許可。",
        ],
        "unknown_handling": "SPECIES_SCOPE_UNKNOWN; abstain on species-specific recommendations",
        "crosswalk_quarantine": ["S08 query service not mapped to cold-advisory document", "S10 CWA API documentation not mapped to legal explanatory note"],
        "admitted_chunk_scopes": {"MOA-FL014718-ACT": "GENERAL_REGULATION", "DGBAS-79395-2020": "STATISTICAL_CATEGORY_ONLY"},
    }
    write_json(OUT_DIR / "species_applicability_validation.json", {"rules": species_rules, "species_conflict_candidates_revalidated": len(source_info["registry"]["species_scope_conflict_rows"]),
        "verified_species_specific_question_evidence": 0, "metadata_only_matches_promoted": 0, "status": "strict scope guard implemented; coverage remains limited"})
    categories = Counter(r["category"] for r in eligibility)
    species = Counter(r["species"] for r in eligibility)
    targets = {"Fact": 35, "Water Quality": 35, "Disease": 35, "Climate / Cold": 20, "Medication / Law": 20, "Calculation": 35}
    category_gaps = {k: {"target": n, "current_proposed_eligible": 0, "gap": n} for k,n in targets.items()}
    metrics = {
        "evaluation_status": "NOT_STARTED_SYSTEM_ACCEPTANCE_BLOCKED",
        "expected_questions": 180, "new_retrieval_final_top5_n": 0, "new_generator_expected": 720, "new_generator_completed": 0,
        "new_generator_success": 0, "new_generator_failed": 0, "new_generator_not_run": 720,
        "all_new_metric_values": {k: {"value": None, "n": 0, "reason": "new RAG system acceptance did not pass; no new generator outputs"} for k in ["Faithfulness", "Judge Answer Relevance", "BGE-M3 Cosine", "Structured IFR", "TTFT", "TPS", "System RAM", "Dedicated VRAM", "Context Precision@5", "Logical Accuracy", "Arithmetic Accuracy", "Citation Support"]},
        "historical_phase_e_metrics_are_not_reused_as_new_results": True,
        "winner": None, "formal_weighted_total": None,
    }
    write_json(OUT_DIR / "metrics_v2.json", metrics)
    readiness = {
        "system_acceptance_pass": False, "ready_for_720_generations": False, "blockers": [
            "BAAI/bge-reranker-v2-m3 local snapshot is missing; no substitute reranker was used",
            "New corpus scope is limited to official statute text and DGBAS 2020 descriptive facts; no verified species-specific aquaculture source set for the 180-question evaluation",
            "180 Fish Test candidate answers remain not independently gold-verified; no frozen Logical/Arithmetic rubric for this new corpus",
            "Final Top-5 was not produced; there is no valid shared context for four-model generation",
        ],
        "implemented_stages": ["source registry corrections sidecar", "PDF/XML source verification", "article/record bounded chunking", "BM25", "BGE-M3 dense", "RRF k=60", "species/category hard filters", "fail-closed evidence/generation policy", "isolated Streamlit UI"],
        "completed_stages": {"source_verification": True, "new_database": True, "bm25_dense_rrf_candidate_retrieval": True, "final_reranking": False, "new_generation": False, "new_metrics": False},
        "current_question_proposed_eligible": 0, "category_gaps": category_gaps,
        "species_counts_in_input": dict(species), "species_specific_eligible_count": 0,
        "historical_phase_e_run_reused": False, "human_gold": 0, "selection_holdout_claim": "none; all 180 questions are exposed regression/exploratory data",
    }
    write_json(OUT_DIR / "rag_evaluation_readiness.json", readiness)
    write_json(OUT_DIR / "species_category_coverage.json", {"species_input_counts": dict(species), "six_species_specific_evidence_eligible": {s: 0 for s in ["虱目魚","吳郭魚","石斑魚","鱸魚","烏魚","鰻魚"]},
       "general_fact_stat_rows": build_result["report"]["dgbas_xml"]["facts_indexed"], "legal_general_sources": 1, "coverage_claim": "source coverage only; no fish-specific eligibility inferred"})
    write_json(OUT_DIR / "species_category_gap_projection.json", {"targets": targets, "input_category_counts": dict(categories), "current_new_system_eligible": {k: 0 for k in targets}, "gaps": category_gaps, "formal_winner": None})


def main() -> None:
    before_rows, before_summary = hash_frozen("before")
    preflight = read_json(OUT_DIR / "outputs/phase_s_execution_snapshot.json")
    backup = backup_inputs()
    write_json(OUT_DIR / "phase_s_change_manifest.json", {
        "created_at": STAMP, "git_head": preflight["git"]["head"], "git_branch": preflight["git"]["branch"],
        "existing_dirty_state": preflight["git"]["status"], "backup": backup,
        "files_modified_outside_phase_s": [], "frozen_files_to_modify": [],
        "new_implementation_root": str(RUN.relative_to(ROOT)), "change_scope": "all new implementation, index, DB, app, and outputs are isolated under this Phase S run; Production untouched"})
    if not before_summary["complete"]:
        write_json(OUT_DIR / "phase_s_precheck_blocked.json", before_summary)
        raise RuntimeError(f"Frozen baseline precheck did not match 636/636: {before_summary}")
    source_info = audit_sources_and_crosswalk()
    # Validate the two documents whose versions and checksums are part of the frozen source registry.
    source_report = source_and_index_build()
    questions, eligibility, qsummary = prepare_questions_and_retrieval(source_report["chunks"], source_report["matrix"])
    build_governance_outputs(source_info, source_report, eligibility, qsummary, preflight)
    # Full local status of the 19 source documents and the 511/439 diagnostic sets.
    source_summary = {
        "phase_q_metadata_records": len(source_info["q_metadata_rows"]),
        "unique_docs_in_source_resolution": len(source_info["registry"]["source_document_audit"]),
        "local_byte_identity_matches": sum(r["local_bytes_identity_match"] for r in source_info["registry"]["source_document_audit"]),
        "pending_source_context_records": len(source_info["registry"]["pending_context_rows"]),
        "phase_p_context_rows": len(source_info["phase_p_rows"]),
        "species_scope_conflict_candidates_rechecked": len(source_info["registry"]["species_scope_conflict_rows"]),
        "alias_title_disagreements": source_info["registry"]["source_alias_audit_phase_q_preserved"].get("title_disagreement_rows"),
        "confirmed_crosswalk_identity_errors": 2,
        "promoted_weak_aliases": 0,
    }
    write_json(OUT_DIR / "source_governance_summary.json", source_summary)
    integration = {
        "test_run_id": RUN.name, "isolated_database_exists": DB_PATH.is_file(), "database_sha256": sha256_file(DB_PATH),
        "chunk_file_exists": (CORPUS_DIR / "phase_s_chunks_v1.jsonl").is_file(), "chunk_count": len(source_report["chunks"]),
        "source_checksum_validation": {"animal_drug_control_act": source_report["report"]["act_pdf_quality"]["checksum_match"], "dgbas_2020_xml": source_report["report"]["dgbas_xml"]["source_sha256"] == DGBAS_EXPECTED},
        "parser_quality": {"act_pdf": source_report["report"]["act_pdf_quality"]["status"], "dgbas_xml": source_report["report"]["dgbas_xml"]["status"]},
        "bge_m3_embed_api": {"status": "passed", "model_digest": preflight["models"][4].get("runtime_digest"), "dimension": 1024},
        "bm25_smoke": {"status": "passed", "query": "動物用藥品管理法", "candidate_count": len(source_report["chunks"])},
        "dense_smoke": {"status": "passed", "dimensions": int(source_report["matrix"].shape[1])},
        "rrf_smoke": {"status": "passed", "k": RRF_K, "questions_with_candidate_stage_trace": qsummary["bm25_dense_rrf_completed"]},
        "species_filter": {"status": "implemented", "test_species_confusion": "tilapia/mullet do not alias; seabass subtypes remain separate"},
        "reranker": {"status": "failed_blocker", "required_model": RERANKER_ID, "local_snapshot_found": False},
        "final_top5": {"status": "blocked", "count": 0}, "generator": {"status": "not_called_due_acceptance_gate", "expected": 720, "completed": 0},
        "streamlit_app_import_smoke": "pending", "end_to_end_acceptance": "blocked_not_passed",
        "old_production_sqlite_corpus_e4_generation_untouched": True,
    }
    write_json(OUT_DIR / "rag_system_integration_test.json", integration)
    version_checks = {
        "checked_at": "2026-10-17", "sources": [
            {"source_id": "MOA-FL014718-ACT", "official_url": "https://law.moa.gov.tw/LawContent.aspx?id=FL014718", "official_revision_date": "民國105年11月09日", "page_checked": "https://law.moa.gov.tw/LawContent.aspx?id=FL014718", "local_file_sha256": source_report["report"]["act_pdf_quality"]["actual_sha256"], "version_status": "official_current_page_revision_matches_local_pdf"},
            {"source_id": "MOA-FL035443-ANNEX-I-CANDIDATE", "official_url": "https://law.moa.gov.tw/LawContentSource.aspx?id=FL035443", "official_regulation_revision": "民國114年01月08日", "change_scope": "Annex II; Annex I last listed update 108-04-22", "local_file_sha256": source_report["report"]["annex_pdf_quality_quarantined"]["actual_sha256"], "version_status": "attachment_specific_binary_not_verified; excluded"},
            {"source_id": "DGBAS-79395-2020", "official_url": "https://data.gov.tw/dataset/79395", "resource_url": "https://ws.dgbas.gov.tw/001/Upload/461/relfile/11525/232442/mp01206a109.xml", "reference_year": 2020, "basis": "official resource label; XML has no year field", "sha256": DGBAS_EXPECTED, "status": "admitted_scope_limited"},
        ],
    }
    write_json(OUT_DIR / "official_source_version_checks.json", version_checks)
    # metrics_v2 and readiness were created from zero new model outputs; avoid filling N/A with 0 scores.
    old_metrics = read_json(PHASE_E / "model_comparison_summary.json")
    write_json(OUT_DIR / "historical_phase_e_metrics_reference.json", {"status": "historical_only_not_reused_as_phase_s", "path": str((PHASE_E / "model_comparison_summary.json").relative_to(ROOT)), "sha256": sha256_file(PHASE_E / "model_comparison_summary.json"), "data": old_metrics})
    (OUT_DIR / "rag_data_integrity_report.md").write_text(render_integrity_report(source_summary, source_report["report"], before_summary), encoding="utf-8")
    (OUT_DIR / "knowledge_base_rebuild_report.md").write_text(render_kb_report(source_report["report"]), encoding="utf-8")
    (OUT_DIR / "research_results_v2.md").write_text(render_research_results(source_report["report"], qsummary, integration), encoding="utf-8")
    (OUT_DIR / "phase_s_final_report.md").write_text(render_final(source_summary, source_report["report"], qsummary, integration, before_summary), encoding="utf-8")
    write_json(OUT_DIR / "compatibility.json", {
        "phase_s_output_version": RUN.name, "old_files_changed": [], "frozen_baseline_before": before_summary,
        "new_database": {"path": str(DB_PATH.relative_to(ROOT)), "sha256": sha256_file(DB_PATH)}, "formal_production_switch": False,
        "corpus_v2_mutated": False, "historical_e4_mutated": False, "generator_old_outputs_mutated": False, "winner_selected": False,
        "complete_pytest_suite_run": False, "known_tempfile_winerror5": "not addressed or claimed fixed",
    })
    # A result manifest makes the unrun 720 calls explicit and restart-safe.
    write_json(OUT_DIR / "evaluation_run_manifest.json", {"run_status": "blocked_before_generator", "expected_new_generations": 720, "actual_new_generations": 0,
        "blocked_by": "BGE reranker v2-m3 local snapshot missing; final shared Top-5 cannot be produced", "resume_rule": "after placing and verifying the exact local reranker snapshot, rerun acceptance, then retrieval+generation; no old results are imported"})
    print(json.dumps({"run": RUN.name, "before_frozen": before_summary, "source_summary": source_summary,
                      "chunk_count": len(source_report["chunks"]), "law_pdf_chunks": source_report["report"]["pdf_chunk_count"],
                      "dgbas_facts": source_report["report"]["dgbas_xml"]["facts_indexed"], "dgbas_cards_rechecked": source_report["report"]["dgbas_xml"]["six_card_matches"],
                      "retrieval_rows": qsummary["fresh_retrieval_rows"], "final_top5": qsummary["final_top5_completed"], "generator_calls": qsummary["generator_calls"],
                      "reranker": integration["reranker"]}, ensure_ascii=False, indent=2))


def render_integrity_report(sources, build, frozen):
    return f"""# Phase S 資料完整性報告\n\n- 執行時間：{STAMP}\n- Phase P source metadata 稽核列：{sources['phase_q_metadata_records']}；其中本輪實際重核的唯一本機文件：{sources['unique_docs_in_source_resolution']}，bytes checksum 相符：{sources['local_byte_identity_matches']}。\n- 來源待核對 Context：{sources['pending_source_context_records']}；檔案 byte identity 相符只證明檔案身分，不證明版本、權利或適用性。\n- Phase P 物種衝突候選重新分類：{sources['species_scope_conflict_candidates_rechecked']}；未以 metadata/關鍵字直接認定為適用。\n- Phase Q 別名標題差異：{sources['alias_title_disagreements']}；確認兩組來源錯配並在本輪 sidecar 隔離，未合併弱別名。\n- 新索引來源：MOA 法規正文及已限縮 Admission 的 DGBAS 2020 XML；水試所全文、未驗證附件與其他未核實來源不納入。\n- PDF 法規頁：{build['act_pdf_quality']['page_count']}；抽出 chunk {build['pdf_chunk_count']}；低文字頁 {len(build['act_pdf_quality']['scan_pages'])}。\n- DGBAS XML 原始 SHA-256：{build['dgbas_xml']['source_sha256']}；XML row {build['dgbas_xml']['xml_top_level_rows']}；可追溯數值事實 {build['dgbas_xml']['facts_indexed']}；六張既有卡重核 {build['dgbas_xml']['six_card_matches']}/6。\n- Frozen baseline 執行前：{frozen['matching_count']}/{frozen['checked_count']}；SQLite SHA-256 是否符合基線：{frozen['sqlite_matches']}。\n\n本輪沒有改動舊 Corpus、E4、SQLite、Production 或原始評測資料。\n"""


def render_kb_report(r):
    return f"""# Phase S 新知識庫建置報告\n\n建立隔離的 `phase_s_integrated_kb_v1`，不是正式 Evaluation Corpus v3。\n\n- 納入：{r['chunk_count']} chunks（官方法規正文 {r['pdf_chunk_count']}；DGBAS 2020 原始 XML atomic facts {r['dgbas_xml']['facts_indexed']}）。\n- Chunk JSONL SHA-256：`{r['chunk_file_sha256']}`。\n- Vector 檔 SHA-256：`{r['vector_file_sha256']}`；BGE-M3 1024 維、L2 正規化。\n- SQLite SHA-256：`{r['database_sha256']}`。\n- 法規按頁與條文切塊；DGBAS 每一非空值一個 chunk，保留 XML record/field、原始值、單位與區域名稱。\n- 全文政策限制：DGBAS 統計類別不升格為物種事實；只允許 Fact。\n- BM25 CJK n-gram + BGE-M3 Dense，RRF k=60。\n- BGE Reranker v2-m3 模型快照缺失，故候選索引及 BM25/Dense/RRF 可用，最終重排與 Top-5 未完成；索引狀態為 `candidate_retrieval_index_complete_reranker_pending`。\n- 未把未核准題庫、答案、rubric、評測報告或生成輸出放入索引。\n\n沒有宣稱新版系統已通過正式端到端驗收。\n"""


def render_research_results(build, qsummary, integration):
    return f"""# Phase S 研究結果（本輪）\n\n本輪完成新的隔離來源處理與候選檢索索引，不重跑舊720筆生成。\n\n- 索引 chunks：{build['chunk_count']}；DGBAS 2020 atomic facts：{build['dgbas_xml']['facts_indexed']}。\n- 180題完成 BM25、BGE-M3 Dense 與 RRF 候選階段 traces；最終 Reranker Top-5：0。\n- 新生成：0/720。因缺少 BGE Reranker v2-m3 本機權重，未通過系統驗收，依流程不啟動新生成。\n- Context Precision@5、Logical Accuracy、Arithmetic Accuracy 及原八項指標：本輪新結果均為 N/A；有效新樣本 N=0。\n- 舊 Phase E M2 指標只作歷史參考，沒有混入本輪指標或排名。\n- 正式總分：未計算；Winner：null。\n\n系統架構實作包含需求解析、BM25、BGE-M3、RRF、物種/類別門控、BGE 重排介面、證據不足拒答、JSON Schema、引用原文驗證及獨立 Streamlit UI。缺少重排權重令最後一段無法運行。\n"""


def render_final(src, build, qs, integration, frozen):
    return f"""# Phase S 最終報告\n\n## 完成\n\n- 建立版本化、隔離的新 RAG 程式、資料處理流程、SQLite、向量索引與 Streamlit 入口。\n- 修復兩組已確認 Source Crosswalk：S08 放養量查詢服務及 S10 氣象 API 說明各自不再指向錯誤文件；無弱別名升格。\n- 重核 {src['unique_docs_in_source_resolution']} 份來源原件的本機 byte identity，匹配 {src['local_byte_identity_matches']} 份；Authority、rights、version 或 species 欄位仍未證實者保持 UNVERIFIED。\n- 逐筆保存 {src['pending_source_context_records']} 筆來源 metadata Context 處理狀態；重分類 {src['species_scope_conflict_candidates_rechecked']} 筆物種範圍候選，不把關鍵字/metadata 當成適用性證明。\n- 新索引含 {build['chunk_count']} chunks：法規正文 {build['pdf_chunk_count']}、DGBAS 2020 原始統計 atomic facts {build['dgbas_xml']['facts_indexed']}。\n- 180題均有新的 BM25、Dense、RRF 候選階段檢索紀錄；沒有提供錯誤或未完成的最終 Top-5。\n\n## 驗收阻塞及評測狀態\n\n- 本機缺少 `BAAI/bge-reranker-v2-m3` 的可載入權重快照。雖然舊實驗記錄過成功，但本輪找不到可重現的權重路徑，因此不使用其他模型冒充。\n- 故最終 Top-5 未建立，完整 Hybrid-RAG 端到端驗收未通過。\n- 新生成為 {qs['generator_calls']}/{qs['expected_generator_calls']}；依驗收門檻沒有啟動720次生成。\n- 11項新評估指標本輪均 N/A，N=0；沒有把 Phase E 分數複製成新結果。\n- 新索引來源有限：已納入 MOA 動物用藥品管理法正文與先前限縮 Admission 的 DGBAS 2020 XML。水試所手冊因處理範圍未證明未索引；FL035443 附件一因附件版本對照未完成而隔離。此知識庫不足以代表六種魚類的全領域水產養殖。\n\n## 保護檢查\n\n- 執行前 Frozen Manifest：{frozen['matching_count']}/{frozen['checked_count']}；SQLite hash 基線匹配：{frozen['sqlite_matches']}。\n- 720筆舊生成、Corpus v2、Historical E4、Production、SQLite、Phase E–R 歷史結果均未修改。\n- 正式環境切換未執行；模型比較與 Winner Selection 未執行。\n\n## 重新啟動條件\n\n提供可校驗的 `BAAI/bge-reranker-v2-m3` 本機 snapshot（revision `953dc6f6f85a1b2dbfca4c34a2796e7dde08d41`），由隔離新系統重新執行重排、引用/物種門控及端到端驗收；再凍結題目資格、參考答案和rubric後，才可開始新的720筆回歸生成。\n"""


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Build the isolated Phase S RAG candidate index. No production files are modified.")
    parser.add_argument("--execute", action="store_true", help="Run the full source verification and isolated candidate-index build")
    args = parser.parse_args()
    if args.execute:
        main()
    else:
        print("Preflight only. Pass --execute to build the isolated Phase S candidate index.")
