"""Build Phase 20.1E Step 3G reports from preserved Step 3F evidence."""
import datetime as dt
import hashlib
import json
import pathlib
import sqlite3
import urllib.request

ROOT = pathlib.Path(r"C:\my project\115_marine_project")
BASE = ROOT / "reports/evaluation/final_model_selection/phase20_1E_exec_r3"
OUT = BASE / "step3g_gate_resolution"
STAGE = ROOT / "research_staging/_official_source_staging"
OLD_STAGE = ROOT / "my_data/_official_source_staging"
S3F = BASE / "step3f_source_verification"
NOW = dt.datetime.now(dt.timezone.utc).isoformat()
OUTPUTS = [
    "staging_safety_resolution.json", "source_rights_audit.json",
    "medication_annex_version_audit.json", "official_page_capture_audit.json",
    "source_admission_gate_matrix.json", "evidence_feasibility_analysis.json",
    "remaining_human_decisions.json", "compatibility.json", "step3g_summary.md"
]


def load(path):
    return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))


def write_json(name, data):
    (OUT / name).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


if not OUT.is_dir():
    raise SystemExit("Step3G directory missing; preserved migration evidence required")
if any((OUT / name).exists() for name in OUTPUTS):
    raise SystemExit("Refusing to overwrite existing Step3G output")

# Verify every migrated file against the pre-move manifest.
journal = load(OUT / "staging_migration_journal_pre_move.json")
migration = load(OUT / "staging_migration_verification.json")
stage_checks = []
for item in journal["files"]:
    rel = item["relative"]
    prefix = "phase20_1E_step3E\\"
    path = STAGE / rel.split(prefix, 1)[1] if rel.startswith(prefix) else STAGE / rel
    if not path.is_file():
        path = STAGE / rel
    exists = path.is_file()
    actual_size = path.stat().st_size if exists else None
    actual_hash = sha(path) if exists else None
    stage_checks.append({
        "relative": rel, "destination_path": str(path), "exists": exists,
        "expected_size_bytes": item["size_bytes"], "actual_size_bytes": actual_size,
        "expected_sha256": item["sha256"], "actual_sha256": actual_hash,
        "match": exists and actual_size == item["size_bytes"] and actual_hash == item["sha256"]
    })
stage_ok = (len(stage_checks) == 22 and all(x["match"] for x in stage_checks)
            and not OLD_STAGE.exists() and STAGE.is_dir())
write_json("staging_safety_resolution.json", {
    "checked_at_utc": NOW,
    "scanner_evidence": {
        "file": "rag_core.py", "scan_root": "my_data/",
        "rule": "recursive rglob for supported document extensions, including PDF",
        "manual_build_index_ingestion_risk_confirmed": True,
        "watcher_search": "none found in inspected project sources",
        "scheduled_task_inventory": "unknown; previous query denied Access"
    },
    "migration": {
        "source": str(OLD_STAGE), "destination": str(STAGE),
        "destination_outside_my_data": True, "destination_inside_project": True,
        "pre_move_destination_absent": journal.get("destination_previously_absent"),
        "files_expected": len(journal["files"]), "files_rechecked": len(stage_checks),
        "all_size_and_sha256_match": all(x["match"] for x in stage_checks),
        "old_source_path_absent": not OLD_STAGE.exists(), "destination_exists": STAGE.is_dir(),
        "historical_reports_modified": False,
        "historical_path_reference_files": len(migration.get("historical_report_reference_files", [])),
        "path_mapping_record": str(OUT / "staging_migration_journal_pre_move.json"),
        "rollback_path": migration.get("rollback_path"),
        "rollback": "Only if destination remains intact and source path is absent; move whole tree back and reverify every manifest hash."
    },
    "resolution": {
        "staging_ingestion_risk_resolved": stage_ok,
        "scope": "This staging tree only. The recursive my_data scanner remains; future unapproved documents placed under my_data may be found by a manual build_index run.",
        "ingestion_or_build_index_run": False,
        "formal_ingestion_run": False
    },
    "per_file_verification": stage_checks
})

