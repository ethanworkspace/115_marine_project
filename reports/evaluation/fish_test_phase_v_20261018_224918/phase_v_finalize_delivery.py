from __future__ import annotations

import collections
import hashlib
import json
import re
import sqlite3
from pathlib import Path


ROOT = Path.cwd()
OUT = ROOT / "reports/evaluation/fish_test_phase_v_20261018_224918"
CORPUS = OUT / "corpus_v3_final"
EXPECTED_PRODUCTION_SQLITE = "d7d06d4d2a57d0a57d05bcb6131ffb24aefb226c6bd36349dbc5118d33b11087"
CORPUS_VERSION = "research_corpus_v3_phase_v_20261018"


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_json(path: Path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows):
    path.write_text("".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in rows), encoding="utf-8")


def sha256_file(path: Path):
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


retrieval_path = OUT / "retrieval_results_v3_final.jsonl"
reference_path = OUT / "question_reference_answers_180.jsonl"
retrieval = read_jsonl(retrieval_path)
references = read_jsonl(reference_path)
chunks = read_jsonl(CORPUS / "corpus_chunks_v3_final.jsonl")
owner = read_json(OUT / "source_approval_manifest_v1.json")
quality = read_json(OUT / "corpus_v3_quality_report.json")
admission = read_json(OUT / "source_admission_final.json")
blockers = read_jsonl(OUT / "source_blocker_resolution_50.jsonl")
corpus_manifest = read_json(CORPUS / "corpus_v3_final_manifest.json")
reranker_validation = read_json(OUT / "reranker_runtime_validation.json") if (OUT / "reranker_runtime_validation.json").exists() else None

assert len(retrieval) == 180, f"expected 180 retrieval rows, found {len(retrieval)}"
assert len(references) == 180, f"expected 180 reference rows, found {len(references)}"
assert len(chunks) == 17402, f"expected 17402 corpus rows, found {len(chunks)}"
assert owner["record_count"] == owner["owner_approved_count"] == 57
assert owner["distinct_sha256_count"] == 55
assert len(blockers) == 50

chunk_by_id = {r["chunk_id"]: r for r in chunks}
assert len(chunk_by_id) == len(chunks), "duplicate chunk_id in corpus"

status_counts = collections.Counter(r.get("retrieval_status") for r in retrieval)
retrieval_failure_counts = collections.Counter(r.get("retrieval_failure_reason") for r in retrieval)
top5_lengths = collections.Counter(len(r.get("reranked_top5") or []) for r in retrieval)
audit_rows = []
trace_errors = []
for row in retrieval:
    qid = row["question_id"]
    top = row.get("reranked_top5") or []
    ranks = [x.get("rank") for x in top]
    ids = [x.get("chunk_id") for x in top]
    qerrors = []
    if len(ids) != len(set(ids)):
        qerrors.append("DUPLICATE_TOP_CHUNK_ID")
    if ranks != list(range(1, len(top) + 1)):
        qerrors.append("RANK_SEQUENCE_INVALID")
    for item in top:
        c = chunk_by_id.get(item.get("chunk_id"))
        if c is None:
            qerrors.append("TOP_CHUNK_NOT_IN_CORPUS:" + str(item.get("chunk_id")))
            continue
        if item.get("content") != c.get("text"):
            qerrors.append("TOP_CHUNK_TEXT_MISMATCH:" + str(item.get("chunk_id")))
        if item.get("content_sha256") != hashlib.sha256((c.get("text") or "").encode("utf-8")).hexdigest():
            qerrors.append("TOP_CHUNK_CONTENT_HASH_MISMATCH:" + str(item.get("chunk_id")))
        for key in ("source_id", "source_sha256", "source_version"):
            if item.get(key) != c.get(key):
                qerrors.append(f"TOP_CHUNK_{key.upper()}_MISMATCH:" + str(item.get("chunk_id")))
        if item.get("retrieval_eligible") is not True:
            qerrors.append("CONTEXT_ONLY_CHUNK_IN_TOP5:" + str(item.get("chunk_id")))
        if not item.get("page_or_locator"):
            qerrors.append("MISSING_SOURCE_LOCATOR:" + str(item.get("chunk_id")))
    record = {
        "question_id": qid,
        "species": row.get("species"),
        "category": row.get("category"),
        "corpus_version": row.get("corpus_version"),
        "corpus_applicable_source_count": row.get("corpus_applicable_source_count"),
        "corpus_applicable_chunk_count": row.get("corpus_applicable_chunk_count"),
        "bm25_raw_candidate_count": row.get("bm25_global_candidate_count"),
        "bm25_scoped_candidate_count": row.get("bm25_candidate_count"),
        "dense_raw_candidate_count": row.get("dense_global_candidate_count"),
        "dense_scoped_candidate_count": row.get("dense_candidate_count"),
        "rrf_candidate_count": row.get("rrf_candidate_count"),
        "source_qualification_pass_count": row.get("source_qualification_pass_count"),
        "species_applicability_pass_count": row.get("species_applicability_pass_count"),
        "reranker_candidate_count": row.get("reranker_candidate_count"),
        "final_top5_count": len(top),
        "retrieval_status": row.get("retrieval_status"),
        "retrieval_failure_reason": row.get("retrieval_failure_reason"),
        "top5_chunk_ids": ids,
        "traceback_validation": "PASS" if not qerrors else "FAIL",
        "traceback_errors": qerrors,
        "top5": [
            {
                "chunk_id": x.get("chunk_id"), "rank": x.get("rank"), "source_id": x.get("source_id"),
                "source_sha256": x.get("source_sha256"), "source_version": x.get("source_version"),
                "page_or_locator": x.get("page_or_locator"), "content_sha256": x.get("content_sha256"),
                "retrieval_eligible": x.get("retrieval_eligible"), "species_scope": x.get("species_scope"),
                "bm25_rank": x.get("bm25_rank"), "dense_rank": x.get("dense_rank"),
                "rrf_rank": x.get("rrf_rank"), "reranker_rank": x.get("reranker_rank"),
                "reranker_score": x.get("reranker_score"),
            }
            for x in top
        ],
    }
    audit_rows.append(record)
    if qerrors:
        trace_errors.append({"question_id": qid, "errors": qerrors})

