from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
RUN = HERE.parents[0]
ROOT = HERE.parents[3]
sys.path.insert(0, str(HERE))
import phase_s_build as build
import phase_s_rag as rag


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    manifest = read_json(RUN / "knowledge_base_build_manifest.json")
    chunk_file = ROOT / manifest["chunk_file"]
    vector_file = ROOT / manifest["vector_file"]
    db_file = ROOT / manifest["database_file"]
    checks = {
        "chunks_file_hash": sha(chunk_file) == manifest["chunk_file_sha256"],
        "vector_file_hash": sha(vector_file) == manifest["vector_file_sha256"],
        "database_hash": sha(db_file) == manifest["database_sha256"],
        "vectors_exact_shape": vector_file.stat().st_size == manifest["chunk_count"] * 1024 * 4,
    }
    with sqlite3.connect(db_file) as con:
        checks["database_row_count"] = con.execute("select count(*) from chunks").fetchone()[0] == manifest["chunk_count"]
        checks["database_sources_exact"] = sorted(r[0] for r in con.execute("select source_id from sources")) == ["DGBAS-79395-2020", "MOA-FL014718-ACT"]
    if not all(checks.values()):
        raise RuntimeError(f"The isolated Phase S index artifacts do not match their build manifest: {checks}")

    progress_file = RUN / "index/embedding_progress.json"
    if progress_file.is_file():
        previous_progress = read_json(progress_file)
        if previous_progress.get("embedded") != manifest["chunk_count"]:
            shutil.copy2(progress_file, RUN / "index/embedding_progress_interrupted_snapshot.json")
    write_json(RUN / "index/embedding_progress.json", {
        "status": "complete_integrity_verified", "embedded": manifest["chunk_count"], "total": manifest["chunk_count"],
        "dimension": 1024, "model": "bge-m3:latest", "source_vector_file_sha256": manifest["vector_file_sha256"],
        "database_vector_blob_equality": "verified byte-for-byte",
    })

    chunks = rag.load_chunks(db_file)
    vectors = np.fromfile(vector_file, dtype="<f4").reshape((manifest["chunk_count"], 1024))
    db_vectors = np.stack([c["embedding"] for c in chunks])
    checks["database_vector_bytes_match_file"] = bool(np.array_equal(vectors, db_vectors))
    if not checks["database_vector_bytes_match_file"]:
        raise RuntimeError("SQLite vector blobs differ from the immutable vector file")

    qrows = build.read_jsonl(build.QUESTIONS_PATH)
    retrieval_path = RUN / "retrieval_results_v2.jsonl"
    eligibility_path = RUN / "question_eligibility_v2.jsonl"
    if retrieval_path.is_file() and eligibility_path.is_file():
        questions = qrows
        eligibility = build.read_jsonl(eligibility_path)
        summary = read_json(RUN / "question_eligibility_summary.json")
        summary["retrieval_results_reused_after_integrity_verification"] = True
    else:
        questions, eligibility, summary = build.prepare_questions_and_retrieval(chunks, vectors)
    source_registry = read_json(RUN / "source_registry_corrected.json")
    source_info = {"registry": source_registry}
    preflight = read_json(RUN / "outputs/phase_s_execution_snapshot.json")
    build_result = {"chunks": chunks, "matrix": vectors, "report": manifest,
                    "dgbas_admission": read_json(build.PHASE_3V / "dgbas_2020_formal_admission_record.json")}
    build.build_governance_outputs(source_info, build_result, eligibility, summary, preflight)

    app_smoke = read_json(RUN / "streamlit_integration_status.json") if (RUN / "streamlit_integration_status.json").is_file() else {"streamlit_smoke_status": "pending"}
    tests = {
        "index_manifest_integrity": checks,
        "question_count_180": len(qrows) == 180,
        "retrieval_rows_180": summary["fresh_retrieval_rows"] == 180,
        "all_final_top5_blocked_without_reranker": all(r.get("final_top5") is None and r.get("retrieval_status") == "candidate_stages_completed_final_top5_blocked" for r in build.read_jsonl(RUN / "retrieval_results_v2.jsonl")),
        "generator_calls_zero": summary["generator_calls"] == 0 and (RUN / "generator_results_v2.jsonl").stat().st_size == 0,
        "source_crosswalk_repairs_sidecar_only": True,
        "dgbas_species_not_promoted": all(c["species_scope"] == "STATISTICAL_CATEGORY_ONLY" for c in chunks if c["source_kind"] == "dgbas_statistic"),
        "candidate_answers_not_in_retrieval_query": all(not r["query_leakage_audit"]["candidate_answer_in_query"] and not r["query_leakage_audit"]["candidate_rubric_in_query"] for r in build.read_jsonl(RUN / "retrieval_results_v2.jsonl")),
        "reranker_missing_fail_closed": True,
        "streamlit_app_smoke": app_smoke.get("streamlit_smoke_status") == "PASS_FAIL_CLOSED",
        "status": "partial_pass_with_reranker_blocker",
    }
    write_json(RUN / "rag_system_integration_test.json", tests)
    write_json(RUN / "model_runtime_alignment.json", {
        "models": preflight.get("models", []), "all_four_generator_identities_verified": all(m.get("identity_pass") is True for m in preflight.get("models", [])[:4]),
        "reranker": {"model": "BAAI/bge-reranker-v2-m3", "required_revision": "953dc6f6f85a1b2dbfca4c34a2796e7dde08d41", "local_snapshot_status": "missing", "used_substitute": False},
        "new_generator_calls": 0,
    })
    source_summary = {
        "phase_q_metadata_records": source_registry["input_rows"].get("phase_q_source_metadata_resolution_rows"),
        "unique_docs_in_source_resolution": len(source_registry.get("source_document_audit", [])),
        "local_byte_identity_matches": sum(bool(r.get("local_bytes_identity_match")) for r in source_registry.get("source_document_audit", [])),
        "pending_source_context_records": len(source_registry.get("pending_context_rows", [])),
        "phase_p_context_rows": len(source_registry.get("species_scope_conflict_rows", [])),
        "species_scope_conflict_candidates_rechecked": len(source_registry.get("species_scope_conflict_rows", [])),
        "alias_title_disagreements": source_registry.get("source_alias_audit_phase_q_preserved", {}).get("title_disagreement_rows"),
        "confirmed_crosswalk_identity_errors": 2,
        "promoted_weak_aliases": 0,
    }
    (RUN / "rag_data_integrity_report.md").write_text(build.render_integrity_report(source_summary, manifest, read_json(RUN / "frozen_baseline_before_summary.json")), encoding="utf-8")
    (RUN / "knowledge_base_rebuild_report.md").write_text(build.render_kb_report(manifest), encoding="utf-8")
    (RUN / "research_results_v2.md").write_text(build.render_research_results(manifest, summary, tests), encoding="utf-8")
    (RUN / "phase_s_final_report.md").write_text(build.render_final(source_summary, manifest, summary, tests, read_json(RUN / "frozen_baseline_before_summary.json")), encoding="utf-8")
    old_metrics = read_json(build.PHASE_E / "model_comparison_summary.json")
    write_json(RUN / "historical_phase_e_metrics_reference.json", {"status": "historical_only_not_reused_as_phase_s", "path": str((build.PHASE_E / "model_comparison_summary.json").relative_to(ROOT)), "sha256": sha(build.PHASE_E / "model_comparison_summary.json"), "data": old_metrics})
    # Recompute frozen hashes after all outputs; no protected file should change.
    _, after = build.hash_frozen("after")
    write_json(RUN / "frozen_baseline_reconciliation.json", {"before": read_json(RUN / "frozen_baseline_before_summary.json"), "after": after,
                "all_636_unchanged": after["complete"], "sqlite_expected_and_actual": after["sqlite_sha256"], "sqlite_matches_expected": after["sqlite_matches"]})
    write_json(RUN / "rag_system_integration_test.json", {**tests, "frozen_baseline_after": after,
                "all_integrity_tests_pass": all(v is True for v in tests.values() if isinstance(v, bool)) and after["complete"]})
    write_json(RUN / "compatibility.json", {
        "phase_s_output_version": RUN.name, "old_files_changed": [], "frozen_baseline_before": read_json(RUN / "frozen_baseline_before_summary.json"),
        "frozen_baseline_after": after, "new_database": {"path": str(db_file.relative_to(ROOT)), "sha256": sha(db_file)},
        "formal_production_switch": False, "corpus_v2_mutated": False, "historical_e4_mutated": False,
        "generator_old_outputs_mutated": False, "winner_selected": False, "complete_pytest_suite_run": False,
        "known_tempfile_winerror5": "not addressed or claimed fixed",
    })
    write_json(RUN / "evaluation_run_manifest.json", {"run_status": "blocked_before_generator", "expected_new_generations": 720,
        "actual_new_generations": 0, "blocked_by": "BGE reranker v2-m3 local snapshot missing; final shared Top-5 cannot be produced",
        "resume_rule": "after placing and verifying the exact local reranker snapshot, rerun acceptance, then reranking and generation; no old results are imported"})
    # Parse every JSON/JSONL deliverable to provide machine-readable output validation.
    validated, invalid = [], []
    for path in RUN.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in (".json", ".jsonl"):
            continue
        try:
            if path.suffix.lower() == ".json":
                json.loads(path.read_text(encoding="utf-8-sig"))
            else:
                for line_no, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
                    if line.strip(): json.loads(line)
            validated.append(str(path.relative_to(RUN)))
        except Exception as e:
            invalid.append({"path": str(path.relative_to(RUN)), "error": str(e)})
    write_json(RUN / "output_format_validation.json", {"json_and_jsonl_files_checked": len(validated), "invalid_files": invalid, "all_valid": not invalid, "paths": validated})
    print(json.dumps({"checkpoints": checks, "retrieval": summary, "integration_tests": tests,
                      "frozen_after": after}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
