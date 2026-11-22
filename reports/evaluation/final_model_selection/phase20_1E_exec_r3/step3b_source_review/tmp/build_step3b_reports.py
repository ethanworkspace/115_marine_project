import hashlib
import json
from collections import Counter
from pathlib import Path

ROOT = Path(r"C:\my project\115_marine_project")
BASE = ROOT / "reports/evaluation/final_model_selection/phase20_1E_exec_r3"
OUT = BASE / "step3b_source_review"
STEP2B = BASE / "step2b_verification_pilot"
STEP3A = BASE / "step3a_targeted_sources"

def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))

def read_jsonl(path):
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]

def write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

def write_jsonl(path, rows):
    path.write_text("".join(json.dumps(x, ensure_ascii=False, sort_keys=True) + "\n" for x in rows), encoding="utf-8")

def sha256(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda: f.read(1024 * 1024), b""):
            h.update(b)
    return h.hexdigest()

OUT.mkdir(parents=True, exist_ok=True)
(OUT / "staging").mkdir(exist_ok=True)

matrix0 = read_json(STEP2B / "pilot_evidence_matrix.json")
units0 = read_jsonl(STEP2B / "promoted_evidence_units.jsonl")
official0 = read_jsonl(STEP3A / "official_source_discovery_registry.jsonl")
local0 = read_jsonl(OUT / "tmp/local_candidate_verification.jsonl")
diagnostics0 = read_json(OUT / "tmp/acquisition_and_temp_diagnostics.json")
test_repro0 = read_json(STEP3A / "test_reproduction_results.json")
test_triage0 = read_json(STEP3A / "test_environment_diagnostics.json")
readiness0 = read_json(STEP2B / "readiness_after_step2b.json")
corpus_path = ROOT / "data/evaluation/corpus_v2.jsonl"
corpus_rows = read_jsonl(corpus_path)
corpus_by_chunk = {x.get("chunk_id"): x for x in corpus_rows}

candidate_context = {
    "targeted_ff8f499834b104e5": {"claim": "愛德華氏病可侵害虱目魚。", "decision": "needs_provenance_review", "why": "PDF/page/span/hash checks pass, and text names milkfish, but the frozen Corpus record is context_only, benchmark_eligible=false and source identity is pending."},
    "targeted_7400f262ec2de577": {"claim": "虱目魚屬不適合冬季養殖的熱帶魚種。", "decision": "needs_provenance_review", "why": "Local one-page candidate and checksum match, but source-version identity remains pending and frozen Corpus role is context_only / benchmark_eligible=false."},
    "targeted_b6635396f8904ce3": {"claim": "研究品系於越冬期的觀察涉及低溫適應性。", "decision": "needs_applicability_review", "why": "PDF/page/span/hash checks pass, but it is an experimental strain study; it does not establish a general tilapia temperature rule. Frozen Corpus role is context_only / benchmark_eligible=false."},
    "targeted_644cdc14755d80c6": {"claim": "石斑魚養殖常見疾病包括白點蟲、弧菌、奴卡氏菌、虹彩病毒及神經壞死病毒。", "decision": "needs_provenance_review", "why": "Official Manual 17 PDF, page 91, chunk provenance and SHA-256 match. The record is context_only / benchmark_eligible=false; reuse/admission rights need review."},
    "targeted_26b2157da6ef077d": {"claim": None, "decision": "rejected", "why": "No exact chunk/document/PDF mapping; keyword co-occurrence is not a supportable evidence candidate."},
    "targeted_2c4900fb18910873": {"claim": "官方附表列有鱸形目相關分類及部分魚名。", "decision": "needs_applicability_review", "why": "Local official annex PDF, page/span and SHA-256 match and the chunk is retrieval eligible. This taxonomy mention does not itself establish a specific medicine authorization; current annex version and item-level scope need review."},
    "targeted_583c210ee8e8ddfd": {"claim": "烏魚養殖常見疾病包括手冊所列疾病。", "decision": "needs_provenance_review", "why": "Official Manual 17 PDF, page 124, chunk provenance and SHA-256 match. Frozen Corpus role is context_only / benchmark_eligible=false; reuse/admission rights need review."},
    "targeted_e2764cb9474564f6": {"claim": "日本鰻養殖資料列有適合生長水溫。", "decision": "needs_provenance_review", "why": "Local PDF/page/span/hash match and the text identifies Anguilla japonica, but source identity is pending; official provenance has not been established."},
}

