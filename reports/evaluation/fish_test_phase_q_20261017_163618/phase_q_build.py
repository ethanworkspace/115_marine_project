from __future__ import annotations

import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

ROOT = Path(r"C:\my project\115_marine_project")
OUT = ROOT / "reports/evaluation/fish_test_phase_q_20261017_163618"
P = ROOT / "reports/evaluation/fish_test_phase_p_20261017_161822"
RUN = ROOT / "reports/evaluation/fish_test_run_20261012_152244"
PHASE_J = ROOT / "reports/evaluation/fish_test_phase_j_20261015_190617"
PHASE_K = ROOT / "reports/evaluation/fish_test_phase_k_20261016_181425"

PATHS = {
    "questions": RUN / "fish_test_questions_normalized.jsonl",
    "retrieval": P / "retrieval_context_audit_900.jsonl",
    "coverage": P / "question_evidence_coverage_180.jsonl",
    "profiles": ROOT / "reports/evaluation/fish_test_phase_o_ai_adjudication_20261016_211742/question_requirement_profiles.jsonl",
    "corpus_v2": ROOT / "data/evaluation/corpus_v2.jsonl",
    "corpus_v1": ROOT / "data/evaluation/corpus_v1.jsonl",
    "manifest_v3": ROOT / "reports/recovery/document_manifest_v3.jsonl",
    "shadow_chunks": ROOT / "data/shadow/chunks_v3.jsonl",
    "source_spans": ROOT / "data/shadow/source_spans_v3.jsonl",
    "aliases": ROOT / "data/evaluation/source_alias_registry_v3.jsonl",
    "source28": PHASE_K / "source_verification_28_phase_k.jsonl",
    "source28_j": PHASE_J / "source_verification_28.jsonl",
    "protected": P / "frozen_baseline_636_recheck.jsonl",
    "law_excerpt": PHASE_J / "official_law_text_capture_excerpt.txt",
}

SPECIES_NAMES = ["虱目魚", "吳郭魚", "石斑魚", "鱸魚", "烏魚", "鰻魚"]
SPECIES_ALIASES = {
    "虱目魚": ["虱目魚", "milkfish", "Chanos chanos"],
    "吳郭魚": ["吳郭魚", "台灣鯛", "tilapia", "Oreochromis"],
    "石斑魚": ["石斑魚", "grouper", "Epinephelus"],
    "鱸魚": ["鱸魚", "金目鱸", "七星鱸", "seabass", "barramundi", "Lates calcarifer"],
    "烏魚": ["烏魚", "鯔魚", "mullet", "Mugil cephalus"],
    "鰻魚": ["鰻魚", "鰻鱺", "eel", "Anguilla"],
}


def read_jsonl(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8-sig") as f:
        return [json.loads(line) for line in f if line.strip()]


def write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def norm_text(s: str) -> str:
    s = (s or "").replace("\u3000", " ").replace("℃", "°C")
    return re.sub(r"\s+", "", s).lower()


def norm_url(u: str | None) -> str | None:
    if not u:
        return None
    p = urlsplit(u.strip())
    # Keep resource-identifying query parameters (such as id=); remove display-only parameters.
    q = [(k.lower(), v) for k, v in parse_qsl(p.query, keep_blank_values=True)
         if k.lower() not in {"print", "theme", "subtheme", "utm_source", "utm_medium", "utm_campaign"}]
    return urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path.rstrip("/").lower(), urlencode(sorted(q)), ""))


def resolve_path(value: str | None) -> Path | None:
    if not value:
        return None
    raw = Path(value)
    candidates = [raw] if raw.is_absolute() else [ROOT / raw, ROOT / raw.name]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return candidates[0]


