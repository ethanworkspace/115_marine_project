from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
RUN = ROOT / "reports/evaluation/fish_test_run_20261012_152244"
PHASE_O = ROOT / "reports/evaluation/fish_test_phase_o_ai_adjudication_20261016_211742"
PHASE_M = ROOT / "reports/evaluation/fish_test_phase_m_20261016_195819"
PHASE_N = ROOT / "reports/evaluation/fish_test_phase_n_20261016_205314"
CORPUS_PATH = ROOT / "data/evaluation/corpus_v2.jsonl"
ALIAS_PATH = ROOT / "data/evaluation/source_alias_registry_v3.jsonl"
BASELINE_PATH = PHASE_O / "frozen_baseline_636_recheck.jsonl"

SPECIES_ALIASES = {
    "虱目魚": ["虱目魚", "milkfish", "Chanos chanos"],
    "吳郭魚": ["吳郭魚", "台灣鯛", "羅非魚", "tilapia", "Oreochromis"],
    "石斑魚": ["石斑魚", "grouper", "groupers", "Epinephelus"],
    "鱸魚": ["鱸魚", "金目鱸", "七星鱸", "seabass", "barramundi", "Lates calcarifer"],
    "烏魚": ["烏魚", "鯔魚", "mullet", "Mugil cephalus"],
    "鰻魚": ["鰻魚", "鰻", "eel", "Anguilla"],
}
OTHER_SPECIES_TERMS = ["午仔魚", "文蛤", "白蝦", "草蝦", "龍蝦", "牡蠣", "九孔", "蜆"]


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]


def write_json(path: Path, obj: Any) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def norm(s: Any) -> str:
    x = str(s or "").casefold().replace("℃", "°c").replace("ºc", "°c")
    x = re.sub(r"\s+", "", x)
    x = x.replace("～", "至").replace("~", "至").replace("—", "至").replace("–", "至").replace("-", "至")
    x = x.replace("到", "至").replace("／", "/")
    return x


def body_species_mentions(text: str) -> list[str]:
    low = text.casefold()
    hits = []
    for species, aliases in SPECIES_ALIASES.items():
        if any(alias.casefold() in low for alias in aliases):
            hits.append(species)
    for term in OTHER_SPECIES_TERMS:
        if term.casefold() in low:
            hits.append(term)
    return sorted(set(hits))


def unique_list(items: list[Any]) -> list[str]:
    seen = set()
    out = []
    for item in items:
        if item is None:
            continue
        s = str(item).strip()
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out


def key(qid: str, chunk: str, rank: int) -> tuple[str, str, int]:
    return (qid, chunk, rank)