candidate_reviews = []
for local in local0:
    c = candidate_context[local["candidate_id"]]
    crow = corpus_by_chunk.get(local.get("chunk_id")) if local.get("chunk_id") else None
    candidate_reviews.append({
        "candidate_id": local["candidate_id"], "species": local["species"], "category": local["category"],
        "chunk_id": local.get("chunk_id"), "document_id": local.get("document_id"), "page": local.get("page"),
        "chunk_exists": local["chunk_exists"], "chunk_document_match": local["chunk_document_match"],
        "source_pdf_path": local.get("pdf_path"), "source_pdf_open": local["pdf_open"], "source_pdf_page_count": local.get("pdf_page_count"),
        "source_pdf_sha256": local.get("pdf_sha256"), "source_sha256_matches_expected": local.get("pdf_sha256_match"),
        "corpus_source_checksum_matches_pdf": local.get("corpus_source_checksum_matches_pdf"),
        "support_span_page": local.get("span_page"), "support_span_text_checks": local.get("support_text_checks"),
        "support_span_locatable": local.get("support_text_match"), "source_identity_status": local.get("source_identity_status"),
        "corpus_retrieval_role": crow.get("retrieval_role") if crow else None,
        "corpus_benchmark_eligible": crow.get("benchmark_eligible") if crow else None,
        "corpus_source_verified": crow.get("source_verified") if crow else None,
        "claim_candidate": c["claim"], "duplicate_check_against_step2b_7_units": "no exact duplicate identified; no promotion without all gates" if c["claim"] else "not_applicable_no_claim",
        "review_decision": c["decision"], "blocking_reason": c["why"],
        "silver_gate_pass": False, "human_reviewed": False,
    })
write_jsonl(OUT / "existing_corpus_candidate_review.jsonl", candidate_reviews)
write_jsonl(OUT / "new_existing_corpus_silver_units.jsonl", [])

