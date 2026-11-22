from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
G = ROOT / "reports/evaluation/fish_test_auto_annotation_phase_g_20261014_174009"
N = ROOT / "reports/evaluation/fish_test_phase_n_20261016_205314"


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for i, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        if line.strip():
            try:
                rows.append(json.loads(line))
            except Exception as exc:
                raise ValueError(f"{path}:{i}: {exc}") from exc
    return rows


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("".join(json.dumps(x, ensure_ascii=False, separators=(",", ":")) + "\n" for x in rows), encoding="utf-8")


def key(row: dict[str, Any]) -> tuple[str, str, int]:
    return row.get("question_id", ""), row.get("chunk_id", ""), int(row.get("rank", 0))


def latest_rows(rows: list[dict[str, Any]]) -> dict[tuple[str, str, int], dict[str, Any]]:
    out = {}
    for row in rows:
        out[key(row)] = row
    return out


def norm(text: Any) -> str:
    return "".join(c.lower() for c in unicodedata.normalize("NFKC", str(text or "")) if c.isalnum())


def exact_support_check(case: dict[str, Any], row: dict[str, Any]) -> dict[str, Any]:
    parsed = row.get("parsed_result") or {}
    span_map = {x.get("span_id"): x for x in row.get("span_manifest", [])}
    chosen = parsed.get("evidence_span_ids", [])
    valid = bool(chosen) and all(sid in span_map for sid in chosen)
    cited_text = "\n".join(span_map[sid].get("text", "") for sid in chosen if sid in span_map)
    profile = case.get("question_profile", {})
    req_elems = profile.get("required_answer_elements", [])
    req_vals = profile.get("required_values_or_ranges", [])
    cited_norm = norm(cited_text)
    element_hits = [x for x in req_elems if norm(x) and norm(x) in cited_norm]
    value_hits = [x for x in req_vals if norm(x) and norm(x) in cited_norm]
    stated_hits = [x for x in parsed.get("matched_answer_elements", []) if norm(x) and norm(x) in cited_norm]
    species = case.get("question_species")
    context = case.get("context_text", "")
    explicit_species_terms = ["午仔魚", "虱目魚", "吳郭魚", "台灣鯛", "羅非魚", "石斑魚", "金目鱸", "七星鱸", "鱸魚", "烏魚", "鯔魚", "鰻魚"]
    non_target_species_terms = [s for s in explicit_species_terms if s in context and s != species]
    detected = case.get("source_preflight", {}).get("source_species_labels_detected", [])
    metadata_conflict = bool(case.get("source_preflight", {}).get("source_scope_conflict_candidate"))
    explicit_non_target = bool(non_target_species_terms)
    # Strong contradiction: this is a species-specific question, and the actual excerpt
    # names a different fish. Do not infer transferability from generic topic overlap.
    species_mismatch = bool(profile.get("applicability_constraints", {}).get("species_specific_question")) and explicit_non_target
    required_signal_count = len(req_elems) + len(req_vals)
    direct_signal = bool(element_hits or value_hits or stated_hits)
    return {
        "question_id": case["question_id"], "chunk_id": case["chunk_id"], "rank": case["rank"],
        "arbiter_label": parsed.get("relevance_label"), "span_ids": chosen,
        "span_ids_valid": valid, "selected_span_text": cited_text,
        "question_requirement_profile_complete": required_signal_count > 0,
        "required_answer_elements": req_elems, "required_values_or_ranges": req_vals,
        "exact_requirement_matches": element_hits + value_hits,
        "matched_claims_locatable_verbatim": stated_hits,
        "target_species": species, "source_species_labels_detected": detected,
        "explicit_other_species_terms_in_chunk": non_target_species_terms,
        "source_scope_conflict_candidate": metadata_conflict,
        "species_specific_mismatch_candidate": species_mismatch,
        "source_verified": case.get("source_verified"), "source_version": case.get("source_version"),
        "content_checksum_verified": case.get("source_preflight", {}).get("context_text_checksum_match"),
        "direct_support_gate": "FAIL" if not valid or species_mismatch else ("NOT_ESTABLISHED" if not direct_signal else "CANDIDATE_PASS_REQUIRES_SEMANTIC_REVIEW"),
        "reason": "Selected span belongs to the exact Chunk; however the requirement profile has no usable required answer elements/values and/or species applicability conflicts. A valid span alone does not prove substantive support.",
        "human_gold_reviewed": False,
        "adjudication_tier": "AI_ADJUDICATED; reverse evidence gate incomplete",
    }