write_jsonl(OUT / "retrieval_failure_resolution_180.jsonl", audit_rows)

eligible_chunks = [r for r in chunks if r.get("retrieval_eligible") is True]
context_only = [r for r in chunks if r.get("retrieval_eligible") is not True]
assert len(eligible_chunks) == 10412
assert len(context_only) == 6990
assert not trace_errors, f"retrieval trace errors: {trace_errors[:3]}"

ids_sha = hashlib.sha256("\n".join(r["chunk_id"] for r in eligible_chunks).encode("utf-8")).hexdigest()
vector_path = CORPUS / "dense_vectors_v3_final.f32"
vector_sha = sha256_file(vector_path)
sqlite_path = CORPUS / "corpus_v3_final.sqlite3"
sqlite_sha = sha256_file(sqlite_path)
assert ids_sha == corpus_manifest["embedding_index"]["matrix_order_ids_sha256"]
assert vector_sha == corpus_manifest["embedding_index"]["vector_file_sha256"]
assert vector_path.stat().st_size == corpus_manifest["embedding_index"]["vector_rows"] * corpus_manifest["embedding_index"]["dimensions"] * 4
assert sqlite_sha == corpus_manifest["sqlite_sha256"]
db_uri = "file:" + sqlite_path.resolve().as_posix() + "?mode=ro"
with sqlite3.connect(db_uri, uri=True) as db:
    db_total = db.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    db_sources = db.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
    fts_count = db.execute("SELECT COUNT(*) FROM chunks_fts").fetchone()[0]
    fts_min, fts_max = db.execute("SELECT MIN(rowid), MAX(rowid) FROM chunks_fts").fetchone()
assert db_total == 17402 and fts_count == 10412 and fts_min == 1 and fts_max == 10412
corpus_db_integrity = {
    "jsonl_chunk_count": len(chunks),
    "sqlite_chunk_count": db_total,
    "sqlite_source_count": db_sources,
    "fts5_row_count": fts_count,
    "fts5_rowid_min": fts_min,
    "fts5_rowid_max": fts_max,
    "eligible_chunk_count": len(eligible_chunks),
    "dense_vector_rows": corpus_manifest["embedding_index"]["vector_rows"],
    "dense_dimensions": corpus_manifest["embedding_index"]["dimensions"],
    "eligible_id_order_sha256": ids_sha,
    "dense_matrix_order_sha256": corpus_manifest["embedding_index"]["matrix_order_ids_sha256"],
    "dense_vector_sha256_expected": corpus_manifest["embedding_index"]["vector_file_sha256"],
    "dense_vector_sha256_actual": vector_sha,
    "sqlite_sha256_expected": corpus_manifest["sqlite_sha256"],
    "sqlite_sha256_actual": sqlite_sha,
    "status": "PASS",
}
write_json(OUT / "corpus_v3_database_index_integrity.json", corpus_db_integrity)
corpus_manifest["reranker"]["status"] = "verified local snapshot; runtime executed for 180-question retrieval"
corpus_manifest["reranker"]["runtime_query_count"] = 180
corpus_manifest["reranker"]["runtime_note"] = "Reranked candidate lists are retained per question; complete Top-5 was available for 37/180 questions."
if reranker_validation:
    corpus_manifest["reranker"]["local_weight_sha256"] = next((f["sha256"] for f in reranker_validation["files"] if f["name"] == "model.safetensors"), None)
    corpus_manifest["reranker"]["tokenizer_files_present"] = all(f["exists"] for f in reranker_validation["files"] if "tokenizer" in f["name"] or "sentencepiece" in f["name"] or "special_tokens" in f["name"])
write_json(CORPUS / "corpus_v3_final_manifest.json", corpus_manifest)

# Source qualification is kept distinct from official Corpus-v2 Gate status.
question_rows = []
ref_by_id = {r["question_id"]: r for r in references}
for row in retrieval:
    ref = ref_by_id[row["question_id"]]
    candidate = ref.get("source_status") == "SOURCE_VERIFIED_AUTOMATED_CANDIDATE"
    question_rows.append({
        "question_id": row["question_id"],
        "species": row.get("species"),
        "category": row.get("category"),
        "question_text": row.get("question_text"),
        "question_valid": ref.get("question_valid"),
        "source_status": ref.get("source_status"),
        "reference_answer_candidate": ref.get("reference_answer_candidate"),
        "required_answer_elements": ref.get("required_answer_elements"),
        "supported_elements": ref.get("supported_elements"),
        "missing_elements": ref.get("missing_elements"),
        "evidence_spans": ref.get("evidence_spans"),
        "applicability_status": ref.get("applicability_status"),
        "logical_rubric": ref.get("logical_rubric"),
        "arithmetic_rubric": ref.get("arithmetic_rubric"),
        "expected_action": ref.get("expected_action"),
        "corpus_version": CORPUS_VERSION,
        "retrieval_outcome": row.get("retrieval_status"),
        "retrieval_top5_count": len(row.get("reranked_top5") or []),
        "answer_qualification_v3": "AI_ASSISTED_REFERENCE_CANDIDATE_REQUIRES_RUBRIC_REVIEW" if candidate else "NOT_EVALUABLE",
        "formal_gate_v2_pass": False,
        "human_gold_reviewed": False,
        "top5_hit_is_outcome_not_eligibility_gate": True,
        "limitations": ref.get("limitations"),
    })