source_details = {
"FA-COLD": dict(available=True, sha="0cc5f430b6c5f957c1661566122a54d37bf0a8fc6e59d021fe0b627967ac5b3b", local_path="my_data/my_data/養殖漁業防寒須知(農業部漁業署).pdf", pages="candidate local PDF p.1; official page accessed but local PDF-to-current-page identity/version not established", span=False, decision="needs_version_verification", block="Local candidate bytes/hash exist, but not matched to the currently served official source revision; original/version correspondence needs verification."),
"FA-HAZARD": dict(available=False, sha=None, local_path=None, pages=None, span=False, decision="needs_original_document", block="Official page URL was identified, but source page request timed out in this run and no original PDF/HTML bytes are staged."),
"TFRIN-MILKFISH-COLD": dict(available=False, sha=None, local_path=None, pages=None, span=False, decision="needs_original_document", block="Official Q&A page was accessible through the research browser, but no source bytes were locally captured or checksummed."),
"TFRIN-GROUPER-DISEASE": dict(available=False, sha=None, local_path=None, pages="official page links an attached PDF; local original not obtained", span=False, decision="needs_original_document", block="Official source page and an attached PDF were identified; the actual attached file was not downloaded into this review staging area."),
"TFRIN-MANUAL17": dict(available=True, sha="a26364f19971d2c98b37f924e680a4664aa7a9887b195e372f486ca3088aeee9", local_path="my_data/my_data/技術手冊17-漁電共生養殖技術應用手冊(下).pdf", pages="PDF p.91 grouper; p.124 mullet; official page publication 2023-08-31, page modified 2025-12-09", span=True, decision="needs_provenance_review", block="Local PDF hash/pages match, but its frozen chunks are context_only and benchmark-ineligible; official page copyright notice requires permission for reproduction/digitization/reprint, so reuse/admission rights and version linkage need review."),
"TFRIN-TILAPIA-ARTICLE": dict(available=True, sha="5eda6d34414dd477988a042b2f36b1989ccc25bc26a5bc78f4b2283a5afb25b5", local_path="my_data/my_data/水產研究16(2)吳郭魚雜交與自交系的成長比較－快速成長品系之研發.pdf.pdf", pages="local PDF p.2; official catalog metadata confirms article title/date/pages, but bytes not matched to linked original", span=True, decision="needs_original_document", block="A local copy exists and has a checksum, but official catalog-to-local file identity has not been established; the experimental findings cannot be generalized beyond the studied strains/conditions."),
"MOA-LAW-FL035443": dict(available=True, sha="b13b9492322d7c0de2e1f7bc4dcee8feb99431ca1085819a697f3966c6b92e3c", local_path="data/recovery/raw_sources/moa_animal_drug_use_rules_attachment_1_FL035443.pdf", pages="current parent regulation page: Article 3; local 14-page Attachment I, PDF p.1 taxonomy excerpt", span=True, decision="needs_applicability_review", block="Current consolidated parent page states aquaculture drug items, target species, use, method, quantity and withdrawal rules follow Attachment I. The local annex hash is verified, but its bytes are not matched to the current online attachment revision; an item/disease/species/use authorization review is still required."),
"TFRIN-EEL-QA": dict(available=False, sha=None, local_path=None, pages=None, span=False, decision="rejected", block="Official Q&A concerns 鱸鰻, not Japanese eel (Anguilla japonica); species mismatch for the target eel climate/grow-out cell."),
"TFRIN-EEL-FRY": dict(available=False, sha=None, local_path=None, pages=None, span=False, decision="rejected", block="Official Q&A is about Japanese eel fry transport, not climate/cold conditions for aquaculture grow-out."),
"TFRIN-SGR-FCR": dict(available=False, sha=None, local_path=None, pages="official 12-page PDF identified via TFRI; browser text indicates formula discussion around PDF p.2; no local original bytes", span=False, decision="needs_applicability_review", block="Official article is for Japanese silver croaker fry; formulas/conditions are not transferable to the six candidate species without an applicable source. No local source hash or complete benchmark assumptions/tolerances."),
"TFRIN-FCR-EXPLAIN": dict(available=False, sha=None, local_path=None, pages=None, span=False, decision="needs_original_document", block="Official explainer is a high-level FCR definition, but no source bytes captured locally and it does not supply a complete deterministic unit with all input/assumption/range/rounding/tolerance details."),
}

official_reviews=[]
for src in official0:
    d=source_details[src["source_id"]]
    official_reviews.append({
        "source_id":src["source_id"], "source_title":src["official_title"], "issuing_authority":src["issuing_authority"],
        "official_url":src["official_url"], "document_type":src["source_type"], "publication_date":src.get("publication_date"),
        "revision_date":src.get("revision_date"), "effective_date":src.get("effective_date"), "species_scope":src.get("species_scope"),
        "topic_scope":src.get("topic_scope"), "official_identity_verified":True,
        "official_identity_evidence":"Official authority domain/source page metadata reviewed; this verifies publisher/page identity, not the local bytes of an unattached original document.",
        "document_available":d["available"], "document_sha256":d["sha"] if d["available"] else None,
        "local_file_reference":d["local_path"], "relevant_page_or_section":d["pages"],
        "evidence_span_available":d["span"], "evidence_span_scope_note":"Span locator is available only for local candidate copies where noted; it is not a verified external-source span when original/current-version identity is not established.",
        "legal_or_technical_applicability": "requires item-level/legal review" if src["source_id"]=="MOA-LAW-FL035443" else ("scope mismatch" if src["source_id"] in {"TFRIN-EEL-QA","TFRIN-EEL-FRY"} else "not fully established"),
        "review_decision":d["decision"], "blocking_reason":d["block"],
        "online_page_accessed":src["source_id"] in {"FA-COLD","TFRIN-MILKFISH-COLD","TFRIN-MANUAL17","TFRIN-TILAPIA-ARTICLE","MOA-LAW-FL035443","TFRIN-EEL-FRY","TFRIN-SGR-FCR"},
        "retrieval_status_step3a":src.get("retrieval_status"), "newly_downloaded_this_run":False,
    })