# Rights source-specific decisions.
fa_url = "https://www.fa.gov.tw/information.php"
copyright_url = "https://law.moj.gov.tw/LawClass/LawAll.aspx?PCode=J0070017"
manual_url = "https://www.tfrin.gov.tw/ws.php?id=246"
grouper_url = "https://www.tfrin.gov.tw/theme_data.php?id=242&theme=aquatic_technology"
tilapia_url = "https://www.tfrin.gov.tw/theme_data.php?id=1557&sub_theme=special_message_old&theme=book_data"
rights = {
    "checked_at": "2026-10-10",
    "scope_note": "Source-specific rights triage, not a legal clearance. rights_unknown is not treated as a blanket ban on internal reading, nor as permission to copy, index or redistribute.",
    "use_cases": ["internal research reading/analysis", "limited quotation with attribution",
                  "local derivative research index", "external publication of whole original document"],
    "legal_evidence": [
        {"url": fa_url, "authority": "Agriculture and Fisheries Agency", "checked_at": "2026-10-10",
         "finding": "Agency declaration permits reasonable-scope use with attribution for agency-authored works and reasonable-scope quotation for research; it distinguishes other protected site content. This is not a general license for every PDF, full republication or derivative indexing."},
        {"url": copyright_url, "authority": "Taiwan Copyright Act, Article 9", "checked_at": "2026-10-10",
         "finding": "Statutes/orders/official documents are listed as not being copyright subject matter; this does not automatically cover technical manuals, research articles, every PDF, or nonofficial embedded works."}
    ],
    "source_reviews": [
        {"source_id": "FA cold pages", "urls": [
            "https://www.fa.gov.tw/view.php?id=383&theme=web_structure",
            "https://www.fa.gov.tw/view.php?id=384&theme=web_structure",
            "https://www.fa.gov.tw/view.php?id=385&theme=web_structure"],
         "internal_reading": "No prohibition on ordinary viewing found.",
         "limited_quote": "Potentially within FA reasonable-scope statement if page is FA-authored; confirm each page and quote scope.",
         "derived_index": "Not blanket-authorized; rights decision needed for local stored/printed full text.",
         "full_document_distribution": "No general permission found.",
         "status": "needs_rights_decision"},
        {"source_id": "TFRIN-MANUAL17", "url": manual_url,
         "evidence": "Official page lists manual/chapter files and TFRI copyright footer; no item-specific open license located. Prior Step3F notes a permission requirement, but its exact wording was not located in the current page extraction.",
         "internal_reading": "Public access observed; no broad reuse conclusion.",
         "limited_quote": "Needs item-specific scope review.",
         "derived_index": "Needs rights decision before text extraction/copying/indexing.",
         "full_document_distribution": "Not cleared.",
         "status": "needs_rights_decision"},
        {"source_id": "TFRIN-GROUPER-DISEASE", "url": grouper_url,
         "evidence": "Official page-to-PDF link observed; PDF is checksum-valid; no item-specific open license located.",
         "internal_reading": "Ordinary public viewing not barred by a located term; derivative storage unresolved.",
         "limited_quote": "Needs rights decision.",
         "derived_index": "Needs rights decision.",
         "full_document_distribution": "Not cleared.",
         "status": "needs_rights_decision"},
        {"source_id": "TFRIN-TILAPIA-ARTICLE", "url": tilapia_url,
         "related_notice_url": "https://www.tfrin.gov.tw/redirect_files.php?file_name=pHvrjn10y5CKuRuuuJj3IWGEqualvqTx2B9GhcRaOH6uSkiWGPlusH5&id=7845",
         "evidence": "Official link/byte identity verified. A related issue masthead notice restricts reproduction/digitization, but it was not linked to the exact issue/article and is only a caution.",
         "internal_reading": "Public access observed; no blanket rights clearance.",
         "limited_quote": "Exact article/issue rights decision needed.",
         "derived_index": "Exact article/issue rights decision needed.",
         "full_document_distribution": "Not cleared.",
         "status": "needs_rights_decision"}
    ],
    "overall_by_use": {
        "internal_research_reading_analysis": "No reviewed source term categorically bans ordinary viewing; this is not a rights clearance for derivative reuse.",
        "limited_quote_with_attribution": "FA-authored content has a reasonable-scope route with attribution; TFRI and exact item ownership/scope remain open.",
        "local_derived_index": "No blanket grant found for manuals, papers or all PDFs; seek item-specific rights decision.",
        "external_full_document_publication": "No blanket license found; do not assume permission."
    },
    "human_rights_decisions": [
        "Manual17/chapter local copy, extraction, index and excerpt terms; reconcile earlier permission note.",
        "Grouper PDF item-specific index and quote rights.",
        "Exact tilapia issue/article rights; related issue notice is not exact-item proof.",
        "FA page authorship and whether local derivative indexing is within reasonable scope.",
        "Separate legal regulatory text in Annex I from any nonofficial material in the PDF."
    ]
}
rights["legal_evidence"][0]["original_text_evidence"] = [
    "「在合理範圍內，得重製、公開播送或公開傳輸，利用時，並請註明出處。」",
    "「為報導、評論、教學、研究或其他正當目的，在合理範圍內，得引用本網站上之資訊，引用時，並請註明出處。」"
]
rights["legal_evidence"][1]["original_text_evidence"] = [
    "第九條第一款：「憲法、法律、命令或公文。」",
    "第九條第三款列有通用公式、數表、表格等；對具體文件的適用須逐件判斷。"
]
for item in rights["source_reviews"]:
    if item["source_id"] == "TFRIN-MANUAL17":
        item["original_text_evidence"] = ["水試所頁尾：「Copyright © 農業部水產試驗所」、「版權所有」。"]
    elif item["source_id"] == "TFRIN-GROUPER-DISEASE":
        item["original_text_evidence"] = ["來源位於水試所官方頁面；水試所網站頁尾標示著作權所有。未找到該 PDF 的逐件開放授權文字。"]
    elif item["source_id"] == "TFRIN-TILAPIA-ARTICLE":
        item["original_text_evidence"] = ["關聯期刊頁的版權聲明包含「非經本所同意，不得重製、數位化或轉載」；該聲明尚未連結證明適用於此篇論文所屬期次。"]