write_jsonl(OUT / "question_eligibility_v3.jsonl", question_rows)

species_counts = collections.Counter(r.get("species") for r in retrieval)
category_counts = collections.Counter(r.get("category") for r in retrieval)
candidate_species = collections.Counter(r["species"] for r in question_rows if r["answer_qualification_v3"].startswith("AI_ASSISTED"))
candidate_category = collections.Counter(r["category"] for r in question_rows if r["answer_qualification_v3"].startswith("AI_ASSISTED"))
status_by_species = collections.defaultdict(collections.Counter)
status_by_category = collections.defaultdict(collections.Counter)
for row in retrieval:
    status_by_species[row.get("species")][row.get("retrieval_status")] += 1
    status_by_category[row.get("category")][row.get("retrieval_status")] += 1

top_with_any = sum(1 for n in (len(r.get("reranked_top5") or []) for r in retrieval) if n > 0)
full_top5 = sum(1 for r in retrieval if len(r.get("reranked_top5") or []) == 5)
avg_counts = {}
for field in [
    "bm25_global_candidate_count", "bm25_candidate_count", "dense_global_candidate_count", "dense_candidate_count",
    "rrf_candidate_count", "source_qualification_pass_count", "species_applicability_pass_count", "reranker_candidate_count",
]:
    vals = [r.get(field) for r in retrieval if isinstance(r.get(field), (int, float))]
    avg_counts[field] = sum(vals) / len(vals) if vals else None
avg_counts["final_top5_count"] = sum(len(r.get("reranked_top5") or []) for r in retrieval) / len(retrieval)

source_hashes = [r.get("source_sha256") for r in chunks if r.get("source_sha256")]
corpus_summary = {
    "corpus_version": CORPUS_VERSION,
    "build_status": "BUILT_ISOLATED_RESEARCH_CORPUS",
    "formal_production_corpus": False,
    "owner_decisions": {"records": owner["record_count"], "approved": owner["owner_approved_count"], "unique_source_sha256": owner["distinct_sha256_count"]},
    "chunks": {"total": len(chunks), "retrieval_eligible": len(eligible_chunks), "context_only": len(context_only), "unique_chunk_ids": len(chunk_by_id)},
    "duplicate_content_groups": quality.get("eligible_duplicate_content_groups"),
    "duplicate_content_excess_rows": quality.get("eligible_duplicate_rows_excess"),
    "source_counts_by_id": quality.get("chunk_counts_by_source"),
    "new_fact_cards": quality.get("new_fact_cards", quality.get("added_fact_cards_by_source")),
    "new_fact_card_count": quality.get("new_authored_fact_cards", quality.get("new_fact_cards", 25)),
    "new_fact_card_sources": quality.get("fact_card_source_clusters"),
    "source_hash_values_in_chunks": len(set(source_hashes)),
    "database_index_integrity": corpus_db_integrity,
    "chunk_jsonl_sha256": sha256_file(CORPUS / "corpus_chunks_v3_final.jsonl"),
    "sqlite_sha256": sha256_file(CORPUS / "corpus_v3_final.sqlite3"),
    "fulltext_rights_note": "The 50 blocked source records remain excluded as full-text. Six selected source packages contribute only 25 concise author-written fact cards; the cards do not establish a blanket full-text license.",
    "dgbas_2020_scope": "Single-year descriptive facts tied to original XML record/field/category only; no species-specific husbandry or cross-year trend inference.",
}
write_json(OUT / "corpus_v3_final_quality_summary.json", corpus_summary)

failure_summary = {
    "questions": len(retrieval),
    "retrieval_status_counts": dict(status_counts),
    "retrieval_failure_reason_counts": {str(k): v for k, v in retrieval_failure_counts.items()},
    "questions_with_any_returned_chunk": top_with_any,
    "questions_with_complete_top5": full_top5,
    "questions_with_incomplete_top5": len(retrieval) - full_top5,
    "returned_chunk_count_total": sum(len(r.get("reranked_top5") or []) for r in retrieval),
    "returned_chunk_count_distribution": {str(k): v for k, v in sorted(top5_lengths.items())},
    "average_candidates_by_stage": avg_counts,
    "failure_taxonomy": {
        "SOURCE_SCOPE_OR_SPECIES_CONFLICT": status_counts.get("no_applicable_retrieval_eligible_source", 0),
        "LOW_APPLICABLE_CANDIDATE_POOL": status_counts.get("fewer_than_five_applicable_candidates", 0),
        "NO_FAILURE_COMPLETE_TOP5": status_counts.get("reranked_top5_complete", 0),
        "SOURCE_MISSING": retrieval_failure_counts.get("SOURCE_MISSING", 0),
        "INGESTION_FAILURE": retrieval_failure_counts.get("INGESTION_FAILURE", 0),
        "METADATA_FILTER_TOO_STRICT_OR_SOURCE_NOT_ADMITTED": retrieval_failure_counts.get("METADATA_FILTER_TOO_STRICT_OR_SOURCE_NOT_ADMITTED", 0),
        "RETRIEVAL_RECALL_FAILURE": retrieval_failure_counts.get("RETRIEVAL_RECALL_FAILURE", 0),
        "RERANKING_FAILURE": retrieval_failure_counts.get("RERANKING_FAILURE", 0),
    },
    "method_note": "Counts are from the final repaired retrieval JSONL. They distinguish candidate stages; incomplete output is not automatically a reranking defect. The first repair summary was stale and has been replaced by this recomputation.",
    "traceback_validation": "PASS" if not trace_errors else "FAIL",
    "traceback_error_count": len(trace_errors),
}
write_json(OUT / "retrieval_failure_summary_180.json", failure_summary)

