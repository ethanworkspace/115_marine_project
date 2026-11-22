"""Prepare candidate-backed, unannotated development work items and reports."""

from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from .annotation import atomic_write_jsonl, sha256_file, utc_now
from .annotation_sprint import MINIMUM_PHASE_9A_REVIEWED, build_annotation_sprint_report
from .corpus import read_jsonl, write_json
from .gold_lint import lint_dataset


ROOT = Path(__file__).resolve().parents[2]
TARGETS = {
    "fact": 10,
    "water_quality": 10,
    "disease": 10,
    "climate": 6,
    "sop": 6,
    "multi_document": 6,
}
SPECIES = ("吳郭魚", "虱目魚", "石斑魚", "鱸魚", "烏魚", "鰻魚")


def _select_diverse(pool: list[dict[str, Any]], limit: int, used: set[str]) -> list[dict[str, Any]]:
    candidates = [row for row in pool if row.get("chunk_id") not in used]
    chosen: list[dict[str, Any]] = []
    document_counts: Counter[str] = Counter()
    species_counts: Counter[str] = Counter()
    while candidates and len(chosen) < limit:
        candidates.sort(key=lambda row: (
            document_counts[str(row.get("source_document_id") or "")],
            species_counts[str(row.get("species") or "unknown")],
            row.get("species_basis") != "chunk_metadata",
            str(row.get("source_document_id") or ""),
            row.get("page") or 0,
            str(row.get("chunk_id") or ""),
        ))
        selected = candidates.pop(0)
        chosen.append(selected)
        used.add(str(selected.get("chunk_id")))
        document_counts[str(selected.get("source_document_id") or "")] += 1
        species_counts[str(selected.get("species") or "unknown")] += 1
        candidates = [row for row in candidates if row.get("chunk_id") not in used]
    return chosen


def _work_item(candidate: dict[str, Any], category: str, corpus_sha: str, created_at: str) -> dict[str, Any]:
    suffix = str(candidate.get("candidate_id", "candidate")).removeprefix("candidate_")
    return {
        "question_id": f"dev_{category}_{suffix}",
        "split": "development",
        "created_at": created_at,
        "question": None,
        "gold_answer": None,
        "answerable": None,
        "expected_abstention": None,
        "category": category,
        "target_category": category,
        "category_verified": False,
        "difficulty": None,
        "species": None,
        "species_verified": False,
        "candidate_species": candidate.get("species"),
        "candidate_species_basis": candidate.get("species_basis"),
        "topic": candidate.get("topic"),
        "document_scope": "multi-document" if category == "multi_document" else "single-document",
        "gold_documents": [], "gold_pages": [], "gold_chunks": [],
        "required_chunks": [], "acceptable_chunks": [], "conflicting_chunks": [],
        "gold_evidence_snapshot": [], "supporting_claims": [],
        "candidate_ids": [candidate["candidate_id"]],
        "candidate_chunk_ids": [candidate["chunk_id"]],
        "source_verification_required": False,
        "source_verification_status": candidate.get("source_verification_status", "pending"),
        "risk_level": "normal",
        "annotation_status": "draft",
        "annotator": None,
        "reviewer": None,
        "annotation_version": "0.1.0",
        "evaluation_corpus_version": "evaluation-corpus-v1",
        "evaluation_corpus_sha256": corpus_sha,
        "question_verified": False,
        "evidence_verified": False,
        "notes": "候選標註工作項，不是 Gold QA。問題、答案與 evidence 必須由人工輸入並核對。",
    }