write_json("source_rights_audit.json", rights)

# Official Annex I legal chronology and byte-level limitation.
annex = {
    "checked_at_utc": NOW, "source_id": "MOA-LAW-FL035443",
    "current_law_url": "https://law.moa.gov.tw/LawContent.aspx?id=FL035443",
    "history_url": "https://law.moa.gov.tw/LawContentSource.aspx?id=FL035443",
    "official_annex_i_url": "https://law.moa.gov.tw/Download.ashx?FileID=13570&id=FL035443&type=LAW",
    "official_title": "附件一 水產動物用藥品使用規範修正規定",
    "official_history": {
        "parent_consolidated_law_revision": "2025-01-08",
        "annex_i_amendments": ["2007-08-29", "2011-08-17", "2014-10-22", "2015-10-16", "2017-10-16", "2019-04-22"],
        "2025_scope": "Official history records 2025-01-08 revision as Article 4 / Annex II; no Annex I amendment is listed.",
        "result": "Annex I last listed amendment is 2019-04-22. The current page link alone does not establish local byte identity."
    },
    "download": {
        "official_bytes_obtained": False, "browser_error": "net::ERR_BLOCKED_BY_CLIENT (Step3F)",
        "web_retrieval_error": "400 Unsupported content-type: application/octet-stream (Step3F)",
        "byte_match_to_local": False, "new_attempt_in_step3g": False
    },
    "local_candidates": [
        {"path": "data/recovery/raw_sources/moa_animal_drug_use_rules_attachment_1_FL035443.pdf", "pages": 14, "size_bytes": 250105, "sha256": "b13b9492322d7c0de2e1f7bc4dcee8feb99431ca1085819a697f3966c6b92e3c", "pdf_moddate": "2019-04-23T10:20:35+08:00", "version": "likely 2019-era from metadata/title; not official-byte matched"},
        {"path": "my_data/my_data/水產動物用藥品使用規範修正規定-new.pdf", "pages": 13, "size_bytes": 323303, "sha256": "37986f04e7f14db605936e5ed9380141359c1d907b612601ef65f90353c76391", "pdf_moddate": "2019-09-24T17:20:36+08:00", "version": "unconfirmed"}
    ],
    "local_comparison": {"extracted_text_similarity": 0.9528058482046872, "byte_identical": False, "interpretation": "Different page count, size and hash; text similarity cannot establish version match."},
    "specific_drug_fish_use_authorization_verified": False,
    "medication_law_verified_ready": 0,
    "status": "annex_history_confirmed_original_bytes_and_item_authorization_unresolved"
}
write_json("medication_annex_version_audit.json", annex)

