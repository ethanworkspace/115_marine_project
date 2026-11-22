"""Build a deterministic shadow corpus from Phase 5/6 reports only."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from ..gate import can_index
from .common import CHUNK_VERSION, ChunkFactory, TextUnit, contiguous_page_groups
from .disease import chunk_disease
from .fallback import chunk_fallback
from .manual import chunk_manual
from .regulation import chunk_regulation
from .router import choose_strategy
from .table import chunk_accepted_tables


ROOT = Path(__file__).resolve().parents[3]


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in records),
                         encoding="utf-8", newline="\n")
    temporary.replace(path)


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                         encoding="utf-8", newline="\n")
    temporary.replace(path)


def _load_config(path: Path) -> dict[str, Any]:
    config = json.loads(path.read_text(encoding="utf-8"))
    for key in ("target_size", "max_size", "minimum_size", "overlap", "table_row_group_size"):
        if not isinstance(config.get(key), int) or config[key] < 0:
            raise ValueError(f"invalid chunking config: {key}")
    if (config["max_size"] <= config["overlap"] or config["minimum_size"] > config["max_size"]
            or config["target_size"] > config["max_size"]):
        raise ValueError("chunking sizes are inconsistent")
    return config


def _length_percentile(lengths: list[int], percentile: float) -> float:
    if not lengths:
        return 0.0
    ordered = sorted(lengths)
    position = (len(ordered) - 1) * percentile
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    return round(ordered[low] + (ordered[high] - ordered[low]) * (position - low), 2)


def _write_outputs(root: Path, records: list[dict[str, Any]], spans: dict[str, dict[str, Any]],
                   excluded_pages: list[dict[str, Any]], decisions: list[dict[str, Any]],
                   input_count: int, eligible_count: int, table_accepted_count: int,
                   config: dict[str, Any]) -> dict[str, Any]:
    report_dir = root / "reports" / "chunking"
    shadow_dir = root / "data" / "shadow"
    write_jsonl(shadow_dir / "chunks_v2.jsonl", records)
    write_jsonl(shadow_dir / "source_spans_v2.jsonl", sorted(spans.values(), key=lambda x: x["source_span_id"]))
    write_jsonl(report_dir / "chunk_inventory.jsonl", [
        {key: value for key, value in record.items() if key not in {"text", "table_data"}}
        for record in records
    ])
    parent_map = [{
        "parent_chunk_id": record["parent_chunk_id"],
        "child_chunk_id": record["chunk_id"],
        "document_id": record["document_id"],
        "page_start": record["page_start"], "page_end": record["page_end"],
        "source_span_ids": record["source_span_ids"],
    } for record in records if record["chunk_type"] == "child"]
    write_jsonl(report_dir / "parent_child_map.jsonl", parent_map)
    write_jsonl(report_dir / "excluded_pages.jsonl", excluded_pages)

    by_doc: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        by_doc[record["document_id"]].append(record)
    children_by_parent = Counter(record["parent_chunk_id"] for record in records if record["chunk_type"] == "child")
    exact_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        exact_groups[record["content_checksum"]].append(record)
    exact_extra = 0
    exact_group_count = 0
    duplicate_output: list[dict[str, Any]] = []
    for group in exact_groups.values():
        if len(group) < 2:
            continue
        unrelated_pairs: list[tuple[str, str]] = []
        for i, first in enumerate(group):
            for second in group[i + 1:]:
                if first["parent_chunk_id"] == second["chunk_id"] or second["parent_chunk_id"] == first["chunk_id"]:
                    continue
                unrelated_pairs.append((first["chunk_id"], second["chunk_id"]))
        if unrelated_pairs:
            exact_group_count += 1
            unrelated_ids = {chunk_id for pair in unrelated_pairs for chunk_id in pair}
            exact_extra += max(0, len(unrelated_ids) - 1)
            duplicate_output.append({
                "content_checksum": group[0]["content_checksum"],
                "chunk_ids": [record["chunk_id"] for record in group],
                "parent_child_relationship_present": any(
                    first["parent_chunk_id"] == second["chunk_id"] or second["parent_chunk_id"] == first["chunk_id"]
                    for i, first in enumerate(group) for second in group[i + 1:]
                ),
                "unrelated_duplicate_pairs": [list(pair) for pair in unrelated_pairs],
                "action": "candidate_only; no automatic deletion",
            })
    write_jsonl(report_dir / "exact_duplicate_candidates.jsonl", duplicate_output)

    # Candidate-only comparison, scoped within each document to avoid an unbounded all-pairs pass.
    from difflib import SequenceMatcher
    near_pairs: list[dict[str, Any]] = []
    for document_id, doc_records in by_doc.items():
        candidates = [r for r in doc_records if len(r["text"]) >= int(config["minimum_size"])]
        normalized = [" ".join(r["text"].casefold().split()) for r in candidates]
        for i, first in enumerate(candidates):
            left = normalized[i]
            for j in range(i + 1, len(candidates)):
                second = candidates[j]
                if first["content_checksum"] == second["content_checksum"]:
                    continue
                if first["parent_chunk_id"] == second["chunk_id"] or second["parent_chunk_id"] == first["chunk_id"]:
                    continue
                right = normalized[j]
                if not right or abs(len(left) - len(right)) / max(len(left), len(right)) > 0.12:
                    continue
                similarity = SequenceMatcher(None, left, right, autojunk=True).ratio()
                if similarity >= float(config.get("near_duplicate_similarity", 0.94)):
                    near_pairs.append({
                        "document_id": document_id,
                        "chunk_id_a": first["chunk_id"], "chunk_id_b": second["chunk_id"],
                        "similarity": round(similarity, 4), "action": "candidate_only; no automatic deletion",
                    })
    write_jsonl(report_dir / "duplicate_candidates.jsonl", near_pairs)

    lengths = [len(record["text"]) for record in records]
    parent_lengths = [len(record["text"]) for record in records if record["chunk_type"] == "parent"]
    child_lengths = [len(record["text"]) for record in records if record["chunk_type"] == "child"]
    statuses = Counter(record["ingestion_status"] for record in records)
    strategy_counts = Counter(record["chunk_strategy"] for record in records)
    type_counts = Counter(record["chunk_type"] for record in records)
    verified = sum(1 for record in records if record["source_verified"])
    current_legal = sum(1 for record in records if record["legal_status"] == "current")
    missing_page = sum(1 for record in records if record["page_start"] is None or record["page_end"] is None)
    missing_section = sum(1 for record in records if not record["section"])
    missing_parent = sum(1 for record in records if record["chunk_type"] == "child" and not record["parent_chunk_id"])
    def has_incomplete_provenance(record: dict[str, Any]) -> bool:
        if (not record.get("document_id") or not record.get("page_start") or not record.get("page_end") or
                not record.get("source_span_ids") or record.get("parser_name") in {None, "", "unknown"} or
                record.get("parser_version") in {None, "", "unknown"} or
                record.get("extraction_method") in {None, "", "unknown"}):
            return True
        for span_id in record["source_span_ids"]:
            span = spans.get(span_id)
            if not span or not all(span.get(field) not in {None, ""} for field in (
                "document_id", "file_checksum", "page_number", "parser_name", "parser_version", "extraction_method"
            )):
                return True
        return False

    provenance_missing = sum(1 for record in records if has_incomplete_provenance(record))
    cross_section = cross_article = cross_document = duplicate_source_overlap = 0
    span_by_id = spans
    overlap_pairs: set[tuple[str, str]] = set()
    record_by_id = {record["chunk_id"]: record for record in records}
    cross_document = sum(
        1 for record in records
        if any(span_by_id.get(span_id, {}).get("document_id") != record["document_id"]
               for span_id in record["source_span_ids"])
    )
    spans_by_location: dict[tuple[str, int], list[tuple[str, int, int]]] = defaultdict(list)
    duplicate_source_pairs: dict[tuple[str, str], dict[str, Any]] = {}
    for record in records:
        for span_id in record["source_span_ids"]:
            span = span_by_id.get(span_id, {})
            if span.get("start_position") is None or span.get("end_position") is None:
                continue
            location = (str(span.get("file_checksum")), int(span.get("page_number") or 0))
            spans_by_location[location].append((record["chunk_id"], int(span["start_position"]), int(span["end_position"])))
    for occurrences in spans_by_location.values():
        occurrences.sort(key=lambda item: (item[1], item[2], item[0]))
        for index, (first_id, first_start, first_end) in enumerate(occurrences):
            first = record_by_id[first_id]
            for second_id, second_start, second_end in occurrences[index + 1:]:
                if second_start >= first_end:
                    break
                if first_id == second_id:
                    continue
                second = record_by_id[second_id]
                if first["parent_chunk_id"] == second_id or second["parent_chunk_id"] == first_id:
                    continue
                if max(first_start, second_start) >= min(first_end, second_end):
                    continue
                pair = tuple(sorted((first_id, second_id)))
                if pair in overlap_pairs:
                    continue
                overlap_pairs.add(pair)
                if first["document_id"] != second["document_id"]:
                    duplicate_source_overlap += 1
                if first["section"] != second["section"]:
                    cross_section += 1
                if first["article"] != second["article"]:
                    cross_article += 1
                if first["document_id"] != second["document_id"]:
                    entry = duplicate_source_pairs.setdefault(pair, {
                        "chunk_ids": list(pair),
                        "document_ids": sorted({first["document_id"], second["document_id"]}),
                        "file_checksum": location[0],
                        "overlapping_pages": [],
                        "action": "duplicate source record review; no automatic deletion",
                    })
                    page_ref = {"file_checksum": location[0], "page_number": location[1]}
                    if page_ref not in entry["overlapping_pages"]:
                        entry["overlapping_pages"].append(page_ref)
    write_jsonl(report_dir / "duplicate_source_overlap_candidates.jsonl", [
        duplicate_source_pairs[key] for key in sorted(duplicate_source_pairs)
    ])
    duplicate_source_overlap = len(duplicate_source_pairs)
    quality = {
        "chunk_version": str(config.get("chunk_version", CHUNK_VERSION)),
        "input_pages": input_count,
        "eligible_pages": eligible_count,
        "excluded_pages": len(excluded_pages),
        "table_records_admitted": table_accepted_count,
        "total_chunks": len(records),
        "parent_chunks": type_counts["parent"], "child_chunks": type_counts["child"],
        "table_chunks": strategy_counts["table"],
        "regulation_chunks": strategy_counts["regulation"],
        "manual_chunks": strategy_counts["manual"], "disease_chunks": strategy_counts["disease"],
        "fallback_chunks": strategy_counts["fallback"],
        "chunkable": sum(bool(r["chunkable"]) for r in records),
        "indexable": sum(bool(r["indexable"]) for r in records),
        "source_verified": verified, "source_unverified": len(records) - verified,
        "legal_current": current_legal,
        "legal_unknown": sum(1 for r in records if r["legal_status"] == "unknown"),
        "legal_status_counts": dict(Counter(r["legal_status"] for r in records)),
        "min_length": min(lengths, default=0), "max_length": max(lengths, default=0),
        "max_parent_length": max(parent_lengths, default=0),
        "max_child_length": max(child_lengths, default=0),
        "mean_length": round(sum(lengths) / len(lengths), 2) if lengths else 0,
        "median_length": _length_percentile(lengths, 0.5),
        "p90_length": _length_percentile(lengths, 0.9), "p95_length": _length_percentile(lengths, 0.95),
        "chunks_under_20": sum(n < 20 for n in lengths),
        "chunks_under_100": sum(n < 100 for n in lengths),
        "chunks_over_limit": sum(n > int(config["max_size"]) for n in lengths),
        "child_chunks_over_limit": sum(n > int(config["max_size"]) for n in child_lengths),
        "parent_chunks_over_limit": sum(1 for r in records if r["chunk_type"] == "parent" and len(r["text"]) > int(config["max_size"])),
        "missing_document_id": sum(1 for r in records if not r["document_id"]),
        "missing_page": missing_page, "missing_species": sum(1 for r in records if not r["species"]),
        "missing_topic": sum(1 for r in records if not r["topic"]),
        "missing_disease": sum(1 for r in records if not r["disease"]),
        "missing_section": missing_section, "missing_parent": missing_parent,
        "exact_duplicates": exact_extra, "exact_duplicate_groups": exact_group_count,
        "near_duplicate_candidates": len(near_pairs),
        "cross_section_overlap": cross_section,
        "cross_article_overlap": cross_article,
        "cross_document_overlap": cross_document,
        "duplicate_source_overlap_candidates": duplicate_source_overlap,
        "provenance_missing": provenance_missing,
        "chunk_ingestion_status_counts": dict(statuses),
        "strategy_document_decisions": decisions,
        "notes": [
            "This is a shadow corpus only. It has not been embedded or indexed.",
            "Parents may exceed the child max_size because they preserve a complete source structure node.",
            "Same-checksum source spans assigned to separate duplicate document records are counted as duplicate_source_overlap_candidates, not cross-document chunk leakage.",
            "No retrieval quality claim is made; no Gold QA retrieval benchmark exists yet.",
            "Near-duplicate candidates compare non-parent-child chunks of at least minimum_size within the same document; no candidates are deleted.",
        ],
    }
    write_json(report_dir / "chunk_quality.json", quality)
    write_json(report_dir / "strategy_summary.json", {
        "chunk_count_by_strategy": dict(strategy_counts),
        "chunk_count_by_type": dict(type_counts),
        "document_count_by_strategy": dict(Counter(decision["strategy"] for decision in decisions)),
        "decisions": decisions,
        "configuration": config,
    })
    _write_baseline_comparison(root, quality)
    return quality


def _write_baseline_comparison(root: Path, quality: dict[str, Any]) -> None:
    baseline = json.loads((root / "reports" / "data_quality.json").read_text(encoding="utf-8"))
    metrics = baseline.get("metrics", {})
    current_chunks = metrics.get("chunks", {})
    current_metadata = metrics.get("metadata", {})
    duplicates = metrics.get("duplicate_chunks", {})
    current = {
        "total_chunks": current_chunks.get("count"),
        "chunks_under_20": current_chunks.get("under_20_chars"),
        "chunks_under_100": current_chunks.get("under_100_chars"),
        "duplicate_chunks_extra_rows": duplicates.get("extra_rows"),
        "missing_page": current_metadata.get("missing_page"),
        "missing_species": current_metadata.get("missing_species"),
        "missing_topic": current_metadata.get("missing_topic"),
        "provenance_complete_count": None,
    }
    v2 = {
        "total_chunks": quality["total_chunks"],
        "chunks_under_20": quality["chunks_under_20"],
        "chunks_under_100": quality["chunks_under_100"],
        "duplicate_chunks_extra_rows": quality["exact_duplicates"],
        "missing_page": quality["missing_page"],
        "missing_species": quality["missing_species"],
        "missing_topic": quality["missing_topic"],
        "provenance_complete_count": quality["total_chunks"] - quality["provenance_missing"],
    }
    comparison = {
        "current_production_chunking": current,
        "chunking_v2_shadow": v2,
        "interpretation": "Descriptive corpus/provenance comparison only. Retrieval quality is unknown until a Gold QA retrieval benchmark exists.",
        "population_note": "The production corpus contains its existing indexed chunk set, while v2 contains only the 485 ingestion-gate-approved Parser v2 records and stores both parent and child nodes; raw counts and short/duplicate ratios are not an apples-to-apples comparison.",
        "short_chunk_note": "In v2, most chunks under 20 characters are regulation nodes or clauses whose legal boundaries were preserved. Review these by strategy; do not merge across articles to improve the size metric.",
        "production_modified": False,
        "formal_index_rebuilt": False,
    }
    write_json(root / "reports" / "chunking" / "baseline_comparison.json", comparison)


def build_shadow_corpus(root: Path | str = ROOT) -> dict[str, Any]:
    root = Path(root)
    config = _load_config(root / "config" / "chunking_v2.json")
    page_records = read_jsonl(root / "reports" / "parsing" / "page_inventory.jsonl")
    documents = {record["document_id"]: record for record in read_jsonl(root / "reports" / "parsing" / "document_eligibility.jsonl")}
    eligible_pages: dict[str, list[dict[str, Any]]] = defaultdict(list)
    excluded: list[dict[str, Any]] = []
    for page in page_records:
        if can_index(page):
            eligible_pages[str(page["document_id"])].append({**page, "_chunkable": True})
        else:
            excluded.append({
                "document_id": page.get("document_id"), "page_number": page.get("page_number"),
                "ingestion_status": page.get("ingestion_status"),
                "review_reason": page.get("review_reason") or [],
                "included_in_shadow": False,
            })
    spans: dict[str, dict[str, Any]] = {}
    factory = ChunkFactory(config=config, span_registry=spans)
    decisions: list[dict[str, Any]] = []
    table_admitted = 0
    for document_id in sorted(eligible_pages):
        pages = sorted(eligible_pages[document_id], key=lambda item: int(item.get("page_number") or 0))
        document = documents.get(document_id)
        if not document:
            # Fail closed if a page has no document manifest row.
            excluded.extend({
                "document_id": document_id, "page_number": page.get("page_number"),
                "ingestion_status": page.get("ingestion_status"),
                "review_reason": ["missing_document_manifest"], "included_in_shadow": False,
            } for page in pages)
            continue
        decision = choose_strategy(document, pages)
        decisions.append({
            "document_id": document_id, "title": document.get("title"),
            "strategy": decision.strategy, "warning": decision.warning,
            "evidence": list(decision.evidence),
            "source_verified": document.get("source_verified") is True,
            "legal_status": document.get("legal_status") or "unknown",
        })
        for group in contiguous_page_groups(pages):
            unit = TextUnit(group)
            if decision.strategy == "regulation":
                chunk_regulation(document, unit, factory)
            elif decision.strategy == "manual":
                chunk_manual(document, unit, factory)
            elif decision.strategy == "disease":
                chunk_disease(document, unit, factory)
            else:
                chunk_fallback(document, group, factory, warning=decision.warning)
        table_admitted += chunk_accepted_tables(document, pages, factory)
    quality = _write_outputs(root, factory.records, spans, excluded, decisions,
                             len(page_records), sum(len(x) for x in eligible_pages.values()),
                             table_admitted, config)
    quality["documents_with_eligible_pages"] = len(eligible_pages)
    quality["documents_missing_manifest"] = sum(1 for row in excluded if "missing_document_manifest" in row.get("review_reason", []))
    quality["excluded_review_or_rejected_pages"] = len(excluded)
    # Rewrite with post-generation diagnostics while keeping deterministic content apart from timestamp.
    write_json(root / "reports" / "chunking" / "chunk_quality.json", quality)
    return quality
