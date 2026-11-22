from __future__ import annotations
import collections
import datetime as dt
import hashlib
import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
WORK = Path(__file__).resolve().parent
DB = WORK / "corpus" / "marine_hybrid_rag_corpus_v3.sqlite3"
PROTECTED_DB = ROOT / "rag_store.sqlite3"
EXPECTED_PROTECTED_DB_SHA = "d7d06d4d2a57d0a57d05bcb6131ffb24aefb226c6bd36349dbc5118d33b11087"


def read_json(path: Path):
    text = path.read_text(encoding="utf-8")
    # A previous PowerShell-assisted manifest update left the two literal
    # characters backslash+n after the JSON document. Normalize only these
    # isolated generated workspace files before validating them.
    if text.endswith("\\n"):
        text = text[:-2] + "\n"
    return json.loads(text)


def read_jsonl(path: Path):
    out = []
    with path.open("r", encoding="utf-8-sig") as f:
        for no, line in enumerate(f, 1):
            if line.strip():
                try:
                    out.append(json.loads(line))
                except Exception as exc:
                    raise ValueError(f"Invalid JSONL: {path}:{no}: {exc}") from exc
    return out


def write_json(path: Path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows):
    path.write_text("".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows), encoding="utf-8")


def sha256_file(path: Path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def main():
    checks = []

    def check(name, passed, detail):
        checks.append({"check": name, "status": "PASS" if passed else "FAIL", "detail": detail})

    manifest = read_json(WORK / "corpus_v3_manifest.json")
    write_json(WORK / "corpus_v3_manifest.json", manifest)
    db_validation = read_json(WORK / "corpus_build_db_validation.json")
    write_json(WORK / "corpus_build_db_validation.json", db_validation)
    source_reg = read_json(WORK / "source_admission_v3.json")
    sources = source_reg["sources"]
    raw_integrity = read_json(WORK / "official_raw_data_integrity_report.json")
    dgbas = read_json(WORK / "dgbas_admission_revalidation.json")
    duplicate_report = read_json(WORK / "duplicate_group_registration_validation.json")
    retrieval = read_jsonl(WORK / "retrieval_results_v3_180.jsonl")
    labels = read_jsonl(WORK / "retrieved_context_relevance_labels.jsonl")
    supports = read_jsonl(WORK / "evidence_support_verification_180.jsonl")
    eligibility = read_jsonl(WORK / "question_eligibility_180.jsonl")
    requirements = read_jsonl(WORK / "question_requirement_profiles_180.jsonl")
    refs_v3 = read_jsonl(WORK / "verified_reference_answers_180.jsonl")
    smoke = read_jsonl(WORK / "generator_smoke_results.jsonl")
    e2e = read_json(WORK / "rag_v3_real_e2e_validation.json")
    streamlit = read_json(WORK / "streamlit_v3_validation.json")
    coverage = read_json(WORK / "six_species_evidence_coverage.json")
    evidence_summary = read_json(WORK / "retrieval_and_evidence_summary.json")

    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    db_integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
    db_sources = [dict(r) for r in con.execute("SELECT source_id,source_sha256,title AS source_title,publisher FROM sources ORDER BY source_id")]
    db_counts = {
        "source_count": con.execute("SELECT COUNT(*) FROM sources").fetchone()[0],
        "source_record_count": con.execute("SELECT COUNT(*) FROM source_records").fetchone()[0],
        "chunk_count": con.execute("SELECT COUNT(*) FROM chunks").fetchone()[0],
        "retrieval_eligible_chunk_count": con.execute("SELECT COUNT(*) FROM chunks WHERE retrieval_eligible=1").fetchone()[0],
        "context_only_chunk_count": con.execute("SELECT COUNT(*) FROM chunks WHERE retrieval_status='CONTEXT_ONLY'").fetchone()[0],
        "fts_row_count": con.execute("SELECT COUNT(*) FROM chunks_fts").fetchone()[0],
        "embedding_count": con.execute("SELECT COUNT(*) FROM chunks WHERE embedding IS NOT NULL").fetchone()[0],
        "embedding_dimensions": sorted({r[0] for r in con.execute("SELECT DISTINCT embedding_dimension FROM chunks WHERE embedding IS NOT NULL")}),
        "distinct_duplicate_groups": con.execute("SELECT COUNT(DISTINCT duplicate_group_id) FROM source_records WHERE duplicate_group_id IS NOT NULL").fetchone()[0],
        "duplicate_group_members": con.execute("SELECT COUNT(*) FROM source_records WHERE duplicate_group_id IS NOT NULL").fetchone()[0],
    }
    chunk_map = {r[0]: dict(r) for r in con.execute("SELECT chunk_id,source_id,source_record_id,source_sha256,locator,source_quote,retrieval_status,retrieval_eligible FROM chunks")}
    source_map = {r[0]: dict(r) for r in con.execute("SELECT source_record_id,source_id,duplicate_group_id FROM source_records")}
    con.close()
    current_db_sha = sha256_file(DB)

    check("corpus_sqlite_integrity", db_integrity == "ok", {"integrity_check": db_integrity})
    check("corpus_counts_match_manifest", all([
        db_counts["source_count"] == manifest["source_count"],
        db_counts["source_record_count"] == manifest["source_records"],
        db_counts["chunk_count"] == manifest["chunks"],
        db_counts["retrieval_eligible_chunk_count"] == manifest["retrieval_eligible_chunks"],
        db_counts["context_only_chunk_count"] == manifest["context_only_chunks"],
    ]), {"db": db_counts, "manifest": {k: manifest.get(k) for k in ["source_count", "source_records", "chunks", "retrieval_eligible_chunks", "context_only_chunks"]}})
    check("fts_and_embedding_row_counts", db_counts["fts_row_count"] == db_counts["retrieval_eligible_chunk_count"] == db_counts["embedding_count"], db_counts)
    check("embedding_dimension", db_counts["embedding_dimensions"] == [1024], db_counts["embedding_dimensions"])
    check("manifest_database_sha256", manifest["sqlite"]["database_sha256"] == current_db_sha, {"manifest": manifest["sqlite"]["database_sha256"], "actual": current_db_sha})
    check("three_approved_official_raw_json_hashes", all(s.get("sha256_matches") and s.get("json_parse_status") == "PASS" for s in raw_integrity["sources"]), [{"file": s["file"], "size": s["actual_size_bytes"], "records": s["actual_records"], "sha256": s["actual_sha256"], "status": s["status"]} for s in raw_integrity["sources"]])
    check("dgbas_limited_admission_revalidation", dgbas["status"] == "PASS" and dgbas["mismatches"] == [] and dgbas["provenance_rows"] == dgbas["exact_xml_value_matches"], dgbas)
    check("source_registry_exactly_four_sources", {s["source_id"] for s in db_sources} == {"MOA-TFRI-OPEN-114846", "MOA-ANIMAL-DRUG-OPEN-7274", "MOA-EEL-STOCKING-OPEN-41845", "DGBAS-79395-2020"}, db_sources)
    check("no_eel_stocking_chunks_retrieval_eligible", conclusive_eel := db_counts["context_only_chunk_count"] == 9 and all(c["retrieval_status"] != "RETRIEVAL_ELIGIBLE" for c in chunk_map.values() if c["source_id"] == "MOA-EEL-STOCKING-OPEN-41845"), {"eel_context_only_chunks": 9, "no_year": True})
    check("exact_duplicate_groups_registered_without_deleting_records", duplicate_report["status"] == "PASS" and duplicate_report["duplicate_group_count"] == 2 and duplicate_report["source_records"] == db_counts["source_record_count"], duplicate_report)

    qids = [r["question_id"] for r in retrieval]
    label_keys = [(r["question_id"], r["rank"]) for r in labels]
    retrieval_sha_values = {r.get("corpus_sha256") for r in retrieval}
    dangling = []
    stale_sources = []
    repeated_dup_groups = []
    context_rows = 0
    dist = collections.Counter()
    for row in retrieval:
        top = row.get("top5", [])
        context_rows += len(top)
        dist[len(top)] += 1
        seen_groups = set()
        for hit in top:
            cid = hit.get("chunk_id")
            c = chunk_map.get(cid)
            if not c:
                dangling.append({"question_id": row["question_id"], "chunk_id": cid, "reason": "chunk_id_not_in_db"})
                continue
            if c["source_id"] != hit.get("source_id") or c["source_record_id"] != hit.get("source_record_id"):
                stale_sources.append({"question_id": row["question_id"], "chunk_id": cid, "retrieval_source": hit.get("source_id"), "db_source": c["source_id"]})
            rec = source_map.get(c["source_record_id"], {})
            group = rec.get("duplicate_group_id")
            if group and group in seen_groups:
                repeated_dup_groups.append({"question_id": row["question_id"], "duplicate_group_id": group})
            if group:
                seen_groups.add(group)
    check("180_questions_unique_and_retrieval_corpus_hash_current", len(retrieval) == 180 and len(set(qids)) == 180 and retrieval_sha_values == {current_db_sha}, {"retrieval_rows": len(retrieval), "unique_question_ids": len(set(qids)), "corpus_hashes": sorted(str(x) for x in retrieval_sha_values), "db_sha256": current_db_sha})
    check("all_top5_chunk_provenance_resolves", len(dangling) == 0 and len(stale_sources) == 0, {"context_rows": context_rows, "dangling": dangling[:20], "source_mismatches": stale_sources[:20]})
    check("no_duplicate_identity_group_repeated_within_question_top5", len(repeated_dup_groups) == 0, repeated_dup_groups[:20])
    check("context_annotation_rows_match_retrieval_contexts", len(labels) == context_rows and len(supports) == context_rows and len(set(label_keys)) == len(label_keys), {"retrieved_contexts": context_rows, "labels": len(labels), "support_rows": len(supports), "unique_question_rank": len(set(label_keys))})
    check("question_level_tables_have_180_unique_ids", all(len(x) == 180 and len({r["question_id"] for r in x}) == 180 for x in [eligibility, requirements, refs_v3]), {"eligibility": len(eligibility), "profiles": len(requirements), "reference_records": len(refs_v3)})
    check("e2e_and_streamlit_use_current_v3", e2e.get("corpus", {}).get("database_sha256") == current_db_sha and streamlit.get("result", {}).get("corpus", {}).get("database_sha256") == current_db_sha and streamlit.get("status") == "PASS", {"db_sha256": current_db_sha, "e2e_sha": e2e.get("corpus", {}).get("database_sha256"), "streamlit_sha": streamlit.get("result", {}).get("corpus", {}).get("database_sha256"), "streamlit_status": streamlit.get("status")})
    check("four_model_smoke_calls_present", e2e.get("real_generator_calls") == 4 and {r.get("model", {}).get("model_id") for r in smoke if r.get("scenario") == "SUPPORTED_POSITIVE_REAL_GENERATOR"} == {"M1", "M2", "M3", "M4"}, {"real_generator_calls": e2e.get("real_generator_calls"), "models": [r.get("model", {}).get("tag") for r in smoke if r.get("scenario") == "SUPPORTED_POSITIVE_REAL_GENERATOR"]})
    check("metric_denominators_remain_unscored_without_labels_or_rubrics", evidence_summary["p_at_5"]["evaluable_exact_p5_questions"] == 0 and evidence_summary["logical_accuracy"]["N"] == 0 and evidence_summary["arithmetic_accuracy"]["N"] == 0, {"p_at_5": evidence_summary["p_at_5"], "logical_accuracy": evidence_summary["logical_accuracy"], "arithmetic_accuracy": evidence_summary["arithmetic_accuracy"]})

    # Revalidate the 15 earlier Phase AA candidates only against exact source IDs present here.
    aa_path = ROOT / "reports" / "evaluation" / "fish_test_phase_aa_20261019_220906" / "reference_answers_frozen.jsonl"
    aa_rows = read_jsonl(aa_path)
    corpus_source_ids = {s["source_id"] for s in db_sources}
    old_refs = []
    for r in aa_rows:
        old_sid = r.get("source_id")
        in_corpus = old_sid in corpus_source_ids
        old_refs.append({
            "question_id": r.get("question_id"),
            "species": r.get("species"),
            "historical_verification_status": r.get("verification_status"),
            "historical_source_id": old_sid,
            "historical_source_version": r.get("source_version"),
            "source_id_present_in_corpus_v3": in_corpus,
            "revalidation_status": "NOT_REVALIDATED_SOURCE_NOT_IN_CORPUS_V3" if not in_corpus else "REQUIRES_EXACT_SPAN_RECHECK",
            "reference_answer_carried_forward": False,
            "human_gold_status": "NOT_HUMAN_GOLD",
            "reason": "Phase AA source material is not among the four admitted Corpus v3 sources; historical verification is preserved but not inherited into this Corpus version."
        })
    write_jsonl(WORK / "previous_reference_candidates_revalidation_15.jsonl", old_refs)

    # Recheck the designated 636-entry frozen baseline, independently of the 58k inventory.
    protected_baseline_path = ROOT / "reports" / "evaluation" / "final_model_selection" / "phase20" / "protected_inputs_before.json"
    pb = read_json(protected_baseline_path)
    protected_rows = pb.get("files", pb.get("entries", []))
    protected_results = []
    for row in protected_rows:
        rel = Path(row["path"])
        path = ROOT / rel
        expected = row.get("sha256") or row.get("expected_sha256")
        if not path.exists():
            protected_results.append({"path": row["path"], "status": "MISSING", "expected_sha256": expected})
            continue
        actual = sha256_file(path)
        protected_results.append({"path": row["path"], "status": "UNCHANGED" if actual == expected else "MISMATCH", "expected_sha256": expected, "actual_sha256": actual})
    protected_counts = collections.Counter(r["status"] for r in protected_results)
    protected_db_actual = sha256_file(PROTECTED_DB)
    protected_report = {
        "checked_at_local": dt.datetime.now().astimezone().isoformat(),
        "manifest_path": str(protected_baseline_path), "expected_entry_count": pb.get("file_count"), "checked_entry_count": len(protected_results),
        "status_counts": dict(protected_counts), "unchanged": protected_counts["UNCHANGED"],
        "mismatches": [r for r in protected_results if r["status"] == "MISMATCH"], "missing": [r for r in protected_results if r["status"] == "MISSING"],
        "production_sqlite": {"path": str(PROTECTED_DB), "expected_sha256": EXPECTED_PROTECTED_DB_SHA, "actual_sha256": protected_db_actual, "matches": protected_db_actual == EXPECTED_PROTECTED_DB_SHA},
    }
    write_json(WORK / "protected_manifest_recheck_post.json", protected_report)
    check("frozen_manifest_636_unchanged", len(protected_results) == 636 and protected_counts["UNCHANGED"] == 636 and protected_counts["MISMATCH"] == 0 and protected_counts["MISSING"] == 0, {k: protected_report[k] for k in ["expected_entry_count", "checked_entry_count", "status_counts"]})
    check("formal_sqlite_hash_unchanged", protected_db_actual == EXPECTED_PROTECTED_DB_SHA, protected_report["production_sqlite"])

    # Persist technical validation separately from professional-answer scoring.
    validation = {
        "run_at_local": dt.datetime.now().astimezone().isoformat(),
        "corpus_id": manifest["corpus_id"], "corpus_version": manifest["corpus_version"], "database_sha256": current_db_sha,
        "counts": db_counts, "question_count": len(retrieval), "retrieval_context_count": context_rows,
        "context_count_distribution": {str(k): v for k, v in sorted(dist.items())},
        "evidence_diagnostic_status_counts": dict(collections.Counter(r.get("evidence_status") for r in labels)),
        "question_eligibility_counts": dict(collections.Counter(r.get("eligibility_status") for r in eligibility)),
        "automated_checks": checks,
        "all_automated_checks_pass": all(x["status"] == "PASS" for x in checks),
        "metric_status": {"context_precision_at_5": "NOT_EVALUABLE_NO_RELIABLE_BINARY_RELEVANCE_LABELS", "logical_accuracy": "NOT_EVALUABLE_NO_FROZEN_CORPUS_SUPPORTED_RUBRIC", "arithmetic_accuracy": "NOT_EVALUABLE_NO_VERIFIED_FORMULA_REFERENCE_SUBSET", "human_gold": 0},
        "protected_baseline": protected_report,
    }
    write_json(WORK / "corpus_v3_integrity_validation.json", validation)

    pytest_report = {
        "status": "NOT_RUN_PYTEST_UNAVAILABLE",
        "requested_command": ".venv\\Scripts\\python.exe -m pytest tests/ --basetemp <phase workspace>\\pytest_basetemp -q",
        "reason": "pytest is not installed in the project venv, reranker venv, system Python, or bundled Python runtime. No dependency installation or network workaround was attempted.",
        "pytest_collection_count": None, "passed": None, "failed": None, "skipped": None,
        "separate_integrity_validation": "corpus_v3_integrity_validation.json",
    }
    write_json(WORK / "repository_pytest_results.json", pytest_report)

    species_rows = []
    for species, data in coverage["species"].items():
        species_rows.append({"species": species, **data})
    species_rows.sort(key=lambda r: r["species"])
    pipeline_totals = {}
    for key in ["bm25_returned", "dense_returned", "rrf_fused_unique_chunks", "rrf_after_record_dedupe", "source_scope_pass", "source_scope_excluded", "reranker_candidates", "final_top_k"]:
        pipeline_totals[key] = sum(r.get("candidate_counts", {}).get(key, 0) for r in retrieval)

    model_rows = []
    model_summary = {}
    smoke_all = []
    for r in smoke:
        scenario = r.get("scenario")
        m = r.get("model", {})
        mid = m.get("model_id") or r.get("model_id")
        citation_obj = r.get("citation_validation") if isinstance(r.get("citation_validation"), dict) else {}
        final_response_obj = r.get("final_response") if isinstance(r.get("final_response"), dict) else {}
        final_answer_obj = final_response_obj.get("answer") if isinstance(final_response_obj.get("answer"), dict) else {}
        smoke_all.append({"scenario": scenario, "model_id": mid, "model_tag": m.get("tag"), "model_digest": m.get("digest"),
                          "answer_origin": r.get("answer_origin"), "evidence_state": r.get("evidence_decision", {}).get("state"),
                          "generator_called": r.get("raw_model_response") is not None, "citation_status": citation_obj.get("status"),
                          "final_answer_status": final_answer_obj.get("status"), "error": r.get("error")})
        if scenario == "SUPPORTED_POSITIVE_REAL_GENERATOR":
            model_rows.append({"model_id": mid, "tag": m.get("tag"), "digest": m.get("digest"), "answer_origin": r.get("answer_origin"),
                               "evidence_state": r.get("evidence_decision", {}).get("state"), "structured_response_valid": r.get("parsed_response") is not None,
                               "citation_status": r.get("citation_validation", {}).get("status"), "citation_reason": r.get("citation_validation", {}).get("reason"),
                               "raw_generator_called": r.get("raw_model_response") is not None, "error": r.get("error"), "scenario": scenario})
            model_summary[mid] = model_rows[-1]
    readiness = {
        "corpus_version": manifest["corpus_version"], "database_sha256": current_db_sha,
        "technical_system_status": "PARTIAL_PASS_REAL_SMOKE_AND_STREAMLIT_PASS; REPOSITORY_PYTEST_NOT_RUN_DEPENDENCY_MISSING",
        "question_count": len(retrieval), "questions_with_any_context": evidence_summary["questions_with_any_context"], "questions_full_top5": evidence_summary["questions_full_top5"],
        "retrieval_pipeline_candidate_totals": pipeline_totals,
        "answer_evidence_status_counts": dict(collections.Counter(r.get("eligibility_status") for r in eligibility)),
        "previous_13_auto_verified_candidates_revalidated_in_corpus_v3": sum(r["source_id_present_in_corpus_v3"] for r in old_refs if r["historical_verification_status"] == "SOURCE_VERIFIED_AUTOMATED"),
        "previous_reference_candidate_revalidation_count": len(old_refs),
        "reference_answer_and_rubric_count_frozen_for_current_corpus": 0,
        "context_precision_at_5_evaluable_questions": 0, "logical_accuracy_evaluable_samples": 0, "arithmetic_accuracy_evaluable_samples": 0,
        "human_gold_count": 0,
        "next_720_run_ready": False,
        "blocking_reasons": ["No current-Corpus exact FULL_SUPPORT answers were established by the conservative evidence screen.", "No validated human or independent binary Top-5 relevance labels, so P@5 cannot be calculated.", "No source-verified logical or arithmetic rubric subset is available in this Corpus version.", "Repository pytest could not run because pytest is absent from available Python environments."],
        "model_smoke": model_rows, "streamlit_validation": {"status": streamlit.get("status"), "assertions": streamlit.get("assertions")},
        "evaluation_readiness_distinction": {"technical_readiness": "smoke plus Streamlit AppTest passed; repository pytest remains unrun", "metric_scoring_readiness": "not ready for P@5/logical/arithmetic accuracy", "species_representativeness": "limited to literal-scope official Q&A/permit facts; not a six-species comprehensive technical corpus"},
    }
    write_json(WORK / "evaluation_readiness_v3.json", readiness)

    # Data extracts for the local Excel builder.
    workbook_data = {
        "dashboard": {"corpus_id": manifest["corpus_id"], "corpus_version": manifest["corpus_version"], "database_sha256": current_db_sha,
                      "sources": db_counts["source_count"], "distinct_source_sha256": len({x["source_sha256"] for x in db_sources}),
                      "source_records": db_counts["source_record_count"], "chunks": db_counts["chunk_count"], "retrieval_eligible_chunks": db_counts["retrieval_eligible_chunk_count"],
                      "context_only_chunks": db_counts["context_only_chunk_count"], "questions": len(retrieval), "with_context": evidence_summary["questions_with_any_context"],
                      "full_top5": evidence_summary["questions_full_top5"], "context_rows": context_rows, "full_support_diagnostics": 0,
                      "eligible_p5_questions": 0, "eligible_logical": 0, "eligible_arithmetic": 0, "human_gold": 0},
        "sources": [{"source_id": s["source_id"], "dataset_id": s.get("dataset_id"), "title": s.get("title"), "publisher": s.get("publisher"), "dataset_url": s.get("dataset_url"),
                     "resource_url": s.get("resource_url"), "source_sha256": s.get("source_sha256"), "file_size_bytes": s.get("file_size_bytes"), "owner_admission_status": s.get("owner_admission_status"),
                     "license_scope_status": s.get("license_scope_status"), "identity_status": s.get("identity_status"), "version_status": s.get("version_status"),
                     "applicability_status": s.get("applicability_status"), "completeness_status": s.get("completeness_status"), "processing_scope": s.get("processing_scope"),
                     "record_counts": json.dumps(s.get("record_counts", {}), ensure_ascii=False)} for s in sources],
        "species": species_rows,
        "questions": [{"question_id": r["question_id"], "species": r["species"], "category": r.get("category"), "eligibility_status": r["eligibility_status"],
                       "retrieval_top5_count": r.get("retrieval_top5_count"), "source_candidate_in_corpus": r.get("corpus_contains_direct_answer_candidate"),
                       "human_gold_status": r.get("human_gold_status"), "reason": r.get("eligibility_reason")} for r in eligibility],
        "retrieval": [{"question_id": r["question_id"], "species": r.get("species"), "category": r.get("category"), "top5_count": len(r.get("top5", [])),
                       "bm25_candidate_count": r.get("candidate_counts", {}).get("bm25_returned"), "dense_candidate_count": r.get("candidate_counts", {}).get("dense_returned"),
                       "rrf_candidate_count": r.get("candidate_counts", {}).get("rrf_fused_unique_chunks"), "rrf_after_record_dedupe": r.get("candidate_counts", {}).get("rrf_after_record_dedupe"),
                       "source_scope_pass": r.get("candidate_counts", {}).get("source_scope_pass"), "source_scope_excluded": r.get("candidate_counts", {}).get("source_scope_excluded"),
                       "reranker_candidate_count": r.get("candidate_counts", {}).get("reranker_candidates"), "final_top_k": len(r.get("top5", [])),
                       "empty_reason": r.get("empty_result_reason"), "corpus_sha256": r.get("corpus_sha256")} for r in retrieval],
        "evidence": [{"question_id": r["question_id"], "rank": r["rank"], "chunk_id": r.get("chunk_id"), "source_id": r.get("source_id"), "source_record_id": r.get("source_record_id"),
                      "evidence_status": r.get("evidence_status"), "matched_elements": json.dumps(r.get("matched_elements", []), ensure_ascii=False), "missing_elements": json.dumps(r.get("missing_elements", []), ensure_ascii=False),
                      "source_applicability_reason": r.get("source_applicability_reason"), "exact_locator": r.get("exact_locator"), "human_or_binary_gold": False} for r in labels],
        "references": [{**r} for r in old_refs],
        "smoke": smoke_all,
        "checks": checks,
    }
    write_json(WORK / "workbook_source_data.json", workbook_data)
    print(json.dumps({"integrity": validation["all_automated_checks_pass"], "checks": collections.Counter(c["status"] for c in checks), "corpus_sha256": current_db_sha,
                      "questions": len(retrieval), "contexts": context_rows, "protected_636": dict(protected_counts), "pytest": pytest_report["status"]}, ensure_ascii=True))


if __name__ == "__main__":
    main()