write_jsonl(OUT / "official_source_review_registry.jsonl", official_reviews)

manual_queue=[]
for r in official_reviews:
    if r["review_decision"] in {"needs_original_document","needs_version_verification","needs_applicability_review","needs_provenance_review"}:
        manual_queue.append({
            "source_id":r["source_id"], "official_title":r["source_title"], "official_url":r["official_url"],
            "expected_document_type":r["document_type"],
            "required_original_file":"Provide the official original PDF/current attachment or an official source-page snapshot with retrieval date and immutable file hash." if not r["document_available"] else "No second copy requested; manually verify current official version, exact source linkage, rights and applicable scope for the existing local file.",
            "target_species":r["species_scope"], "target_category":r["topic_scope"],
            "download_blocker":"Configured local proxy 127.0.0.1:9 refuses TCP connections (WinError 10061) before TLS/HTTP; no direct bypass attempted." if not r["document_available"] else "Source is already present locally; remaining blocker is source-to-file/current-version or applicability verification.",
            "manual_verification_needed":r["blocking_reason"], "document_sha256":r["document_sha256"],
            "status":"manual_action_required",
        })
write_jsonl(OUT / "manual_source_acquisition_queue.jsonl", manual_queue)

write_json(OUT / "source_acquisition_diagnostics.json", {
    "diagnostics":diagnostics0,
    "interpretation":{"dns":"PASS for tested official hosts.","proxy_tcp":"FAIL before TLS/HTTP: local configured proxy connection refused, WinError 10061.","tls":"not_reached","http":"not_reached; no HTTP status received","official_sites_absent":False,"downloads_attempted_this_run":0,"new_raw_documents_acquired":0,"credentials_recorded":False,"direct_bypass_attempted":False},
})

staged_docs=[]
for r in official_reviews:
    if r["document_available"]:
        staged_docs.append({"source_id":r["source_id"],"local_file_reference":r["local_file_reference"],"sha256":r["document_sha256"],"present_before_step3b":True,"copied_into_isolated_staging":False,"newly_acquired":False,"identity_or_version_status":r["review_decision"],"note":"Pre-existing workspace file; not newly downloaded or copied into this Step 3B staging directory."})
write_json(OUT / "staged_document_manifest.json", {"new_documents_downloaded":0,"new_documents_copied_to_staging":0,"preexisting_local_candidate_files":staged_docs,"staging_directory":"reports/evaluation/final_model_selection/phase20_1E_exec_r3/step3b_source_review/staging/","formal_corpus_admissions":0})

source_decisions=[]
for r in official_reviews:
    source_decisions.append({"item_type":"official_source","item_id":r["source_id"],"decision":r["review_decision"],"formal_admitted":False,"reason":r["blocking_reason"]})
for r in candidate_reviews:
    source_decisions.append({"item_type":"existing_corpus_candidate","item_id":r["candidate_id"],"decision":r["review_decision"],"formal_admitted":False,"reason":r["blocking_reason"]})
write_jsonl(OUT / "source_admission_decisions.jsonl", source_decisions)

write_json(OUT / "medication_law_review.json", {
    "verified_ready_units":0,"target_units":30,
    "current_official_parent_source":"MOA Animal Drug Use Rules, consolidated law page FL035443; revision date 2025-01-08 as shown on the official current page reviewed 2026-10-09.",
    "article_3_effect":"Aquaculture drug item, target species, use, method, quantity and withdrawal requirements refer to Attachment I.",
    "local_attachment":{"available":True,"pages":14,"sha256":"b13b9492322d7c0de2e1f7bc4dcee8feb99431ca1085819a697f3966c6b92e3c","corpus_chunk":"chunk_4dd88188fe6951b9bb22626ad1e20abc","span_page":1,"verified_scope":"taxonomy/listed group excerpt only"},
    "current_attachment_version_matched_to_online_bytes":False,
    "current_effective_status_of_specific_annex_entry": "not_verified at item level",
    "aquaculture_scope": "general law sets the required control dimensions; individual unit still needs exact item, target species, use, disease/indication, route, quantity and withdrawal statement verification",
    "species_specific_scope": "not established for any proposed evidence unit beyond taxonomy names in the local annex excerpt",
    "fish_species_authorizations_inferred":False,"dosage_or_withdrawal_advice_generated":False,
    "decision":"needs_applicability_review","remaining_gates":["obtain/match current official Attachment I bytes and checksum","identify a discrete legal proposition supported by exact provision","verify effective date and applicable species/use","legal/technical reviewer confirms no inference beyond text"],
})

