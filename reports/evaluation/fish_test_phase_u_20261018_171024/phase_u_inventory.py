from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import sys
import traceback
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import fitz

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "reports/evaluation/fish_test_phase_u_20261018_171024"
PHASE_S = ROOT / "reports/evaluation/fish_test_phase_s_integrated_20261017_173906"
PHASE_T = ROOT / "reports/evaluation/fish_test_phase_t_20261017_174751"
SPECIES = {
    "虱目魚": ["虱目魚", "milkfish"],
    "吳郭魚": ["吳郭魚", "台灣鯛", "tilapia", "oreochromis"],
    "石斑魚": ["石斑魚", "grouper", "epinephelus"],
    "鱸魚": ["鱸魚", "金目鱸", "七星鱸", "sea bass", "seabass", "lates calcarifer", "lateolabrax"],
    "烏魚": ["烏魚", "烏仔魚", "mullet", "mugil"],
    "鰻魚": ["鰻魚", "鰻", "eel", "anguilla"],
}
CATEGORY_TERMS = {
    "Fact": ["養殖", "產量", "面積", "生產", "品種", "種苗", "規格", "分類"],
    "Water Quality": ["水質", "溶氧", "氧氣", "氨氮", "亞硝酸", "pH", "鹽度", "水溫", "水質管理"],
    "Disease": ["疾病", "病原", "病毒", "細菌", "寄生蟲", "症狀", "防治", "生物安全"],
    "Climate/Cold": ["寒害", "防寒", "低溫", "氣候", "颱風", "災害", "水溫下降"],
    "Medication/Law": ["法規", "藥品", "用藥", "停藥期", "動物用藥", "條例", "準則", "附表"],
    "Calculation": ["公式", "計算", "飼料轉換", "FCR", "SGR", "活存率", "放養密度", "單位面積"],
}
TERMS_TO_REMOVE = {"_", "-"}


def read_json(path: Path, default=None):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8-sig"))


def read_jsonl(path: Path):
    if not path.exists():
        return []
    rows = []
    with path.open("r", encoding="utf-8-sig") as f:
        for n, line in enumerate(f, 1):
            if line.strip():
                try:
                    rows.append(json.loads(line))
                except Exception as e:
                    rows.append({"_parse_error": str(e), "_line": n})
    return rows