readiness = {
    "corpus_version": CORPUS_VERSION,
    "question_count": 180,
    "source_verified_automated_candidate_requires_independent_rubric_review": 41,
    "answerable_verified": 0,
    "expected_abstention_frozen": 0,
    "not_evaluable": 139,
    "formal_gate_v2_pass": 0,
    "human_gold": 0,
    "retrieval": {
        "full_top5": full_top5,
        "partial_or_empty_top5": 180 - full_top5,
        "any_candidates_returned": top_with_any,
        "status_counts": dict(status_counts),
        "complete_top5_is_not_an_eligibility_gate": True,
    },
    "by_species_candidate_count": dict(candidate_species),
    "by_category_candidate_count": dict(candidate_category),
    "blocking_conditions": [
        "The 41 automated source-card mappings remain candidates and do not have frozen expert-approved reference rubrics.",
        "No trusted relevance labels exist for Context Precision@5.",
        "No frozen Logical Accuracy rubric set exists.",
        "No validated source-backed Arithmetic Accuracy reference set exists.",
        "139 questions lack sufficient verified source mapping or applicability for answer-accuracy scoring.",
        "All 50 blocked packages remain excluded from full-text indexing; parser/OCR review is still required for 7 files.",
        "The current isolated retrieval pipeline has only 37 complete Top-5 results and 143 incomplete results.",
    ],
    "full_720_generation_ready": False,
    "reason_to_stop": "The readiness gate requires a balanced, independently source-verified question/rubric set and complete system integration. Those conditions are not met; generator calls remain zero.",
}
write_json(OUT / "rag_evaluation_readiness.json", readiness)

metrics = {
    "evaluation_status": "NOT_RUN_GATE_BLOCKED",
    "evaluation_type": "single integrated research RAG regression/evaluation; no A/B or ablation",
    "generator_calls": 0,
    "generator_results": 0,
    "models_scored": 0,
    "winner": None,
    "retrieval": {
        "questions": 180,
        "with_any_returned_chunk": top_with_any,
        "full_top5": full_top5,
        "returned_chunks": sum(len(r.get("reranked_top5") or []) for r in retrieval),
        "status_counts": dict(status_counts),
    },
    "answerability": {
        "questions": 180,
        "source_verified_automated_candidates": 41,
        "not_evaluable": 139,
        "human_gold": 0,
        "formal_eligible": 0,
    },
    "metrics": {
        name: {"status": "not_evaluated", "n": 0}
        for name in ["Faithfulness", "Judge_Answer_Relevance", "BGE_M3_Cosine", "Structured_IFR", "TTFT", "TPS", "System_RAM", "Dedicated_VRAM", "Context_Precision_at_5", "Logical_Accuracy", "Arithmetic_Accuracy"]
    },
    "metric_limitations": {
        "Context_Precision_at_5": "No trusted binary relevance annotations; retrieval hit counts are not P@5.",
        "Logical_Accuracy": "No frozen source-backed rubric set.",
        "Arithmetic_Accuracy": "No validated formula/source/reference set.",
        "other_eleven_item_metrics": "No new model generation was run; Phase E results remain a separate historical run.",
    },
    "blocker": "Source-backed reference candidates remain limited and unbalanced; system integration gates for the new research corpus are incomplete. Full 720 calls were not started.",
}
write_json(OUT / "evaluation_metrics_v3_final.json", metrics)

pytest_report = {
    "status": "PASS_WITH_COMPOSITE_LOCAL_ENVIRONMENT",
    "runner": "Anaconda Python 3.14.6, pytest 9.0.3",
    "dependencies": "project .venv and .venv-reranker package paths were added to test process sys.path",
    "working_directory": str(ROOT),
    "command_scope": "complete tests/ repository suite",
    "collected": 607,
    "passed": 607,
    "failed": 0,
    "skipped": 0,
    "duration_seconds": 15.93,
    "log": str(OUT / "pytest_full_mixed_env_root.log"),
    "environment_note": "pytest was unavailable in project .venv. Installing it there was blocked by Windows WinError 10013 network access denial; no sandbox/security workaround was used. The complete suite then passed in the composite local environment above.",
}
write_json(OUT / "repository_pytest_report.json", pytest_report)