calc_rows=read_jsonl(STEP2B/"calculation_formula_registry_v1.jsonl")
nonempty=[r for r in calc_rows if (r.get("formula") or "").strip()]
formula_counts=Counter((r.get("formula") or "").strip() for r in nonempty)
formula_cues=[{"formula_text":k,"candidate_rows":v,"candidate_species":sorted({r.get("species") for r in nonempty if (r.get("formula") or "").strip()==k and r.get("species")}),"interpretation":"Repeated label/cue, not distinct verified formula units."} for k,v in formula_counts.items()]
write_json(OUT/"calculation_review.json", {
    "candidate_chunk_rows_reviewed":len(calc_rows),"nonempty_formula_cue_rows":len(nonempty),"distinct_formula_text_cues":len(formula_counts),"formula_cues":formula_cues,
    "distinct_verified_formulas":0,"verified_ready_units":0,"target_units":30,
    "formula_source_candidate":"TFRI official study on silver croaker fry has DWG, PWG, SGR and FCR formula descriptions in the browser-readable PDF text, but original bytes/hash are not staged and study species/experimental conditions differ from target benchmark species.",
    "TFRI_FCR_explainer":"High-level concept only; not enough to establish all variable definitions, units, assumptions, range, rounding and tolerance.",
    "step2b_formula_texts":"Four repeated SGR label/cue rows plus one FCR expression cue in the 72-row screening registry; all 72 remain needs_review.",
    "missing_fields":["source-matched original bytes/checksum","complete mathematical expression without OCR ambiguity","variable definitions","input and output units","species/culture applicability","valid range","assumptions","rounding rule","allowed tolerance"],
    "deterministic_reference_implementation":"not_executed; do only after source formula and all domain conditions are verified",
    "candidate_llm_or_judge_used_for_gold":False,"gold_answers_created":0,"decision":"not_verified",
})

write_json(OUT/"test_environment_diagnostics.json", {
    "prior_suite_baseline":{"passed":525,"skipped":6,"failed":22,"errors":4,"reported_collection_errors":9},
    "latest_reproducible_state":{"suite_level_reproduction":"Step 3A repeated the same unchanged suite twice with the same interpreter/pytest and got 525 passed, 6 skipped, 22 failed, 4 errors both times; all failures were tied to sandbox temporary-directory PermissionError, not a demonstrated assertion regression.","individual_failed_test_reproduction_this_step":"not_executed_environment_unchanged","full_suite_rerun_this_step":"not_executed_environment_unchanged"},
    "collection":{"tests_directory_collected":594,"current_collection_errors":7,"root_cause":"Anaconda Python 3.14.6 environment lacks python-docx and PyMuPDF imports; previous full repository collection also had two sandbox-temp path errors."},
    "interpreter_inventory":[
      {"path":"C:\\Users\\ethan\\anaconda3\\python.exe","python":"3.14.6","pytest":"9.0.3","python_docx":False,"pymupdf":False},
      {"path":"C:\\Python314\\python.exe","python":"3.14.7","pytest":False,"python_docx":False,"pymupdf":False},
      {"path":".venv\\Scripts\\python.exe","python":"3.14.7","pytest":False,"python_docx":True,"pymupdf":True},
      {"path":".venv-ragas\\Scripts\\python.exe","python":"3.14.7","pytest":False,"python_docx":False,"pymupdf":False},
      {"path":".venv-reranker\\Scripts\\python.exe","python":"3.14.7","pytest":False,"python_docx":False,"pymupdf":False}
    ],
    "step3b_temp_probe":{"direct_create_write_read_delete_cleanup":"PASS","python_tempfile_temporarydirectory":"FAIL","exception_type":"PermissionError","errno":13,"winerror":5,"implication":"Do not use the inaccessible temp root; no sandbox or ACL change attempted."},
    "dependency_changes":"none","test_code_changes":"none","security_changes":"none","rerun_decision":"No rerun because interpreter/dependency/temp-root conditions have not changed and test temp API remains blocked." ,
    "recommendation":"Provide an approved cleanable temporary root and a single interpreter with the repository test dependencies; then rerun unchanged failed test IDs and collection errors with original assertions.",
})

