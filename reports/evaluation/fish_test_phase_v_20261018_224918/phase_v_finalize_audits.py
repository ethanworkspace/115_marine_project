from __future__ import annotations

import collections
import hashlib
import importlib.util
import json
import pathlib
import re
import sqlite3
import unicodedata

import pymupdf

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[2]
BUILDER_PATH = HERE / "phase_v_build_and_retrieval.py"


def read_jsonl(path: pathlib.Path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_jsonl(path: pathlib.Path, rows):
    path.write_text("".join(json.dumps(x, ensure_ascii=False, separators=(",", ":")) + "\n" for x in rows), encoding="utf-8")


def sha256(path: pathlib.Path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


TOPIC_NEEDLES = {
    "temperature": ["水溫", "溫度", "攝氏", "°c", "℃"],
    "salinity": ["鹽度", "psu", "半淡鹹", "淡水", "海水"],
    "depth": ["水深", "池深", "深度"],
    "density": ["放養密度", "密度", "每公頃", "尾/公頃", "放養量"],
    "taxonomy": ["學名", "分類", "物種", "棲地", "分布"],
    "lime": ["石灰", "整池"],
    "cold_management": ["寒流", "寒害", "防寒", "越冬", "冬季"],
    "disease": ["水黴", "黴菌", "病原", "診斷", "症狀", "感染"],
    "feeding": ["攝食", "攝餌", "食慾", "投餌", "投餵"],
}

FACT_TOPIC = {
    "m17s-001": {"taxonomy"},
    "m17s-002": {"temperature", "feeding"},
    "m17s-003": {"salinity"},
    "m17s-004": {"depth"},
    "m17s-005": {"density"},
    "m17g-001": {"taxonomy"},
    "m17g-002": {"temperature"},
    "m17g-003": {"depth"},
    "m17g-004": {"density"},
    "m17b-001": {"taxonomy"},
    "m17b-002": {"temperature", "feeding", "disease"},
    "m17b-003": {"salinity"},
    "m17b-004": {"depth"},
    "m17b-005": {"density"},
    "m17b-006": {"lime"},
    "m17m-001": {"taxonomy"},
    "m17m-002": {"temperature"},
    "m17m-003": {"density"},
    "fa385-001": {"cold_management"},
    "fa385-002": {"cold_management"},
    "fa385-003": {"density", "cold_management"},
    "fa385-004": {"cold_management", "temperature"},
    "fa385-005": {"cold_management"},
    "eel-2006-001": {"disease"},
    "eel-2006-002": {"disease"},
}


def question_topics(text: str):
    t = text.casefold()
    return {topic for topic, needles in TOPIC_NEEDLES.items() if any(n.casefold() in t for n in needles)}


def question_species_conflict(text: str, target: str):
    aliases = {
        "虱目魚": ["虱目魚", "milkfish", "chanos chanos"],
        "吳郭魚": ["吳郭魚", "台灣鯛", "tilapia", "oreochromis"],
        "石斑魚": ["石斑魚", "grouper", "epinephelus"],
        "鱸魚": ["鱸魚", "金目鱸", "七星鱸", "seabass", "lates calcarifer", "lateolabrax japonicus"],
        "烏魚": ["烏魚", "鯔魚", "mullet", "mugil cephalus"],
        "鰻魚": ["鰻魚", "eel", "anguilla"],
    }
    t = text.casefold()
    hits = {s for s, terms in aliases.items() if any(term.casefold() in t for term in terms)}
    return sorted(hits - {target}) if len(hits) > 1 else []


def card_species_applies(card, question):
    target = question.get("species_chinese") or ""
    text = question.get("question_text", "")
    meta = card.get("metadata", {})
    scope = set(str(meta.get("species_scope", "")).split("|"))
    tax = str(meta.get("species_taxonomy", ""))
    conflicts = question_species_conflict(text, target)
    if conflicts:
        return False, "EXPLICIT_CROSS_SPECIES_QUESTION_OR_SCOPE_CONFLICT"
    fid = meta.get("fact_id", "")
    if target == "鱸魚":
        if "金目鱸" in text:
            return ("Lates calcarifer" in tax, "EXACT_GOLD_SEABASS_SCOPE" if "Lates calcarifer" in tax else "SPECIES_SCOPE_MISMATCH")
        if "七星鱸" in text:
            return ("Lateolabrax japonicus" in tax, "EXACT_SEVENSTAR_SCOPE" if "Lateolabrax japonicus" in tax else "SPECIES_SCOPE_MISMATCH")
        return False, "GENERIC_SEABASS_NOT_PROMOTED_TO_SPECIES_SCOPE"
    if fid in {"m17g-003", "m17g-004"}:
        ok = any(x in text for x in ["鞍帶石斑", "龍膽", "Epinephelus lanceolatus"])
        return ok, "EXACT_GIANT_GROUPER_SCOPE" if ok else "GROUPER_FACT_IS_SPECIES_SPECIFIC"
    if fid == "m17g-002":
        ok = target == "石斑魚" and not any(x in text for x in ["鞍帶", "龍膽", "Epinephelus"])
        return ok, "MANUAL_DEFINED_GROUP_SCOPE" if ok else "GROUPER_SCOPE_NOT_MATCHED"
    if "general_aquaculture" in scope:
        if target in scope:
            return True, "EXPLICIT_MULTI_SPECIES_SCOPE"
        if target == "" and question.get("general_aquaculture"):
            return True, "GENERAL_AQUACULTURE_SCOPE"
        return False, "GENERAL_SCOPE_NOT_AUTOMATICALLY_EXTENDED_TO_TARGET_SPECIES"
    if target in scope:
        return True, "EXACT_SPECIES_LABEL_SCOPE"
    if target == "石斑魚" and "GROUP" in tax:
        return True, "MANUAL_DEFINED_GROUP_SCOPE"
    return False, "SOURCE_SPECIES_SCOPE_MISMATCH_OR_UNKNOWN"


def card_topic_complete(card, question):
    fid = card.get("metadata", {}).get("fact_id", "")
    required = question_topics(question.get("question_text", ""))
    covered = FACT_TOPIC.get(fid, set())
    # A single fact card can support a multi-element question only if it covers all detected requirements.
    if not required or not required.issubset(covered):
        return False, sorted(required), sorted(covered)
    text = question.get("question_text", "")
    # Preserve the distinction between optimal, survival, risk and emergency thresholds.
    if fid in {"m17s-002", "m17g-002", "m17b-002", "m17m-002"} and not any(x in text for x in ["水溫", "溫度", "攝氏", "°C", "℃"]):
        return False, sorted(required), sorted(covered)
    if fid == "fa385-003" and "虱目魚" not in text:
        return False, sorted(required), sorted(covered)
    if fid in {"m17s-005", "m17g-004", "m17b-005", "m17m-003"} and not any(x in text for x in ["密度", "放養", "每公頃", "尾/公頃"]):
        return False, sorted(required), sorted(covered)
    if fid == "m17b-006" and not any(x in text for x in ["石灰", "整池"]):
        return False, sorted(required), sorted(covered)
    if fid in {"eel-2006-001", "eel-2006-002"} and not any(x in text for x in ["歷史", "2006", "特刊", "黴菌", "水黴", "病原", "診斷"]):
        return False, sorted(required), sorted(covered)
    if fid.startswith("fa385-") and question.get("species_chinese") not in {"虱目魚", "吳郭魚"} and "general_aquaculture" not in str(card.get("metadata", {}).get("species_scope", "")):
        return False, sorted(required), sorted(covered)
    return True, sorted(required), sorted(covered)


def main():
    spec = importlib.util.spec_from_file_location("phase_v_builder", BUILDER_PATH)
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    run = builder.RUN

    questions = read_jsonl(builder.QUESTION_FILE)
    cards = read_jsonl(run / "evidence_cards_v3.jsonl")
    retrieval = read_jsonl(run / "retrieval_results_v3_final.jsonl")
    retrieval_by = {r["question_id"]: r for r in retrieval}
    source_audit = []
    for r in read_jsonl(run / "source_blocker_resolution_50.jsonl"):
        owner_path = ROOT / r["local_file"] if r.get("local_file") else None
        actual = sha256(owner_path) if owner_path and owner_path.is_file() else None
        parse = {"format": r.get("format"), "page_count": None, "extracted_characters": None, "empty_or_unextractable_pages": None, "parser_error": None}
        if owner_path and owner_path.is_file() and actual == r.get("sha256_expected"):
            try:
                if owner_path.suffix.lower() == ".pdf":
                    doc = pymupdf.open(owner_path)
                    texts = [page.get_text("text") for page in doc]
                    parse.update({"page_count": len(doc), "extracted_characters": sum(len(x) for x in texts), "empty_or_unextractable_pages": sum(len(x.strip()) < 20 for x in texts)})
                elif owner_path.suffix.lower() in {".html", ".htm"}:
                    raw = owner_path.read_text(encoding="utf-8", errors="replace")
                    text = re.sub(r"<[^>]+>", " ", raw)
                    parse.update({"extracted_characters": len(re.sub(r"\s+", " ", text)), "empty_or_unextractable_pages": 0})
                else:
                    parse.update({"parser_error": "unsupported_format_for_phase_v_parser"})
            except Exception as exc:
                parse["parser_error"] = f"{type(exc).__name__}:{exc}"
        blockers = []
        if not owner_path or not owner_path.is_file(): blockers.append("SOURCE_FILE_MISSING")
        if not actual or actual != r.get("sha256_expected"): blockers.append("SOURCE_CHECKSUM_MISMATCH")
        if not r.get("publisher") or str(r.get("publisher")).lower() in {"unverified", "unknown"}: blockers.append("PUBLISHER_NOT_VERIFIED")
        if not r.get("document_version") or str(r.get("document_version")).lower() in {"unverified", "unknown"}: blockers.append("DOCUMENT_VERSION_NOT_FIXED")
        if "unverified" in str(r.get("rights_status_fulltext", "")).lower() or "copyright" in str(r.get("rights_status_fulltext", "")).lower(): blockers.append("FULLTEXT_INDEX_RIGHTS_NOT_ESTABLISHED")
        if parse.get("parser_error") or parse.get("empty_or_unextractable_pages"): blockers.append("PARSER_OR_OCR_QUALITY_REQUIRES_REVIEW")
        row = dict(r)
        row.update({"sha256_rechecked": actual, "checksum_recheck_status": "MATCH" if actual and actual == r.get("sha256_expected") else "BLOCKED", "parser_forensics_rechecked": parse, "blocker_codes": list(dict.fromkeys(blockers)), "fulltext_index_status": "BLOCKED_PENDING_RIGHTS_AND_SOURCE_REVIEW", "limited_fact_card_status": "INCLUDED_FOR_SELECTED_CARDS_ONLY" if r.get("source_id") in {c.get("source_id") for c in cards} else "NOT_INCLUDED", "owner_decision_is_not_third_party_license": True})
        source_audit.append(row)
    write_jsonl(run / "source_blocker_resolution_50.jsonl", source_audit)
    counts = collections.Counter(code for r in source_audit for code in r["blocker_codes"])
    builder.write_json(run / "source_blocker_resolution_summary.json", {"records": len(source_audit), "unique_source_sha256": len({r.get("sha256_rechecked") for r in source_audit if r.get("sha256_rechecked")}), "checksum_matches": sum(r["checksum_recheck_status"] == "MATCH" for r in source_audit), "fulltext_index_blocked": sum(r["fulltext_index_status"].startswith("BLOCKED") for r in source_audit), "blocker_code_counts": dict(counts), "parser_rechecked": True, "note": "Owner approval is recorded for 57 decisions, but third-party rights are evaluated separately. No broad full-text rights are inferred."})

    ref_rows = []
    for q in questions:
        text = q.get("question_text", "")
        target = q.get("species_chinese", "")
        explicit_conflicts = question_species_conflict(text, target)
        topics = sorted(question_topics(text))
        candidates = []
        rejected = []
        for c in cards:
            meta = c.get("metadata", {})
            species_ok, species_reason = card_species_applies(c, q)
            complete, required, covered = card_topic_complete(c, q)
            if species_ok and complete:
                candidates.append((c, species_reason, required, covered))
            else:
                if not species_ok or (required and not complete):
                    rejected.append({"fact_id": meta.get("fact_id"), "species_check": species_reason, "required_topics": required, "card_topics": covered})
        # Require a single fact card to cover the detected request; do not combine unrelated facts into a synthetic answer.
        selected = candidates[:1] if len(candidates) == 1 else []
        if selected:
            c, species_reason, required, covered = selected[0]
            m = c["metadata"]
            quote = m.get("evidence_span", "")
            row_status = "SOURCE_VERIFIED_AUTOMATED_CANDIDATE"
            answer = c["text"]
            spans = [{"source_id": c["source_id"], "source_sha256": c["source_sha256"], "source_version": c["source_version"], "locator": c["record_locator"], "exact_evidence_span": quote, "fact_id": m["fact_id"], "species_scope": m["species_scope"], "quote_verified": bool(m.get("evidence_quote_verified")), "quote_start_char": m.get("evidence_span_start_char"), "quote_end_char": m.get("evidence_span_end_char")}]
            supported = [m["fact_id"]]
            missing = []
            applicability = species_reason
            expected_action = "ANSWER_FROM_CITED_FACT_WITH_SCOPE_LIMITS"
        else:
            row_status = "NOT_EVALUABLE"
            answer = None
            spans = []
            supported = []
            missing = topics or ["question_requirement_not_machine_resolved"]
            applicability = "SPECIES_SCOPE_CONFLICT" if explicit_conflicts else "NOT_VERIFIED"
            expected_action = "ABSTAIN_IF_NO_ADMISSIBLE_EVIDENCE; benchmark scoring not eligible"
        ret = retrieval_by[q["question_id"]]
        ref_rows.append({"question_id": q["question_id"], "species": target, "category": q.get("inferred_category"), "question_text": text, "question_valid": bool(text.strip()), "question_requirement_profile": {"detected_topics": topics, "species_conflict_candidates": explicit_conflicts, "needs_numeric_or_condition_support": bool(re.search(r"\d|範圍|單位|條件|以上|以下|至少|至多|適宜|最適", text)), "profile_method": "deterministic_question_text_rules_v1; requires review"}, "source_status": row_status, "reference_answer_candidate": answer, "required_answer_elements": topics, "supported_elements": supported, "missing_elements": missing, "evidence_spans": spans, "applicability_status": applicability, "logical_rubric": ("Candidate only: response must match cited fact and explicit species/condition; no unsupported extrapolation." if selected else None), "arithmetic_rubric": None, "expected_action": expected_action, "corpus_version": "research_corpus_v3_phase_v_20261018", "retrieval_outcome": ret["retrieval_status"], "top5_hit_is_outcome_not_eligibility_gate": True, "human_gold_reviewed": False, "verification_level": "AI_ASSISTED_SOURCE_TRACE_CANDIDATE" if selected else "NOT_EVALUABLE", "candidate_mapping_reasons": [{"fact_id": c.get("metadata", {}).get("fact_id"), "species_rule": sr, "required_topics": req, "card_topics": cov} for c, sr, req, cov in selected], "rejected_card_diagnostics": rejected, "limitations": "This is a source-backed candidate mapping only; no Human Gold, no formal final benchmark qualification, and no M1-M4 output was used."})
    write_jsonl(run / "question_reference_answers_180.jsonl", ref_rows)
    counts = collections.Counter(r["source_status"] for r in ref_rows)
    by_species = collections.defaultdict(collections.Counter)
    by_category = collections.defaultdict(collections.Counter)
    for r in ref_rows:
        by_species[r["species"]][r["source_status"]] += 1
        by_category[str(r["category"])][r["source_status"]] += 1
    builder.write_json(run / "question_reference_qualification_summary.json", {"status_counts": dict(counts), "by_species": {k: dict(v) for k, v in by_species.items()}, "by_category": {k: dict(v) for k, v in by_category.items()}, "human_gold": 0, "formal_gate_v2_pass": 0, "note": "Candidate references are based on exact source card/topic/scope mapping; all remain non-human and require rubric review."})

    # Preserve raw-versus-filtered stage counts from the repaired retrieval trace.
    retrieval_failure = []
    for r in retrieval:
        retrieval_failure.append({"question_id": r["question_id"], "species": r["species"], "category": r["category"], "possible_source_count_from_allowlist": r.get("candidate_sources_in_scope_allowlist_present"), "corpus_applicable_source_count": r["corpus_applicable_source_count"], "corpus_applicable_chunk_count": r["corpus_applicable_chunk_count"], "bm25_raw_global_candidate_count": r.get("bm25_global_candidate_count"), "bm25_allowed_source_candidate_count": r["bm25_candidate_count"], "dense_raw_global_candidate_count": r.get("dense_global_candidate_count"), "dense_allowed_source_candidate_count": r["dense_candidate_count"], "rrf_fused_candidate_count": r["rrf_candidate_count"], "source_qualification_pass_count": r["source_qualification_pass_count"], "source_qualification_rejected_reasons": r.get("source_qualification_rejected_reasons", {}), "species_applicability_pass_count": r["species_applicability_pass_count"], "species_scope_rejected_reasons": r.get("species_scope_rejected_reasons", {}), "reranker_candidate_count": r["reranker_candidate_count"], "final_top5_count": r["final_top5_count"], "failure_reason": r.get("retrieval_failure_reason"), "top5_chunk_ids": [x["chunk_id"] for x in r["reranked_top5"]], "stage_count_limitation": None})
    write_jsonl(run / "retrieval_failure_resolution_180.jsonl", retrieval_failure)

    # Correct the admission summary so full-text blocks are not confused with source approval.
    ap = json.loads((run / "source_admission_final.json").read_text(encoding="utf-8"))
    ap["blocked_fulltext_source_count"] = 50
    ap["new_source_processing_status"] = "limited researcher-authored factual cards indexed only where SHA, exact locator and source identity were checked; copyrighted or otherwise unverified fulltext not indexed"
    ap["note"] = "Owner decisions 57/57 are recorded; this does not grant third-party rights. Six technical source packages contribute only 25 precisely sourced, researcher-authored fact cards. The 50 full-text packages remain blocked pending rights/identity/version/parser checks. DGBAS-2020 remains limited to original single-period Fact rows."
    builder.write_json(run / "source_admission_final.json", ap)

    status_counts = collections.Counter(r["source_status"] for r in ref_rows)
    retrieval_status = collections.Counter(r["retrieval_status"] for r in retrieval)
    metrics = json.loads((run / "evaluation_metrics_v3_final.json").read_text(encoding="utf-8"))
    metrics["answerability"] = {"questions": len(ref_rows), "source_verified_automated_candidates": status_counts.get("SOURCE_VERIFIED_AUTOMATED_CANDIDATE", 0), "not_evaluable": status_counts.get("NOT_EVALUABLE", 0), "human_gold": 0, "formal_eligible": 0}
    metrics["retrieval"]["status_counts"] = dict(retrieval_status)
    metrics["blocker"] = "Source-backed reference candidate set remains limited, unbalanced and not independently rubric-frozen across six species/categories; full 720-call comparison is not authorized by the readiness gates."
    builder.write_json(run / "evaluation_metrics_v3_final.json", metrics)

    print(json.dumps({"source_blocker_summary": json.loads((run / "source_blocker_resolution_summary.json").read_text(encoding="utf-8")), "reference_summary": json.loads((run / "question_reference_qualification_summary.json").read_text(encoding="utf-8")), "retrieval_status": dict(retrieval_status)}, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