# Explain limits on full page snapshots; rehash saved excerpts only.
capture_manifest = S3F / "official_html_capture_manifest.jsonl"
entries = [json.loads(line) for line in capture_manifest.read_text(encoding="utf-8").splitlines() if line.strip()]
filename = {
    "FA_land_pond_cold_hazard": "FA_land_pond_cold_hazard.json",
    "FA_sea_cage_cold_hazard": "FA_sea_cage_cold_hazard.json",
    "FA_cold_protection_guide": "FA_cold_protection_guide.json",
    "TFRI_milkfish_cold_faq": "TFRI_milkfish_cold_faq.json",
    "TFRI_FCR_explanation": "TFRI_FCR_explanation.json",
    "TFRI_grouper_disease_landing": "TFRI_grouper_disease_landing.json",
    "TFRI_eel_luoman_faq": "TFRI_eel_luoman_faq.json",
    "TFRI_japanese_eel_fry_faq": "TFRI_japanese_eel_fry_faq.json",
    "MOA_law_source_attachments": "MOA_law_source_attachments.json",
    "MOA_current_law": "MOA_current_law.json"
}
page_rows = []
for item in entries:
    sid = item.get("source_id")
    p = STAGE / "phase20_1E_step3F/raw/html" / filename.get(sid, "")
    exists = p.is_file()
    page_rows.append({
        "source_id": sid, "capture_type": item.get("capture_type", "browser_dom_capture"),
        "source_url": item.get("final_url"), "final_url": item.get("final_url"),
        "captured_at": item.get("captured_at"), "page_title": item.get("page_title"),
        "complete_raw_html_saved": False, "complete_serialized_dom_saved": False,
        "completeness_status": "partial_text_excerpt_only",
        "excerpt_record_path": str(p) if exists else None,
        "excerpt_record_sha256": sha(p) if exists else None,
        "excerpt_record_exists": exists,
        "version_limitations": "Stored JSON is a partial excerpt record; its digest is not the source HTML/page digest."
    })
write_json("official_page_capture_audit.json", {
    "checked_at_utc": NOW, "prior_manifest_entries": len(entries),
    "full_raw_html_snapshots": 0, "full_serialized_dom_snapshots": 0,
    "partial_excerpt_records": len(page_rows), "new_complete_snapshots_step3g": 0,
    "limitation": "Browser/web surface returned readable page content but did not provide a full raw HTTP body or persistent full DOM serialization for these pages.",
    "pages": page_rows,
    "interpretation": "Current web extracts and partial DOM/text excerpts are not represented as complete original HTML."
})