species=["虱目魚","吳郭魚","石斑魚","鱸魚","烏魚","鰻魚"]
categories=["Fact","Water Quality","Disease","Climate / Cold","Safe Medication / Law","Calculation"]
existing_by_cell=Counter((u["species"],u["category"]) for u in units0)
local_by_cell=Counter((r["species"],r["category"]) for r in candidate_reviews)
status_by_cell={
 (r["species"],r["category"]):r["review_decision"] for r in candidate_reviews
}
matrix_cells=[]
for sp in species:
  for cat in categories:
    base=existing_by_cell[(sp,cat)]
    count=local_by_cell[(sp,cat)]
    status=status_by_cell.get((sp,cat),"no_new_candidate_reviewed")
    if count and status=="needs_provenance_review": detail="candidate has matching local chunk/PDF page/hash, but source verification or frozen eligibility/rights gate blocks promotion"
    elif count and status=="needs_applicability_review": detail="candidate exists but its subject-specific legal/technical applicability is insufficient for an evidence unit"
    elif count and status=="rejected": detail="keyword hit had no exact chunk/document provenance"
    elif count: detail="candidate remains under review; no gate passed for promotion"
    else: detail="no newly reviewed Step3B candidate; prior gap remains"
    matrix_cells.append({"species":sp,"category":cat,"target_count":5,"baseline_ready":base,"new_existing_corpus_silver_ready":0,"new_external_staged_candidates":0,"external_admitted_ready":0,"total_formal_ready":base,"remaining_shortfall":max(5-base,0),"source_review_status":status,"source_gap_classification":detail,"existing_corpus_candidates_reviewed":count,"structurally_infeasible":False})
write_json(OUT/"updated_evidence_matrix.json", {"species_count":6,"category_count":6,"cell_count":36,"candidate_counts_are_not_units":True,"baseline_ready_units_from_step2b":len(units0),"new_existing_corpus_silver_ready":0,"new_external_staged_candidates":0,"external_admitted_ready":0,"total_formal_ready_units":len(units0),"cells":matrix_cells,"summary":{"cells_at_target":sum(c["total_formal_ready"]>=5 for c in matrix_cells),"cells_partial":sum(0<c["total_formal_ready"]<5 for c in matrix_cells),"cells_zero_formal_ready":sum(c["total_formal_ready"]==0 for c in matrix_cells),"total_shortfall_to_5":sum(c["remaining_shortfall"] for c in matrix_cells),"source_reviewed_cells":sum(c["existing_corpus_candidates_reviewed"]>0 for c in matrix_cells)}})

write_json(OUT/"readiness_after_step3b.json", {
    "existing_silver_ready":len(units0),"new_existing_corpus_silver_ready":0,"normal_risk_target":120,"normal_risk_shortfall":113,"normal_evidence_ready":False,
    "medication_law_verified_ready":0,"medication_law_target":30,"high_risk_ready":False,
    "calculation_verified_ready":0,"calculation_target":30,"calculation_ready":False,
    "independent_judge_ready":True,"four_models_ready":True,"strict_matrix_ready":False,"final_corpus_ready":True,"e4_final_ready":True,
    "phase20_2_benchmark_construction_ready":False,"winner":None,"official_sources_registered":len(official0),"new_source_downloads":0,"formal_source_admissions":0,"formal_corpus_rebuilds":0,"formal_e4_rebuilds":0,"benchmark_questions_created":0,"formal_model_scoring":0,
    "reason":"No Step3B candidate passed the frozen corpus eligibility/source-identity gates. The 7 previously verified Silver units remain immutable; official source bytes/current attachment identity and legal applicability remain incomplete.",
})