def build_worklist(root: str | Path = ROOT) -> dict[str, Any]:
    root = Path(root)
    corpus_path = root / "data" / "evaluation" / "corpus_v1.jsonl"
    manifest_path = root / "data" / "evaluation" / "corpus_manifest.json"
    candidate_path = root / "reports" / "evaluation" / "question_candidates.jsonl"
    output_path = root / "data" / "gold" / "development" / "questions.jsonl"
    corpus = read_jsonl(corpus_path)
    candidates = read_jsonl(candidate_path)
    corpus_manifest = __import__("json").loads(manifest_path.read_text(encoding="utf-8"))
    corpus_sha = sha256_file(corpus_path)
    if corpus_manifest.get("evaluation_corpus_sha256") != corpus_sha:
        raise RuntimeError("Evaluation Corpus v1 checksum changed; refusing to rebind development annotations")
    current = {row.get("question_id"): row for row in read_jsonl(output_path)}
    created_at_default = utc_now()

    eligible_candidates = [
        row for row in candidates
        if row.get("benchmark_eligible") is True and row.get("risk_level") == "normal"
        and row.get("source_verification_status") in {"pending", "verified"}
        and row.get("chunk_id") in {item.get("chunk_id") for item in corpus if item.get("retrieval_role") == "retrieval"}
    ]
    created: list[dict[str, Any]] = []
    used_chunks: set[str] = set()
    gaps: list[dict[str, Any]] = []
    available_by_category: dict[str, list[dict[str, Any]]] = {
        category: [row for row in eligible_candidates if category in (row.get("possible_categories") or [])]
        for category in TARGETS
    }
    for category, target in TARGETS.items():
        selected = _select_diverse(available_by_category[category], target, used_chunks)
        if len(selected) < target:
            gaps.append({"category": category, "target": target, "available": len(available_by_category[category]), "selected": len(selected), "status": "coverage_gap"})
        for candidate in selected:
            item = _work_item(candidate, category, corpus_sha, created_at_default)
            existing = current.get(item["question_id"])
            if existing:
                item["created_at"] = existing.get("created_at", created_at_default)
                # Preserve completed human annotations on a rerun; candidate
                # locator and frozen corpus identity remain tied to this version.
                for key in (
                    "question", "gold_answer", "answerable", "expected_abstention", "category", "category_verified",
                    "difficulty", "species", "species_verified", "gold_documents", "gold_pages", "gold_chunks",
                    "required_chunks", "acceptable_chunks", "conflicting_chunks", "gold_evidence_snapshot",
                    "supporting_claims", "source_verification_required", "source_verification_status",
                    "annotation_status", "annotator", "reviewer", "question_verified", "evidence_verified", "notes",
                ):
                    if key in existing:
                        item[key] = existing[key]
                item["annotation_version"] = existing.get("annotation_version", "0.1.0")
            created.append(item)

    # Preserve human-authored records that no longer occur in the current
    # candidate selection; never silently discard annotation work.
    selected_ids = {row["question_id"] for row in created}
    created.extend(row for key, row in current.items() if key not in selected_ids)
    created.sort(key=lambda row: row["question_id"])
    atomic_write_jsonl(output_path, created)

    reports = refresh_reports(root, created, category_gaps=gaps)
    progress = reports["progress"]
    lint = reports["lint"]
    return {"eligible_candidates": len(eligible_candidates), "work_items": len(created), "progress": progress, "lint": lint}