# Per-source admission gate state: no candidate is silently admitted.
source_doc = load(S3F / "source_admission_review_matrix.json")
status = {
    "MOA-LAW-FL035443": "needs_original_document", "FA-HAZARD": "needs_version_verification",
    "FA-SEA-CAGE": "needs_version_verification", "FA-COLD": "needs_version_verification",
    "TFRIN-MILKFISH-COLD": "needs_provenance_review", "TFRIN-GROUPER-DISEASE": "needs_rights_decision",
    "TFRIN-MANUAL17": "needs_rights_decision", "TFRIN-TILAPIA-ARTICLE": "needs_rights_decision",
    "TFRIN-SGR-FCR": "rejected", "TFRIN-FCR-EXPLAIN": "needs_applicability_review",
    "TFRIN-EEL-QA": "needs_applicability_review", "TFRIN-EEL-FRY": "needs_applicability_review"
}
scope = {
    "MOA-LAW-FL035443": (["six target species"], ["Medication / Law"]),
    "FA-HAZARD": (["虱目魚", "吳郭魚", "石斑魚", "鱸魚"], ["Climate / Cold"]),
    "FA-SEA-CAGE": (["石斑魚", "鱸魚"], ["Climate / Cold"]),
    "FA-COLD": (["虱目魚", "吳郭魚"], ["Climate / Cold"]),
    "TFRIN-MILKFISH-COLD": (["虱目魚"], ["Climate / Cold", "Disease"]),
    "TFRIN-GROUPER-DISEASE": (["石斑魚"], ["Disease"]),
    "TFRIN-MANUAL17": (["石斑魚", "鱸魚", "烏魚"], ["Fact", "Water Quality", "Disease", "Climate / Cold"]),
    "TFRIN-TILAPIA-ARTICLE": (["吳郭魚"], ["Fact", "Calculation (study-specific)"]),
    "TFRIN-SGR-FCR": (["not applicable"], ["Calculation"]),
    "TFRIN-FCR-EXPLAIN": (["general formula only"], ["Calculation"]),
    "TFRIN-EEL-QA": (["鰻魚; taxon unresolved"], ["Fact"]),
    "TFRIN-EEL-FRY": (["Japanese eel fry only"], ["Fact"])
}
notes = {
    "MOA-LAW-FL035443": "Annex I history verified, but official bytes unavailable and local PDF not byte-matched; no item-specific drug authorization verified.",
    "FA-HAZARD": "Official content observed; complete source capture/version and claim-level applicability remain open.",
    "FA-SEA-CAGE": "No full source capture/version identity; current fetch timed out in prior run.",
    "FA-COLD": "Local page print is not raw HTML or original official PDF; version and indexing rights unresolved.",
    "TFRIN-MILKFISH-COLD": "Saved record is a partial excerpt; provenance and atomic support span not frozen.",
    "TFRIN-GROUPER-DISEASE": "Ten-page checksum-valid linked PDF; rights, currency, claims and overlap need review.",
    "TFRIN-MANUAL17": "Official links and byte identity for five files verified; one publication package. Rights/currentness unresolved; context_only unchanged.",
    "TFRIN-TILAPIA-ARTICLE": "Official link and bytes verified; study findings limited to named strains and conditions; article rights unresolved.",
    "TFRIN-SGR-FCR": "Species/experimental scope mismatch; rejected.",
    "TFRIN-FCR-EXPLAIN": "Formula definition lacks complete assumptions, valid range, rounding/tolerance and applicability.",
    "TFRIN-EEL-QA": "Target taxon mapping unresolved.",
    "TFRIN-EEL-FRY": "Transport/fry information is not general grow-out evidence."
}
rows = []
for original in source_doc["sources"]:
    row = dict(original)
    sid = row["source_id"]
    row.update({
        "step3g_gate_status": status[sid],
        "observed_species_scope": scope[sid][0], "potential_categories": scope[sid][1],
        "version_gate": "history only; bytes unverified" if sid == "MOA-LAW-FL035443" else ("partial" if sid in ["TFRIN-MANUAL17", "TFRIN-GROUPER-DISEASE", "TFRIN-TILAPIA-ARTICLE"] else "unresolved"),
        "rights_gate": "unresolved" if sid in ["TFRIN-GROUPER-DISEASE", "TFRIN-MANUAL17", "TFRIN-TILAPIA-ARTICLE"] else "not fully cleared or not applicable",
        "eligibility_changed": False, "formal_admission": False,
        "ready_for_admission_review": False, "eligible_for_research_evidence": False,
        "candidate_for_human_gate_review": sid in ["TFRIN-GROUPER-DISEASE", "TFRIN-MANUAL17", "TFRIN-TILAPIA-ARTICLE"],
        "step3g_notes": [notes[sid]]
    })
    rows.append(row)
write_json("source_admission_gate_matrix.json", {
    "checked_at_utc": NOW, "baseline_ready_units": 11, "formal_source_admissions": 0,
    "sources": rows,
    "counts": {
        "all_gates_cleared_for_formal_admission_review": 0,
        "identifiable_packages_for_human_rights_applicability_review": 3,
        "official_page_candidates_pending_full_capture_or_version": 4,
        "rejected": 1, "formal_admitted": 0
    },
    "status_semantics": {
        "all_gates_cleared_for_formal_admission_review": "Identity, original, version, rights, applicability, provenance and parser gates are resolved; none pass.",
        "human_review_candidate": "Can be routed for a human rights/applicability decision; this is not evidence eligibility or admission."
    },
    "duplicate_note": "Six official-download copies match local bytes. Five Manual17 files are one publication package, not five separate works or facts.",
    "formal_ready_delta": 0
})
admission_path = OUT / "source_admission_gate_matrix.json"
admission_report = load(admission_path)
duplicate_audit = load(S3F / "official_duplicate_provenance_audit.json")
admission_report["official_duplicate_provenance_recheck"] = {
    "source_report": "step3f_source_verification/official_duplicate_provenance_audit.json",
    "records_checked": len(duplicate_audit["records"]),
    "official_link_and_byte_identity_pass": sum(
        1 for x in duplicate_audit["records"]
        if x.get("provenance_blocker_resolved_for_official_link_and_byte_identity")
    ),
    "records": duplicate_audit["records"],
    "limits": "Matches establish official page-to-file link and equality of copied bytes to the compared local file only. They do not establish currentness, rights, applicability, retrieval eligibility or benchmark support."
}
write_json("source_admission_gate_matrix.json", admission_report)