write_json(OUT/"execution_manifest.json", {
    "phase":"RAG v2 Phase 20.1E Exec r3 Step 3B","execution_id":"phase20_1E_exec_r3_step3b","started_utc":"2026-10-09","workdir":str(ROOT),"report_dir":str(OUT),
    "inputs":{"step2b_existing_silver_ready":7,"normal_target":120,"normal_shortfall":113,"medication_law_verified_ready":0,"calculation_verified_ready":0,"official_sources_registered":11,"source_downloads_baseline":0,"source_admissions_baseline":0,"phase20_2_ready_baseline":False,"winner_baseline":None},
    "scope":"review existing corpus candidates and 11 registered sources; diagnose acquisition blocker; no formal source admission or corpus/index change",
    "actual_counts":{"existing_corpus_candidates_reviewed":len(candidate_reviews),"new_existing_corpus_silver_ready":0,"official_sources_reviewed":len(official_reviews),"new_raw_documents_acquired":0,"formal_admissions":0},
})

compat_prev=read_json(STEP3A/"compatibility.json")
compat={
 "step3a_anchor_recheck":compat_prev["step3a_post_write_anchor_recheck"],
 "protected_file_baseline": {"phase15_20_count":636,"mismatch_count_at_step3a_end":0,"phase20_1_count":35,"mismatch_count_at_step3a_end":0,"step2b_report_rechecks":15,"mismatch_count":0},
 "evaluation_corpus_v2_sha256":"540a7dfa641fdbf9c2246feea75a226ade41a8e85d5c995fa5b3c8514aa03162",
 "historical_e4_manifest_sha256":"80236c7346ac9a4a527fd2fcc596fce951366a169170ac262dabfd4741d56ea6",
 "e1_manifest_sha256":"5122b6ff5c5b684c1a82df3159524c6985e67e6ca81da8ffdb8c928017ce35b5",
 "e2_manifest_sha256":"c07d1c218ab0d3798886db59586aa3e1dd8e6cf83e10a0b65fea2b2dbb3b131f",
 "e2_dense_index_manifest_sha256":"ecf4b2428f229bb32591a4bb66bc0859ff34ee05838e9560480e90db01fe900b",
 "e2_vectors_sha256":"7607c0cbde53c18b80aa4972c4f62d181e8d4596a049c0bd474cfe41db87abc2",
 "e4_ranking_trace_sha256":"9f5285ab64552f98b3b90acdba9ff19cc01c9e1bccb9eb935f145790c265ec9d",
 "e4_reranker_trace_sha256":"a21d830f1886333aa1ddb284264a9306bfde8282eb69a23fd84277a1994f2a57",
 "rag_store_sqlite3":{"size_bytes":54169600,"mtime_utc":"2026-09-11T03:51:29.621136Z","sha256":"d7d06d4d2a57d0a57d05bcb6131ffb24aefb226cbd36349dbc5118d33b11087","opened_read_only":True,"quick_check":"ok"},
 "current_model_digests":{"M1":"755ced02ce7befdb13b7ca74e1e4d08cddba4986afdb63a480f2c93d3140383f","M2":"dae161e27b0e90dd1856c8bb3209201fd6736d8eb66298e75ed87571486f4364","M3":"aab87d0e8a585cc6260d3a448e3f66ff2057d1cd6975c834151deeb1eae94b42","M4":"ff02c3702f322b9e075e9568332d96c0a7028002f1a5a056e0a6784320a4db0b","Independent_Judge":"daf6737417121831e572a9c482e92a221ee0c33537f35f1f857c7b4f7191df55"},
 "production_streamlit_http":"not_run; baseline listener was absent and was not started",
 "protected_artifacts_modified_by_step3b":False,"formal_corpus_or_e4_rebuilds":0,"source_admissions":0,
}
write_json(OUT/"compatibility.json",compat)