def dump_json(path: Path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def dump_jsonl(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def sha256(path: Path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def norm_path(s: str):
    return str(s or "").replace("/", "\\").casefold()


def file_candidates():
    roots = [
        ROOT / "my_data",
        ROOT / "data/recovery/raw_sources",
        ROOT / "research_staging/_official_source_staging/phase20_1E_step3I/raw",
        ROOT / "research_staging/_official_source_staging/phase20_1E_step3E/raw/pdf",
    ]
    extensions = {".pdf", ".xml", ".csv", ".html", ".htm"}
    found, errors = [], []
    for base in roots:
        if not base.exists():
            continue
        for dirpath, dirnames, filenames in os.walk(base, onerror=lambda e: errors.append({"path": str(e.filename), "error": str(e)})):
            dirnames[:] = [d for d in dirnames if d not in {"__pycache__", ".pytest_cache"}]
            for name in filenames:
                p = Path(dirpath) / name
                if p.suffix.lower() in extensions:
                    found.append(p)
    return sorted(set(found), key=lambda p: str(p).casefold()), errors


def parse_document(path: Path):
    ext = path.suffix.lower()
    result = {"file_format": ext.lstrip("."), "page_count": None, "nonempty_pages": None,
              "empty_pages": None, "total_extracted_characters": None, "parser": None,
              "pdf_metadata_title": None, "pdf_metadata_author": None, "pdf_metadata_creation": None,
              "species_content_hits": {}, "species_candidate_pages": {}, "category_content_hits": {},
              "category_candidate_pages": {}, "first_page_text_sample": None, "parse_error": None}
    text = ""
    try:
        if ext == ".pdf":
            doc = fitz.open(path)
            result.update(page_count=doc.page_count, parser=f"PyMuPDF {fitz.VersionBind}")
            meta = doc.metadata or {}
            result.update(pdf_metadata_title=meta.get("title"), pdf_metadata_author=meta.get("author"),
                          pdf_metadata_creation=meta.get("creationDate"))
            page_texts = [page.get_text("text") or "" for page in doc]
            result["nonempty_pages"] = sum(bool(x.strip()) for x in page_texts)
            result["empty_pages"] = len(page_texts) - result["nonempty_pages"]
            text = "\n".join(page_texts)
            result["total_extracted_characters"] = len(text)
            result["first_page_text_sample"] = re.sub(r"\s+", " ", page_texts[0])[:500] if page_texts else ""
            result["species_content_hits"] = {sp: sum(text.count(term) for term in aliases) for sp, aliases in SPECIES.items()}
            result["species_candidate_pages"] = {
                sp: [i + 1 for i, page in enumerate(page_texts) if any(term in page for term in aliases)]
                for sp, aliases in SPECIES.items() if any(any(term in page for term in aliases) for page in page_texts)
            }
            result["category_content_hits"] = {cat: sum(text.lower().count(term.lower()) for term in terms) for cat, terms in CATEGORY_TERMS.items()}
            result["category_candidate_pages"] = {
                cat: [i + 1 for i, page in enumerate(page_texts) if any(term.lower() in page.lower() for term in terms)]
                for cat, terms in CATEGORY_TERMS.items() if any(any(term.lower() in page.lower() for term in terms) for page in page_texts)
            }
            doc.close()
        elif ext == ".xml":
            raw = path.read_bytes()
            # Fail closed on DTD declarations and parse with the standard XML parser, which does not fetch external resources.
            if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
                result["parse_error"] = "DTD/entity declaration present; parsing not attempted"
            else:
                root = ET.fromstring(raw)
                result.update(parser="xml.etree.ElementTree (external retrieval disabled)", page_count=None,
                              nonempty_pages=None, empty_pages=None, total_extracted_characters=len(raw.decode("utf-8", "replace")),
                              xml_root_tag=root.tag, xml_element_count=sum(1 for _ in root.iter()),
                              xml_record_count=len(list(root)))
                text = " ".join([root.tag] + [el.tag + " " + (el.text or "") for el in root.iter()])
                result["first_page_text_sample"] = text[:500]
                result["species_content_hits"] = {sp: sum(text.count(term) for term in aliases) for sp, aliases in SPECIES.items()}
                result["category_content_hits"] = {cat: sum(text.lower().count(term.lower()) for term in terms) for cat, terms in CATEGORY_TERMS.items()}
        elif ext == ".csv":
            raw = path.read_bytes()
            import csv as csvmod
            with path.open("r", encoding="utf-8-sig", newline="") as f:
                rows = list(csvmod.reader(f))
            result.update(parser="Python csv", csv_row_count=max(len(rows) - 1, 0), csv_columns=rows[0] if rows else [],
                          total_extracted_characters=len(raw.decode("utf-8-sig", "replace")))
            text = " ".join(str(c) for row in rows[:5000] for c in row)
            result["first_page_text_sample"] = " | ".join(rows[0])[:500] if rows else ""
            result["species_content_hits"] = {sp: sum(text.count(term) for term in aliases) for sp, aliases in SPECIES.items()}
            result["category_content_hits"] = {cat: sum(text.lower().count(term.lower()) for term in terms) for cat, terms in CATEGORY_TERMS.items()}
        elif ext in {".html", ".htm"}:
            raw = path.read_bytes()
            text = raw.decode("utf-8", "replace")
            result.update(parser="UTF-8 replacement decode; HTML not rendered", total_extracted_characters=len(text),
                          first_page_text_sample=re.sub(r"\s+", " ", text)[:500])
        return result
    except Exception as e:
        result["parse_error"] = f"{type(e).__name__}: {e}"
        return result


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    source_reg = read_json(PHASE_S / "source_registry_corrected.json", {})
    phase_s_manifest = read_json(PHASE_S / "knowledge_base_build_manifest.json", {})
    doc_manifest = read_jsonl(ROOT / "reports/recovery/document_manifest_v3.jsonl")
    eligibility = read_jsonl(ROOT / "reports/parsing/document_eligibility.jsonl")
    phase_s_integrity = read_jsonl(PHASE_S / "source_integrity_19_documents.jsonl")
    alias_summary = read_json(PHASE_S / "source_alias_resolution_summary.json", {})
    open_data_manifest = read_jsonl(ROOT / "research_staging/_official_source_staging/phase20_1E_step3I/metadata/open_data_acquisition_manifest.jsonl")
    phase_t_elig = read_jsonl(PHASE_T / "question_eligibility_v3.jsonl")
    phase_t_retrieval = read_jsonl(PHASE_T / "retrieval_results_v3.jsonl")
    gov_admission = read_json(ROOT / "reports/evaluation/final_model_selection/phase20_1E_exec_r3/step3v_dgbas_formal_admission/dgbas_2020_formal_admission_record.json", {})

    manifest_by_path = {norm_path(x.get("file_path")): x for x in doc_manifest}
    elig_by_path = {norm_path(x.get("file_path")): x for x in eligibility}
    phase_s_int_by_path = {norm_path(x.get("file_path")): x for x in phase_s_integrity}
    phase_s_int_by_hash = {x.get("actual_sha256"): x for x in phase_s_integrity if x.get("actual_sha256")}
    gov_artifact_map = {}
    for dataset in open_data_manifest:
        for artifact in dataset.get("artifacts", []):
            local = norm_path(artifact.get("local_path"))
            if local:
                gov_artifact_map[local] = (dataset, artifact)
    sources = []
    walk_errors = []
    paths, walk_errors = file_candidates()
    for path in paths:
        rel = str(path.relative_to(ROOT)).replace("\\", "/")
        info = {
            "source_record_id": "SRC-" + hashlib.sha256(rel.encode("utf-8")).hexdigest()[:12],
            "original_path": rel,
            "file_name": path.name,
            "file_exists": path.is_file(),
            "file_size_bytes": path.stat().st_size if path.is_file() else None,
            "checksum_sha256": None,
            "checksum_status": "not_computed",
            "source_id": None,
            "document_id": None,
            "title": path.stem,
            "publisher": None,
            "url": None,
            "version": None,
            "effective_date": None,
            "species_scope": "unknown_pending_content_and_source_validation",
            "categories": [],
            "parsing_quality": None,
            "admission_status": "unverified_not_admitted",
            "intended_use_scope": None,
            "duplicate_sha256_group": None,
            "phase_s_manifest_status": None,
            "phase_t_source_use_status": None,
        }
        try:
            info["checksum_sha256"] = sha256(path)
            info["checksum_status"] = "computed_read_only"
        except Exception as e:
            info["checksum_status"] = f"unreadable:{type(e).__name__}:{e}"
        source_meta = manifest_by_path.get(norm_path(rel)) or manifest_by_path.get(norm_path(str(path)))
        eligible_meta = elig_by_path.get(norm_path(rel)) or elig_by_path.get(norm_path(str(path)))
        integ = phase_s_int_by_path.get(norm_path(rel)) or phase_s_int_by_path.get(norm_path(str(path)))
        gov_pair = gov_artifact_map.get(norm_path(rel)) or gov_artifact_map.get(norm_path(str(path)))
        if not integ and info["checksum_sha256"]:
            integ = phase_s_int_by_hash.get(info["checksum_sha256"])
        if source_meta:
            info.update(source_id=source_meta.get("source_id"), document_id=source_meta.get("document_id"),
                        title=source_meta.get("title") or info["title"], publisher=source_meta.get("organization"),
                        url=source_meta.get("source_url"), version=source_meta.get("version"),
                        effective_date=source_meta.get("effective_date"), phase_s_manifest_status=source_meta.get("ingestion_status"),
                        source_manifest_species=source_meta.get("species"), source_manifest_topics=source_meta.get("topics"),
                        source_manifest_parser=source_meta.get("parser_version"))
        if eligible_meta:
            info["parsing_eligibility"] = {"ingestion_status": eligible_meta.get("ingestion_status"),
                                           "source_verified": eligible_meta.get("source_verified"),
                                           "review_reason": eligible_meta.get("review_reason"),
                                           "page_status_counts": eligible_meta.get("page_status_counts")}
        if integ:
            info.update(document_id=info.get("document_id") or integ.get("document_id"),
                        title=info.get("title") or integ.get("source_title"),
                        source_id=info.get("source_id") or integ.get("corpus_source_id"),
                        url=info.get("url") or integ.get("corpus_source_url"),
                        phase_t_source_use_status="BYTE_IDENTITY_CONFIRMED_ONLY; publisher/version/rights/species remain unverified")
        if gov_pair:
            dataset, artifact = gov_pair
            info.update(source_id=dataset.get("source_id"), title=dataset.get("title") or info.get("title"),
                        publisher=dataset.get("publisher"), url=artifact.get("resource_url") or dataset.get("landing_url"),
                        version=artifact.get("period") or dataset.get("metadata_updated"),
                        license=dataset.get("license"), license_url=dataset.get("license_url"),
                        attribution_requirements="Follow dataset-specific attribution terms recorded on data.gov.tw; exact resource scope must be checked.",
                        dataset_scope=dataset.get("scope"), dataset_version_limitations=dataset.get("version_limitations"),
                        resource_download_status=dataset.get("download_status"), dataset_formal_admitted=dataset.get("formal_admitted"),
                        intended_use_scope="Source-specific; only facts supported by exact original fields/records; no inference beyond dataset schema.")
            if dataset.get("formal_admitted"):
                info["admission_status"] = "admitted_scope_limited" if dataset.get("source_id") == "DGBAS-AQUACULTURE-SPECIES-79395" and "2020" in path.name else "not_admitted"
            else:
                info["admission_status"] = "not_admitted_owner_decision_required"
        # Match a small set of already-known source identities by exact checksum, never by title alone.
        if info["checksum_sha256"] == "31c4cdb6fc3cdcd58abc4a5ba8a1cde908f1ca12f9f338fb39da4d4bf494dd31" and path.suffix.lower() == ".xml" and "2020" in path.name:
            info.update(source_id="DGBAS-79395-2020", title="DGBAS-79395 2020 XML resource", publisher="行政院主計總處",
                        url="https://data.gov.tw/dataset/79395", version="resource label 2020; XML has no year field",
                        effective_date="reference year 2020; resource label basis", species_scope="statistical categories only; not precise biological species",
                        categories=["Fact"], admission_status="admitted_scope_limited; corpus_inclusion=not_ingested",
                        intended_use_scope="2020 single-year descriptive Fact using original areas, categories, fields and values only")
        # Exact local path/known source overrides for the two already verified official statute resources.
        if path.name == "動物用藥品管理法.pdf":
            info.update(source_id="MOA-FL014718-ACT", title="動物用藥品管理法", publisher="農業部",
                        url="https://law.moa.gov.tw/LawContent.aspx?id=FL014718", version="official page revision 105-11-09; Phase S local PDF aligned",
                        categories=["Medication/Law"], admission_status="verified_source_in_Corpus_v2; new Corpus v3 use requires explicit source approval",
                        intended_use_scope="statute text only; no specific drug approval inferred beyond text")
        if path.name == "moa_animal_drug_use_rules_attachment_1_FL035443.pdf":
            info.update(source_id="MOA-FL035443-ANNEX-I-CANDIDATE", title="動物用藥品使用準則附表一候選原件", publisher="農業部",
                        url="https://law.moa.gov.tw/LawContentSource.aspx?id=FL035443", version="attachment identity/version mapping unverified",
                        categories=["Medication/Law"], admission_status="excluded_pending_attachment_version_and_admission",
                        intended_use_scope="not approved for indexing until exact Annex I binary and effective version are verified")
        parse = parse_document(path)
        info["content_parse"] = parse
        # Content matches are candidate locators only, not a verified scope assertion.
        if parse.get("species_candidate_pages"):
            info["content_species_signals"] = parse["species_candidate_pages"]
        cat_hits = parse.get("category_content_hits", {}) or {}
        info["content_category_signals"] = [k for k, v in cat_hits.items() if v > 0]
        if parse.get("page_count") is not None:
            empty_ratio = (parse.get("empty_pages") or 0) / max(parse.get("page_count") or 0, 1)
            avg_chars = (parse.get("total_extracted_characters") or 0) / max(parse.get("page_count") or 0, 1)
            info["parsing_quality"] = {
                "page_count": parse.get("page_count"),
                "native_text_pages": parse.get("nonempty_pages"),
                "empty_or_unextractable_pages": parse.get("empty_pages"),
                "avg_extracted_chars_per_page": round(avg_chars, 1),
                "empty_page_ratio": round(empty_ratio, 4),
                "parse_error": parse.get("parse_error"),
                "tables_and_layout_manually_validated": False,
                "scope": "text extraction diagnostic only; not a semantic or rights review",
            }
        sources.append(info)

    # Physical duplicate checks; do not merge records or alter originals.
    hash_paths = defaultdict(list)
    for item in sources:
        if item.get("checksum_sha256"):
            hash_paths[item["checksum_sha256"]].append(item["original_path"])
    for item in sources:
        copies = hash_paths.get(item.get("checksum_sha256"), [])
        if len(copies) > 1:
            item["duplicate_sha256_group"] = item["checksum_sha256"]
            item["identical_file_paths"] = copies

    # Explicit crosswalk overlay scoped to the workbook/source keys documented in Phase S.
    repairs = alias_summary.get("phase_s_applied_crosswalk_repairs", [])
    overlay = {
        "overlay_version": "phase_u_source_overlay_v1",
        "applies_to_new_phase_u_inventory_and_candidate_processing_only": True,
        "does_not_modify_production_or_any_historical_registry_or_corpus": True,
        "corrections": [
            {"source_key": "fish test/鱸魚_AI測試題庫_2026_1003.xlsx::S08", "source_id": "S08",
             "detach_from_document_id": "30b9fedc-1646-50b0-b7f0-0aeb9f54a76a", "canonical_resource": "漁業署養殖漁業放養量查詢服務",
             "url": "https://fadopen.fa.gov.tw/fadopen/service/qryBreedPredictReport.htmx", "mapping_status": "corrected_identity_detached; content/schema/version not captured",
             "admission_status": "not_admitted"},
            {"source_key": "fish test/鱸魚_AI測試題庫_2026_1003.xlsx::S10", "source_id": "S10",
             "detach_from_document_id": "3ac134e2-d7d8-52e4-9e3f-af2ffcb5a20d", "canonical_resource": "中央氣象署 Open Data API Swagger documentation",
             "url": "https://opendata.cwa.gov.tw/dist/opendata-swagger.html", "mapping_status": "corrected_identity_detached; no snapshot/version captured",
             "admission_status": "not_admitted"},
        ],
        "source_evidence": "Phase S preserved Phase Q crosswalk audit; identity errors are source-role contradictions, not source-content falsity",
        "prior_phase_repairs": repairs,
    }
    dump_json(OUT / "source_crosswalk_overlay.json", overlay)

    # Government open-data status and resource metadata are retained from the verified acquisition record.
    gov_summary = []
    for row in open_data_manifest:
        gov_summary.append(dict(row))

    # Six-species inventory joins only exact evidence signals; unknown scope stays unknown.
    species_rows = []
    for sp in SPECIES:
        matched = []
        for item in sources:
            pages = (item.get("content_species_signals") or {}).get(sp, [])
            manifest_species = item.get("source_manifest_species") or []
            title_signal = sp in (item.get("title") or "")
            if pages or sp in manifest_species or title_signal:
                matched.append({"source_record_id": item["source_record_id"], "source_id": item.get("source_id"),
                                "title": item.get("title"), "path": item["original_path"],
                                "content_pages": pages, "manifest_species_claim": manifest_species,
                                "title_signal_only": bool(title_signal and not pages and sp not in manifest_species),
                                "admission_status": item.get("admission_status"),
                                "usage_scope_status": "candidate content signal only; independent species applicability not established"})
        species_rows.append({"species": sp, "candidate_source_records": len(matched), "verified_species_specific_admitted_sources": 0,
                             "sources": matched})

    # Fresh read-only verification of the 636-entry Frozen manifest listed by Phase T.
    frozen_path = PHASE_T / "frozen_baseline_post_finalize.jsonl"
    frozen = read_jsonl(frozen_path)
    frozen_results = []
    for entry in frozen:
        rel = entry.get("path") or entry.get("relative_path") or entry.get("file")
        expected = entry.get("sha256") or entry.get("expected_sha256") or entry.get("digest")
        if not rel or not expected:
            frozen_results.append({"path": rel, "expected_sha256": expected, "status": "manifest_schema_unrecognized"})
            continue
        p = ROOT / rel
        try:
            actual = sha256(p)
            frozen_results.append({"path": rel, "expected_sha256": expected, "actual_sha256": actual,
                                   "status": "MATCH" if actual == expected else "MISMATCH"})
        except Exception as e:
            frozen_results.append({"path": rel, "expected_sha256": expected, "status": "UNREADABLE",
                                   "error": f"{type(e).__name__}: {e}"})
    frozen_counts = Counter(x.get("status") for x in frozen_results)
    sqlite_actual = None
    try:
        sqlite_actual = sha256(ROOT / "rag_store.sqlite3")
    except Exception:
        pass
    frozen_report = {"checked_at": datetime.now(timezone.utc).isoformat(), "manifest_source": str(frozen_path.relative_to(ROOT)),
                     "manifest_rows": len(frozen), "status_counts": dict(frozen_counts),
                     "all_636_match": len(frozen) == 636 and frozen_counts.get("MATCH", 0) == 636,
                     "protected_sqlite_sha256": sqlite_actual,
                     "protected_sqlite_expected_sha256": "d7d06d4d2a57d0a57d05bcb6131ffb24aefb226c6bd36349dbc5118d33b11087",
                     "protected_sqlite_matches": sqlite_actual == "d7d06d4d2a57d0a57d05bcb6131ffb24aefb226c6bd36349dbc5118d33b11087",
                     "per_file_results": frozen_results}
    dump_json(OUT / "frozen_baseline_recheck.json", frozen_report)

    # Baseline reconciliation with historical/new run separation.
    t_readiness = read_json(PHASE_T / "rag_evaluation_readiness.json", {})
    t_summary = read_json(PHASE_T / "retrieval_results_summary.json", {})
    t_gen = read_jsonl(PHASE_T / "generator_results_v3.jsonl")
    t_elig_counts = Counter(x.get("category") for x in phase_t_elig)
    t_species_counts = Counter(x.get("species") for x in phase_t_elig)
    statuses = Counter(x.get("gate_status") for x in phase_t_elig)
    retrieval_counts = Counter(x.get("retrieval_status") for x in phase_t_retrieval)
    baseline = {
        "phase": "U", "as_of_local_date": "2026-10-18", "input_phase_t": str(PHASE_T.relative_to(ROOT)),
        "phase_t_baseline": {"candidate_index_chunk_count": phase_s_manifest.get("chunk_count"),
                              "candidate_index_sources": len(phase_s_manifest.get("included_sources", [])),
                              "formal_corpus_v3_built": phase_s_manifest.get("formal_evaluation_corpus_v3"),
                              "phase_t_questions": len(phase_t_elig), "phase_t_retrieval_rows": len(phase_t_retrieval),
                              "phase_t_retrieval_status_counts": dict(retrieval_counts),
                              "phase_t_eligibility_counts": dict(statuses), "phase_t_generator_rows": len(t_gen),
                              "phase_t_system_acceptance": t_readiness.get("system_acceptance_pass"),
                              "phase_t_ready_for_720": t_readiness.get("ready_for_720_generations"),
                              "phase_t_zero_answer_verified": t_readiness.get("current_question_proposed_eligible", 0) == 0},
        "phase_s_source_registry": {"source_docs": len(source_reg.get("source_document_audit", [])),
                                    "pending_context_rows": source_reg.get("input_rows", {}).get("phase_q_source_metadata_resolution_rows"),
                                    "species_scope_conflict_rows": len(source_reg.get("species_scope_conflict_rows", [])),
                                    "crosswalk_confirmed_identity_error_pairs": 2,
                                    "crosswalk_correction_overlay_applied_to_phase_u": True},
        "formal_admission_history": {"dgbas_79395_2020": gov_admission.get("admission_execution_status", "admitted_scope_limited"),
                                     "dgbas_corpus_inclusion": gov_admission.get("corpus_inclusion_status", "not_ingested"),
                                     "other_new_source_admissions_in_phase_u": 0},
        "question_species_counts": dict(t_species_counts), "question_category_counts": dict(t_elig_counts),
        "new_corpus_build_status": "NOT_BUILT_BLOCKED_PENDING_SOURCE_APPROVAL_AND_COVERAGE",
        "new_retrievals_executed": 0, "new_generator_calls": 0,
        "blockers": ["Owner has not explicitly admitted any new professional aquaculture sources in Phase U.",
                     "Phase T candidate corpus was statute plus DGBAS statistics and had 0/180 eligible questions.",
                     "A versioned new corpus cannot be built from pending or unverified sources.",
                     "No refreshed retrieval contexts or frozen source-backed scoring rubrics exist for 180 questions."],
        "formal_winner": None,
    }
    dump_json(OUT / "baseline_reconciliation.json", baseline)

    # Records for workbook and audit output.
    dump_jsonl(OUT / "source_inventory_records.jsonl", sources)
    dump_jsonl(OUT / "government_data_source_records.jsonl", gov_summary)
    dump_json(OUT / "species_source_coverage.json", {"species": species_rows,
                "taxonomy_policy": {"吳郭魚": "keep statistical/type labels distinct from biological species", "鱸魚": "金目鱸 and 七星鱸 remain separate; no group-wide inference",
                                    "烏魚": "Mugilidae/Mugil labels do not imply tilapia", "DGBAS categories": "statistical classes only"},
                "status": "CANDIDATE_LOCATORS_ONLY_NOT_VERIFIED_APPLICABILITY", "verified_admitted_species_specific_sources": 0,
                "method_warning": "Text/title/manifest signals locate candidate pages only; no professional cross-species inference is made."})
    dump_json(OUT / "species_applicability_validation.json", {"species": species_rows,
                "taxonomy_policy": {"吳郭魚": "keep statistical/type labels distinct from biological species", "鱸魚": "金目鱸 and 七星鱸 remain separate; no group-wide inference",
                                    "烏魚": "Mugilidae/Mugil labels do not imply tilapia", "DGBAS categories": "statistical classes only"},
                "status": "CANDIDATE_LOCATORS_ONLY_NOT_VERIFIED_APPLICABILITY", "verified_admitted_species_specific_sources": 0,
                "method_warning": "Text/title/manifest signals locate candidate pages only; no professional cross-species inference is made."})

    # Approval matrix: no new source is admitted here; current owner decision remains pending.
    matrix = []
    for item in sources:
        if item.get("source_id") == "DGBAS-79395-2020":
            decision = "already_admitted_scope_limited"
        elif item.get("source_id") == "MOA-FL014718-ACT":
            decision = "previously_verified_in_corpus_v2; new_corpus_use_requires_owner_decision"
        elif item.get("admission_status", "").startswith("excluded_pending"):
            decision = "blocked_version_identity_and_owner_admission"
        else:
            decision = "pending_owner_source_admission"
        rec = {
            "source_record_id": item["source_record_id"], "source_id": item.get("source_id"), "title": item.get("title"),
            "publisher": item.get("publisher") or "UNVERIFIED", "original_path": item.get("original_path"),
            "url": item.get("url"), "version": item.get("version") or "UNVERIFIED", "effective_date": item.get("effective_date") or "UNVERIFIED",
            "checksum_sha256": item.get("checksum_sha256"), "species_content_signals": item.get("content_species_signals", {}),
            "categories_content_signals": item.get("content_category_signals", []),
            "content_review_status": "text_extraction_and_keyword_locator_only; substantive source validation pending",
            "source_integrity_status": item.get("checksum_status"), "parsing_quality": item.get("parsing_quality"),
            "current_admission_status": item.get("admission_status", "unverified_not_admitted"),
            "new_corpus_admission_decision": decision,
            "candidate_allowed_processing_scope": "none until owner decision; research staging/metadata review only",
            "attribution_or_license": "UNVERIFIED unless a source-specific official license record is linked",
            "expected_species_and_categories": {"species_candidates": list(item.get("content_species_signals", {}).keys()),
                                                 "category_candidates": item.get("content_category_signals", [])},
            "risk_and_blockers": [x for x in [
                "publication/version/effective date not independently fixed" if not item.get("version") else None,
                "publisher/source URL not verified" if not item.get("publisher") and not item.get("url") else None,
                "source use/attribution scope not documented for new corpus" if decision not in {"already_admitted_scope_limited"} else None,
                "PDF table/layout and exact page spans not audited" if item.get("file_format") == "pdf" else None,
                "species signal is lexical and does not establish applicability" if item.get("content_species_signals") else None,
            ] if x],
            "owner_decision": "PENDING" if decision != "already_admitted_scope_limited" else "NOT_REQUIRED_FOR_EXISTING_LIMITED_ADMISSION",
        }
        if item.get("license"):
            rec["attribution_or_license"] = item.get("license")
            rec["license_url"] = item.get("license_url")
            rec["attribution_requirements"] = item.get("attribution_requirements")
            rec["dataset_scope"] = item.get("dataset_scope")
            rec["dataset_version_limitations"] = item.get("dataset_version_limitations")
        matrix.append(rec)
    dump_jsonl(OUT / "source_admission_approval_matrix.jsonl", matrix)

    # Carry forward the 180 T gate records without changing historical fields.
    elig_u = []
    for row in phase_t_elig:
        new = dict(row)
        new["phase_u_status"] = "blocked_not_eligible_before_new_corpus_build"
        new["phase_u_source_admission_status"] = "no_new_source_admissions"
        new["phase_u_benchmark_eligible"] = False
        new["historical_phase_t_record_preserved"] = True
        elig_u.append(new)
    dump_jsonl(OUT / "question_eligibility_v3.jsonl", elig_u)
    # Explicit NOT_RUN records are not retrieval results and contain no fabricated ranks/chunks.
    retr_u = [{"question_id": row.get("question_id"), "run_id": "phase_u_blocked_before_retrieval",
               "run_status": "NOT_RUN", "corpus_version": None, "top5": [],
               "reason": "No designated approved Corpus v3 was built; Phase T retrieval is historical and not reused as Phase U output."}
              for row in phase_t_elig]
    dump_jsonl(OUT / "retrieval_results_v3_final.jsonl", retr_u)
    # Zero new generation rows, intentionally empty file.
    (OUT / "generator_results_v3_final.jsonl").write_text("", encoding="utf-8")
    metric_names = ["faithfulness", "judge_answer_relevance", "bge_m3_cosine_similarity", "structured_ifr", "ttft", "tps",
                    "system_ram", "dedicated_vram", "context_precision_at_5", "logical_accuracy", "arithmetic_accuracy"]
    metrics = {"run_status": "NOT_RUN_BLOCKED_BEFORE_GENERATION", "corpus_version": None, "model_generation_count": 0,
               "metrics": {name: {"value": None, "n": 0, "status": "NOT_EVALUATED", "reason": "No Phase U retrieval/generation and no frozen eligible reference set."} for name in metric_names},
               "formal_weighted_score": None, "winner": None}
    dump_json(OUT / "evaluation_metrics_v3_final.json", metrics)

    # Corpus v3 manifest is explicitly a blocked manifest, not an index or authorization.
    corpus_manifest = {"manifest_schema": "phase_u_corpus_v3_manifest_candidate_1.0", "status": "BLOCKED_NOT_BUILT",
                       "formal_corpus_created": False, "index_files_created": False,
                       "admitted_source_allowlist": [{"source_id": "DGBAS-79395-2020", "source_sha256": "31c4cdb6fc3cdcd58abc4a5ba8a1cde908f1ca12f9f338fb39da4d4bf494dd31",
                                                       "admission_status": "admitted_scope_limited", "scope": "2020 descriptive Fact using original statistical region/category/value only", "corpus_inclusion_status": "not_ingested"}],
                       "proposed_sources_not_included": [{"source_id": r.get("source_id"), "title": r.get("title"), "path": r.get("original_path"), "status": r.get("new_corpus_admission_decision")}
                                                          for r in matrix if r.get("new_corpus_admission_decision") not in {"already_admitted_scope_limited"}],
                       "chunk_count": 0, "embedding_count": 0, "bm25_index": None, "vector_index": None,
                       "excluded_inputs": ["fish test workbooks", "question bank", "reference answers", "rubrics", "Selection/Holdout", "generation logs", "evaluation reports"],
                       "blockers": baseline["blockers"]}
    dump_json(OUT / "corpus_v3_manifest.json", corpus_manifest)

    # Source coverage projection: textual findings vs admitted formal evidence are separate.
    total_by_species = Counter(x.get("species") for x in phase_t_elig)
    category_counts = Counter(x.get("category") for x in phase_t_elig)
    readiness = {"design": "Phase U: do not infer admission or applicability from filenames/keyword hits",
                 "gate_status": "NO_GO_SOURCE_ADMISSION_AND_CORPUS_BUILD",
                 "phase_t_180": {"eligible": sum(bool(x.get("benchmark_eligible_v3")) for x in phase_t_elig), "questions": len(phase_t_elig),
                                 "top5_candidate_count_distribution": dict(Counter(x.get("reranked_top5_count") for x in phase_t_elig))},
                 "new_phase_u_corpus": {"built": False, "chunks": 0, "retrievals_executed": 0, "generations_executed": 0},
                 "species_candidate_inventory_count": {x["species"]: x["candidate_source_records"] for x in species_rows},
                 "species_verified_admitted_technical_sources": {sp: 0 for sp in SPECIES},
                 "category_question_counts": dict(category_counts),
                 "reason": "Professional local documents exist, but source authority/version/use scope and corpus admission are not established for the bulk of them; DGBAS remains narrowly admitted and cannot substantiate husbandry answers."}
    dump_json(OUT / "rag_evaluation_readiness.json", readiness)

    # Detailed compatibility and operational validation status.
    validation = {"phase_u_source_inventory": {"source_files_discovered": len(sources), "unique_sha256_count": len(hash_paths),
                                                  "duplicate_hash_groups": sum(1 for v in hash_paths.values() if len(v) > 1),
                                                  "directory_walk_errors": walk_errors},
                  "source_admission": {"newly_admitted_sources": 0, "dgbas_2020_existing_admission_preserved": True},
                  "corpus_v3": {"built": False, "reason": "owner admission decisions and sufficient specialist coverage missing"},
                  "retrieval": {"phase_u_fresh_retrieval_count": 0, "historical_phase_t_rows": len(phase_t_retrieval), "historical_not_relabelled": True},
                  "generation": {"phase_u_generator_rows": len(t_gen), "new_generator_calls": 0},
                  "formal_model_scoring": False, "winner": None}
    dump_json(OUT / "phase_u_validation_status.json", validation)

    print(json.dumps({"sources": len(sources), "unique_hashes": len(hash_paths),
                      "duplicate_groups": sum(1 for v in hash_paths.values() if len(v) > 1),
                      "walk_errors": walk_errors, "frozen_rows": len(frozen), "frozen_counts": dict(frozen_counts),
                      "sqlite_matches": frozen_report.get("protected_sqlite_matches"),
                      "species_candidate_counts": {x["species"]: x["candidate_source_records"] for x in species_rows},
                      "phase_t_eligibility": dict(statuses), "phase_t_retrieval": dict(retrieval_counts)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