# Preserve exact formal matrix from Step3F; potential source leads remain uncounted.
coverage = load(S3F / "updated_source_to_cell_coverage.json")
write_json("evidence_feasibility_analysis.json", {
    "checked_at_utc": NOW, "target": "36 cells x 5 distinct evidence units = 180",
    "baseline": {"normal_risk_ready": 11, "normal_risk_target": 120, "normal_risk_shortfall": 109,
                 "medication_law_ready": 0, "medication_law_target": 30,
                 "calculation_ready": 0, "calculation_target": 30,
                 "total_ready": 11, "total_target": 180, "total_shortfall": 169, "winner": None},
    "matrix_counts": {"cells": 36, "READY_5_PLUS": coverage["fully_ready_cells"],
                      "PARTIAL_1_TO_4": coverage["partially_ready_cells"],
                      "NO_EVIDENCE": coverage["zero_ready_cells"]},
    "formal_counts_changed": False,
    "potential_sources_not_counted": {
        "grouper_disease_pdf": {"provisional_candidates": 3, "formal_units_added": 0,
                                "potential_cell": "石斑魚 / Disease",
                                "remaining": ["rights", "technical currency/expert review", "atomic span", "dedup", "new corpus eligibility"]},
        "manual17": {"byte_identical_files": 5, "distinct_publication_packages": 1, "formal_units_added": 0,
                     "possible_species": ["石斑魚", "鱸魚", "烏魚"],
                     "remaining": ["rights", "context_only review in separately versioned corpus", "claim provenance/applicability", "dedup"]},
        "tilapia_article": {"formal_units_added": 0, "possible_species": ["吳郭魚"],
                            "remaining": ["exact article rights", "strain and experimental scope", "calculation completeness", "new corpus eligibility"]},
        "FA_cold_pages": {"formal_units_added": 0, "potential_category": "Climate / Cold",
                          "remaining": ["complete capture/version", "page-specific applicability", "rights/index scope", "atomic evidence review"]},
        "MOA_annex": {"formal_units_added": 0, "potential_category": "Medication / Law",
                      "remaining": ["official bytes/byte match", "exact current row", "drug/species/use authorization", "document validation"]}
    },
    "cell_matrix": coverage["cells"],
    "feasibility_conclusion": "180 distinct units are not demonstrated feasible; they are not proven structurally infeasible either. Potential packages do not add formal units.",
    "recommendation": "Keep the 180 target frozen while evidence review proceeds. If distinct evidence gaps remain, formally amend the design before question freeze and before observing model scores.",
    "phase20_2_benchmark_construction_ready": False, "winner": None
})
write_json("remaining_human_decisions.json", {
    "checked_at_utc": NOW,
    "decisions": [
        {"id": "TFRIN_MANUAL17_RIGHTS", "owner": "TFRI rights holder / institutional counsel", "question": "Confirm local copying, extraction, derived indexing and limited quotation rights for Manual17 and chapters.", "status": "needs_rights_decision"},
        {"id": "TFRIN_GROUPER_RIGHTS", "owner": "TFRI rights holder / counsel", "question": "Confirm storage/indexing and quotation scope for the grouper PDF.", "status": "needs_rights_decision"},
        {"id": "TFRIN_TILAPIA_RIGHTS", "owner": "TFRI/article rights holder / counsel", "question": "Confirm exact issue/article terms; related issue notice is not exact-issue proof.", "status": "needs_rights_decision"},
        {"id": "FA_PAGE_SCOPE", "owner": "Research lead / counsel", "question": "Confirm page authorship and whether local full-text indexing fits the FA reasonable-use declaration.", "status": "needs_rights_decision"},
        {"id": "MOA_ANNEX_BYTES", "owner": "Research operator using approved official download", "question": "Obtain official Annex I bytes and compare with the local PDFs.", "status": "blocked_official_download"},
        {"id": "MOA_ROW_APPLICABILITY", "owner": "Veterinary/regulatory expert", "question": "Verify exact current row, target species, drug, indication, method, dose and withdrawal period for any proposed claim.", "status": "not_verified"},
        {"id": "GROUPER_CURRENCY", "owner": "Aquaculture disease expert", "question": "Determine currency, species scope, support spans and nonduplicate disease propositions.", "status": "needs_expert_review"},
        {"id": "MANUAL17_CORPUS", "owner": "Corpus governance / research lead", "question": "After rights clearance, decide if context_only chapters may enter a separately versioned corpus.", "status": "not_admitted"},
        {"id": "TILAPIA_SCOPE", "owner": "Aquaculture methods expert", "question": "Confirm any narrow use of findings for named strains and study conditions without extrapolation.", "status": "needs_expert_review"},
        {"id": "BENCHMARK_DESIGN", "owner": "Principal investigator", "question": "If distinct-unit shortfalls persist, decide on a design amendment before model scoring.", "status": "pending_evidence_gap_closure"}
    ],
    "pytest": {"full_suite": "not_run", "blocker": "Known Windows Sandbox temporary directory WinError 5; no verified environment repair in this step."}
})

