import hashlib
import json
from pathlib import Path

ROOT = Path.cwd()
OUT = ROOT / "reports/evaluation/fish_test_phase_u_20261018_195823"


def jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]


def test_corpus_v3_manifest_and_artifacts_match():
    manifest = json.loads((OUT / "corpus_v3_final/corpus_v3_manifest.json").read_text(encoding="utf-8"))
    chunks = jsonl(OUT / "corpus_v3_final/corpus_chunks_v3_final.jsonl")
    assert len(chunks) == manifest["total_chunk_count"] == manifest["sqlite_chunk_count"]
    assert sum(bool(x["retrieval_eligible"]) for x in chunks) == manifest["retrieval_eligible_chunk_count"]
    assert sum(not bool(x["retrieval_eligible"]) for x in chunks) == manifest["context_only_chunk_count"]
    vectors = OUT / "corpus_v3_final/dense_vectors_final.f32"
    assert vectors.stat().st_size == manifest["embedding_index"]["vector_file_bytes"]
    assert hashlib.sha256(vectors.read_bytes()).hexdigest() == manifest["embedding_index"]["vector_file_sha256"]


def test_all_owner_decisions_are_approved_but_rights_are_separate():
    rows = jsonl(OUT / "source_owner_decision_update_57.jsonl")
    assert len(rows) == 57
    assert all(x["owner_decision"] == "APPROVED" for x in rows)
    rights = jsonl(OUT / "source_rights_version_scope_audit_57_final.jsonl")
    assert len(rights) == 57
    assert any(x.get("rights_status") == "source_identity_version_or_usage_basis_unverified" for x in rights)


def test_dgbas_2020_and_context_only_scope_are_preserved():
    rows = jsonl(OUT / "source_admission_registry_v3_final.jsonl")
    dgbas20 = next(x for x in rows if x["source_id"] == "DGBAS-79395-2020")
    assert "2020" in dgbas20["approved_usage_scope"]
    wra = next(x for x in rows if x["source_id"] == "WRA-AQUACULTURE-WATER-58700")
    assert "context_only" in wra["corpus_v3_inclusion_status"]
    assert any("water-quality" in x.casefold() for x in wra["prohibited_usage_scope"])


def test_retrieval_trace_only_uses_scope_approved_statute():
    rows = jsonl(OUT / "retrieval_results_v3_final.jsonl")
    assert len(rows) == 180
    populated = [x for x in rows if x["reranked_top5"]]
    assert len(populated) == 19
    assert sum(len(x["reranked_top5"]) for x in populated) == 95
    for row in populated:
        assert all(x["source_id"] == "MOA-FL014718-ACT" for x in row["reranked_top5"])
        assert [x["rank"] for x in row["reranked_top5"]] == [1, 2, 3, 4, 5]


def test_answer_scored_generation_fails_closed_when_no_question_qualified():
    eligibility = jsonl(OUT / "question_eligibility_v3.jsonl")
    assert len(eligibility) == 180
    assert not any(x["benchmark_eligible_v3"] for x in eligibility)
    generated = OUT / "generator_results_v3_final.jsonl"
    assert generated.exists() and generated.stat().st_size == 0


def test_no_exam_items_or_reference_answers_in_corpus():
    chunks = jsonl(OUT / "corpus_v3_final/corpus_chunks_v3_final.jsonl")
    ids = {x["chunk_id"] for x in chunks}
    assert not any(str(x.get("chunk_id", "")).startswith("FT-") for x in chunks)
    assert not any("candidate_reference_answer" in x for x in chunks)
    assert len(ids) == len(chunks)