def refresh_reports(root: str | Path = ROOT, records: list[dict[str, Any]] | None = None,
                    *, category_gaps: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    root = Path(root)
    corpus_path = root / "data" / "evaluation" / "corpus_v1.jsonl"
    corpus_manifest_path = root / "data" / "evaluation" / "corpus_manifest.json"
    corpus = read_jsonl(corpus_path)
    candidates = read_jsonl(root / "reports" / "evaluation" / "question_candidates.jsonl")
    if records is None:
        records = read_jsonl(root / "data" / "gold" / "development" / "questions.jsonl")
    if category_gaps is None:
        category_gaps = []
    corpus_manifest = __import__("json").loads(corpus_manifest_path.read_text(encoding="utf-8"))
    corpus_version = corpus_manifest.get("corpus_id", "evaluation-corpus-v1")
    corpus_sha = sha256_file(corpus_path)
    coverage = build_coverage_report(corpus, candidates, records)
    progress = build_progress_report(records, category_gaps, coverage)
    lint = lint_dataset(records, corpus, corpus_version=corpus_version, corpus_sha256=corpus_sha)
    sprint = build_annotation_sprint_report(
        read_jsonl(root / "data" / "gold" / "question_bank_candidates.jsonl")
        if (root / "data" / "gold" / "question_bank_candidates.jsonl").exists() else [],
        records,
        corpus,
        corpus_version=corpus_version,
        corpus_sha256=corpus_sha,
    )
    write_json(root / "reports" / "evaluation" / "annotation_sprint.json", sprint)
    status_counts = Counter(str(row.get("annotation_status") or "draft") for row in records)
    reviewed_complete = sprint["phase_9a_readiness"]["reviewed_gold_count"]
    readiness = {
        "development_target": sum(TARGETS.values()),
        "draft": status_counts["draft"],
        "annotated": status_counts["annotated"],
        "reviewed": reviewed_complete,
        "reviewed_status_rows": status_counts["reviewed"],
        "evidence_verified": sum(bool(row.get("evidence_verified")) for row in records),
        "minimum_smoke_test_questions": MINIMUM_PHASE_9A_REVIEWED,
        "minimum_baseline_questions": 48,
        "smoke_test_ready": reviewed_complete >= MINIMUM_PHASE_9A_REVIEWED,
        "baseline_ready": reviewed_complete >= 48,
        "evaluation_corpus_sha256": corpus_sha,
        "benchmark_executed": False,
        "note": "Readiness only. Only complete human-reviewed Gold records with no lint errors count; no retrieval benchmark is started automatically.",
    }
    write_json(root / "reports" / "evaluation" / "coverage_gaps.json", coverage)
    write_json(root / "reports" / "evaluation" / "annotation_progress.json", progress)
    write_json(root / "reports" / "evaluation" / "gold_lint_report.json", lint)
    write_json(root / "reports" / "evaluation" / "benchmark_readiness.json", readiness)
    return {"coverage": coverage, "progress": progress, "lint": lint, "sprint": sprint, "readiness": readiness}


def build_coverage_report(corpus: list[dict[str, Any]], candidates: list[dict[str, Any]], records: list[dict[str, Any]]) -> dict[str, Any]:
    matrix: list[dict[str, Any]] = []
    for species in SPECIES:
        for category in TARGETS:
            category_rows = [row for row in candidates if category in (row.get("possible_categories") or [])]
            species_rows = [row for row in category_rows if row.get("species") == species]
            eligible = [row for row in species_rows if row.get("benchmark_eligible") is True and row.get("risk_level") == "normal"]
            high_blocked = [row for row in species_rows if row.get("risk_level") == "high" and row.get("source_verification_status") != "verified"]
            unknown = [row for row in category_rows if not row.get("species") and row.get("benchmark_eligible") is True and row.get("risk_level") == "normal"]
            status = "has_candidate" if eligible else ("source_blocked" if high_blocked else ("metadata_unknown" if unknown else "no_candidate"))
            matrix.append({
                "species": species, "category": category,
                "candidate_count": len(species_rows),
                "eligible_normal_candidate_count": len(eligible),
                "species_from_chunk_metadata": sum(row.get("species_basis") == "chunk_metadata" for row in eligible),
                "species_from_title_candidate_only": sum(row.get("species_basis") == "document_title_candidate_only" for row in eligible),
                "metadata_unknown_candidate_count": len(unknown),
                "source_blocked_high_risk_count": len(high_blocked),
                "status": status,
            })
    slots_by_category = Counter(row.get("target_category") or row.get("category") for row in records)
    missing_slots = [row for row in matrix if row["status"] in {"no_candidate", "metadata_unknown", "source_blocked"}]
    source_blocked_categories = sorted({row["category"] for row in matrix if row["status"] == "source_blocked"})
    return {
        "corpus_version": "evaluation-corpus-v1",
        "eligible_candidate_filter": "benchmark_eligible=true, risk_level=normal, retrieval_role=retrieval",
        "species_categories": matrix,
        "category_work_items": dict(sorted(slots_by_category.items())),
        "coverage_gaps": missing_slots,
        "source_blocked_categories": source_blocked_categories,
        "notes": [
            "Candidate species derived from title remain provisional; question species stays null until annotator verifies source evidence.",
            "Coverage gaps are reported only; no gap is automatically converted into a question.",
            "High-risk and ineligible records are excluded from the development worklist.",
        ],
    }


def build_progress_report(records: list[dict[str, Any]], category_gaps: list[dict[str, Any]], coverage: dict[str, Any]) -> dict[str, Any]:
    answerable_counts = Counter(str(row.get("answerable")).lower() if isinstance(row.get("answerable"), bool) else "pending" for row in records)
    abstention_counts = Counter(str(row.get("expected_abstention")).lower() if isinstance(row.get("expected_abstention"), bool) else "pending" for row in records)
    difficulty_counts = Counter(str(row.get("difficulty") or "missing") for row in records)
    species_counts = Counter(str(row.get("species") or "missing") for row in records)
    statuses = Counter(str(row.get("annotation_status") or "missing") for row in records)
    categories = Counter(str(row.get("target_category") or row.get("category") or "missing") for row in records)
    snapshot_reference_count = sum(len(row.get("gold_evidence_snapshot", []) or []) for row in records)
    source_docs = [set(row.get("gold_documents", []) or []) for row in records]
    multi = sum(row.get("document_scope") == "multi-document" for row in records)
    return {
        "target_questions": sum(TARGETS.values()),
        "work_items_created": len(records),
        "draft": statuses["draft"], "annotated": statuses["annotated"], "reviewed": statuses["reviewed"],
        "blocked": statuses["blocked"], "locked": statuses["locked"],
        "by_category": dict(sorted(categories.items())),
        "by_species": dict(sorted(species_counts.items())),
        "by_difficulty": dict(sorted(difficulty_counts.items())),
        "answerable": {"true": answerable_counts["true"], "false": answerable_counts["false"], "pending": answerable_counts["pending"]},
        "abstention": {"true": abstention_counts["true"], "false": abstention_counts["false"], "pending": abstention_counts["pending"]},
        "single_document": len(records) - multi,
        "multi_document": multi,
        "missing_species": sum(not row.get("species") for row in records),
        "missing_topic": sum(not row.get("topic") for row in records),
        "evidence_snapshot_count": snapshot_reference_count,
        "gold_chunk_reference_count": sum(len(row.get("gold_chunks", []) or []) for row in records),
        "required_chunk_reference_count": sum(len(row.get("required_chunks", []) or []) for row in records),
        "acceptable_chunk_reference_count": sum(len(row.get("acceptable_chunks", []) or []) for row in records),
        "evidence_verified": sum(bool(row.get("evidence_verified")) for row in records),
        "question_verified": sum(bool(row.get("question_verified")) for row in records),
        "candidate_species_hints_unverified": dict(sorted(Counter(str(row.get("candidate_species") or "unknown") for row in records).items())),
        "coverage_gaps": category_gaps,
        "species_category_gap_count": len(coverage.get("coverage_gaps", [])),
        "annotation_completion_note": "Work items are draft slots only until a human supplies question, answer and evidence.",
    }