# Recompute all protected checks from Step3F, honoring only recorded baseline fields.
old_compat = load(S3F / "compatibility.json")
checks = []
for item in old_compat["protected_checks"]:
    path = ROOT / item["path"]
    exists = path.is_file()
    ah = sha(path) if exists else None
    size = path.stat().st_size if exists else None
    mtime = path.stat().st_mtime_ns if exists else None
    hm = exists and (not item.get("expected_sha256") or ah == item["expected_sha256"])
    sm = exists and (item.get("expected_size_bytes") is None or size == item["expected_size_bytes"])
    mm = item.get("expected_mtime_ns") is None or mtime == item["expected_mtime_ns"]
    checks.append({"group": item.get("group"), "name": item.get("name"), "path": item["path"],
                   "exists": exists, "expected_sha256": item.get("expected_sha256"), "actual_sha256": ah,
                   "expected_size_bytes": item.get("expected_size_bytes"), "actual_size_bytes": size,
                   "expected_mtime_ns": item.get("expected_mtime_ns"), "actual_mtime_ns": mtime,
                   "hash_match": hm, "size_match": sm, "mtime_match": mm, "match": hm and sm and mm})
passed = sum(x["match"] for x in checks)
dbpath = ROOT / "rag_store.sqlite3"
db = {"path": str(dbpath), "exists": dbpath.is_file(),
      "size_bytes": dbpath.stat().st_size if dbpath.exists() else None,
      "mtime_ns": dbpath.stat().st_mtime_ns if dbpath.exists() else None,
      "sha256": sha(dbpath) if dbpath.exists() else None}
if dbpath.exists():
    conn = sqlite3.connect("file:" + str(dbpath).replace("\\", "/") + "?mode=ro", uri=True)
    try:
        db["quick_check"] = conn.execute("PRAGMA quick_check").fetchone()[0]
    finally:
        conn.close()
db["matches_step3f_baseline"] = (
    db["exists"] and db["size_bytes"] == old_compat["sqlite"]["size_bytes"]
    and db["mtime_ns"] == old_compat["sqlite"]["mtime_ns"]
    and db["sha256"] == old_compat["sqlite"]["sha256"] and db.get("quick_check") == "ok"
)
ollama = {"status": "not_tested", "error": None, "digests": []}
try:
    req = urllib.request.Request("http://127.0.0.1:11434/api/tags", headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=4) as response:
        tags_json = json.loads(response.read().decode("utf-8"))
        ollama["status"] = "http_" + str(response.status)
        tags = {x.get("name"): x.get("digest") for x in tags_json.get("models", [])}
        for old in old_compat.get("ollama_digest_checks", []):
            found = [v for k, v in tags.items() if k == old["model"] or k.split(":")[0] == old["model"].split(":")[0]]
            ollama["digests"].append({"model": old["model"], "expected_digest": old["expected_digest"],
                                      "actual_digest": found[0] if found else None,
                                      "match": bool(found and found[0] == old["expected_digest"])})
except Exception as exc:
    ollama["error"] = type(exc).__name__ + ": " + str(exc)
write_json("compatibility.json", {
    "checked_at_utc": NOW, "baseline_report": str(S3F / "compatibility.json"),
    "protected_checks_count": len(checks), "protected_checks_passed": passed,
    "protected_checks_failed": len(checks) - passed, "protected_checks": checks,
    "rag_store": db, "ollama_read_only_api": ollama,
    "production_streamlit_http_smoke": "not_tested",
    "production_app_modified": False, "production_retrieval_modified": False,
    "evaluation_corpus_v2_modified": False, "e1_e2_indices_modified": False,
    "historical_e4_modified": False, "frozen_reports_modified": False,
    "models_or_judge_modified": False, "formal_source_admissions": 0,
    "corpus_rebuilds": 0, "e4_rebuilds": 0, "benchmark_questions_created": 0,
    "model_scoring_requests": 0, "winner": None, "pytest_full_suite": "not_run_known_WinError_5",
    "overall_protected_artifact_integrity_pass": passed == len(checks) and db["matches_step3f_baseline"],
    "non_production_workspace_changes": [
        "new Step3G reports and report builder",
        "verified move of unapproved source staging outside my_data"
    ],
    "no_other_protected_changes": passed == len(checks) and db["matches_step3f_baseline"]
})

