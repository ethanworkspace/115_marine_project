"""Evidence-led candidate inventory and empty annotation-slot generation."""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from .corpus import read_jsonl, write_json, write_jsonl


SPECIES_ALIASES = {
    "吳郭魚": ("吳郭魚", "羅非魚", "tilapia"),
    "虱目魚": ("虱目魚", "milkfish"),
    "石斑魚": ("石斑魚", "石斑", "龍膽石斑", "groupers"),
    "鱸魚": ("鱸魚", "七星鱸", "金目鱸", "海鱸", "perch"),
    "烏魚": ("烏魚", "鯔魚", "mullet"),
    "鰻魚": ("鰻魚", "鰻", "eel"),
}


def _species(row: dict[str, Any]) -> tuple[str | None, str | None]:
    value = str(row.get("species") or "").strip()
    for canonical, aliases in SPECIES_ALIASES.items():
        if any(alias.casefold() in value.casefold() for alias in aliases):
            return canonical, "chunk_metadata"
    title = str(row.get("source_title") or "")
    for canonical, aliases in SPECIES_ALIASES.items():
        if any(alias.casefold() in title.casefold() for alias in aliases):
            return canonical, "document_title_candidate_only"
    return None, None


def _categories(row: dict[str, Any]) -> set[str]:
    strategy = str(row.get("chunk_strategy") or "")
    text = " ".join(str(row.get(key) or "") for key in ("topic", "disease", "chapter", "section", "source_title", "text"))
    categories: set[str] = set()
    if row.get("topic") or row.get("species"):
        categories.add("fact")
    if strategy == "disease" or row.get("disease") or any(term in text for term in ("疾病", "病原", "症狀", "診斷", "防治", "病害")):
        categories.add("disease")
    if any(term in text for term in ("水質", "溶氧", "氨氮", "亞硝酸", "pH", "鹽度")):
        categories.add("water_quality")
    if any(term in text for term in ("寒流", "低溫", "氣候", "防寒", "冷氣團")):
        categories.add("climate")
    if any(term in text for term in ("SOP", "操作程序", "管理技術", "養殖要點", "飼養管理")):
        categories.add("sop")
    if strategy == "regulation":
        categories.add("regulation")
    if any(term in text for term in ("動物用藥", "藥物", "用藥", "抗生素", "藥品")):
        categories.add("drug")
    if any(term in text for term in ("停藥期", "休藥期", "停藥", "休藥")):
        categories.add("withdrawal_period")
    if any(term in text for term in ("劑量", "dosage", "mg/kg", "濃度換算", "施用量", "計算濃度")):
        categories.add("calculation")
    if any(term in text for term in ("安全標準", "安全界線", "法定標準")):
        categories.add("safety_boundary")
    return categories