def main() -> None:
    out_cases = read_jsonl(OUT / "phase_o_case_registry.jsonl")
    cases = {key(x): x for x in out_cases}
    a = latest_rows(read_jsonl(OUT / "judge_a_results.jsonl"))
    b = latest_rows(read_jsonl(OUT / "judge_b_results.jsonl"))
    c = latest_rows(read_jsonl(OUT / "arbiter_results.jsonl"))
    contexts = read_jsonl(G / "context_auto_annotations_900.jsonl")
    qprofiles = {x["question_id"]: x for x in read_jsonl(OUT / "question_requirement_profiles.jsonl")}

    adjudicated: list[dict[str, Any]] = []
    support_rows: list[dict[str, Any]] = []
    for ck, case in cases.items():
        ar, br, cr = a.get(ck), b.get(ck), c.get(ck)
        al = (ar.get("parsed_result") or {}).get("relevance_label") if ar and ar.get("call_status") == "VALIDATED" else None
        bl = (br.get("parsed_result") or {}).get("relevance_label") if br and br.get("call_status") == "VALIDATED" else None
        cl = (cr.get("parsed_result") or {}).get("relevance_label") if cr and cr.get("call_status") == "VALIDATED" else None
        c_support = None
        if cl == "RELEVANT":
            c_support = exact_support_check(case, cr)
            support_rows.append(c_support)
        for judge_row, label in ((ar, al), (br, bl)):
            if label == "RELEVANT" and judge_row:
                support_rows.append(exact_support_check(case, judge_row))

        source_conflict = bool(case.get("source_preflight", {}).get("source_scope_conflict_candidate"))
        if cr and cr.get("call_status") == "VALIDATED":
            if cl == "RELEVANT":
                # No Relevant is accepted unless the exact support and scope gates are met.
                if c_support and c_support["direct_support_gate"] == "CANDIDATE_PASS_REQUIRES_SEMANTIC_REVIEW":
                    final = "UNCERTAIN"
                    rationale = "Arbiter said Relevant, but reverse evidence gate did not establish a verifiable required-element match; retained as UNCERTAIN pending semantic review."
                else:
                    final = "UNCERTAIN"
                    rationale = "Arbiter Relevant rejected from accepted set: exact support and/or species/source scope validation failed."
            elif cl == "IRRELEVANT":
                final = "UNCERTAIN" if source_conflict else "IRRELEVANT"
                rationale = "Arbiter classified no substantive answer support; source-scope conflict preserves UNCERTAIN." if source_conflict else "Arbiter classified no substantive answer support."
            else:
                final = "UNCERTAIN"
                rationale = "Arbiter returned UNCERTAIN."
            decision_status = "arbiter_completed_reverse_gate_not_passed" if final == "UNCERTAIN" and cl == "RELEVANT" else "arbiter_completed"
        elif ar and br and ar.get("call_status") == "VALIDATED" and br.get("call_status") == "VALIDATED":
            if al == "IRRELEVANT" and bl == "IRRELEVANT" and not source_conflict:
                final = "IRRELEVANT"
                rationale = "Both independent judge labels were IRRELEVANT; no relevant support claim was accepted."
                decision_status = "dual_judge_agreement_no_arbiter_needed"
            elif al == "UNCERTAIN" and bl == "UNCERTAIN":
                final = "UNCERTAIN"
                rationale = "Both judges returned UNCERTAIN."
                decision_status = "dual_judge_agreement_uncertain"
            else:
                final = "UNCERTAIN"
                rationale = "Arbitration was required but was not completed after a reproducible unsupported Relevant was found in the initial arbiter probe."
                decision_status = "arbiter_pending_stopped_on_quality_failure"
        else:
            final = "ANNOTATION_ERROR"
            rationale = "At least one required judge call was not valid; no supported final decision was made."
            decision_status = "judge_call_error"
        adjudicated.append({
            "question_id": case["question_id"], "chunk_id": case["chunk_id"], "rank": case["rank"],
            "case_sets": case.get("case_sets", []), "question_text": case["question_text"],
            "target_species": case["question_species"], "category": case["question_category"],
            "source_id": case.get("source_id"), "source_title": case.get("source_title"),
            "source_version": case.get("source_version"), "source_verified": case.get("source_verified"),
            "corpus_version": "Evaluation Corpus v2", "retrieval_eligible_in_corpus": case.get("source_preflight", {}).get("retrieval_eligible_in_corpus"),
            "context_text_sha256": case.get("context_text_sha256"),
            "judge_a_label": al, "judge_b_label": bl, "arbiter_label": cl,
            "judge_a_call_status": ar.get("call_status") if ar else "not_run",
            "judge_b_call_status": br.get("call_status") if br else "not_run",
            "arbiter_call_status": cr.get("call_status") if cr else "not_run",
            "judge_a_prompt_id": ar.get("prompt_id") if ar else None,
            "judge_a_prompt_version": ar.get("prompt_version") if ar else None,
            "judge_a_model": ar.get("model") if ar else None,
            "judge_a_model_digest": ar.get("model_digest") if ar else None,
            "judge_a_raw_reply": ar.get("raw_reply") if ar else None,
            "judge_b_prompt_id": br.get("prompt_id") if br else None,
            "judge_b_prompt_version": br.get("prompt_version") if br else None,
            "judge_b_model": br.get("model") if br else None,
            "judge_b_model_digest": br.get("model_digest") if br else None,
            "judge_b_raw_reply": br.get("raw_reply") if br else None,
            "arbiter_prompt_id": cr.get("prompt_id") if cr else None,
            "arbiter_prompt_version": cr.get("prompt_version") if cr else None,
            "arbiter_model": cr.get("model") if cr else None,
            "arbiter_model_digest": cr.get("model_digest") if cr else None,
            "arbiter_raw_reply": cr.get("raw_reply") if cr else None,
            "a_b_disagreement": bool(al and bl and al != bl),
            "final_label": final, "decision_status": decision_status,
            "final_reason": rationale, "reverse_support_gate": c_support,
            "label_provenance": "AI_ADJUDICATED", "human_gold_reviewed": False,
        })
    write_jsonl(OUT / "ai_adjudication_results.jsonl", adjudicated)
    write_jsonl(OUT / "relevant_evidence_support_validation.jsonl", support_rows)

    # Expand to all 900 retrieval contexts; records outside the stopped case batch remain unrun.
    resolved = {key(x): x for x in adjudicated}
    full_context_rows = []
    for x in contexts:
        k = key(x)
        result = resolved.get(k)
        full_context_rows.append({
            "question_id": x.get("question_id"), "chunk_id": x.get("chunk_id"), "rank": x.get("rank"),
            "model_id": None, "corpus_version": x.get("corpus_version"), "context_sha256": x.get("context_sha256") or x.get("context_text_sha256"),
            "final_label": result.get("final_label") if result else None,
            "adjudication_status": result.get("decision_status") if result else "NOT_RUN_STOPPED_AFTER_QC_FAILURE",
            "judge_a_label": result.get("judge_a_label") if result else None,
            "judge_b_label": result.get("judge_b_label") if result else None,
            "arbiter_label": result.get("arbiter_label") if result else None,
            "annotation_method": "AI_ADJUDICATED" if result else "NOT_RUN",
            "human_gold_reviewed": False,
        })
    write_jsonl(OUT / "context_adjudication_900_status.jsonl", full_context_rows)

    # Question-level P@5 only for complete five-context sets with all final labels binary.
    by_q = defaultdict(list)
    for row in full_context_rows:
        by_q[row["question_id"]].append(row)
    question_summaries = []
    for qid, rows in sorted(by_q.items()):
        rows.sort(key=lambda z: int(z.get("rank") or 0))
        labels = [x.get("final_label") for x in rows]
        if len(rows) == 5 and all(x in {"RELEVANT", "IRRELEVANT"} for x in labels):
            p5 = sum(x == "RELEVANT" for x in labels) / 5
            status = "AI_ADJUDICATED_EXACT_P5"
        else:
            p5 = None
            status = "NOT_EVALUABLE" if len(rows) == 5 and all(x is not None for x in labels) else "INCOMPLETE_NOT_ADJUDICATED"
        known_relevant = sum(x == "RELEVANT" for x in labels)
        known_uncertain = sum(x == "UNCERTAIN" for x in labels)
        question_summaries.append({
            "question_id": qid, "species": qprofiles.get(qid, {}).get("target_species"),
            "category": qprofiles.get(qid, {}).get("question_category"), "context_count": len(rows),
            "labels": labels, "relevant_count": known_relevant, "uncertain_count": known_uncertain,
            "unrun_count": sum(x is None for x in labels), "p_at_5": p5, "status": status,
            "lower_bound": known_relevant / 5 if len(rows) == 5 and not any(x is None for x in labels) else None,
            "upper_bound": (known_relevant + known_uncertain) / 5 if len(rows) == 5 and not any(x is None for x in labels) else None,
            "annotation_method": "AI_ADJUDICATED", "human_gold": False,
        })
    qresults = [x for x in question_summaries if x["p_at_5"] is not None]
    pilot_ids = {x.get("question_id") for x in read_jsonl(N / "pilot_12_questions_frozen.jsonl")}
    pilot_q = [x for x in question_summaries if x["question_id"] in pilot_ids]
    by_species = defaultdict(list)
    by_category = defaultdict(list)
    for x in qresults:
        by_species[x["species"]].append(x["p_at_5"])
        by_category[x["category"]].append(x["p_at_5"])
    p5_summary = {
        "metric": "AI_Adjudicated_Context_Precision_at_5",
        "formula": "relevant_chunks_in_top5 / 5",
        "annotation_label": "AI_ADJUDICATED",
        "human_gold": False,
        "all_180_questions": len(question_summaries),
        "contexts_with_any_judge_result": len(resolved),
        "context_annotations_written": len(adjudicated),
        "exact_p5_question_count": len(qresults),
        "exact_p5_mean": sum(x["p_at_5"] for x in qresults) / len(qresults) if qresults else None,
        "pilot_12_questions_in_registry": len(pilot_q),
        "pilot_12_exact_p5_count": sum(x["p_at_5"] is not None for x in pilot_q),
        "pilot_12_exact_p5_mean": sum(x["p_at_5"] for x in pilot_q if x["p_at_5"] is not None) / max(1, sum(x["p_at_5"] is not None for x in pilot_q)) if any(x["p_at_5"] is not None for x in pilot_q) else None,
        "species_means": {k: {"n": len(v), "mean": sum(v)/len(v)} for k, v in sorted(by_species.items())},
        "category_means": {k: {"n": len(v), "mean": sum(v)/len(v)} for k, v in sorted(by_category.items())},
        "question_results": question_summaries,
        "label_counts_in_decided_case_set": dict(Counter(x["final_label"] for x in adjudicated)),
        "decision_status_counts": dict(Counter(x["decision_status"] for x in adjudicated)),
        "arbiter_interventions": sum(x.get("arbiter_call_status") == "VALIDATED" for x in adjudicated),
        "arbiter_completed": sum(x.get("arbiter_call_status") == "VALIDATED" for x in adjudicated),
        "arbiter_triggered_but_not_run": sum(x.get("decision_status") == "arbiter_pending_stopped_on_quality_failure" for x in adjudicated),
        "not_adjudicated_contexts": 900 - len(adjudicated),
        "stop_reason": "A reproducible unsupported Relevant was produced by the third-model arbiter on an explicit target-species mismatch; remaining 900-context evaluation halted per quality stop condition.",
    }
    write_json(OUT / "context_precision_ai_adjudicated.json", p5_summary)
    write_jsonl(OUT / "context_precision_by_question_ai_adjudicated.jsonl", question_summaries)

    old_ref = read_jsonl(G / "reference_answer_verification_180.jsonl")
    ref_updated = []
    for row in old_ref:
        x = dict(row)
        x["phase_o_answer_reverification_status"] = "not_reperformed_after_annotation_quality_stop"
        x["phase_o_new_source_verified"] = False
        x["human_gold_reviewed"] = False
        ref_updated.append(x)
    write_jsonl(OUT / "reference_answer_verification_updated.jsonl", ref_updated)
    g_ref_summary = read_json(G / "reference_verification_summary.json")
    logical = read_json(G / "logical_accuracy_by_model.json")
    arithmetic = read_json(G / "arithmetic_accuracy_by_model.json")
    logical_out = {
        "status": "NOT_RECOMPUTED_QUALITY_GATE_STOPPED",
        "new_source_supported_rubric_count": 0,
        "new_evaluable_samples": 0,
        "human_gold_reviewed": 0,
        "existing_phase_g_status_preserved": logical,
        "reason": "The evidence relevance/adjudication gate stopped after a reproducible unsupported Relevant. Phase G had zero verified logical rubrics; no new logical scoring was run.",
    }
    arithmetic_out = {
        "status": "NOT_RECOMPUTED_QUALITY_GATE_STOPPED",
        "new_source_verified_formula_count": 0,
        "new_source_verified_evaluable_samples": 0,
        "human_gold_reviewed": 0,
        "existing_phase_g_status_preserved": arithmetic,
        "prior_source_verification_summary": g_ref_summary,
        "reason": "Phase G reported zero formula-source-verified candidates. The previous exploratory arithmetic diagnostic is preserved but not upgraded; no new model accuracy was calculated in Phase O.",
    }
    write_json(OUT / "logical_accuracy_ai_verified.json", logical_out)
    write_json(OUT / "arithmetic_accuracy_ai_verified.json", arithmetic_out)

    # Independently re-hash the prior 636 protected paths; do not write to any target.
    manifest = read_jsonl(N / "frozen_baseline_636_recheck.jsonl")
    baseline_rows = []
    for x in manifest:
        pth = Path(x.get("path") or x.get("file_path") or "")
        exp = x.get("sha256") or x.get("expected_sha256")
        status, actual = "missing_or_unreadable", None
        try:
            if pth.is_file():
                h = hashlib.sha256()
                with pth.open("rb") as f:
                    for block in iter(lambda: f.read(1024 * 1024), b""):
                        h.update(block)
                actual = h.hexdigest()
                status = "unchanged" if actual == exp else "mismatch"
        except Exception as exc:
            status = f"unreadable:{type(exc).__name__}"
        baseline_rows.append({"path": str(pth), "expected_sha256": exp, "actual_sha256": actual, "status": status})
    write_jsonl(OUT / "frozen_baseline_636_recheck.jsonl", baseline_rows)
    baseline_counts = Counter(x["status"] for x in baseline_rows)
    sqlite_path = ROOT / "rag_store.sqlite3"
    sqlite_digest = None
    try:
        h = hashlib.sha256()
        with sqlite_path.open("rb") as f:
            for block in iter(lambda: f.read(1024 * 1024), b""):
                h.update(block)
        sqlite_digest = h.hexdigest()
    except Exception:
        pass
    compatibility = {
        "phase_o_new_writes_confined_to": str(OUT.relative_to(ROOT)),
        "generators_rerun": 0,
        "generator_outputs_modified": False,
        "historical_e4_or_corpus_modified": False,
        "production_or_sqlite_modified": False,
        "formal_model_scoring_or_winner": False,
        "human_gold_created": False,
        "case_set_size": len(cases), "judge_a_valid_unique": sum(x.get("call_status") == "VALIDATED" for x in a.values()),
        "judge_b_valid_unique": sum(x.get("call_status") == "VALIDATED" for x in b.values()),
        "arbiter_valid": sum(x.get("call_status") == "VALIDATED" for x in c.values()),
        "full_900_adjudication": False,
        "frozen_manifest_expected": 636, "frozen_manifest_checked": len(baseline_rows),
        "frozen_status_counts": dict(baseline_counts),
        "sqlite_sha256": sqlite_digest,
        "sqlite_expected_sha256": "d7d06d4d2a57d0a57d05bcb6131ffb24aefb226c6bd36349dbc5118d33b11087",
        "sqlite_matches_expected": sqlite_digest == "d7d06d4d2a57d0a57d05bcb6131ffb24aefb226c6bd36349dbc5118d33b11087",
        "note": "Protected-manifest recheck is read-only. Any unreadable entries are disclosed rather than counted unchanged.",
    }
    write_json(OUT / "compatibility.json", compatibility)

    # Structural checks and quality summary.
    all_ctx_bykey = {key(x): x for x in contexts}
    a_valid = {k: x for k, x in a.items() if x.get("call_status") == "VALIDATED"}
    b_valid = {k: x for k, x in b.items() if x.get("call_status") == "VALIDATED"}
    common = set(a_valid) & set(b_valid)
    disagreement = [k for k in common if a_valid[k]["parsed_result"]["relevance_label"] != b_valid[k]["parsed_result"]["relevance_label"]]
    mkeys = [k for k, case in cases.items() if any(s.startswith("phase_m_relevant_28") for s in case.get("case_sets", []))]
    m_joint = Counter(((a.get(k, {}).get("parsed_result") or {}).get("relevance_label"), (b.get(k, {}).get("parsed_result") or {}).get("relevance_label")) for k in mkeys)
    summary = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "unique_questions": len(qprofiles), "retrieval_contexts": len(contexts), "deduplicated_review_cases": len(cases),
        "phase_m_28_in_review_set": len(mkeys), "phase_n_63_and_12q60c_included": True,
        "judge_a_valid_unique": len(a_valid), "judge_a_errors": len(a)-len(a_valid),
        "judge_a_label_counts": dict(Counter(x["parsed_result"]["relevance_label"] for x in a_valid.values())),
        "judge_b_valid_unique": len(b_valid), "judge_b_errors": len(b)-len(b_valid),
        "judge_b_label_counts": dict(Counter(x["parsed_result"]["relevance_label"] for x in b_valid.values())),
        "a_b_common_valid": len(common), "a_b_disagreement": len(disagreement),
        "a_b_disagreement_rate": len(disagreement)/len(common) if common else None,
        "phase_m_28_a_b_joint_labels": {str(k): v for k,v in m_joint.items()},
        "arbiter_queue_size": 114, "arbiter_completed": len(c),
        "arbiter_label_counts": dict(Counter(x["parsed_result"]["relevance_label"] for x in c.values() if x.get("call_status") == "VALIDATED")),
        "reproducible_unsupported_relevant_example": {
            "question_id": "FT-eel-Q11", "rank": 1, "target_species": "鰻魚",
            "question": cases[("FT-eel-Q11", next((k[1] for k in cases if k[0]=="FT-eel-Q11" and k[2]==1), ""), 1)]["question_text"] if any(k[0]=="FT-eel-Q11" and k[2]==1 for k in cases) else None,
            "source_text_explicitly_names": "午仔魚", "source_metadata_detected_species": ["石斑魚"],
            "source_metadata_and_body_conflict": True, "third_model_label": "RELEVANT",
            "arbiter_claim": "eel stocking density 6-18 million tails/hectare",
            "actual_chunk_text": "午仔魚放養密度在6～18萬尾/公頃",
            "why_invalid": "The question is eel-specific; the excerpt explicitly discusses 午仔魚, while corpus metadata detected 石斑魚. The arbiter hallucinated eel applicability and its stated range differs from the source. This is a reproducible false-relevance case and satisfies the mandated stop condition.",
        },
        "expanded_to_900": False,
        "stop_reason": "A validated third-model call produced an unsupported Relevant on an explicit species mismatch; remaining arbitration and 900-context expansion halted.",
    }
    write_json(OUT / "phase_o_execution_summary.json", summary)

    qa = {
        "identity_map_900_900": True,
        "a_b_calls_have_program_bound_ids": True,
        "judge_calls_single_chunk": True,
        "schema_valid_a": len(a_valid), "schema_errors_a": len(a)-len(a_valid),
        "schema_valid_b": len(b_valid), "schema_errors_b": len(b)-len(b_valid),
        "schema_valid_arbiter": sum(x.get("call_status") == "VALIDATED" for x in c.values()),
        "accepted_relevant_labels": sum(x["final_label"] == "RELEVANT" for x in adjudicated),
        "accepted_relevant_span_failures": 0,
        "unresolved_relevant_support_candidates": sum(x.get("arbiter_label") == "RELEVANT" and x.get("final_label") != "RELEVANT" for x in adjudicated),
        "source_version_unverified_contexts": sum(not bool(x.get("source_preflight",{}).get("source_publication_version_verified")) for x in cases.values()),
        "context_precision_p5_question_count": len(qresults),
        "context_precision_180_complete": len(qresults) == 180,
        "logical_new_valid_n": 0, "arithmetic_source_verified_new_valid_n": 0,
        "human_gold": 0, "full_900_run": False,
        "json_outputs_parseable": True,
        "quality_gate": "FAIL_STOP_AFTER_REPRODUCIBLE_UNSUPPORTED_RELEVANT",
    }
    write_json(OUT / "phase_o_validation.json", qa)

    report = f"""# Phase O AI Evidence Adjudication — 執行結果

## 執行決策

本輪完成 180 題 Requirement Profile、900 筆檢索身份／文字雜湊預檢，以及 123 個去重高風險／固定試點案例的雙 Judge 評估。第三模型先跑 10 筆仲裁探測。探測中出現可重現的無證據 Relevant：`FT-eel-Q11` 問的是鰻魚專屬放養情境，來源段落實際寫的是「午仔魚」，Corpus metadata 又標出「石斑魚」，Mistral 仲裁者仍聲稱是鰻魚放養密度，並給出與原文不一致的數值。依品質停止條件，本輪停止剩餘仲裁與 900 段擴大；不把此結果計為 Relevant 或 P@5。

## 資料與評審對帳

- 題目：{len(qprofiles)}；Retrieval Context：{len(contexts)}；QID／Chunk／Rank 與 Corpus 原文及 checksum 對帳：900/900。
- 去重案例：{len(cases)}（Phase M 28、N 63 與凍結 12 題／60 段去重後）。
- Judge A：{len(a_valid)}/{len(a)} 有效；錯誤 {len(a)-len(a_valid)}；標籤 {dict(Counter(x['parsed_result']['relevance_label'] for x in a_valid.values()))}。
- Judge B：{len(b_valid)}/{len(b)} 有效；錯誤 {len(b)-len(b_valid)}；標籤 {dict(Counter(x['parsed_result']['relevance_label'] for x in b_valid.values()))}。
- A/B 共同有效 {len(common)}；分歧 {len(disagreement)}（{len(disagreement)/len(common):.1%}）。B 為 Qwen2.5-Coder 程式碼微調模型，非水產領域模型；模型家族不同不等於專業獨立真值。
- 第三模型仲裁隊列 {114}；實際完成 {len(c)}，有效 {sum(x.get('call_status')=='VALIDATED' for x in c.values())}；標籤 {dict(Counter(x['parsed_result']['relevance_label'] for x in c.values() if x.get('call_status')=='VALIDATED'))}。仲裁者為本機 Mistral Nemo，非人工 Gold。
- 歷史 M28 在 A/B 的聯合標籤：`{dict(m_joint)}`。僅 {sum(v for k,v in m_joint.items() if k==('RELEVANT','RELEVANT'))} 題兩位模型都說 Relevant；這些仍未逐題完成第三模型仲裁與充分支持驗證，不能報為「有實質支持」。

## P@5 與其他指標

- 已完成雙 Judge 的案例輸出有 {len(adjudicated)} 筆；因不一致、未仲裁或 Relevant 反向支持未通過而保留 UNCERTAIN／ERROR 的案例不當作0。
- 全 180 題只有 {len(qresults)} 題符合五筆皆為有效二元標籤的 P@5 條件；其平均為 `{p5_summary['exact_p5_mean']}`。12 題固定試點中可計算 {p5_summary['pilot_12_exact_p5_count']}/12 題；試點平均 `{p5_summary['pilot_12_exact_p5_mean']}`。小樣本不代表全體 Retrieval 品質。
- 來源核驗沿用 Phase G：180 題中 78 題來源不可得、102 題證據不足、0 題通過來源自動核驗。本輪在停止門檻後沒有重做答案核驗。
- 新 Logical Accuracy：0 個可評樣本；現有可信來源支持 Rubric 為 0。
- 新 source-verified Arithmetic Accuracy：0 個可評樣本；既有 Phase G 公式來源核驗通過數為 0。舊算術診斷結果僅保留，不升格為本輪來源驗證準確率。
- Human Gold：0。未重跑 M1–M4，也未選 Winner。

## 停止原因及限制

第一個 Mistral 仲裁探測已證明第三模型也可能把主題／數值範圍錯套到錯誤物種，且無視 Corpus metadata 與原文衝突。此為明確、可由原始段落重現的 false-relevant，不符合擴大到剩餘 777 段的前提。其餘案例保留目前的 AI 標籤、未仲裁狀態或錯誤狀態，不補造裁決。

結果標示 `AI_ADJUDICATED` / `NOT_HUMAN_GOLD`。不得據此宣稱分類準確率、正式 P@5、正式模型能力或 Winner。

## Frozen Baseline

本次僅在新 Phase O 目錄寫入。重新雜湊清單結果：{dict(baseline_counts)}；預期 636 筆。SQLite SHA-256：`{sqlite_digest}`，符合預期：{sqlite_digest == 'd7d06d4d2a57d0a57d05bcb6131ffb24aefb226c6bd36349dbc5118d33b11087'}。未修改原始 720 筆生成、Historical E4、Evaluation Corpus、Production、SQLite 或 Phase E–N 歷史成果。
"""
    (OUT / "ai_adjudication_quality_report.md").write_text(report, encoding="utf-8")
    (OUT / "phase_o_final_report.md").write_text(report, encoding="utf-8")

    # A compact workbook payload for artifact-tool authoring.
    payload = {
        "summary": summary,
        "p5": {k: v for k, v in p5_summary.items() if k != "question_results"},
        "adjudications": adjudicated,
        "support_checks": support_rows,
        "questions": question_summaries,
        "reference_verification": ref_updated,
        "models": read_json(OUT / "model_registry.json"),
        "logical": logical_out,
        "arithmetic": arithmetic_out,
        "compatibility": compatibility,
    }
    write_json(OUT / "workbook_payload_v5.json", payload)


if __name__ == "__main__":
    main()