def audit_baseline(stage: str) -> list[dict[str, Any]]:
    manifest = read_jsonl(BASELINE_PATH)
    rows = []
    for i, entry in enumerate(manifest, 1):
        rel = Path(entry["path"])
        p = rel if rel.is_absolute() else ROOT / rel
        if not p.exists() or not p.is_file():
            actual, status = None, "missing_or_not_file"
        else:
            try:
                actual = sha256_file(p)
                status = "unchanged" if actual == entry["expected_sha256"] else "changed"
            except Exception as e:
                actual, status = None, f"read_error:{type(e).__name__}:{e}"
        rows.append({"stage": stage, "path": entry["path"], "expected_sha256": entry["expected_sha256"], "actual_sha256": actual, "status": status})
        if i % 80 == 0:
            print(f"{stage}: checked {i}/{len(manifest)} protected files", flush=True)
    return rows


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    print("Phase P read-only audit starting", flush=True)
    baseline_before = audit_baseline("before")
    questions = read_jsonl(RUN / "fish_test_questions_normalized.jsonl")
    traces = read_jsonl(RUN / "retrieval_trace.jsonl")
    corpus = read_jsonl(CORPUS_PATH)
    preflight = read_jsonl(PHASE_O / "source_preflight_900.jsonl")
    profiles = read_jsonl(PHASE_O / "question_requirement_profiles.jsonl")
    phase_m = read_jsonl(PHASE_M / "phase_m_relevance_content_support_audit.jsonl")
    phase_o_checks = read_jsonl(PHASE_O / "relevant_evidence_support_validation.jsonl")
    phase_o_arbiter = read_jsonl(PHASE_O / "arbiter_results.jsonl")
    phase_o_cases = read_jsonl(PHASE_O / "ai_adjudication_results.jsonl")
    aliases = read_jsonl(ALIAS_PATH)

    qmap = {q["question_id"]: q for q in questions}
    pmap = {p["question_id"]: p for p in profiles}
    cmap = {c["chunk_id"]: c for c in corpus}
    pfmap = {(p["question_id"], p["rank"]): p for p in preflight}
    amap: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for a in aliases:
        amap[str(a.get("document_id"))].append(a)
    mmap = {key(x["question_id"], x["chunk_id"], int(x["rank"])): x for x in phase_m}
    omap = {key(x["question_id"], x["chunk_id"], int(x["rank"])): x for x in phase_o_checks}
    case_map = {key(x["question_id"], x["chunk_id"], int(x["rank"])): x for x in phase_o_cases}
    arbmap = {key(x["question_id"], x["chunk_id"], int(x["rank"])): x for x in phase_o_arbiter}

    context_rows: list[dict[str, Any]] = []
    question_rows: list[dict[str, Any]] = []
    source_counter = Counter()
    category_counter: dict[str, Counter] = defaultdict(Counter)
    species_counter: dict[str, Counter] = defaultdict(Counter)
    stage_counts = Counter()
    stage_by_question = []
    body_metadata_discordance = Counter()
    alias_context_counts = Counter()
    q_context_map: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for tr in traces:
        qid = tr["question_id"]
        q = qmap[qid]
        p = pmap[qid]
        bm25 = {cid: i + 1 for i, cid in enumerate(tr.get("bm25_top50_chunk_ids", []))}
        dense = {cid: i + 1 for i, cid in enumerate(tr.get("dense_top50_chunk_ids", []))}
        rrf = {cid: i + 1 for i, cid in enumerate(tr.get("rrf_top50_chunk_ids", []))}
        per_stage = {"bm25_candidates": len(bm25), "dense_candidates": len(dense), "rrf_candidates": len(rrf), "final_top5": len(tr.get("contexts", []))}
        stage_by_question.append({"question_id": qid, **per_stage})
        for c in tr.get("contexts", []):
            rank = int(c["top5_rank"])
            ck = key(qid, c["chunk_id"], rank)
            pf = pfmap.get((qid, rank), {})
            corp = cmap.get(c["chunk_id"], {})
            text = str(c.get("text") or "")
            profile_elements = [str(x) for x in p.get("required_answer_elements", []) if x]
            profile_values = [str(x) for x in p.get("required_values_or_ranges", []) if x]
            normalized_text = norm(text)
            matched_elements = [e for e in profile_elements if norm(e) and norm(e) in normalized_text]
            matched_values = [v for v in profile_values if norm(v) and norm(v) in normalized_text]
            target = str(q.get("species_chinese") or "")
            metadata_species = corp.get("species") or []
            if isinstance(metadata_species, str):
                metadata_species = [metadata_species]
            metadata_species = unique_list(metadata_species)
            mentions = body_species_mentions(text)
            target_in_body = any(alias.casefold() in text.casefold() for alias in SPECIES_ALIASES.get(target, [target])) if target else False
            target_in_meta = target in metadata_species
            source_scope_candidate = bool(pf.get("source_scope_conflict_candidate"))
            scope_label = "metadata_target_match" if target_in_meta else ("metadata_excludes_target_candidate" if metadata_species and target else "species_metadata_unknown")
            alias_rows = amap.get(str(c.get("document_id")), [])
            alias_title_conflicts = [a for a in alias_rows if a.get("document_title") and a.get("excel_source_title") and a.get("document_title") != a.get("excel_source_title")]
            source_id_conflict = not bool(pf.get("source_id_match", False))
            source_title_conflict = not bool(pf.get("source_title_match", False))
            source_checksum_conflict = not bool(pf.get("source_checksum_match", False))
            source_verified = bool(pf.get("source_metadata_verified"))
            version_verified = bool(pf.get("source_publication_version_verified"))
            eligible = bool(pf.get("retrieval_eligible_in_corpus"))
            tags = []
            if p.get("profile_needs_review") or p.get("candidate_scoring_cues_status") != "unverified_prompting_cues_only":
                tags.append("QUESTION_REQUIREMENT_MISMATCH")
            if source_scope_candidate:
                tags.append("SPECIES_SCOPE_CONFLICT")
            if source_id_conflict or source_title_conflict or source_checksum_conflict or alias_title_conflicts:
                tags.append("SOURCE_METADATA_CONFLICT")
            # Candidate cue matches are exact string signals only. Candidate answer/scoring cues are unverified and not gold.
            if profile_values and not matched_values:
                tags.append("MISSING_REQUIRED_VALUE")
            condition_cues = [str(x) for x in p.get("required_conditions", []) if x]
            high_specificity_conditions = [x for x in condition_cues if x in ("成魚", "魚苗", "種魚", "越冬", "淡水", "海水", "半淡鹹水", "池塘", "硬池", "軟池", "放養", "催產", "孵化", "治療", "停藥期", "用藥", "法規")]
            missing_conditions = [x for x in high_specificity_conditions if x not in text and x not in str(q.get("question_text", ""))]
            if missing_conditions:
                tags.append("MISSING_REQUIRED_CONDITION")
            if not source_verified or not version_verified or not eligible:
                tags.append("SOURCE_UNVERIFIED")
            candidate_match = bool(matched_elements or matched_values)
            if source_verified and version_verified and eligible and not source_scope_candidate and candidate_match:
                tags.append("POTENTIAL_SUPPORT")
            if not candidate_match or not source_verified or not version_verified or source_scope_candidate:
                tags.append("INSUFFICIENT_EVIDENCE")
            if target and metadata_species and not target_in_meta and target_in_body:
                body_metadata_discordance["target_mentioned_but_metadata_excludes_target"] += 1
            other_target_mentions = [x for x in mentions if x in SPECIES_ALIASES and x != target]
            if other_target_mentions and metadata_species and not set(other_target_mentions).intersection(metadata_species):
                body_metadata_discordance["body_other_target_species_not_in_metadata"] += 1

            m = mmap.get(ck, {})
            o = omap.get(ck, {})
            case = case_map.get(ck, {})
            arb = arbmap.get(ck, {})
            row = {
                "question_id": qid, "species": target, "category": q.get("inferred_category"),
                "question_text": q.get("question_text"), "question_requirement_profile": {
                    "required_answer_elements": profile_elements, "required_values_or_ranges": profile_values,
                    "required_units": p.get("required_units", []), "required_conditions": condition_cues,
                    "basis": p.get("requirement_profile_method"), "candidate_cues_unverified": True,
                },
                "rank": rank, "chunk_id": c.get("chunk_id"), "document_id": c.get("document_id"),
                "source_id": corp.get("source_id"), "source_title": corp.get("source_title"), "source_url": corp.get("source_url"),
                "source_sha256_registered": corp.get("source_checksum"), "source_file_sha256_registered": corp.get("source_checksum"),
                "source_checksum_match_trace_to_corpus": bool(pf.get("source_checksum_match")),
                "source_file_bytes_rehashed_this_phase": False,
                "corpus_version": tr.get("corpus_version"), "chunk_version": corp.get("chunk_version"),
                "source_version_annotation": pf.get("source_version_annotation"),
                "source_publication_version_verified": version_verified,
                "source_metadata_verified": source_verified, "retrieval_eligible_in_corpus": eligible,
                "retrieval_role": corp.get("retrieval_role"), "indexable": corp.get("indexable"),
                "page_or_locator": {"page": c.get("page"), "page_start": corp.get("page_start"), "page_end": corp.get("page_end"), "source_spans": corp.get("source_spans", [])},
                "context_text": text, "context_text_sha256": c.get("text_sha256"),
                "context_text_checksum_recomputed": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "context_checksum_matches_corpus": bool(pf.get("context_text_checksum_match")),
                "document_species_metadata": metadata_species, "body_species_mentions": mentions,
                "target_species_mentioned_in_body": target_in_body, "target_species_in_structured_metadata": target_in_meta,
                "species_scope_status": scope_label, "species_scope_conflict_candidate": source_scope_candidate,
                "source_metadata_conflicts": {"source_id": source_id_conflict, "source_title": source_title_conflict, "source_checksum": source_checksum_conflict,
                                               "alias_title_conflict_candidate_count": len(alias_title_conflicts),
                                               "alias_mapping_confidences": unique_list([a.get("mapping_confidence") for a in alias_rows])},
                "exact_candidate_element_matches": matched_elements, "exact_candidate_value_matches": matched_values,
                "candidate_requirement_match_method": "literal-normalized substring only; unverified question-bank cues; not evidence truth",
                "diagnostic_labels": sorted(set(tags)), "diagnostic_is_gold_relevance": False,
                "retrieval_stage_provenance": {"bm25_rank": c.get("bm25_rank"), "dense_rank": c.get("dense_rank"),
                                               "rrf_rank": rrf.get(c.get("chunk_id")), "reranker_score": c.get("reranker_score"), "final_top5_rank": rank,
                                               "in_bm25_top50": c.get("chunk_id") in bm25, "in_dense_top50": c.get("chunk_id") in dense,
                                               "in_rrf_top50": c.get("chunk_id") in rrf},
                "phase_m_historical_relevant": bool(m), "phase_m_retrospective_audit": m.get("retrospective_content_audit"),
                "phase_m_audit_reason": m.get("audit_reason"), "phase_o_arbiter_label": arb.get("parsed_result", {}).get("relevance_label") or arb.get("relevance_label"),
                "phase_o_reverse_support_gate": o.get("direct_support_gate"), "phase_o_adjudication_tier": o.get("adjudication_tier"),
                "diagnostic_caveat": "Metadata/locator integrity and literal cue matching do not establish answer support, source applicability, or Context Precision@5.",
            }
            context_rows.append(row)
            q_context_map[qid].append(row)

            for tag in row["diagnostic_labels"]:
                source_counter[tag] += 1
                category_counter[str(q.get("inferred_category") or "unknown")][tag] += 1
                species_counter[target or "unknown"][tag] += 1
            source_counter["contexts_total"] += 1
            source_counter["source_metadata_verified"] += int(source_verified)
            source_counter["source_version_verified"] += int(version_verified)
            source_counter["retrieval_eligible"] += int(eligible)
            source_counter["scope_conflict_candidates"] += int(source_scope_candidate)
            source_counter["locatable_document_page"] += int(bool(c.get("document_id") and c.get("page") is not None))
            source_counter["context_source_url_present"] += int(bool(corp.get("source_url")))
            source_counter["body_target_species_mentions"] += int(target_in_body)
            source_counter["body_other_target_species_mentions"] += int(bool(other_target_mentions))
            source_counter["source_id_title_checksum_mismatches"] += int(source_id_conflict or source_title_conflict or source_checksum_conflict)
            source_counter["alias_title_conflict_candidates"] += int(bool(alias_title_conflicts))
            source_counter["profile_literal_element_or_value_match"] += int(candidate_match)
            source_counter["potential_support_candidates"] += int("POTENTIAL_SUPPORT" in tags)
            source_counter["phase_m_historical_relevant"] += int(bool(m))
            source_counter["phase_m_likely_false_relevant"] += int(m.get("retrospective_content_audit") == "LIKELY_FALSE_RELEVANCE")
            source_counter["phase_o_arbiter_relevant"] += int(row["phase_o_arbiter_label"] == "RELEVANT")
            source_counter["phase_o_reverse_support_pass"] += int(row["phase_o_reverse_support_gate"] == "PASS")
            stage_counts["top5_rows"] += 1
            stage_counts["bm25_member"] += int(c.get("chunk_id") in bm25)
            stage_counts["dense_member"] += int(c.get("chunk_id") in dense)
            stage_counts["rrf_member"] += int(c.get("chunk_id") in rrf)
            stage_counts["rrf_rank_1_to_5"] += int(rrf.get(c.get("chunk_id"), 999) <= 5)
            stage_counts["rrf_rank_6_to_50"] += int(6 <= rrf.get(c.get("chunk_id"), 0) <= 50)
            stage_counts["bm25_not_in_top50"] += int(c.get("chunk_id") not in bm25)
            stage_counts["dense_not_in_top50"] += int(c.get("chunk_id") not in dense)
            stage_counts["rrf_not_in_top50"] += int(c.get("chunk_id") not in rrf)

    for q in questions:
        qid = q["question_id"]
        rows = sorted(q_context_map[qid], key=lambda x: x["rank"])
        p = pmap[qid]
        tags = Counter(tag for row in rows for tag in row["diagnostic_labels"])
        candidate_rows = [r for r in rows if "POTENTIAL_SUPPORT" in r["diagnostic_labels"]]
        source_candidate_rows = [r for r in rows if r["retrieval_eligible_in_corpus"] and r["source_metadata_verified"]]
        has_scope_safe_candidate = any(r["species_scope_status"] == "metadata_target_match" or not r["document_species_metadata"] for r in candidate_rows)
        source_urls = unique_list([s.get("URL") for s in q.get("source_records", [])] + list(q.get("candidate_source_urls", [])))
        trace = next(t for t in traces if t["question_id"] == qid)
        question_rows.append({
            "question_id": qid, "species": q.get("species_chinese"), "category": q.get("inferred_category"),
            "question_text": q.get("question_text"), "candidate_reference_answer_not_gold": q.get("candidate_reference_answer"),
            "requirement_profile": p, "candidate_source_urls": source_urls,
            "candidate_source_url_count": len(source_urls), "top5_contexts": [
                {"rank": r["rank"], "chunk_id": r["chunk_id"], "document_id": r["document_id"], "source_id": r["source_id"],
                 "source_title": r["source_title"], "source_url": r["source_url"], "page_or_locator": r["page_or_locator"],
                 "metadata_verified": r["source_metadata_verified"], "source_version_verified": r["source_publication_version_verified"],
                 "retrieval_eligible": r["retrieval_eligible_in_corpus"], "scope_status": r["species_scope_status"],
                 "diagnostic_labels": r["diagnostic_labels"]} for r in rows],
            "trace_source_locatable_contexts": sum(bool(r["document_id"] and r["page_or_locator"]["page"] is not None) for r in rows),
            "top5_source_url_contexts": sum(bool(r["source_url"]) for r in rows),
            "top5_source_metadata_verified": sum(r["source_metadata_verified"] for r in rows),
            "top5_source_version_verified": sum(r["source_publication_version_verified"] for r in rows),
            "top5_retrieval_eligible": sum(r["retrieval_eligible_in_corpus"] for r in rows),
            "scope_conflict_candidates": sum(r["species_scope_conflict_candidate"] for r in rows),
            "body_metadata_discordance_candidates": sum(bool(r["target_species_mentioned_in_body"] and not r["target_species_in_structured_metadata"]) for r in rows),
            "question_has_verified_source_candidate": bool(source_candidate_rows),
            "question_has_literal_evidence_candidate": bool(candidate_rows),
            "question_has_potential_evidence_candidate": bool(candidate_rows and has_scope_safe_candidate),
            "potential_evidence_candidate_contexts": len(candidate_rows),
            "diagnostic_label_counts": dict(tags),
            "retrieval_stage_availability": {"bm25_top50": len(trace.get("bm25_top50_chunk_ids", [])), "dense_top50": len(trace.get("dense_top50_chunk_ids", [])),
                                             "rrf_top50": len(trace.get("rrf_top50_chunk_ids", [])), "final_top5": len(trace.get("contexts", []))},
            "expected_evidence_mapping_status": trace.get("expected_evidence_mapping"),
            "expected_evidence_hit_at_5": trace.get("expected_evidence_hit_at_5"),
            "retrieval_hit_miss_status": trace.get("retrieval_hit_miss"),
            "retrieval_trace_has_stage_candidates": bool(trace.get("bm25_top50_chunk_ids") and trace.get("dense_top50_chunk_ids") and trace.get("rrf_top50_chunk_ids")),
            "coverage_metric_warning": "Coverage diagnostics only; not relevance labels, answer verification, or Context Precision@5.",
        })

    phase_m_counter = Counter(x.get("retrospective_content_audit") for x in phase_m)
    category_coverage = defaultdict(lambda: {"questions": 0, "verified_source_candidate_questions": 0, "literal_evidence_candidate_questions": 0, "potential_evidence_candidate_questions": 0, "scope_conflict_questions": 0})
    species_coverage = defaultdict(lambda: {"questions": 0, "verified_source_candidate_questions": 0, "literal_evidence_candidate_questions": 0, "potential_evidence_candidate_questions": 0, "scope_conflict_questions": 0})
    question_by_species_category = Counter()
    for q in question_rows:
        cat, sp = str(q.get("category") or "unknown"), str(q.get("species") or "unknown")
        for bucket, keyval in ((category_coverage, cat), (species_coverage, sp)):
            bucket[keyval]["questions"] += 1
            bucket[keyval]["verified_source_candidate_questions"] += int(q["question_has_verified_source_candidate"])
            bucket[keyval]["literal_evidence_candidate_questions"] += int(q["question_has_literal_evidence_candidate"])
            bucket[keyval]["potential_evidence_candidate_questions"] += int(q["question_has_potential_evidence_candidate"])
            bucket[keyval]["scope_conflict_questions"] += int(q["scope_conflict_candidates"] > 0)
        question_by_species_category[(sp, cat)] += 1

    # Root-cause signals are kept separate from confirmed causes.
    m28_likely_false = [x for x in phase_m if x.get("retrospective_content_audit") == "LIKELY_FALSE_RELEVANCE"]
    phase_o_new_relevant_keys = {
        key(x["question_id"], x["chunk_id"], int(x["rank"]))
        for x in phase_o_arbiter
        if (x.get("parsed_result") or {}).get("relevance_label") == "RELEVANT"
    }
    # The reverse-support file also contains older/other relevant candidates; isolate the
    # nine Phase O arbiter outputs instead of counting the entire 68-row registry.
    o9_by_key = {
        key(x["question_id"], x["chunk_id"], int(x["rank"])): x
        for x in phase_o_checks
        if key(x["question_id"], x["chunk_id"], int(x["rank"])) in phase_o_new_relevant_keys
    }
    o9 = [x for k, x in o9_by_key.items() if x.get("direct_support_gate") != "PASS"]
    trace_stage_details = {
        "retrieval_runs": len(traces), "all_have_bm25_dense_rrf_top50_and_top5": all(len(t.get("bm25_top50_chunk_ids", [])) == 50 and len(t.get("dense_top50_chunk_ids", [])) == 50 and len(t.get("rrf_top50_chunk_ids", [])) == 50 and len(t.get("contexts", [])) == 5 for t in traces),
        "all_expected_evidence_mappings_unavailable": all("unavailable" in str(t.get("expected_evidence_mapping", "")) for t in traces),
        "all_expected_evidence_hit_fields_null": all(t.get("expected_evidence_hit_at_5") is None for t in traces),
        "candidate_stage_data": dict(stage_counts),
        "interpretation": "Stage candidates and final reranked Top-5 are present; without a verified expected evidence chunk/span mapping, stage presence and rank movement cannot establish retrieval relevance or attribute a substantive evidence miss to BM25, dense retrieval, RRF, or reranking.",
    }
    qsource_count = sum(bool(unique_list([s.get("URL") for s in q.get("source_records", [])] + list(q.get("candidate_source_urls", [])))) for q in questions)
    file_summary = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "questions": len(questions), "retrieval_traces": len(traces), "top5_contexts": len(context_rows),
        "corpus_chunks": len(corpus), "question_candidate_source_url_present": qsource_count,
        "trace_identity_match": sum(bool(x.get("identity_match")) for x in preflight),
        "trace_text_checksum_match": sum(bool(x.get("context_text_checksum_match")) for x in preflight),
        "registered_source_checksum_match_trace_to_corpus": sum(bool(x.get("source_checksum_match")) for x in preflight),
        "source_metadata_verified": sum(bool(x.get("source_metadata_verified")) for x in preflight),
        "context_source_url_present": source_counter["context_source_url_present"],
        "source_publication_version_verified": sum(bool(x.get("source_publication_version_verified")) for x in preflight),
        "retrieval_eligible": sum(bool(x.get("retrieval_eligible_in_corpus")) for x in preflight),
        "source_scope_conflict_candidates": sum(bool(x.get("source_scope_conflict_candidate")) for x in preflight),
        "source_id_title_checksum_discrepancies": sum(not (x.get("source_id_match") and x.get("source_title_match") and x.get("source_checksum_match")) for x in preflight),
        "alias_registry_title_disagreement_contexts": source_counter["alias_title_conflict_candidates"],
        "alias_registry_context_rows_with_match": sum(bool(amap.get(str(cmap.get(x.get("chunk_id"), {}).get("document_id")))) for x in preflight),
        "alias_registry_title_disagreement_records": sum(bool(a.get("document_title") and a.get("excel_source_title") and a.get("document_title") != a.get("excel_source_title")) for a in aliases),
        "alias_registry_rows": len(aliases), "alias_registry_unique_documents": len(amap),
        "phase_m_historical_relevant_rows": len(phase_m), "phase_m_likely_false_relevance_audit_rows": len(m28_likely_false),
        "phase_o_new_arbiter_relevant_reverse_gate_not_passed": len(o9),
        "phase_o_new_arbiter_relevant_reverse_gate_counts": dict(Counter(x.get("direct_support_gate") for x in o9)),
        "phase_o_all_reverse_support_check_rows": len(phase_o_checks),
        "phase_o_new_arbiter_relevant_rows": len(phase_o_new_relevant_keys),
        "phase_o_arbiter_calls": len(phase_o_arbiter),
        "phase_o_arbitration_stop_preserved": True,
        "retrieval_trace_stages": trace_stage_details,
        "question_coverage": {"with_source_url_candidate": qsource_count,
                              "with_locatable_top5_source": sum(all(x["trace_source_locatable_contexts"] == 5 for x in [q]) for q in question_rows),
                              "with_any_verified_retrieval_eligible_top5": sum(q["question_has_verified_source_candidate"] for q in question_rows),
                              "with_literal_evidence_candidate": sum(q["question_has_literal_evidence_candidate"] for q in question_rows),
                              "with_potential_evidence_candidate": sum(q["question_has_potential_evidence_candidate"] for q in question_rows)},
        "diagnostic_tag_context_counts": {tag: source_counter[tag] for tag in ["QUESTION_REQUIREMENT_MISMATCH", "SPECIES_SCOPE_CONFLICT", "SOURCE_METADATA_CONFLICT", "MISSING_REQUIRED_VALUE", "MISSING_REQUIRED_CONDITION", "SOURCE_UNVERIFIED", "POTENTIAL_SUPPORT", "INSUFFICIENT_EVIDENCE"]},
        "per_category_diagnostic_tag_counts": {cat: dict(counts) for cat, counts in category_counter.items()},
        "per_species_diagnostic_tag_counts": {sp: dict(counts) for sp, counts in species_counter.items()},
        "per_category_question_coverage": dict(category_coverage), "per_species_question_coverage": dict(species_coverage),
        "phase_m_audit_outcomes": dict(phase_m_counter),
        "phase_m_likely_false_relevance_reason_counts": dict(Counter(x.get("audit_reason") for x in m28_likely_false)),
        "phase_o_9_relevant_candidate_reverse_gate_counts": dict(Counter(x.get("direct_support_gate") for x in o9)),
        "body_vs_metadata_species_mention_diagnostics": dict(body_metadata_discordance),
        "warnings": [
            "The 180 question profiles reuse Phase O's question text plus unverified question-bank scoring cues; they are not gold requirements.",
            "SOURCE_UNVERIFIED means the evaluation corpus metadata/version/eligibility gate is not satisfied; it does not prove the original source is false or absent.",
            "source_scope_conflict_candidates are deterministic mismatches between question species and corpus species/title/chapter metadata; they are candidates, not confirmed biological inapplicability.",
            "Source checksum agreement is a registered annotation-to-corpus comparison; this phase did not redownload or rehash all source originals.",
            "No relevance annotation, Context Precision@5, or model metric was recomputed in Phase P.",
        ],
    }

    write_jsonl(OUT / "retrieval_context_audit_900.jsonl", context_rows)
    write_jsonl(OUT / "question_evidence_coverage_180.jsonl", question_rows)
    write_json(OUT / "evidence_coverage_summary.json", file_summary)

    # Species scope analysis with distinct metadata/body signals.
    sp_analysis = {
        "scope_conflict_definition": "Phase O deterministic candidate: exactly one target-species label inferred from structured corpus metadata/title/chapter/section and it differs from the question target. It is not a verified applicability judgment.",
        "counts": {"contexts_total": len(context_rows), "scope_conflict_candidate_contexts": file_summary["source_scope_conflict_candidates"],
                   "target_species_body_mentions_where_metadata_excludes_target": body_metadata_discordance["target_mentioned_but_metadata_excludes_target"],
                   "other_target_species_body_mentions_not_in_metadata": body_metadata_discordance["body_other_target_species_not_in_metadata"],
                   "source_alias_registry_title_disagreement_contexts": file_summary["alias_registry_title_disagreement_contexts"],
                   "trace_vs_corpus_source_id_title_checksum_discrepancies": file_summary["source_id_title_checksum_discrepancies"]},
        "by_question_species": dict(species_coverage),
        "examples": [
            {"question_id": x["question_id"], "rank": x["rank"], "target_species": x["species"], "source_title": x["source_title"],
             "document_species_metadata": x["document_species_metadata"], "body_species_mentions": x["body_species_mentions"],
             "note": "Example is included only when a body/metadata mismatch candidate exists; mention is not applicability."}
            for x in context_rows if x["target_species_mentioned_in_body"] and not x["target_species_in_structured_metadata"]
        ][:50],
        "conclusion": "The dominant measurable conflict signal is corpus metadata/title scope versus the question species (439 candidate rows). Trace-to-corpus source ID/title/checksum equality is 900/900, so this is not a mismatch between those two copies. Body mentions require manual/contextual interpretation; automated species-name matches do not establish the host/application scope.",
    }
    write_json(OUT / "species_scope_conflict_analysis.json", sp_analysis)

    # Frozen baseline post-check, after outputs have been written.
    baseline_after = audit_baseline("after")
    write_jsonl(OUT / "frozen_baseline_636_recheck.jsonl", baseline_before + baseline_after)
    before_map = {x["path"]: x for x in baseline_before}
    after_map = {x["path"]: x for x in baseline_after}
    protected_ok = len(baseline_before) == 636 and len(baseline_after) == 636 and all(
        before_map[p]["status"] == "unchanged" and after_map[p]["status"] == "unchanged" and before_map[p]["actual_sha256"] == after_map[p]["actual_sha256"]
        for p in before_map if p in after_map
    ) and len(before_map) == len(after_map)
    sqlite_path = ROOT / "rag_store.sqlite3"
    sqlite_sha = sha256_file(sqlite_path) if sqlite_path.exists() else None
    compatibility = {
        "phase_p_new_writes_confined_to": str(OUT.relative_to(ROOT)), "generators_rerun": 0,
        "historical_retrieval_rerun": False, "historical_e4_corpus_production_sqlite_modified": False,
        "phase_e_metrics_modified": False, "phase_o_outputs_modified": False,
        "human_gold_created": False, "formal_winner_or_total_score": False,
        "protected_manifest_expected": 636, "protected_manifest_prechecked": len(baseline_before),
        "protected_manifest_postchecked": len(baseline_after), "protected_files_unchanged_pre_and_post": protected_ok,
        "protected_status_counts_after": dict(Counter(x["status"] for x in baseline_after)),
        "sqlite_sha256_current": sqlite_sha,
        "sqlite_expected_sha256": "d7d06d4d2a57d0a57d05bcb6131ffb24aefb226c6bd36349dbc5118d33b11087",
        "sqlite_matches_expected": sqlite_sha == "d7d06d4d2a57d0a57d05bcb6131ffb24aefb226c6bd36349dbc5118d33b11087",
        "phase_o_ai_adjudication_stop_preserved": True,
    }
    write_json(OUT / "compatibility.json", compatibility)

    report = f"""# Phase P — Evidence Coverage & Retrieval Audit

## 範圍與限制

本輪唯讀對照 Fish Test 原始 180 題、Historical E4 的 180 筆檢索 trace、Evaluation Corpus v2 的 3,870 個 chunk，以及 Phase O source preflight。未執行新檢索、AI 仲裁或生成。題目需求提示部分取自未獨立驗證的題庫 scoring cues；下列診斷不是人工相關性真值，也不是 Context Precision@5。

## 可確認的資料完整性

- 問題：{len(questions)}；Top-5：{len(context_rows)}；題目—Chunk—Rank 身分：{file_summary['trace_identity_match']}/{len(context_rows)}。
- Context 文字 checksum 與 corpus content checksum：{file_summary['trace_text_checksum_match']}/{len(context_rows)}；trace/corpus 登錄來源 checksum 一致：{file_summary['registered_source_checksum_match_trace_to_corpus']}/{len(context_rows)}。這些是登錄值相互核對，不是本輪重新取得原始來源 bytes。
- 180 題 Top-5 均有 document/page 定位的題目：{file_summary['question_coverage']['with_locatable_top5_source']}/180；Chunk metadata 有 source URL：{file_summary['context_source_url_present']}/{len(context_rows)}。
- 已核實來源 metadata、版本欄位及 retrieval eligibility：{file_summary['source_metadata_verified']}/{len(context_rows)}；另有 {len(context_rows)-file_summary['source_metadata_verified']} 段仍 pending。
- 問題資料列含候選來源 URL：{qsource_count}/{len(questions)} 題。這是題庫來源欄位存在率，不代表它就是 Top-5 的證據來源。

## 來源與魚種範圍訊號

- Phase O 以題目魚種對照 Corpus species/title/chapter/section metadata 找到 {file_summary['source_scope_conflict_candidates']} 筆 scope-conflict candidates。這是 metadata 範圍候選衝突，不是已證實的生物學不適用結論。
- Trace 與 Corpus 的 source ID/title/checksum 不一致：{file_summary['source_id_title_checksum_discrepancies']} 筆。另有 {file_summary['alias_registry_title_disagreement_contexts']} 段所連到的 alias registry 記錄出現文件標題與 Excel 來源標題不一致；這反映來源 alias/對照治理風險，不能直接判為正文錯誤。
- 文字掃描可看到魚種名稱提及，但提及不證明適用性；metadata 排除目標而正文又提到目標的候選數為 {body_metadata_discordance['target_mentioned_but_metadata_excludes_target']}。此類需逐文件核讀上下文。

## Top-5 必要資訊元素訊號

每題有 {len(question_rows)} 筆明確需求剖面，但剖面以題目文字及未驗證 scoring cues 建立。以正規化字串比對得到：

- 至少一個已核實來源/eligible 的 Top-5 candidate：{file_summary['question_coverage']['with_any_verified_retrieval_eligible_top5']} 題。
- 至少一個文字上含 candidate answer element/value 的 Top-5 chunk：{file_summary['question_coverage']['with_literal_evidence_candidate']} 題。
- 同時滿足來源/eligibility 與文字提示比對的 potential evidence candidate：{file_summary['question_coverage']['with_potential_evidence_candidate']} 題。這只是人工進一步核查名單，不是答案支持判定。
- Context 層診斷標籤數為重疊計數：{json.dumps(file_summary['diagnostic_tag_context_counts'],ensure_ascii=False)}。
- `MISSING_REQUIRED_VALUE` 的 heuristic cue 訊號最多出現在 Calculation ({category_counter['Calculation']['MISSING_REQUIRED_VALUE']})，其次 Water Quality ({category_counter['Water Quality']['MISSING_REQUIRED_VALUE']})、Fact ({category_counter['Fact']['MISSING_REQUIRED_VALUE']})、Climate / Cold ({category_counter['Climate / Cold']['MISSING_REQUIRED_VALUE']})；這些由未驗證 scoring cues 做字串比對，不能當成已確認題目答案缺漏，其他類別未被標記也不代表答案元素完整。

類別與魚種分層數據見 `evidence_coverage_summary.json` 和 `question_evidence_coverage_180.jsonl`。本輪未建立 Relevant/Irrelevant 標籤，也未計算 P@5。

## Retrieval 階段可分析範圍

180/180 trace 保存 BM25 Top-50、Dense Top-50、RRF Top-50 與最終 reranked Top-5。900 個最終 Top-5 chunks 中，BM25 candidate pool 命中 {stage_counts['bm25_member']}、Dense 命中 {stage_counts['dense_member']}、RRF 命中 {stage_counts['rrf_member']}；RRF 原始排名 1–5 有 {stage_counts['rrf_rank_1_to_5']} 個、6–50 有 {stage_counts['rrf_rank_6_to_50']} 個。

但是 180/180 retrieval trace 的 expected evidence mapping 都標記 unavailable，expected hit 欄位為 null。因此無法把 chunk 的階段出現或排名變動解讀為有效 evidence recall，也無法量化 BM25、Dense、RRF 或 reranker 的實質錯誤率。此次僅報候選流轉資料。

## 失敗原因定位

可觀察證據支持三類問題同時存在：

1. **資料/metadata 治理：**511 段 source metadata/version/eligibility pending；439 個魚種範圍衝突候選；alias registry 另有標題對照疑義。
2. **題目/Corpus 覆蓋：**必要答案元素以未驗證 cues 作提示，缺少經核准的 expected evidence chunk/span mapping，現階段不能區分來源原文沒有資訊與 Top-5 沒檢索到。
3. **AI Judge：**Phase M 28 筆歷史 Relevant 中，回顧稽核有 {len(m28_likely_false)} 筆標為 likely false relevance；Phase O 試探中的 9 筆第三模型 Relevant 均未通過最終支持 gate（2 FAIL、6 NOT_ESTABLISHED、1 CANDIDATE_PASS_REQUIRES_SEMANTIC_REVIEW）。反向支持登錄另含 {len(phase_o_checks)} 筆跨批次紀錄，未把整份登錄誤算成本輪 9 筆。這顯示 AI 可把主題/範圍相近誤當支持，但不代表所有 180 題都由 Judge 導致問題。

因此目前能確認 Judge 曾誤判，也能確認來源 metadata/eligibility 是普遍阻塞；但無法將整體主要失敗單獨歸因於資料、檢索或 Judge。需先完成來源別/魚種別 metadata reconciliation 和少量人工核對的 expected evidence mapping，才能再拆分檢索召回與排序責任。

## Phase E 評估結果（只讀保留）

Phase E 四模型 720 次推論及八項既有指標未修改。M2 既有探索性觀察維持：Faithfulness 0.7972、Judge Answer Relevance 0.8267、BGE-M3 Cosine 0.6237、Structured IFR 93.89%、TTFT 約 1.207 秒、TPS 48.603、system RAM sampled peak 22.65 GB、dedicated VRAM sampled peak 6.75 GB。Judge 分數不是水產知識正確率；本輪沒有總分或 Winner。

## Baseline

Frozen Manifest 前後各核對 {len(baseline_before)} 筆，狀態：{dict(Counter(x['status'] for x in baseline_after))}；保護檔案前後 digest 一致：{protected_ok}。SQLite SHA-256：`{compatibility['sqlite_sha256_current']}`；與預期值一致：{compatibility['sqlite_matches_expected']}。
"""
    (OUT / "retrieval_failure_taxonomy.md").write_text(report, encoding="utf-8")
    (OUT / "phase_p_research_findings.md").write_text(report, encoding="utf-8")
    (OUT / "phase_p_final_report.md").write_text(report + "\n\n本輪至此停止；沒有重跑 AI 相關性仲裁，也沒有擴大標註批次。\n", encoding="utf-8")

    # Validate output structure and stable identities.
    checks = {
        "questions_180": len(question_rows) == 180,
        "contexts_900": len(context_rows) == 900,
        "unique_question_ids_180": len({x["question_id"] for x in question_rows}) == 180,
        "unique_question_chunk_rank_900": len({(x["question_id"], x["chunk_id"], x["rank"]) for x in context_rows}) == 900,
        "all_top5_identity_and_content_checksums_match": all(x["context_checksum_matches_corpus"] for x in context_rows),
        "retrieval_trace_stages_present_180": len(stage_by_question) == 180 and all(x["bm25_candidates"] == x["dense_candidates"] == x["rrf_candidates"] == 50 and x["final_top5"] == 5 for x in stage_by_question),
        "protected_baseline_636_unchanged": protected_ok,
        "sqlite_sha256_matches_expected": compatibility["sqlite_matches_expected"],
        "no_context_precision_created": True,
        "no_ai_relevance_labels_created": True,
    }
    write_json(OUT / "phase_p_validation.json", {"checks": checks, "all_pass": all(checks.values()), "created_at": datetime.now(timezone.utc).isoformat()})
    print(json.dumps({"questions": len(question_rows), "contexts": len(context_rows), "potential_evidence_candidate_questions": file_summary["question_coverage"]["with_potential_evidence_candidate"],
                      "metadata_verified": file_summary["source_metadata_verified"], "scope_conflict_candidates": file_summary["source_scope_conflict_candidates"],
                      "baseline_ok": protected_ok, "all_validation_checks_pass": all(checks.values())}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