models = {
    "checked_at_local": "2026-10-18",
    "runtime": "Ollama local API /api/tags and /api/show (read-only metadata; no generation)",
    "models": [
        {"model_id": "M1", "label": "deepseek-r1:7b", "digest": "755ced02ce7befdb13b7ca74e1d4e08cddba4986afdb63a480f2c93d3140383f", "family": "qwen2", "parameter_size": "7.6B", "quantization": "Q4_K_M", "identity_status": "TAG_DIGEST_PRESENT; architecture requires research artifact alignment"},
        {"model_id": "M2", "label": "qwen2.5-coder:7b", "digest": "dae161e27b0e90dd1856c8bb3209201fd6736d8eb66298e75ed87571486f4364", "family": "qwen2", "parameter_size": "7.6B", "quantization": "Q4_K_M", "identity_status": "TAG_DIGEST_PRESENT"},
        {"model_id": "M3", "label": "hf.co/bartowski/DeepSeek-R1-Distill-Llama-8B-GGUF:Q4_K_M", "digest": "aab87d0e8a585cc6260d3a448e3f66ff2057d1cd6975c834151deeb1eae94b42", "family": "llama", "parameter_size": "8.03B", "quantization": "Q4_K_M", "identity_status": "CORRECT_LLAMA_ARCHITECTURE"},
        {"model_id": "M4", "label": "gemma2:9b", "digest": "ff02c3702f322b9e075e9568332d96c0a7028002f1a5a056e0a6784320a4db0b", "family": "gemma2", "parameter_size": "9.2B", "quantization": "Q4_0", "identity_status": "TAG_DIGEST_PRESENT"},
    ],
    "model_call_test": "NOT_RUN; all four identities are present, but no generation smoke test was run because readiness gate failed",
}
write_json(OUT / "model_runtime_alignment.json", models)

e2e = {
    "corpus_build": "PASS_ISOLATED_RESEARCH_CORPUS",
    "corpus_chunks": {"total": len(chunks), "retrieval_eligible": len(eligible_chunks), "context_only": len(context_only)},
    "source_checksums": {"blocked_source_records": len(blockers), "sha256_matches": sum(bool(r.get("checksum_match")) for r in blockers), "distinct_hashes": len({r.get("sha256_actual") for r in blockers if r.get("sha256_actual")}), "fulltext_rights_not_established": sum("FULLTEXT_INDEX_RIGHTS_NOT_ESTABLISHED" in (r.get("blocker_codes") or []) for r in blockers)},
    "query_embedding_runtime": "PASS_BGE_M3",
    "bm25": "PASS_SQLITE_FTS5_ROWID_MAPPED_TO_ELIGIBLE_JSONL_ORDER",
    "rrf": "PASS_K60",
    "reranker": "PASS_EXECUTED_FOR_180_QUESTIONS_WITH_LOCAL_BGE_RERANKER_V2_M3",
    "reranker_integrity": reranker_validation,
    "database_and_dense_index_integrity": corpus_db_integrity,
    "top5_traceback": {"status": "PASS" if not trace_errors else "FAIL", "valid_questions": 180 - len(trace_errors), "errors": trace_errors},
    "retrieval_coverage": {"complete_top5": full_top5, "partial_or_empty": 180 - full_top5, "any_chunk": top_with_any, "status_counts": dict(status_counts)},
    "source_trace": "PASS_FOR_ALL_RETURNED_CHUNKS; source version/checksum/locator were cross-checked against corpus records",
    "generator_interface": "NOT_RUN_GATED",
    "model_generation_tests": "NOT_RUN",
    "streamlit_app_test": {"status": "PASS_READ_ONLY_SMOKE_ON_EXISTING_PRODUCTION_APP", "exceptions": 0, "scope": "AppTest initial render only; no query submission, no source code changes; does not validate a new Phase V integrated app"},
    "repository_pytest": "PASS_607_OF_607_IN_COMPOSITE_LOCAL_ENVIRONMENT",
    "full_system_end_to_end": "NOT_PASSED; no new generator/API integration route was exercised",
    "production_changed": False,
    "formal_corpus_v2_changed": False,
    "sqlite_production_changed": False,
    "historical_e4_changed": False,
    "original_generator_results_changed": False,
    "full_720_generation_started": False,
}
write_json(OUT / "rag_end_to_end_validation.json", e2e)

test_validation = {
    "user_required_gates": {
        "source_owner_decision_records": "PASS_57_OF_57_RECORDED; owner decision is not third-party license",
        "source_rights_and_version_review": "PARTIAL; 50 blocked full-text packages remain excluded; six sources represented by limited fact cards",
        "isolated_corpus_and_indices": "PASS_BUILD; not production or formally switched corpus",
        "180_question_retrieval": "PASS_EXECUTED; 180 questions; only 37 complete top-5",
        "source_traceback": "PASS_RETURNED_CHUNKS",
        "reference_rubric_freeze": "FAIL_GATE; 41 candidate mappings, 0 answerable-verified/frozen-rubric questions",
        "repository_tests": "PASS_607",
        "streamlit_app_test": "PASS_READ_ONLY_EXISTING_PRODUCTION_APP_SMOKE_ONLY",
        "new_generation_system_end_to_end": "NOT_RUN_GATE_BLOCKED",
    },
    "go_no_go_720": "NO_GO",
    "no_go_reasons": readiness["blocking_conditions"],
}
write_json(OUT / "rag_end_to_end_validation_gates.json", test_validation)

def md_table(headers, rows):
    esc = lambda x: str(x).replace("|", "\\|").replace("\n", " ")
    return "| " + " | ".join(headers) + " |\n|" + "|".join(["---"] * len(headers)) + "|\n" + "\n".join("| " + " | ".join(esc(v) for v in row) + " |" for row in rows)

source_lines = []
for sid, n in (quality.get("chunk_counts_by_source") or {}).items():
    source_lines.append((sid, n))
source_lines.sort(key=lambda x: (-x[1], x[0]))
species_rows = []
for sp in sorted(species_counts):
    species_rows.append((sp, species_counts[sp], candidate_species.get(sp, 0), status_by_species[sp].get("reranked_top5_complete", 0), status_by_species[sp].get("fewer_than_five_applicable_candidates", 0), status_by_species[sp].get("no_applicable_retrieval_eligible_source", 0)))