summary = f'''# Phase 20.1E Exec r3 — Step 3B Summary\n\n## Outcome\n\nReviewed {len(candidate_reviews)} targeted existing-Corpus candidates and all {len(official_reviews)} registered official sources. No new evidence unit passed the complete frozen eligibility and provenance gates, so the existing 7 Silver units remain unchanged. No source was downloaded, admitted, or copied into formal data; no Corpus or E4 rebuild, question creation, model scoring, or Winner selection occurred.\n\n## Existing Corpus candidates\n\nThe 8 historical zero-candidate cells now have textual candidates in 7 cells. Exact chunk/document/PDF-page/hash checks succeeded for the mapped local candidates; the grouper Medication/Law keyword result has no exact chunk mapping. Two official TFRI Manual 17 disease spans (grouper p.91 and mullet p.124) and the MOA attachment excerpt have verified local provenance. However, the Manual 17 chunks are `context_only` and benchmark-ineligible; the MOA excerpt supports a listed taxonomy scope, not an item-level authorization. Other local candidate copies have pending source identity or scope. New Silver units promoted: 0.\n\n## Official sources and acquisition\n\nAll 11 source entries were reviewed. The configured proxy exists as `http://127.0.0.1:9` with no credentials; DNS resolved for the tested government hosts. TCP connection to the local proxy failed with `ConnectionRefusedError` / WinError 10061, so TLS and HTTP were never reached and no HTTP status was received. No direct proxy bypass was attempted. New source downloads: 0. Local copies already existed for selected candidate sources but were not newly staged. See `official_source_review_registry.jsonl` and `manual_source_acquisition_queue.jsonl`.\n\nThe MOA current law page states that aquaculture drug items, target species and use details are governed by Attachment I, but the local attachment bytes were not matched to the current online revision and no specific medicine authorization was inferred.\n\n## Calculations\n\nAll 72 calculation candidate records remain `needs_review`; the five non-empty formula cues reduce to four repeated SGR labels and one FCR expression cue. No formula was verified, and no Gold answer was created. The TFRI formula paper concerns silver croaker fry, not the six target benchmark species, and its original file was not staged locally.\n\n## Tests and compatibility\n\nThe unchanged suite was not rerun in this Step 3B because the test interpreter/dependency/temp conditions had not changed. Step 3A had reproduced 525 passed, 6 skipped, 22 failed, 4 errors twice; the failures were sandbox temp-directory PermissionError, and no assertion-level regression was established. This Step3B direct write/read/delete temp probe passed, but Python `TemporaryDirectory` failed with PermissionError (WinError 5).\n\nProtected checksums remain at the Step 3A verified baseline: Evaluation Corpus v2, E1/E2, historical E4, model/Judge digests and SQLite. SQLite remains size 54,169,600 bytes, SHA-256 `d7d06d4d…b11087`; no Production service was started.\n\n## Readiness\n\n`normal_evidence_ready=false`; `high_risk_ready=false`; `calculation_ready=false`; `phase20_2_benchmark_construction_ready=false`; Winner remains null. No source yet qualifies as fully ready for formal admission review. Manual 17, MOA Attachment I, and official source-linked documents are review candidates, but rights/version/applicability gates remain open.\n'''
(OUT/"step3b_summary.md").write_text(summary,encoding="utf-8")

# Validate output JSON/JSONL and the requested 36-cell / 11-source invariants.
for p in OUT.glob("*.json"):
    json.loads(p.read_text(encoding="utf-8"))
for p in OUT.glob("*.jsonl"):
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.strip(): json.loads(line)
assert len(read_jsonl(OUT/"official_source_review_registry.jsonl")) == 11
assert len(read_json(OUT/"updated_evidence_matrix.json")["cells"]) == 36
assert len(read_jsonl(OUT/"new_existing_corpus_silver_units.jsonl")) == 0
assert len(read_jsonl(OUT/"source_admission_decisions.jsonl")) == 19
print(json.dumps({"reports_written":sorted(p.name for p in OUT.iterdir() if p.is_file()),"existing_candidates":len(candidate_reviews),"sources_reviewed":len(official_reviews),"new_silver_units":0,"new_source_downloads":0,"matrix_cells":36,"validations":"PASS"},ensure_ascii=True))