def build_question_candidates(corpus: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    usable = [row for row in corpus if row.get("retrieval_role") == "retrieval" and row.get("duplicate_status") not in {"exact_duplicate", "duplicate_source"}]
    details: list[tuple[dict[str, Any], str | None, str | None, set[str]]] = []
    docs_per_species_topic: dict[tuple[str, str], set[str]] = defaultdict(set)
    for row in usable:
        species, basis = _species(row)
        topic = str(row.get("topic") or "").strip()
        if species and topic:
            docs_per_species_topic[(species, topic)].add(str(row.get("document_id")))
        categories = _categories(row)
        if species and not categories:
            categories.add("fact")
        details.append((row, species, basis, categories))
    candidates: list[dict[str, Any]] = []
    for row, species, basis, categories in details:
        if species and row.get("topic") and len(docs_per_species_topic[(species, str(row["topic"]))]) >= 2:
            categories.add("multi_document")
        category = next((item for item in (
            "regulation", "withdrawal_period", "drug", "safety_boundary", "calculation",
            "water_quality", "disease", "climate", "sop", "multi_document", "fact"
        ) if item in categories), None)
        candidate_id = f"candidate_{row['chunk_id'].removeprefix('chunk_')}"
        candidates.append({
            "candidate_id": candidate_id,
            "source_document_id": row.get("document_id"),
            "source_title": row.get("source_title"),
            "page": row.get("page_start"),
            "chunk_id": row.get("chunk_id"),
            "species": species,
            "species_basis": basis,
            "topic": row.get("topic"),
            "possible_category": category,
            "possible_categories": sorted(categories),
            "risk_level": row.get("risk_level", "normal"),
            "benchmark_eligible": bool(row.get("benchmark_eligible")),
            "source_verification_status": row.get("source_verification_status", "pending"),
            "candidate_status": "candidate_only_not_gold",
        })
    candidates.sort(key=lambda item: (str(item.get("species") or ""), str(item.get("possible_category") or ""), str(item.get("source_document_id") or ""), item.get("page") or 0, item["chunk_id"]))
    summary = {
        "candidate_count": len(candidates),
        "species_counts": dict(sorted(Counter(row["species"] or "unknown" for row in candidates).items())),
        "possible_category_counts": dict(sorted(Counter(row["possible_category"] or "unsupported_or_unclassified" for row in candidates).items())),
        "category_tags": dict(sorted(Counter(category for row in candidates for category in row["possible_categories"]).items())),
        "warning": "Candidates are source locators only, not questions or Gold labels. Species derived from title is provisional candidate metadata.",
    }
    return candidates, summary


def build_pilot_slots(candidates: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Make null-valued slots only where a real candidate supports a category."""
    by_species_category: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in candidates:
        if row.get("species") and row.get("possible_category"):
            by_species_category[(row["species"], row["possible_category"])].append(row)
    group_a_categories = ("fact", "water_quality", "disease", "climate", "sop", "multi_document")
    group_a_caps = {"fact": 3, "water_quality": 3, "disease": 3, "climate": 2, "sop": 2, "multi_document": 2}
    group_b_categories = ("insufficient_information", "conflicting_sources", "ambiguous", "multi_document")
    group_c_categories = ("regulation", "drug", "withdrawal_period", "calculation", "safety_boundary")
    specs: list[tuple[str, str | None, str, int]] = []
    for species in SPECIES_ALIASES:
        for category in group_a_categories:
            specs.append(("A", species, category, group_a_caps[category]))
    # Group B needs evidence of actual coverage (or a sourced disagreement), which
    # cannot be inferred by absence alone. Only multi-document locators are offered.
    specs.append(("B", None, "multi_document", 30))
    for category in group_c_categories:
        specs.append(("C", None, category, 6))

    slots: list[dict[str, Any]] = []
    gaps: list[dict[str, Any]] = []
    next_id = 1
    for group, species, category, cap in specs:
        pool = []
        if species:
            pool = [row for row in candidates if row.get("species") == species and category in row.get("possible_categories", [])]
        else:
            pool = [row for row in candidates if category in row.get("possible_categories", [])]
        # For grouped Group B/C categories we still make at most one slot per
        # unique source chunk. No question or target answer is authored here.
        count = min(cap, len(pool))
        if not count:
            gaps.append({"group": group, "species": species, "category": category, "target_slots": cap, "available_candidates": 0, "status": "unsupported_by_current_candidate_inventory"})
            continue
        for candidate in pool[:count]:
            is_high = category in group_c_categories or candidate.get("risk_level") == "high"
            question_id = f"pilot_{next_id:04d}"
            next_id += 1
            slots.append({
                "question_id": question_id,
                "group": f"Group {group}",
                "question": None,
                "species": species or candidate.get("species"),
                "category": category,
                "difficulty": None,
                "answerable": None,
                "expected_abstention": None,
                "gold_answer": None,
                "gold_documents": [], "gold_pages": [], "gold_chunks": [],
                "required_chunks": [], "acceptable_chunks": [], "supporting_claims": [], "conflicting_chunks": [],
                "source_verification_required": is_high,
                "source_verification_status": "pending" if is_high else "pending",
                "annotation_status": "blocked" if is_high else "draft",
                "annotator": None, "reviewer": None,
                "notes": "空白標註 slot；不是問題或 Gold record。需人工撰題與核對 evidence。" + (" 高風險且來源未驗證，維持 blocked。" if is_high else ""),
                "candidate_ids": [candidate["candidate_id"]],
                "risk_level": "high" if is_high else "normal",
            })
        if count < cap:
            gaps.append({"group": group, "species": species, "category": category, "target_slots": cap, "available_candidates": len(pool), "created_slots": count, "status": "partial_candidate_coverage"})
    summary = {
        "target_slots": 150,
        "group_targets": {"Group A - Retrieval Core": 90, "Group B - Reliability": 30, "Group C - High Risk": 30},
        "created_annotation_slots": len(slots),
        "status_counts": dict(sorted(Counter(row["annotation_status"] for row in slots).items())),
        "group_counts": dict(sorted(Counter(row["group"] for row in slots).items())),
        "category_counts": dict(sorted(Counter(row["category"] for row in slots).items())),
        "high_risk_blocked_slots": sum(row["risk_level"] == "high" and row["annotation_status"] == "blocked" for row in slots),
        "coverage_gaps": gaps,
        "blocked_categories": ["insufficient_information", "conflicting_sources", "ambiguous"],
        "blocked_categories_reason": "Current corpus has no human-confirmed negative coverage, source conflict, or question ambiguity labels; these cannot be inferred safely from document presence alone.",
        "gold_answers_generated": 0,
        "gold_evidence_generated": 0,
    }
    return slots, summary


def build_pilot_outputs(root, corpus_path=None) -> dict[str, Any]:
    from pathlib import Path
    root = Path(root)
    corpus = read_jsonl(corpus_path or root / "data" / "evaluation" / "corpus_v1.jsonl")
    candidates, candidate_summary = build_question_candidates(corpus)
    slots, slot_summary = build_pilot_slots(candidates)
    write_jsonl(root / "reports" / "evaluation" / "question_candidates.jsonl", candidates)
    write_jsonl(root / "data" / "gold" / "pilot" / "questions.jsonl", slots)
    result = {"candidate_inventory": candidate_summary, "pilot_slots": slot_summary}
    write_json(root / "reports" / "evaluation" / "pilot_dataset_summary.json", result)
    return result