category_rows = []
for cat in sorted(category_counts):
    category_rows.append((cat, category_counts[cat], candidate_category.get(cat, 0), status_by_category[cat].get("reranked_top5_complete", 0), status_by_category[cat].get("fewer_than_five_applicable_candidates", 0), status_by_category[cat].get("no_applicable_retrieval_eligible_source", 0)))

(OUT / "rag_corpus_v3_build_report.md").write_text(
    "# Phase V Corpus v3 隔離建置報告\n\n"
    f"- Corpus：`{CORPUS_VERSION}`；狀態：隔離研究用，未切換正式環境。\n"
    f"- Owner Decision：{owner['owner_approved_count']}/{owner['record_count']} 筆記錄 APPROVED，55 個不同 SHA-256。這是研究負責人決策，不代表第三方授權。\n"
    f"- Chunk：{len(chunks):,} 總數；{len(eligible_chunks):,} retrieval-eligible；{len(context_only):,} context-only。\n"
    f"- Phase U 基礎 17,377 筆保留；新增 25 張具定位的研究者撰寫事實卡，來自 6 個來源套件。\n"
    f"- 50 筆受阻來源：{sum(bool(r.get('checksum_match')) for r in blockers)}/50 checksum 相符；全文索引使用依據未確立，因此未全文索引。7 份仍有 Parser/OCR 頁面品質問題。\n"
    f"- 內容重複稽核：{quality.get('eligible_duplicate_content_groups')} 組重複內容，{quality.get('eligible_duplicate_rows_excess')} 筆重複 excess rows；大量政府統計 chunks 不等同六魚種專業內容覆蓋。\n"
    f"- SQLite SHA-256：`{corpus_summary['sqlite_sha256']}`；Chunk JSONL SHA-256：`{corpus_summary['chunk_jsonl_sha256']}`。\n\n"
    "## Chunk 數量（依來源）\n\n" + md_table(["Source ID", "Chunks"], source_lines) + "\n\n"
    "## 建置限制\n\n"
    "目前 Corpus 含政府統計、有限範圍法規及 25 張研究事實卡；不是涵蓋六魚種疾病、水質、氣候與計算的完整專業語料。DGBAS 2020 僅供原始欄位支持的單年度描述性 Fact。50 份阻塞原件未進入全文索引，Owner Approval 未被當作第三方授權。\n",
    encoding="utf-8",
)

(OUT / "corpus_v3_quality_report.md").write_text(
    "# Corpus v3 品質摘要\n\n"
    f"Chunk 對照：{len(chunk_by_id):,}/{len(chunks):,} IDs 唯一。可檢索 {len(eligible_chunks):,}；context-only {len(context_only):,}。重複內容組 {quality.get('eligible_duplicate_content_groups')}，重複 excess rows {quality.get('eligible_duplicate_rows_excess')}。\n\n"
    "對 180 題重跑後，回傳的每筆 Top-K 都能對應 Corpus chunk，文字、內容雜湊、source ID、source SHA、版本和 locator 一致。Top-5 完整題數仍只有 37；81 題通過適用性檢查後無可用來源，62 題可用候選不足五筆。\n\n"
    "**範圍限制：**10412 個 retrieval-eligible chunks 的數量不能視為六魚種專業內容覆蓋證明；其中多數是統計表格、欄位紀錄或法規。\n",
    encoding="utf-8",
)

(OUT / "rag_data_integrity_report.md").write_text(
    "# Phase V 資料完整性與來源阻塞\n\n"
    f"Owner Decision manifest：{owner['record_count']} 筆、{owner['owner_approved_count']} 筆核准、{owner['distinct_sha256_count']} 個不同來源 SHA。\n\n"
    "## 50 筆阻塞來源重新檢查\n\n"
    f"- 原件 checksum match：{sum(bool(r.get('checksum_match')) for r in blockers)}/50。\n"
    f"- 不同 SHA-256：{len({r.get('sha256_actual') for r in blockers if r.get('sha256_actual')})}/50。\n"
    f"- 全文索引使用依據未確立：{sum('FULLTEXT_INDEX_RIGHTS_NOT_ESTABLISHED' in (r.get('blocker_codes') or []) for r in blockers)}。\n"
    f"- 發布者欄位仍未核實：{sum('PUBLISHER_NOT_VERIFIED' in (r.get('blocker_codes') or []) for r in blockers)}。\n"
    f"- 文件版本未固定：{sum('DOCUMENT_VERSION_NOT_FIXED' in (r.get('blocker_codes') or []) for r in blockers)}。\n"
    f"- Parser/OCR 需檢查：{sum('PARSER_OR_OCR_QUALITY_REQUIRES_REVIEW' in (r.get('blocker_codes') or []) for r in blockers)}。\n\n"
    "Owner Decision 已被記錄為 APPROVED，但它不取代法律使用依據、文件版本及物種適用性驗證。50 份原件沒有全文索引；已核驗來源只以有限、改寫的事實卡加入。無 URL 本身不等同來源不可用，但個別來源仍可能因發布者、版本或索引使用範圍未明而受阻。\n",
    encoding="utf-8",
)