def canonical_species_mentions(text: str) -> list[str]:
    found = []
    for species, aliases in SPECIES_ALIASES.items():
        if any(alias.lower() in (text or "").lower() for alias in aliases):
            found.append(species)
    return found


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    questions = read_jsonl(PATHS["questions"])
    contexts = read_jsonl(PATHS["retrieval"])
    coverage = read_jsonl(PATHS["coverage"])
    profiles = read_jsonl(PATHS["profiles"])
    corpus2 = read_jsonl(PATHS["corpus_v2"])
    corpus1 = read_jsonl(PATHS["corpus_v1"])
    manifest = read_jsonl(PATHS["manifest_v3"])
    shadow_chunks = read_jsonl(PATHS["shadow_chunks"])
    source_spans = read_jsonl(PATHS["source_spans"])
    aliases = read_jsonl(PATHS["aliases"])
    ver28 = read_jsonl(PATHS["source28"])
    ver28_j = read_jsonl(PATHS["source28_j"])

    qmap = {x["question_id"]: x for x in questions}
    pmap = {x["question_id"]: x for x in profiles}
    corp2_by_chunk = {x["chunk_id"]: x for x in corpus2}
    manifest_by_doc = defaultdict(list)
    for row in manifest:
        manifest_by_doc[row.get("document_id")].append(row)
    corpus1_by_doc = defaultdict(list)
    for row in corpus1:
        corpus1_by_doc[row.get("document_id")].append(row)
    shadow_by_doc = defaultdict(list)
    for row in shadow_chunks:
        shadow_by_doc[row.get("document_id")].append(row)
    spans_by_doc = defaultdict(list)
    for row in source_spans:
        spans_by_doc[row.get("document_id")].append(row)
    aliases_by_doc = defaultdict(list)
    for row in aliases:
        if row.get("document_id"):
            aliases_by_doc[row["document_id"]].append(row)

    # Fresh, read-only source hash check for the P-era protected manifest. It contains before/after rows;
    # deduplicate by path while retaining a single expected digest per protected path.
    protected_records = read_jsonl(PATHS["protected"])
    expected_by_path: dict[str, str] = {}
    for row in protected_records:
        expected_by_path.setdefault(row["path"], row["expected_sha256"])
    protected_before = {}
    for i, (rel, expected) in enumerate(expected_by_path.items(), 1):
        path = resolve_path(rel)
        actual = sha256_file(path) if path and path.is_file() else None
        protected_before[rel] = {"expected": expected, "actual": actual, "status": "unchanged" if actual == expected else "missing_or_changed"}
        if i % 120 == 0:
            print(f"baseline before: {i}/{len(expected_by_path)}", flush=True)

    # Use manifest-declared file paths only for documents that appear among unresolved Top-5 records.
    pending = [x for x in contexts if not (x.get("source_metadata_verified") and x.get("source_publication_version_verified") and x.get("retrieval_eligible_in_corpus"))]
    file_cache: dict[str, dict] = {}
    source_resolution_rows = []
    for row in pending:
        doc_id = row.get("document_id")
        mrows = manifest_by_doc.get(doc_id, [])
        m = mrows[0] if len(mrows) == 1 else None
        aliases_for_doc = aliases_by_doc.get(doc_id, [])
        local = resolve_path(m.get("file_path")) if m else None
        if doc_id not in file_cache:
            actual = sha256_file(local) if local and local.is_file() else None
            manifest_sha = m.get("checksum") if m else None
            corpus_sha = row.get("source_sha256_registered")
            file_cache[doc_id or "<missing>"] = {
                "manifest_count": len(mrows), "manifest_file_path": m.get("file_path") if m else None,
                "local_file_exists": bool(local and local.is_file()), "local_file_actual_sha256": actual,
                "manifest_sha256": manifest_sha, "corpus_registered_sha256": corpus_sha,
                "actual_matches_manifest": bool(actual and manifest_sha and actual == manifest_sha),
                "actual_matches_corpus": bool(actual and corpus_sha and actual == corpus_sha),
                "manifest_source_id": m.get("source_id") if m else None,
                "manifest_source_url": m.get("source_url") if m else None,
                "manifest_version": m.get("version") if m else None,
                "manifest_publication_date": m.get("publication_date") if m else None,
                "manifest_species": m.get("species") if m else None,
                "manifest_legal_status": m.get("legal_status") if m else None,
            }
        file_info = file_cache[doc_id or "<missing>"]
        v1rows = [v for v in corpus1_by_doc.get(doc_id, []) if v.get("source_checksum") == row.get("source_sha256_registered")]
        v1_urls = sorted({v.get("source_url") for v in v1rows if v.get("source_url")})
        v1_ids = sorted({v.get("source_id") for v in v1rows if v.get("source_id")})
        exact_aliases = [a for a in aliases_for_doc if a.get("mapping_method") == "exact_normalized_url" and a.get("source_verified") is True]
        alias_urls = sorted({a.get("excel_source_url") for a in exact_aliases if a.get("excel_source_url")})
        if file_info["actual_matches_manifest"] and file_info["actual_matches_corpus"]:
            outcome = "SOURCE_BYTES_HASH_MATCHED_METADATA_STILL_PENDING"
        elif file_info["actual_matches_manifest"]:
            outcome = "SOURCE_BYTES_MATCH_MANIFEST_BUT_NOT_CORPUS_CHECKSUM"
        elif file_info["manifest_count"] == 0:
            outcome = "NO_UNAMBIGUOUS_SOURCE_MANIFEST_RECORD"
        elif not file_info["local_file_exists"]:
            outcome = "MANIFEST_PATH_NOT_LOCALLY_AVAILABLE"
        else:
            outcome = "SOURCE_BYTES_HASH_MISMATCH_OR_INCOMPLETE"
        source_resolution_rows.append({
            "question_id": row.get("question_id"), "chunk_id": row.get("chunk_id"), "rank": row.get("rank"),
            "document_id": doc_id, "corpus_source_id": row.get("source_id"), "corpus_source_title": row.get("source_title"),
            "corpus_source_url": row.get("source_url"), "corpus_source_checksum": row.get("source_sha256_registered"),
            "corpus_version": row.get("corpus_version"), "page_or_locator": row.get("page_or_locator"),
            "document_species_metadata": row.get("document_species_metadata"),
            "body_species_mentions": row.get("body_species_mentions"),
            "target_species_mentioned_in_body": row.get("target_species_mentioned_in_body"),
            "metadata_verified_before": row.get("source_metadata_verified"), "version_verified_before": row.get("source_publication_version_verified"),
            "retrieval_eligible_before": row.get("retrieval_eligible_in_corpus"),
            "resolution_outcome": outcome, "local_file_evidence": file_info,
            "same_document_same_checksum_corpus_v1_urls": v1_urls, "same_document_same_checksum_corpus_v1_source_ids": v1_ids,
            "verified_exact_url_alias_candidates": alias_urls,
            "other_alias_candidates": [{"excel_source_id": a.get("excel_source_id"), "excel_source_title": a.get("excel_source_title"),
                                        "excel_source_url": a.get("excel_source_url"), "mapping_confidence": a.get("mapping_confidence"),
                                        "mapping_method": a.get("mapping_method"), "source_verified": a.get("source_verified")} for a in aliases_for_doc],
            "fields_resolved_by_this_audit": ["local file byte identity" if file_info["actual_matches_manifest"] and file_info["actual_matches_corpus"] else "none"],
            "fields_still_unresolved": ["source authority/identity", "publication version/currentness", "species applicability", "usage rights", "designated corpus eligibility"],
            "promotion_applied": False,
        })

    # Audit exactly the 47 title-disagreement registry rows. No title similarity is treated as identity.
    title_mismatches = [a for a in aliases if a.get("document_title") and a.get("excel_source_title") and a.get("document_title") != a.get("excel_source_title")]
    alias_rows = []
    for a in title_mismatches:
        drows = corp2_by_chunk.values()
        d = next((x for x in corpus2 if x.get("document_id") == a.get("document_id")), {})
        eu = a.get("excel_source_url")
        du = d.get("source_url") or (manifest_by_doc.get(a.get("document_id"), [{}])[0].get("source_url") if manifest_by_doc.get(a.get("document_id")) else None)
        method = a.get("mapping_method")
        contradiction = None
        low_eurl = (eu or "").lower()
        low_dtitle = (d.get("source_title") or a.get("document_title") or "").lower()
        low_etitle = (a.get("excel_source_title") or "").lower()
        if "qrybreedpredictreport" in low_eurl and "防寒" in low_dtitle and "放養量" in low_etitle:
            contradiction = "EXPLICIT_FUNCTION_AND_TITLE_CONTRADICTION: stocking-query service was crosswalked to a cold-weather advisory"
        elif "opendata.cwa.gov.tw" in low_eurl and "swagger" in low_eurl and "逐條說明" in low_dtitle:
            contradiction = "EXPLICIT_PUBLISHER_RESOURCE_CONTRADICTION: CWA Open Data API URL was crosswalked to a legal explanatory document"
        same_url = bool(norm_url(eu) and norm_url(eu) == norm_url(du))
        if method == "exact_normalized_url" and a.get("source_verified") is True and same_url:
            status = "TITLE_VARIANT_URL_IDENTITY_CONFIRMED"
        elif contradiction:
            status = "CONFIRMED_CROSSWALK_IDENTITY_ERROR"
        elif method == "strong_lexical_title_match" and a.get("mapping_confidence") in ("high", "medium"):
            status = "TITLE_CANDIDATE_REQUIRES_SOURCE_ORIGINAL_CONFIRMATION"
        else:
            status = "WEAK_OR_UNMAPPED_CROSSWALK_NOT_ACCEPTED"
        alias_rows.append({
            "source_key": a.get("source_key"), "source_workbook": a.get("source_workbook"),
            "excel_source_id": a.get("excel_source_id"), "excel_source_title": a.get("excel_source_title"),
            "excel_source_url": eu, "document_id": a.get("document_id"), "document_title": a.get("document_title"),
            "corpus_source_title": d.get("source_title"), "corpus_source_url": d.get("source_url"),
            "mapping_confidence": a.get("mapping_confidence"), "mapping_method": method,
            "mapping_score": a.get("mapping_score"), "source_verified_registry_flag": a.get("source_verified"),
            "same_canonical_url": same_url,
            "crosswalk_status": status, "contradiction_basis": contradiction,
            "title_difference_alone_proves_error": False, "promoted_or_merged": False,
        })

    # Recheck all 28 Phase K source records against local originals and existing saved evidence.
    jmap = {x.get("question_id"): x for x in ver28_j}
    excerpt = PATHS["law_excerpt"].read_text(encoding="utf-8", errors="replace") if PATHS["law_excerpt"].exists() else ""
    try:
        from pypdf import PdfReader
    except Exception:
        PdfReader = None
    local_doc_cache: dict[str, dict] = {}
    source28_rows = []
    for old in ver28:
        qid = old.get("question_id")
        src = resolve_path(old.get("source_path"))
        src_key = str(src) if src else str(old.get("source_path"))
        if src_key not in local_doc_cache:
            file_exists = bool(src and src.is_file())
            actual_sha = sha256_file(src) if file_exists else None
            page_texts = []
            extraction_method = "not_attempted"
            if file_exists and PdfReader is not None and src.suffix.lower() == ".pdf":
                try:
                    reader = PdfReader(str(src), strict=False)
                    page_texts = [(p.extract_text() or "") for p in reader.pages]
                    extraction_method = "pypdf_text_extraction"
                except Exception as e:
                    extraction_method = f"pdf_extraction_error:{type(e).__name__}:{e}"
            local_doc_cache[src_key] = {"exists": file_exists, "actual_sha256": actual_sha, "page_texts": page_texts,
                                        "page_count": len(page_texts) if page_texts else None, "extraction_method": extraction_method}
        info = local_doc_cache[src_key]
        quote = old.get("exact_quote") or ""
        nq = norm_text(quote)
        page_hits = [i + 1 for i, txt in enumerate(info["page_texts"]) if nq and nq in norm_text(txt)]
        saved_excerpt_match = bool(nq and nq in norm_text(excerpt))
        expected_sha = old.get("source_sha256_expected")
        if expected_sha is None:
            expected_sha = old.get("source_sha256_actual_if_local_copy")
        sha_match = bool(info["actual_sha256"] and expected_sha and info["actual_sha256"] == expected_sha)
        j = jmap.get(qid, {})
        status = old.get("phase_k_support_status") or old.get("answer_support_status")
        source_id = old.get("source_id")
        live_law_page = source_id == "S09"
        source28_rows.append({
            "question_id": qid, "species": old.get("species"), "question_text": old.get("question_text"),
            "candidate_reference_answer": old.get("candidate_reference_answer"), "source_id": source_id,
            "source_url": old.get("source_url"), "source_local_path": old.get("source_path"),
            "source_version_prior": old.get("phase_k_source_version") or old.get("document_version"),
            "expected_source_sha256": expected_sha, "actual_local_source_sha256": info["actual_sha256"],
            "source_file_exists": info["exists"], "source_checksum_recomputed_match": sha_match,
            "local_pdf_extraction_method": info["extraction_method"], "local_pdf_page_count": info["page_count"],
            "exact_quote": quote, "quote_matches_local_pdf": bool(page_hits), "local_pdf_matching_pages": page_hits,
            "quote_matches_saved_official_excerpt": saved_excerpt_match,
            "prior_quote_reproduced_phase_k": old.get("phase_k_exact_quote_reproduced"),
            "prior_support_status": status,
            "updated_support_status": ("DIRECT_SUPPORT_REPRODUCED_LOCATOR_RECHECKED" if status == "DIRECT_SUPPORT_REPRODUCED" and (page_hits or saved_excerpt_match) and sha_match
                                       else "PARTIAL_SUPPORT_REMAINS_LOCATOR_RECHECKED" if status == "PARTIAL_SUPPORT_REMAINS" and (page_hits or saved_excerpt_match) and sha_match
                                       else "PRIOR_SUPPORT_STATUS_RETAINED_SOURCE_RECHECK_INCOMPLETE"),
            "species_applicability_prior": old.get("species_applicability"),
            "retrieval_corpus_admission": old.get("retrieval_corpus_admission"), "human_gold_reviewed": False,
            "live_official_law_page_recheck": ({"checked": True, "url": "https://law.moa.gov.tw/LawContent.aspx?id=FL035443&media=print",
                "page_print_date": "115-09-24", "revision_date": "114-01-08", "article_3_locator": "lines 47-49",
                "current_law_page_matches_prior_revision_date": True, "raw_html_bytes_saved": False,
                "attachment_click_result": "official page links attachment 1; browser retrieval returned unsupported application/octet-stream; local PDF bytes separately checked"} if live_law_page else None),
            "answer_support_change": "no semantic promotion; prior 12 direct / 16 partial classification preserved",
            "limitations": ["source hash establishes local file identity, not answer correctness or rights", "not admitted as designated Corpus evidence", "not Human Gold"],
        })

    # Profiles are structured for downstream use but explicitly provisional; candidate answer cues remain non-gold.
    profile_rows = []
    for q in questions:
        p = pmap.get(q.get("question_id"), {})
        profile_rows.append({
            "question_id": q.get("question_id"), "target_species": q.get("species_chinese"),
            "question_category": q.get("inferred_category"), "category_basis": q.get("category_basis"),
            "question_text": q.get("question_text"), "question_format": q.get("question_format"),
            "required_answer_elements": p.get("required_answer_elements", []),
            "required_values_or_ranges": p.get("required_values_or_ranges", []),
            "required_units": p.get("required_units", []), "required_conditions": p.get("required_conditions", []),
            "applicability_constraints": p.get("applicability_constraints", {}),
            "source_version_requirements": p.get("source_version_requirements"),
            "candidate_reference_answer": q.get("candidate_reference_answer"),
            "candidate_answer_used_as_gold": False,
            "requirement_profile_basis": p.get("requirement_profile_method"),
            "candidate_scoring_cues_status": p.get("candidate_scoring_cues_status"),
            "profile_validation_status": "PROVISIONAL_REQUIREMENT_PROFILE_NOT_HUMAN_OR_SOURCE_GOLD",
            "requires_human_or_source_review": bool(p.get("profile_needs_review")) or p.get("candidate_scoring_cues_status") != "unverified_prompting_cues_only",
        })

    # Exact candidate cues are only search aids. For any apparent candidate, recheck the exact
    # document bytes and the cited PDF page before using SOURCE_VERIFIED_CANDIDATE.
    support_rows = []
    candidate_source_checks: dict[tuple[str, int], dict] = {}
    for row in contexts:
        q = qmap.get(row.get("question_id"), {})
        p = pmap.get(row.get("question_id"), {})
        text = row.get("context_text") or ""
        values = row.get("exact_candidate_value_matches") or []
        elements = row.get("exact_candidate_element_matches") or []
        matches = []
        for cue in list(elements) + list(values):
            cue_text = cue if isinstance(cue, str) else str(cue)
            if cue_text and cue_text in text:
                pos = text.find(cue_text)
                matches.append({"exact_text": cue_text, "chunk_offset_start": pos, "chunk_offset_end": pos + len(cue_text),
                                "locator_scope": "exact match in stored Corpus chunk text; page locator retained separately"})
        manual_review_key = (row.get("question_id"), row.get("rank"))
        manual_review_specs = {
            ("FT-seabass-Q02", 2): {"required_phrase": "金目鱸養殖適溫", "review_note": "question asks the temperature threshold for appetite decline and a disease-risk reminder"},
            ("FT-seabass-Q30", 4): {"required_phrase": "金目鱸養殖適溫", "review_note": "source can only be checked for partial support; it contains no death-time guarantee"},
        }
        manual_spec = manual_review_specs.get(manual_review_key)
        manual_quote = None
        if manual_spec and manual_spec["required_phrase"] in text:
            start = text.find(manual_spec["required_phrase"])
            end = text.find("。", start)
            if end >= 0:
                manual_quote = text[start:end + 1]
                matches.append({"exact_text": manual_quote, "chunk_offset_start": start, "chunk_offset_end": end + 1,
                                "locator_scope": "phase-Q source review candidate; exact source page recheck required"})
        source_verified = bool(row.get("source_metadata_verified") and row.get("source_publication_version_verified") and row.get("retrieval_eligible_in_corpus"))
        conflict = bool(row.get("species_scope_conflict_candidate"))
        locator = row.get("page_or_locator") or {}
        page_no = locator.get("page") if isinstance(locator, dict) else None
        doc_id = row.get("document_id") or ""
        original_check = {"attempted": False, "file_exists": False, "actual_sha256": None,
                          "matches_manifest_and_corpus_checksum": False, "page_text_reproduces_candidate_cue": False,
                          "page_number": page_no, "failure_reason": "no exact candidate cue or no page locator"}
        if matches and page_no and len(manifest_by_doc.get(doc_id, [])) == 1:
            cache_key = (doc_id, int(page_no))
            if cache_key not in candidate_source_checks:
                m = manifest_by_doc[doc_id][0]
                local = resolve_path(m.get("file_path"))
                actual = sha256_file(local) if local and local.is_file() else None
                expected = row.get("source_sha256_registered")
                manifest_sha = m.get("checksum")
                reproduced = False
                page_excerpt = None
                extraction_error = None
                if actual and expected and manifest_sha and actual == expected == manifest_sha and local and local.suffix.lower() == ".pdf" and PdfReader is not None:
                    try:
                        reader = PdfReader(str(local), strict=False)
                        if 1 <= int(page_no) <= len(reader.pages):
                            page_text = reader.pages[int(page_no) - 1].extract_text() or ""
                            reproduced = any(norm_text(mch["exact_text"]) in norm_text(page_text) for mch in matches)
                            if manual_quote and norm_text(manual_quote) in norm_text(page_text):
                                page_excerpt = manual_quote
                    except Exception as e:
                        extraction_error = f"{type(e).__name__}: {e}"
                candidate_source_checks[cache_key] = {
                    "attempted": True, "file_exists": bool(local and local.is_file()), "file_path_from_manifest": m.get("file_path"),
                    "actual_sha256": actual, "manifest_sha256": manifest_sha, "corpus_registered_sha256": expected,
                    "matches_manifest_and_corpus_checksum": bool(actual and expected and manifest_sha and actual == expected == manifest_sha),
                    "page_text_reproduces_candidate_cue": reproduced, "page_number": int(page_no),
                    "exact_source_page_excerpt": page_excerpt,
                    "failure_reason": extraction_error or (None if reproduced else "candidate cue not reproduced in source PDF page"),
                }
            original_check = candidate_source_checks[cache_key]
        if conflict:
            status = "SPECIES_SCOPE_CONFLICT"
        elif not source_verified:
            status = "SOURCE_VERSION_UNVERIFIED"
        elif matches and original_check.get("matches_manifest_and_corpus_checksum") and original_check.get("page_text_reproduces_candidate_cue"):
            status = "SOURCE_VERIFIED_CANDIDATE"
        else:
            status = "INSUFFICIENT_EVIDENCE"
        if (row.get("question_id") == "FT-seabass-Q30" and row.get("rank") == 4 and
                status == "SOURCE_VERIFIED_CANDIDATE"):
            # The source does not state a time-to-death at 21 C; keep only partial evidence status.
            status = "PARTIALLY_SUPPORTED"
        source_verified_candidate = status == "SOURCE_VERIFIED_CANDIDATE"
        manual_supported = (manual_quote is not None and original_check.get("matches_manifest_and_corpus_checksum")
                            and original_check.get("page_text_reproduces_candidate_cue")
                            and status in ("SOURCE_VERIFIED_CANDIDATE", "PARTIALLY_SUPPORTED"))
        if row.get("question_id") == "FT-seabass-Q02" and row.get("rank") == 2 and manual_supported:
            supported_candidate_elements = ["低於23°C時食慾下降", "長期低溫易感染水黴"]
            missing_candidate_elements = []
            unsupported_candidate_answer_claims = ["候選答案提到的二次感染風險未由此原文段落直接支持"]
        elif row.get("question_id") == "FT-seabass-Q30" and row.get("rank") == 4 and manual_supported:
            supported_candidate_elements = ["長期低溫易感染水黴", "需考量低溫影響"]
            missing_candidate_elements = ["21°C下必然死亡的時間", "足以回答問題的明確處置步驟"]
            unsupported_candidate_answer_claims = []
        else:
            supported_candidate_elements = []
            missing_candidate_elements = list(p.get("required_answer_elements", []))
            unsupported_candidate_answer_claims = []
        support_rows.append({
            "question_id": row.get("question_id"), "species": row.get("species"), "question_category": row.get("category"),
            "question_text": row.get("question_text"), "required_answer_elements": p.get("required_answer_elements", []),
            "required_values_or_ranges": p.get("required_values_or_ranges", []), "required_units": p.get("required_units", []),
            "required_conditions": p.get("required_conditions", []), "candidate_cues_unverified": True,
            "chunk_id": row.get("chunk_id"), "rank": row.get("rank"), "source_id": row.get("source_id"),
            "source_title": row.get("source_title"), "source_url": row.get("source_url"),
            "source_version": row.get("source_version_annotation"), "source_sha256": row.get("source_sha256_registered"),
            "source_checksum_rehashed_from_original_this_phase": row.get("source_file_bytes_rehashed_this_phase"),
            "page_or_locator": row.get("page_or_locator"), "source_spans": (row.get("page_or_locator") or {}).get("source_spans", []),
            "original_context_text": text, "context_text_sha256": row.get("context_text_sha256"),
            "context_text_sha256_recomputed": sha256_text(text),
            "context_hash_matches_recorded": bool(text and sha256_text(text) == row.get("context_text_sha256")),
            "context_hash_matches_corpus_as_recorded_in_phase_p": row.get("context_checksum_matches_corpus"),
            "exact_candidate_element_matches": elements, "exact_candidate_value_matches": values,
            "exact_support_text_candidates": matches,
            "source_original_integrity_check": original_check,
            "source_verified_in_designated_corpus_metadata": source_verified,
            "species_scope_conflict_candidate": conflict,
            "verification_status": status,
            "support_candidate_status": "POTENTIAL_SUPPORT" if matches else "NO_LITERAL_CANDIDATE_CUE",
            "supported_elements_claimed": supported_candidate_elements,
            "missing_elements": missing_candidate_elements,
            "unsupported_candidate_answer_claims": unsupported_candidate_answer_claims,
            "manual_source_review_note": manual_spec.get("review_note") if manual_spec else None,
            "support_assessment": "exploratory candidate only; exact string overlap and metadata do not prove answer sufficiency",
            "formal_relevance_label": None, "context_precision_label_created": False, "human_gold": False,
        })

    # Reconcile the old 28 sources without modifying their historical records.
    prior_status_counts = Counter(x.get("prior_support_status") for x in source28_rows)
    updated_status_counts = Counter(x.get("updated_support_status") for x in source28_rows)
    source_bytes_match_count = sum(x["source_checksum_recomputed_match"] for x in source28_rows)
    quote_local_count = sum(x["quote_matches_local_pdf"] for x in source28_rows)
    quote_any_saved_count = sum(x["quote_matches_local_pdf"] or x["quote_matches_saved_official_excerpt"] for x in source28_rows)
    source28_summary = {
        "rows": len(source28_rows), "prior_support_status_counts": dict(prior_status_counts),
        "updated_support_status_counts": dict(updated_status_counts), "local_source_bytes_hash_matches": source_bytes_match_count,
        "exact_quote_matches_local_pdf": quote_local_count, "exact_quote_matches_local_pdf_or_saved_official_excerpt": quote_any_saved_count,
        "raw_html_snapshots": 0, "human_gold": 0, "designated_corpus_admission_asserted": False,
        "note": "Prior 12 direct/16 partial classifications are preserved. Rehashing does not prove answer correctness; no semantic upgrades were made.",
    }

    # Construct the conservative verifiable subset. A single source-verified direct item can be considered
    # a reference-evidence candidate, but it is not enough for P@5 or a frozen accuracy metric.
    subset_rows = []
    source_by_q = defaultdict(list)
    for x in source28_rows:
        source_by_q[x["question_id"]].append(x)
    for x in source28_rows:
        if x["prior_support_status"] == "DIRECT_SUPPORT_REPRODUCED" and x["source_checksum_recomputed_match"] and (x["quote_matches_local_pdf"] or x["quote_matches_saved_official_excerpt"]):
            subset_rows.append({
                "question_id": x["question_id"], "species": x["species"], "question": x["question_text"],
                "candidate_answer": x["candidate_reference_answer"], "source_id": x["source_id"],
                "source_url": x["source_url"], "source_version": x["source_version_prior"],
                "source_sha256": x["actual_local_source_sha256"], "exact_evidence_span": x["exact_quote"],
                "page_or_locator": {"previous_locator": x.get("page_or_locator"), "local_pdf_pages": x["local_pdf_matching_pages"]},
                "verification_status": "SOURCE_VERIFIED_CANDIDATE",
                "reference_answer_basis": "Phase K direct-support status retained; exact quote and local checksum rechecked",
                "p_at_5_evaluable": False, "logical_accuracy_evaluable_now": False,
                "arithmetic_accuracy_evaluable_now": False,
                "blockers": ["no complete five-chunk binary relevance labels", "no frozen question-specific logical rubric", "not admitted to a designated corpus from this audit", "not Human Gold"],
            })

    # Existing question set evidence candidate projection. Candidate answer cues are explicitly not gold.
    subset_questions = {x["question_id"] for x in subset_rows}
    potential_qids = {x["question_id"] for x in support_rows if x["verification_status"] in ("SOURCE_VERIFIED_CANDIDATE", "PARTIALLY_SUPPORTED")}
    for qid in sorted(potential_qids):
        if qid not in subset_questions:
            # Keep distinct Top-5 candidate facts (e.g. 23 C), but not as an answer-validated benchmark item.
            related = [x for x in support_rows if x["question_id"] == qid and x["verification_status"] in ("SOURCE_VERIFIED_CANDIDATE", "PARTIALLY_SUPPORTED")]
            for item in related:
                exact_candidate_spans = item.get("exact_support_text_candidates") or []
                source_page_excerpt = (item.get("source_original_integrity_check") or {}).get("exact_source_page_excerpt")
                evidence_span = source_page_excerpt or (exact_candidate_spans[0].get("exact_text") if exact_candidate_spans else None)
                subset_rows.append({
                    "question_id": qid, "species": item["species"], "question": item["question_text"],
                    "candidate_answer": qmap.get(qid, {}).get("candidate_reference_answer"),
                    "source_id": item["source_id"], "source_url": item["source_url"], "source_version": item["source_version"],
                    "source_sha256": item["source_sha256"], "exact_evidence_span": evidence_span,
                    "page_or_locator": item["page_or_locator"], "verification_status": item["verification_status"],
                    "reference_answer_basis": "Top-5 literal/located evidence candidate only; source original recheck required for item-level answer verification",
                    "p_at_5_evaluable": False, "logical_accuracy_evaluable_now": False, "arithmetic_accuracy_evaluable_now": False,
                    "blockers": ["candidate question requirements include unverified scoring cues", "no complete five-chunk binary labels", "no frozen rubric", "not Human Gold"],
                })

    # Alias audit summary: distinguish direct identity evidence, weak candidates, and explicit crosswalk contradictions.
    alias_counts = Counter(x["crosswalk_status"] for x in alias_rows)
    alias_method_counts = Counter(x.get("mapping_method") for x in alias_rows)
    explicit_wrong = [x for x in alias_rows if x["crosswalk_status"] == "CONFIRMED_CROSSWALK_IDENTITY_ERROR"]
    explicit_wrong_groups: dict[tuple, set[str]] = defaultdict(set)
    for x in explicit_wrong:
        key = (x.get("excel_source_title"), x.get("excel_source_url"), x.get("document_id"), x.get("document_title"))
        explicit_wrong_groups[key].add(str(x.get("excel_source_id")))
    alias_summary = {
        "registry_rows": len(aliases), "title_disagreement_rows": len(title_mismatches),
        "title_disagreement_by_mapping_method": dict(alias_method_counts), "resolution_status_counts": dict(alias_counts),
        "confirmed_crosswalk_identity_errors": len(explicit_wrong_groups),
        "confirmed_crosswalk_identity_error_rows": len(explicit_wrong),
        "confirmed_crosswalk_identity_pairs": [
            {"excel_source_ids": sorted(ids), "excel_source_title": key[0], "excel_source_url": key[1],
             "document_id": key[2], "document_title": key[3]}
            for key, ids in sorted(explicit_wrong_groups.items(), key=lambda kv: (str(kv[0][0]), str(kv[0][2])))
        ],
        "confirmed_error_basis": "exactly incompatible source service/page role and corpus document title in registry pair; this is a crosswalk identity error, not a finding that the source document itself is false",
        "unresolved_or_unverified_title_mismatches": sum(v for k, v in alias_counts.items() if k != "TITLE_VARIANT_URL_IDENTITY_CONFIRMED" and k != "CONFIRMED_CROSSWALK_IDENTITY_ERROR"),
        "title_variant_url_identity_confirmed": alias_counts.get("TITLE_VARIANT_URL_IDENTITY_CONFIRMED", 0),
        "raw_source_bytes_verified_for_all_alias_rows": False,
        "no_aliases_promoted_or_merged": True,
        "records": alias_rows,
    }

    pending_cache_rows = list(file_cache.values())
    pending_first_by_doc = {}
    for item in pending:
        pending_first_by_doc.setdefault(item.get("document_id"), item)
    pending_summary = {
        "pending_context_rows": len(pending), "unique_document_ids": len({x.get("document_id") for x in pending}),
        "manifest_records_found_unique_docs": sum(x["manifest_count"] == 1 for x in pending_cache_rows),
        "local_source_files_available_unique_docs": sum(x["local_file_exists"] for x in pending_cache_rows),
        "actual_file_sha256_matches_manifest_unique_docs": sum(x["actual_matches_manifest"] for x in pending_cache_rows),
        "actual_file_sha256_matches_corpus_unique_docs": sum(x["actual_matches_corpus"] for x in pending_cache_rows),
        "pending_context_rows_with_file_identity_match_to_manifest_and_corpus": sum(
            bool(x["local_file_evidence"]["actual_matches_manifest"] and x["local_file_evidence"]["actual_matches_corpus"])
            for x in source_resolution_rows),
        "unique_docs_with_manifest_source_url": sum(bool(x["manifest_source_url"]) for x in pending_cache_rows),
        "unique_docs_with_manifest_version": sum(bool(x["manifest_version"]) for x in pending_cache_rows),
        "unique_docs_with_species_metadata": sum(bool(x["manifest_species"]) for x in pending_cache_rows),
        "unique_docs_with_corpus_trace_source_url": sum(bool(x.get("source_url")) for x in pending_first_by_doc.values()),
        "unique_docs_with_corpus_trace_version": sum(bool(x.get("source_version_annotation")) for x in pending_first_by_doc.values()),
        "unique_docs_with_corpus_species_metadata": sum(bool(x.get("document_species_metadata")) for x in pending_first_by_doc.values()),
        "corpus_species_metadata_is_verified_applicability": False,
        "fully_resolved_to_verified_eligible_corpus_source": 0,
        "interpretation": "A matching source-file hash resolves byte identity only; it does not verify publisher/source authority, current version, rights, species applicability, or Corpus eligibility. No Frozen Corpus metadata was changed.",
    }

    # Evidence candidates and requirement profiles support summary stats only; no relevance labels are created.
    category_candidates = Counter(x.get("question_category") for x in support_rows if x["verification_status"] == "SOURCE_VERIFIED_CANDIDATE")
    question_status = Counter()
    for x in support_rows:
        question_status[x["question_id"]] = max(question_status[x["question_id"]],
                                                 {"SOURCE_VERIFIED_CANDIDATE": 3, "PARTIALLY_SUPPORTED": 2, "SOURCE_VERSION_UNVERIFIED": 1, "SPECIES_SCOPE_CONFLICT": 1, "INSUFFICIENT_EVIDENCE": 0}[x["verification_status"]])
    question_candidate_counts = Counter()
    status_order = ["INSUFFICIENT_EVIDENCE", "SOURCE_VERSION_UNVERIFIED", "SPECIES_SCOPE_CONFLICT", "PARTIALLY_SUPPORTED", "SOURCE_VERIFIED_CANDIDATE"]
    numeric_rank_to_status = {0: "INSUFFICIENT_EVIDENCE", 1: "SOURCE_VERSION_UNVERIFIED", 2: "PARTIALLY_SUPPORTED", 3: "SOURCE_VERIFIED_CANDIDATE"}
    for qid, score in question_status.items():
        question_candidate_counts[numeric_rank_to_status.get(score, "INSUFFICIENT_EVIDENCE")] += 1

    p5_historical_eligible = 0  # Source/provenance checks do not create binary relevance truth.
    conflict_rows = [x for x in contexts if x.get("species_scope_conflict_candidate")]
    scope_summary = {
        "phase_p_scope_conflict_candidate_contexts": len(conflict_rows),
        "unique_questions_with_scope_conflict_candidates": len({x.get("question_id") for x in conflict_rows}),
        "unique_documents_with_scope_conflict_candidates": len({x.get("document_id") for x in conflict_rows}),
        "status_counts": dict(Counter(x.get("species_scope_status") for x in conflict_rows)),
        "target_species_literal_mentioned_in_body": sum(bool(x.get("target_species_mentioned_in_body")) for x in conflict_rows),
        "target_species_literal_absent_from_body": sum(not bool(x.get("target_species_mentioned_in_body")) for x in conflict_rows),
        "confirmed_applicability_from_this_phase": 0,
        "interpretation": "Literal species mention and document metadata are screening signals, not proof that a technical claim applies. No batch of the 439 candidates received source-level applicability validation; all remain candidates or unresolved.",
    }
    readiness = {
        "phase": "Q", "created_at": datetime.now(timezone.utc).isoformat(),
        "questions": len(questions), "top5_contexts": len(contexts),
        "source_metadata_resolution": pending_summary,
        "alias_audit": {k: v for k, v in alias_summary.items() if k != "records"},
        "species_scope_conflict_audit": scope_summary,
        "existing_28_source_verification": source28_summary,
        "evidence_candidate_questions_by_strictest_candidate_status": dict(question_candidate_counts),
        "source_verified_candidate_contexts": sum(x["verification_status"] == "SOURCE_VERIFIED_CANDIDATE" for x in support_rows),
        "partially_supported_contexts": sum(x["verification_status"] == "PARTIALLY_SUPPORTED" for x in support_rows),
        "source_evidence_subset_rows": len(subset_rows),
        "source_evidence_subset_unique_questions": len({x["question_id"] for x in subset_rows}),
        "source_evidence_subset_unique_question_texts": len({norm_text(x.get("question") or "") for x in subset_rows if x.get("question")}),
        "source_verified_candidate_question_ids": sorted({x["question_id"] for x in subset_rows if x["verification_status"] == "SOURCE_VERIFIED_CANDIDATE"}),
        "partial_support_candidate_question_ids": sorted({x["question_id"] for x in subset_rows if x["verification_status"] == "PARTIALLY_SUPPORTED"}),
        "p_at_5_countable_questions_new_phase": p5_historical_eligible,
        "logical_accuracy_new_effective_samples": 0,
        "arithmetic_accuracy_new_effective_samples": 0,
        "answer_verified_human_gold": 0,
        "formal_corpus_mutation": False, "new_retrieval_labels_created": False,
        "new_generator_runs": 0,
        "notes": [
            "Question profiles reuse existing requirement cues and keep them explicitly provisional; candidate answers were not treated as gold.",
            "Evidence candidate rows do not create Relevant/Irrelevant labels and cannot be converted into Context Precision@5.",
            "No formula registry with a fully reverified source, protocol, units, conditions, and tolerance was introduced in Phase Q; no Arithmetic Accuracy sample was added.",
            "No question-specific Logical rubric was frozen and no generator answer was rescored; no Logical Accuracy sample was added.",
            "Historical Phase K AI-only P@5 pilot values remain historical and were not promoted to verified relevance truth.",
        ],
    }

    # Freeze and recheck all protected hashes after writing data; the allowlisted Q output directory is outside the manifest.
    write_jsonl(OUT / "source_metadata_resolution.jsonl", source_resolution_rows)
    write_json(OUT / "source_alias_audit.json", alias_summary)
    write_jsonl(OUT / "question_requirement_profiles_180.jsonl", profile_rows)
    write_jsonl(OUT / "evidence_support_candidates_900.jsonl", support_rows)
    write_jsonl(OUT / "source_verification_28_updated.jsonl", source28_rows)
    write_jsonl(OUT / "verifiable_evaluation_subset.jsonl", subset_rows)

    protected_after = {}
    for i, (rel, expected) in enumerate(expected_by_path.items(), 1):
        path = resolve_path(rel)
        actual = sha256_file(path) if path and path.is_file() else None
        protected_after[rel] = {"expected": expected, "actual": actual, "status": "unchanged" if actual == expected else "missing_or_changed"}
        if i % 120 == 0:
            print(f"baseline after: {i}/{len(expected_by_path)}", flush=True)
    protected_manifest = [{"path": k, "expected_sha256": expected_by_path[k],
                           "before_sha256": protected_before[k]["actual"], "after_sha256": protected_after[k]["actual"],
                           "status": "unchanged" if protected_before[k]["actual"] == expected_by_path[k] == protected_after[k]["actual"] else "changed_or_missing"}
                          for k in expected_by_path]
    write_jsonl(OUT / "frozen_baseline_636_recheck.jsonl", protected_manifest)
    sqlite_path = ROOT / "rag_store.sqlite3"
    sqlite_sha = sha256_file(sqlite_path) if sqlite_path.is_file() else None
    compatibility = {
        "output_scope": str(OUT.relative_to(ROOT)), "questions_original_count": len(questions),
        "retrieval_contexts_audited": len(contexts), "source_resolution_rows": len(source_resolution_rows),
        "source_alias_records_audited": len(alias_rows), "source_verification_28_rows": len(source28_rows),
        "phase_p_outputs_modified": False, "phase_o_to_p_history_modified": False,
        "generator_runs": 0, "retrieval_runs": 0, "corpus_v2_or_historical_e4_modified": False,
        "production_or_sqlite_modified": False, "sqlite_sha256": sqlite_sha,
        "sqlite_expected_sha256": "d7d06d4d2a57d0a57d05bcb6131ffb24aefb226c6bd36349dbc5118d33b11087",
        "sqlite_hash_matches_expected": sqlite_sha == "d7d06d4d2a57d0a57d05bcb6131ffb24aefb226c6bd36349dbc5118d33b11087",
        "protected_manifest_unique_paths": len(expected_by_path),
        "protected_status_counts": dict(Counter(x["status"] for x in protected_manifest)),
        "protected_636_unchanged": len(expected_by_path) == 636 and all(x["status"] == "unchanged" for x in protected_manifest),
        "human_gold_created": False, "winner_or_weighted_score_created": False,
        "p_at_5_labels_created": 0,
    }
    write_json(OUT / "benchmark_readiness_summary.json", readiness)
    write_json(OUT / "compatibility.json", compatibility)

    validation = {
        "questions_180": len(profile_rows) == 180,
        "retrieval_candidates_900": len(support_rows) == 900,
        "unique_question_chunk_rank_keys_900": len({(x["question_id"], x["chunk_id"], x["rank"]) for x in support_rows}) == 900,
        "context_text_hashes_match_recorded": all(x["context_hash_matches_recorded"] for x in support_rows),
        "source_pending_rows_match_phase_p": len(source_resolution_rows) == 511,
        "source_verification_rows_28": len(source28_rows) == 28,
        "alias_title_mismatch_rows_47": len(alias_rows) == 47,
        "alias_confirmed_unique_crosswalk_errors": alias_summary["confirmed_crosswalk_identity_errors"] == 2 and alias_summary["confirmed_crosswalk_identity_error_rows"] == 11,
        "no_relevance_labels_created": all(x["formal_relevance_label"] is None for x in support_rows),
        "no_p5_or_accuracy_filled": readiness["p_at_5_countable_questions_new_phase"] == 0 and readiness["logical_accuracy_new_effective_samples"] == 0 and readiness["arithmetic_accuracy_new_effective_samples"] == 0,
        "protected_636_unchanged": compatibility["protected_636_unchanged"],
        "sqlite_expected_sha256": compatibility["sqlite_hash_matches_expected"],
    }
    write_json(OUT / "phase_q_validation.json", {"checks": validation, "all_pass": all(validation.values()), "created_at": datetime.now(timezone.utc).isoformat()})

    report = f"""# Phase Q — 可查核證據集建置結果

## 範圍

本輪以 Phase P 的 180 題與 900 筆固定 Top-5 trace、Evaluation Corpus v2、source manifest、source alias registry，以及 Phase J/K 的 28 題來源核驗紀錄建立研究用來源與證據候選登錄。沒有重跑生成或檢索、沒有建立相關性真值，沒有修改 Frozen Corpus。

## 511 筆來源待確認

- 原始待確認 Context：{len(pending)}；唯一文件數：{pending_summary['unique_document_ids']}。
- 在既有來源 manifest 找到唯一文件紀錄：{pending_summary['manifest_records_found_unique_docs']} 個文件；本機來源檔可讀：{pending_summary['local_source_files_available_unique_docs']} 個。
- 重新計算的原件 SHA-256 同時符合 manifest 與 Corpus 登錄值：{pending_summary['actual_file_sha256_matches_manifest_unique_docs']} 個唯一文件。
- 以重算原件身分對上 manifest 與 Corpus 的待確認 Context：{pending_summary['pending_context_rows_with_file_identity_match_to_manifest_and_corpus']} 筆；這只補強 bytes 身分，不代表補齊來源網址、版本、物種適用性、權利或准入狀態。
- 有來源 URL／版本／species 欄位的 manifest 文件數分別為 {pending_summary['unique_docs_with_manifest_source_url']}／{pending_summary['unique_docs_with_manifest_version']}／{pending_summary['unique_docs_with_species_metadata']}。
- Corpus trace 另有來源 URL／版本／species metadata 的唯一文件數為 {pending_summary['unique_docs_with_corpus_trace_source_url']}／{pending_summary['unique_docs_with_corpus_trace_version']}／{pending_summary['unique_docs_with_corpus_species_metadata']}；其中 species 欄位仍是待核 metadata，不當成適用性證明。
- 能因此完整補成「已核實來源、版本、適用性、權利及 retrieval eligibility」的 Context：0；原件 checksum 只確認檔案身分，不補足來源權威性、現行版本、權利、魚種適用性或 Corpus eligibility。

逐筆修復建議見 `source_metadata_resolution.jsonl`。所有結果均未寫回 Corpus。

## 47 筆標題別名差異

- URL 相符、標題粒度不同：{alias_counts.get('TITLE_VARIANT_URL_IDENTITY_CONFIRMED', 0)} 筆，可按 URL 身分視為標題別名，不代表文件內容或版本已核驗。
- 以標題強比對／弱比對建立、仍待來源原件確認：{alias_summary['unresolved_or_unverified_title_mismatches']} 筆。
- 可由來源 URL 功能與文件標題直接確認為錯誤 crosswalk：{alias_summary['confirmed_crosswalk_identity_errors']} 個不同錯配（{alias_summary['confirmed_crosswalk_identity_error_rows']} 筆重複登錄列）；主要是兩個錯配關係被重複記錄。這是登錄中的文件身分錯配，不是原始文件內容錯誤。其餘未能以原件確認者保留未決，沒有按標題自動合併。

完整逐筆對照在 `source_alias_audit.json`。

## 180 題需求與 900 段候選證據

- 建立需求剖面：{len(profile_rows)}/180。題庫答案線索保留為未驗證 cue，未當成 Gold。
- 每段保留題目、Rank、Chunk、來源欄位、原文、頁碼、source spans、checksum、魚種 metadata 與原文魚種名稱訊號。
- Top-5 證據候選：{sum(x['verification_status'] == 'SOURCE_VERIFIED_CANDIDATE' for x in support_rows)} 段；部分支持候選：{sum(x['verification_status'] == 'PARTIALLY_SUPPORTED' for x in support_rows)} 段。候選句不得直接視為答案充分或相關性真值。
- 其中 FT-seabass-Q02 Rank 2 的手冊第16頁原件 checksum、頁面文字與 Corpus checksum 相符；原文支持低於23°C食慾下降及長期低溫水黴風險，但不支持候選答案額外提到的「二次感染」主張。FT-seabass-Q30 Rank 4 只支持部分低溫風險，沒有21°C死亡時間。
- 以題目需求 profile 聚合，具有來源文字候選的題數為 {len(potential_qids)}；唯一可列入 source-verified reference-candidate 的既有題目數為 {len({x['question_id'] for x in subset_rows if x['verification_status']=='SOURCE_VERIFIED_CANDIDATE'})}，仍須人工確認標準答案／rubric。
- 可追溯證據子集共 {len(subset_rows)} 筆紀錄、{len({x['question_id'] for x in subset_rows})} 個題目 ID、{len({norm_text(x.get('question') or '') for x in subset_rows if x.get('question')})} 種不同題幹；包含重複的跨魚種法規題，不代表同數量的獨立知識群組。
- 439 筆適用範圍衝突仍是篩查候選，涵蓋 {scope_summary['unique_questions_with_scope_conflict_candidates']} 個題目及 {scope_summary['unique_documents_with_scope_conflict_candidates']} 份文件；其中 {scope_summary['target_species_literal_mentioned_in_body']} 筆正文可見題目魚種字串，這不等於內容適用已確認；本輪對 439 筆均未作出來源層級的適用性確認。

## 28 題來源重核

- Phase K 舊分類維持：12 題直接支持、16 題部分支持；沒有把部分支持升級。
- 本輪逐題重算本機原件 checksum：{source_bytes_match_count}/28 相符；精確引文在本機 PDF 文字中重現 {quote_local_count}/28；在本機 PDF 或既存官方頁面摘錄中重現 {quote_any_saved_count}/28。
- 23 題為農業部現行法規頁面／附件來源；[官方頁面](https://law.moa.gov.tw/LawContent.aspx?id=FL035443&media=print)列修正日民國114年1月8日、頁面列印時間民國115年9月24日；第3條要求水產動物用藥品目、對象、用途、用法、用量與停藥期符合附件一。未把這條一般規定解讀成特定藥品或魚種的許可。官方頁面的附件連結未能由網頁讀取器下載，但本機附件 PDF 以已登錄 checksum 核對。原始 HTML bytes 未保存。
- 5 題來自水試所金目鱸生物安全手冊；checksum／引文結果見逐題登錄。仍維持既有 12/16 支持分類，不等於 Corpus v2 admission 或 Human Gold。

## 可評估範圍

- 新增可計算 P@5：0 題。來源存在或有候選證據不等於五筆 Top-5 都有可靠二元標籤。
- 新增 Logical Accuracy：0 筆；本輪沒有凍結逐題 rubric，也沒有重新評分既有 Generator 回答。
- 新增 Arithmetic Accuracy：0 筆；本輪沒有新核實含公式協定、變數、單位、條件、標準答案與容差的計算題。
- `verifiable_evaluation_subset.jsonl` 留存可追溯、可供下一輪 rubric 審查的來源直接支持候選，全部仍標記非 Human Gold；不含新的模型正確率分數。

## 完整性

Frozen Manifest 唯一路徑 {len(expected_by_path)} 筆前後重新雜湊，結果 {compatibility['protected_status_counts']}；SQLite SHA-256 與預期值相符：{compatibility['sqlite_hash_matches_expected']}。沒有修改 Phase P、720 筆生成、Historical E4、Corpus、Production 或 SQLite。
"""
    (OUT / "phase_q_final_report.md").write_text(report, encoding="utf-8")

    # Ensure the delivered files are parseable and counts are stable.
    for name in ["source_metadata_resolution.jsonl", "question_requirement_profiles_180.jsonl", "evidence_support_candidates_900.jsonl", "source_verification_28_updated.jsonl", "verifiable_evaluation_subset.jsonl", "frozen_baseline_636_recheck.jsonl"]:
        _ = read_jsonl(OUT / name)
    for name in ["source_alias_audit.json", "benchmark_readiness_summary.json", "compatibility.json", "phase_q_validation.json"]:
        _ = json.loads((OUT / name).read_text(encoding="utf-8"))
    print(json.dumps({"questions": len(profile_rows), "contexts": len(support_rows), "pending_rows": len(source_resolution_rows),
                      "alias_mismatches": len(alias_rows), "alias_confirmed_crosswalk_errors": alias_summary["confirmed_crosswalk_identity_errors"],
                      "28_hash_match": source_bytes_match_count, "28_quote_pdf_match": quote_local_count,
                      "28_quote_any_saved_match": quote_any_saved_count, "subset_rows": len(subset_rows),
                      "candidate_contexts": dict(Counter(x["verification_status"] for x in support_rows)),
                      "protected_636_unchanged": compatibility["protected_636_unchanged"],
                      "validation_all_pass": all(validation.values())}, ensure_ascii=False))


if __name__ == "__main__":
    main()