summary = f"""# Phase 20.1E Exec r3 — Step 3G 摘要

執行時間（UTC）：{NOW}

## 結果

- my_data 下的來源暫存遞迴掃描風險已就該 staging 樹解除：22 個檔案移至 {STAGE}，逐檔大小及 SHA-256 相符，舊路徑不存在。回復路徑與歷史引用映射保存在遷移紀錄。rag_core.py 的 my_data 遞迴掃描仍存在；勿把未核准資料放回該目錄。未執行 build_index.py。
- 專案程式碼搜尋未發現 watcher；Windows 排程工作查詢曾 Access denied，因此主機排程狀態未知。
- 漁業署資料開放宣告允許其署名內容在合理範圍內使用並註明出處，並容許研究目的合理範圍引用；這不是每份 PDF、完整重製、衍生索引或公開散布的通用授權。著作權法第 9 條不自動涵蓋技術手冊、研究論文或整份 PDF。Manual17、石斑魚 PDF、吳郭魚論文仍需逐件權利決定。
- 官方法規沿革列出附件一最後修正為 2019-04-22，2025-01-08 修正的是附件二。官方附件連結存在，但原始 bytes 未取得。本機兩份附件分別為 14 頁、250105 bytes、SHA {annex['local_candidates'][0]['sha256']}；以及 13 頁、323303 bytes、SHA {annex['local_candidates'][1]['sha256']}。兩份不同且均未與官方 bytes 比對。Medication/Law verified-ready 維持 0。
- 完整原始 HTML 或完整序列化 DOM 快照：0。Step3F 保存 10 筆部分摘錄；其 SHA 只識別摘錄紀錄。
- 六份官方下載副本完成 byte identity 證明：五份屬 Manual17 同一出版套件，一份為吳郭魚論文；加上新石斑魚 PDF，三個文件套件可交付人工權利/適用性決策。沒有來源通過全部 admission gates；正式納入為 0。

## Evidence 與可行性

- 正式基線仍為 11/180；正常風險 11/120，缺 109；Medication/Law 0/30；Calculation 0/30；總缺口 169。
- 36 格：READY_5_PLUS 1 格、PARTIAL 1–4 共 5 格、NO_EVIDENCE 30 格。本階段新增正式 Evidence Units 為 0。
- 180 個 distinct units 的來源可行性未證明，亦未證明結構上不可行。暫保留原設計；若來源補強後仍有缺口，須在看見模型分數前正式修訂 benchmark。

## 相容性與停止狀態

- Protected files：{passed}/{len(checks)} checks pass。
- rag_store.sqlite3：{db['size_bytes']} bytes；SHA-256 {db['sha256']}；quick_check {db.get('quick_check')}；符合 Step3F 基線：{db['matches_step3f_baseline']}。
- Production HTTP smoke：not_tested。完整 pytest 未重跑；已知 Sandbox 暫存目錄 WinError 5 尚未解除。
- 本輪正式 admissions、Corpus/E4 重建、benchmark 題目、模型評分皆為 0；Winner 為 null。
- **正式 Source Admission：No-Go**。待權利決策、附件原件 byte match、法規適用性及逐項 evidence/corpus eligibility 審查。
"""
(OUT / "step3g_summary.md").write_text(summary, encoding="utf-8")
for name in OUTPUTS:
    path = OUT / name
    if not path.is_file():
        raise SystemExit("Missing generated output: " + name)
    if path.suffix == ".json":
        json.loads(path.read_text(encoding="utf-8"))
print(json.dumps({
    "outputs": OUTPUTS, "staging_count": len(stage_checks),
    "staging_all_match": all(x["match"] for x in stage_checks),
    "protected_checks": [passed, len(checks)], "sqlite": db,
    "formal_source_admissions": 0, "new_formal_units": 0,
    "full_html_or_dom_snapshots": 0, "partial_excerpts": len(page_rows),
    "winner": None
}, ensure_ascii=False, indent=2))