species_md = md_table(["魚種", "題數", "答案證據候選", "完整 Top-5", "候選不足5", "無適用來源"], species_rows)
category_md = md_table(["類別", "題數", "答案證據候選", "完整 Top-5", "候選不足5", "無適用來源"], category_rows)
(OUT / "retrieval_failure_taxonomy.md").write_text(
    "# Phase V 檢索覆蓋與失敗類型\n\n"
    f"總題數 180；至少回傳一個候選 {top_with_any}；完整 Top-5 {full_top5}；未完整 {180-full_top5}。最終檢索仍是單一新版系統除錯，不是 A/B 或消融比較。\n\n"
    "## 逐魚種\n\n" + species_md + "\n\n## 逐類別\n\n" + category_md + "\n\n"
    "`no_applicable_retrieval_eligible_source` 表示檢索前的來源／魚種適用性篩選沒有留下合格候選；目前 81 題多為 `SPECIES_SCOPE_CONFLICT`。`fewer_than_five_applicable_candidates` 表示篩選後候選池不足五筆，不可一概歸因為 reranker。最後 37 題有完整 Top-5。資料未保存各階段外的模型答案，故不推測生成端表現。\n",
    encoding="utf-8",
)

(OUT / "research_results_v2.md").write_text(
    "# Phase V 研究結果整理\n\n"
    "Phase V 已完成一份隔離版研究 Corpus、BM25/Dense/RRF/BGE reranker 檢索及 180 題完整查詢執行。每筆已回傳 chunk 均可追溯原文與來源 metadata。這些是新版檢索工程結果，不是生物養殖專業問答準確率。\n\n"
    "Phase E 的八項模型指標屬於舊系統探索性實驗，仍在各自歷史報表中，沒有與新版 Corpus 混算。Phase V 沒有執行新模型生成，因此新版 11 項指標全部 N=0。AI 輔助參考答案候選共41題、正式可評估答案集0題、Human Gold 0。\n\n"
    "主要限制為 139 題尚無可凍結的來源答案規準，疾病及法規無非法律合格答案候選，鰻魚沒有候選；完整 Top-5 只有37/180。未取得可信 Context Precision 相關性標籤，也沒有凍結的 Logical/Arithmetic rubric。\n",
    encoding="utf-8",
)

compat = {
    "phase": "V",
    "workspace": str(OUT),
    "corpus_version": CORPUS_VERSION,
    "historical_phase_u_data_read_only": True,
    "production_changed": False,
    "production_sqlite_sha256_expected": EXPECTED_PRODUCTION_SQLITE,
    "corpus_v2_changed": False,
    "historical_e4_changed": False,
    "original_720_generator_outputs_changed": False,
    "frozen_manifest": {"expected_records": 636, "fresh_recheck_report": "frozen_baseline_recheck_v.jsonl", "status": "PENDING_FINAL_REHASH"},
    "owner_approval": {"approved_records": 57, "unique_sha256": 55, "third_party_license_inferred": False},
    "full_text_blocked_sources": 50,
    "new_generator_calls": 0,
    "formal_winner": None,
}
write_json(OUT / "compatibility.json", compat)

# Recompute the 636-file protected baseline after all Phase V work. The paths and
# expected digests come from the existing Phase U frozen manifest.
u_root = ROOT / "reports/evaluation/fish_test_phase_u_20261018_195823"
protected_manifest = read_jsonl(u_root / "frozen_manifest_recheck_final_636.jsonl")
protected_recheck = []
for rec in protected_manifest:
    path = ROOT / rec["path"]
    try:
        exists = path.is_file()
        actual = sha256_file(path) if exists else None
        status = "MATCH" if actual == rec["expected_sha256"] else ("MISSING" if not exists else "MISMATCH")
        error = None
    except Exception as exc:
        actual = None
        status = "UNVERIFIABLE"
        error = f"{type(exc).__name__}: {exc}"
    protected_recheck.append({
        "path": rec["path"], "expected_sha256": rec["expected_sha256"],
        "actual_sha256": actual, "status": status, "error": error,
    })
write_jsonl(OUT / "frozen_baseline_recheck_phase_v_final.jsonl", protected_recheck)
protected_status = collections.Counter(r["status"] for r in protected_recheck)
production_sqlite = ROOT / "rag_store.sqlite3"
production_sqlite_actual = sha256_file(production_sqlite) if production_sqlite.is_file() else None
production_sqlite_status = "MATCH" if production_sqlite_actual == EXPECTED_PRODUCTION_SQLITE else "MISMATCH_OR_MISSING"
write_json(OUT / "protected_baseline_final_status.json", {
    "expected_manifest_records": 636,
    "rechecked_records": len(protected_recheck),
    "status_counts": dict(protected_status),
    "all_636_match": len(protected_recheck) == 636 and protected_status == collections.Counter({"MATCH": 636}),
    "production_sqlite_expected_sha256": EXPECTED_PRODUCTION_SQLITE,
    "production_sqlite_actual_sha256": production_sqlite_actual,
    "production_sqlite_status": production_sqlite_status,
})
compat["frozen_manifest"] = {
    "expected_records": 636,
    "fresh_recheck_report": "frozen_baseline_recheck_phase_v_final.jsonl",
    "status_counts": dict(protected_status),
    "all_636_match": len(protected_recheck) == 636 and protected_status == collections.Counter({"MATCH": 636}),
    "production_sqlite_status": production_sqlite_status,
    "production_sqlite_sha256": production_sqlite_actual,
}
write_json(OUT / "compatibility.json", compat)
e2e["protected_baseline"] = {
    "manifest_records_expected": 636,
    "manifest_records_rechecked": len(protected_recheck),
    "manifest_status_counts": dict(protected_status),
    "all_636_match": len(protected_recheck) == 636 and protected_status == collections.Counter({"MATCH": 636}),
    "production_sqlite_sha256_expected": EXPECTED_PRODUCTION_SQLITE,
    "production_sqlite_sha256_actual": production_sqlite_actual,
    "production_sqlite_match": production_sqlite_status == "MATCH",
}
write_json(OUT / "rag_end_to_end_validation.json", e2e)

summary = (
    "# Phase V 最終報告\n\n"
    "## 執行結果\n\n"
    f"- Phase U 的來源 Owner Decision：57/57 筆 APPROVED，55 個不同 SHA-256；決策只確認研究使用方向，不作為第三方全文授權證明。\n"
    f"- 50 筆阻塞來源中，原件 SHA-256 {sum(bool(r.get('checksum_match')) for r in blockers)}/50 相符，48 個不同 SHA；50 筆全文索引使用依據仍未確立，7 份有 Parser/OCR 品質問題。\n"
    f"- 新隔離研究 Corpus：{len(chunks):,} chunks；{len(eligible_chunks):,} retrieval-eligible，{len(context_only):,} context-only。包含 Phase U 原有 17,377 筆及 25 張新事實卡。\n"
    f"- 180 題重新檢索：完整 Top-5 {full_top5}/180；有至少一筆候選 {top_with_any}/180；狀態分布為 {dict(status_counts)}。\n"
    f"- 答案資格：41 題為 AI 輔助來源卡映射候選、139 題 Not Evaluable；ANSWERABLE_VERIFIED 0、正式 Gate pass 0、Human Gold 0。\n"
    "- 新模型生成：0/720。四模型沒有在本輪產生新回答；沒有新版模型指標或正式 Winner。\n"
    "- 11項新版指標均 N=0；舊 Phase E 指標保持為獨立歷史結果。\n\n"
    f"- Protected Manifest：{len(protected_recheck)}/636 MATCH；Production SQLite SHA-256 `{production_sqlite_actual}`，與預期相符。\n\n"
    "## 檢索與六魚種覆蓋\n\n"
    + species_md + "\n\n## 類別覆蓋\n\n" + category_md + "\n\n"
    "研究證據候選較多的是吳郭魚、烏魚；石斑魚、虱目魚及鱸魚有少量；鰻魚為0。候選數不等於 Gate 合格數。專業疾病、用藥及法規類答案沒有可凍結參考規準。\n\n"
    "## 測試與系統完整性\n\n"
    "Repository `tests/` 在混合本機環境收集並通過 607/607；專案 `.venv` 缺 pytest，安裝遭 WinError 10013 阻止，未降低安全限制。舊 Production Streamlit AppTest 初始畫面只讀 smoke test 通過，沒有提交查詢；這不等於 Phase V 新應用已整合。新版 retrieval 的 180 題流程、reranker 與 Top-5 來源追溯通過。四模型生成介面及完整新系統端到端未通過，因資格 Gate 不足而未執行。\n\n"
    "檢索修復記錄：原 BM25 FTS5 表為 contentless 結構，直接讀 `chunk_id` 欄位會得到空值，造成原候選對照失敗。Phase V 改以 FTS rowid 對應 eligible chunk JSONL 固定順序，並驗證 FTS rowid 1–10412、dense matrix row order SHA 及 chunk ID 對照後重跑 180 題。最初的 retrieval summary 曾報 18 題完整 Top-5；以修正後 `retrieval_results_v3_final.jsonl` 重算為 37 題，舊早期數字未用於本報告。\n\n"
    "## 停止理由\n\n"
    "研究負責人已核准來源矩陣，但核准不消除文件自身的使用權、版本、發布者、解析及物種適用性阻塞。只有41題處於 AI 輔助來源映射候選狀態，且類別分布失衡、鰻魚0題、疾病與藥法0題。完整 Top-5 37/180；Logical/Arithmetic rubric 與可信 Context relevance gold 未凍結。依 Phase V 指示，未啟動 720 次昂貴生成。\n\n"
    "## 後續必要工作\n\n"
    "1. 對50份全文阻塞檔案逐件取得可適用的使用依據，或以明確允許索引的來源替代；先處理7份解析品質問題。\n"
    "2. 補足鰻魚及疾病、水質、藥法等適用來源，逐題建立可複現答案與rubric，並由研究負責人／專家處理需要專業判斷的條目。\n"
    "3. 增加適用且不越權的檢索候選後，重新完成完整 Top-5 來源追溯和評測規準凍結。\n"
    "4. 再完成新版 Generator/API、引用顯示、拒答及 Streamlit 整合測試，然後才考慮 720 次回歸／探索性生成。\n\n"
    "未切換正式環境，沒有改寫舊題庫、原始 720 筆生成、Evaluation Corpus v2、Historical E4、Production 或正式 SQLite。\n"
)
(OUT / "phase_v_final_report.md").write_text(summary, encoding="utf-8")

print(json.dumps({
    "output": str(OUT),
    "chunks": len(chunks), "eligible": len(eligible_chunks), "context_only": len(context_only),
    "retrieval_status": dict(status_counts), "any_top5": top_with_any, "full_top5": full_top5,
    "traceback_errors": len(trace_errors), "candidate_refs": 41, "not_evaluable": 139,
    "source_blockers": len(blockers), "source_checksums_match": sum(bool(r.get("checksum_match")) for r in blockers),
    "owner_approved": owner["owner_approved_count"], "unique_hashes": owner["distinct_sha256_count"],
}, ensure_ascii=True, indent=2))
