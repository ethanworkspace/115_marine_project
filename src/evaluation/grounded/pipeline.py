"""Evidence-first Silver dataset construction; isolated from production RAG."""

from __future__ import annotations

import hashlib
import json
import re
import statistics
from collections import Counter, defaultdict
from typing import Any, Iterable


SPECIES_ALIASES: dict[str, tuple[str, ...]] = {
    "虱目魚": ("虱目魚",),
    "吳郭魚": ("吳郭魚", "羅非魚", "福壽魚"),
    "石斑魚": ("龍膽石斑", "鞍帶石斑", "石斑魚"),
    "鱸魚": ("金目鱸", "七星鱸", "鱸魚"),
    "烏魚": ("烏魚", "鯔魚"),
    "鰻魚": ("鰻魚", "鰻線"),
}
SPECIES_ORDER = ("虱目魚", "吳郭魚", "石斑魚", "鱸魚", "烏魚", "鰻魚")

CATEGORY_TERMS: dict[str, tuple[str, ...]] = {
    "disease": ("疾病", "病害", "病原", "病徵", "症狀", "診斷", "寄生蟲", "細菌", "病毒", "感染"),
    "water_quality": ("水質", "溶氧", "氨氮", "亞硝酸", "pH", "鹽度", "透明度", "水色"),
    "climate": ("寒流", "寒害", "颱風", "氣候", "氣溫", "冷氣團", "極端氣候"),
    "sop": ("放苗", "整池", "清池", "消毒", "投餌", "投料", "餵食", "收成", "收穫", "作業流程", "管理作業"),
}

STRUCTURAL_WARNING_MARKERS = (
    "document type or stable heading structure could not be confirmed",
    "manual strategy found no heading",
    "parser error",
    "OCR quality reject",
    "unknown format",
)
ALLOWED_QUERY_STYLES = ("direct", "paraphrase", "contextual")
STYLE_DIFFICULTY = {"direct": "easy", "paraphrase": "medium", "contextual": "medium"}


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _species_mentions(text: str) -> set[str]:
    return {
        species
        for species, aliases in SPECIES_ALIASES.items()
        if any(alias.casefold() in text.casefold() for alias in aliases)
    }


def reliable_species(record: dict[str, Any]) -> tuple[str | None, str]:
    """Retain only explicit text/title species evidence; correct conflicting inherited tags."""
    text = str(record.get("text") or "")
    title = str(record.get("source_title") or "")
    in_text = _species_mentions(text)
    in_title = _species_mentions(title)
    metadata = record.get("species")
    if len(in_text) == 1:
        found = next(iter(in_text))
        return found, "explicit_chunk_text"
    if len(in_text) > 1:
        return None, "multiple_species_in_chunk_text"
    if len(in_title) == 1:
        found = next(iter(in_title))
        if metadata == found:
            return found, "document_title_and_corpus_metadata"
        return found, "explicit_document_title"
    if metadata in SPECIES_ALIASES and not in_title:
        return str(metadata), "corpus_metadata_no_text_conflict"
    return None, "unknown_or_ambiguous"


def classify_categories(text: str, topic: str | None = None, strategy: str | None = None) -> list[str]:
    """Assign only categories with explicit topic/text evidence; fact is the safe fallback."""
    found: list[str] = []
    normalized_topic = (topic or "").casefold()
    if strategy == "disease" or "疾病" in normalized_topic or "病害" in normalized_topic:
        return ["disease"]
    for category, terms in CATEGORY_TERMS.items():
        if category == "disease":
            continue
        if any(term.casefold() in normalized_topic for term in terms) or any(term.casefold() in text.casefold() for term in terms):
            found.append(category)
    if not found:
        return ["fact"]
    # A category is a benchmark slice, not an exhaustive semantic annotation.
    # Prefer the most specific issue class when a chunk mentions several topics.
    priority = ("disease", "water_quality", "climate", "sop")
    return [next(category for category in priority if category in found)]


def _page_numbers(record: dict[str, Any], spans: list[dict[str, Any]]) -> list[int]:
    pages = sorted({int(span["page_number"]) for span in spans if span.get("page_number") is not None})
    if not pages and record.get("page_start") is not None:
        pages = [int(record["page_start"])]
    return pages


def _quality_status(record: dict[str, Any], spans: list[dict[str, Any]], pages: list[int]) -> tuple[str, list[str]]:
    text = str(record.get("text") or "")
    warnings = [str(item) for item in (record.get("warnings") or [])]
    reasons: list[str] = []
    if len(text.strip()) < 20:
        reasons.append("text_under_20_characters")
        return "rejected", reasons
    if not record.get("document_id") or not record.get("chunk_id"):
        reasons.append("missing_chunk_or_document_id")
        return "rejected", reasons
    if not pages or not spans:
        reasons.append("missing_page_or_source_span")
        return "rejected", reasons
    checksum = str(record.get("content_checksum") or "")
    if not checksum or checksum != sha256_text(text):
        reasons.append("content_checksum_mismatch")
        return "rejected", reasons
    if "\ufffd" in text:
        reasons.append("replacement_character_present")
        return "rejected", reasons
    if record.get("chunk_strategy") == "table":
        table_data = record.get("table_data")
        if not table_data or table_data.get("quality_status") != "accepted":
            reasons.append("table_structure_not_gate_accepted")
            return "review_candidate", reasons
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    toc_line = re.compile(r"^(?:目錄|目次|contents|第.{1,8}[章節篇]|.{1,40}\s+\d{1,3})$", re.IGNORECASE)
    if len(lines) >= 4 and sum(bool(toc_line.match(line)) for line in lines) / len(lines) >= 0.8:
        reasons.append("table_of_contents_or_heading_fragment")
        return "review_candidate", reasons
    if any(any(marker.casefold() in warning.casefold() for marker in STRUCTURAL_WARNING_MARKERS) for warning in warnings):
        reasons.append("structural_parser_warning")
        return "review_candidate", reasons
    confidence = record.get("extraction_confidence")
    if isinstance(confidence, (int, float)) and confidence < 0.65:
        reasons.append("extraction_confidence_below_0_65")
        return "review_candidate", reasons
    if len(text.strip()) < 100:
        reasons.append("text_under_100_characters")
        return "review_candidate", reasons
    if len(text) > 6000:
        reasons.append("long_chunk_context_requires_review")
        return "review_candidate", reasons
    if warnings:
        reasons.extend(f"nonfatal_metadata_warning:{warning}" for warning in warnings)
    return "accepted", reasons


def build_evidence_pool(corpus_rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build a new, normal-risk retrieval-only pool without mutating Evaluation Corpus v2."""
    result: list[dict[str, Any]] = []
    for source in corpus_rows:
        if source.get("retrieval_role") != "retrieval":
            continue
        if source.get("duplicate_status") not in {"none", "canonical"}:
            continue
        if source.get("duplicate_status") == "canonical" and source.get("canonical_chunk_id") != source.get("chunk_id"):
            continue
        if source.get("duplicate_status") == "none" and source.get("canonical_chunk_id") not in (None, source.get("chunk_id")):
            continue
        if source.get("risk_level") != "normal":
            continue

        spans = [dict(span) for span in (source.get("source_spans") or [])]
        pages = _page_numbers(source, spans)
        status, reasons = _quality_status(source, spans, pages)
        species, species_provenance = reliable_species(source)
        text = str(source.get("text") or "")
        topic = source.get("topic") if isinstance(source.get("topic"), str) else None
        categories = classify_categories(text, topic, str(source.get("chunk_strategy") or ""))
        result.append({
            "chunk_id": str(source.get("chunk_id") or ""),
            "canonical_chunk_id": str(source.get("canonical_chunk_id") or source.get("chunk_id") or ""),
            "document_id": str(source.get("canonical_document_id") or source.get("document_id") or ""),
            "canonical_document_id": str(source.get("canonical_document_id") or source.get("document_id") or ""),
            "document_title": source.get("source_title"),
            "page": pages[0] if pages else None,
            "pages": pages,
            "source_span": spans,
            "content_checksum": source.get("content_checksum"),
            "source_checksum": source.get("source_checksum"),
            "text": text,
            "species": species,
            "species_metadata_candidate": source.get("species"),
            "species_provenance": species_provenance,
            "topic": topic,
            "category": categories[0],
            "category_candidates": categories,
            "chunk_strategy": source.get("chunk_strategy"),
            "chunk_type": source.get("chunk_type"),
            "chunk_version": source.get("chunk_version"),
            "parser_name": source.get("parser_name"),
            "parser_version": source.get("parser_version"),
            "extraction_method": source.get("extraction_method"),
            "extraction_confidence": source.get("extraction_confidence"),
            "risk_level": "normal",
            "source_verified": source.get("source_verified"),
            "source_verification_status": source.get("source_verification_status"),
            "warnings": list(source.get("warnings") or []),
            "evidence_quality_status": status,
            "quality_reasons": reasons,
        })
    return sorted(result, key=lambda row: (row["document_id"], row["page"] or 0, row["chunk_id"]))


def _balanced_take(records: list[dict[str, Any]], count: int, *, doc_counts: Counter[str],
                   species_counts: Counter[str], strategy_counts: Counter[str], max_per_doc: int,
                   already: set[str]) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    remaining = [row for row in records if row["chunk_id"] not in already]
    while remaining and len(selected) < count:
        allowed = [row for row in remaining if doc_counts[row["document_id"]] < max_per_doc]
        if not allowed:
            break
        def score(row: dict[str, Any]) -> tuple[float, str]:
            species = str(row.get("species") or "unknown")
            strategy = str(row.get("chunk_strategy") or "unknown")
            value = 2.0 / (1 + doc_counts[row["document_id"]])
            value += 1.5 / (1 + species_counts[species])
            value += 0.5 / (1 + strategy_counts[strategy])
            return value, str(row["chunk_id"])
        chosen = max(allowed, key=score)
        selected.append(chosen)
        already.add(chosen["chunk_id"])
        doc_counts[chosen["document_id"]] += 1
        species_counts[str(chosen.get("species") or "unknown")] += 1
        strategy_counts[str(chosen.get("chunk_strategy") or "unknown")] += 1
        remaining.remove(chosen)
    return selected


def select_multidocument_pairs(accepted: list[dict[str, Any]], count: int = 6) -> list[list[dict[str, Any]]]:
    grouped: dict[tuple[str, str], dict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    for row in accepted:
        species = row.get("species")
        if not species:
            continue
        grouped[(str(species), str(row.get("category") or "fact"))][row["document_id"]].append(row)
    pair_candidates: list[tuple[tuple[str, str], list[dict[str, Any]]]] = []
    for key, docs in grouped.items():
        if len(docs) < 2:
            continue
        ordered_docs = sorted(docs)
        left_doc, right_doc = ordered_docs[:2]
        left = max(docs[left_doc], key=lambda row: (len(row["text"]), row["chunk_id"]))
        right = max(docs[right_doc], key=lambda row: (len(row["text"]), row["chunk_id"]))
        pair_candidates.append((key, [left, right]))

    chosen: list[list[dict[str, Any]]] = []
    used_chunks: set[str] = set()
    document_use: Counter[str] = Counter()
    species_use: Counter[str] = Counter()
    category_use: Counter[str] = Counter()
    while pair_candidates and len(chosen) < count:
        allowed = [item for item in pair_candidates
                   if all(row["chunk_id"] not in used_chunks for row in item[1])
                   and all(document_use[row["document_id"]] < 2 for row in item[1])]
        if not allowed:
            break
        def pair_score(item: tuple[tuple[str, str], list[dict[str, Any]]]) -> tuple[float, str]:
            (species, category), records = item
            docs = {row["document_id"] for row in records}
            score = 2.0 / (1 + species_use[species]) + 2.0 / (1 + category_use[category])
            score += sum(1.0 / (1 + document_use[doc]) for doc in docs)
            return score, species + category + "|" + "|".join(row["chunk_id"] for row in records)
        key, pair = max(allowed, key=pair_score)
        chosen.append(pair)
        used_chunks.update(row["chunk_id"] for row in pair)
        species_use[key[0]] += 1
        category_use[key[1]] += 1
        for row in pair:
            document_use[row["document_id"]] += 1
        pair_candidates.remove((key, pair))
    return chosen


def select_single_evidence(accepted: list[dict[str, Any]], count: int = 54,
                           excluded_chunk_ids: set[str] | None = None,
                           max_per_document: int = 7) -> list[dict[str, Any]]:
    excluded = set(excluded_chunk_ids or ())
    doc_counts: Counter[str] = Counter()
    species_counts: Counter[str] = Counter()
    strategy_counts: Counter[str] = Counter()
    selected: list[dict[str, Any]] = []
    # Reserve scarce semantic/document strata before common fact chunks fill document caps.
    quotas = {"climate": 4, "sop": 8, "water_quality": 10, "disease": 12, "fact": 20}
    for category, quota in quotas.items():
        rows = [row for row in accepted if row.get("category") == category]
        selected.extend(_balanced_take(rows, min(quota, count - len(selected)), doc_counts=doc_counts,
                                       species_counts=species_counts, strategy_counts=strategy_counts,
                                       max_per_doc=max_per_document, already=excluded))
    if len(selected) < count:
        leftovers = [row for row in accepted if row["chunk_id"] not in excluded]
        selected.extend(_balanced_take(leftovers, count - len(selected), doc_counts=doc_counts,
                                       species_counts=species_counts, strategy_counts=strategy_counts,
                                       max_per_doc=max_per_document, already=excluded))
    return selected[:count]


def lexical_overlap(question: str, evidence: str) -> float:
    """Question n-gram coverage in Chinese text, with word tokens for Latin text."""
    def units(value: str) -> set[str]:
        compact = re.sub(r"\s+", "", value.casefold())
        chars = [char for char in compact if "\u3400" <= char <= "\u9fff"]
        grams = {"C:" + "".join(chars[index:index + 2]) for index in range(max(0, len(chars) - 1))}
        words = {"W:" + token for token in re.findall(r"[a-z0-9]+(?:\.[0-9]+)?", compact)}
        return grams | words
    q = units(question)
    e = units(evidence)
    return len(q & e) / len(q) if q else 0.0


def extract_simple_feed_rate(evidence: dict[str, Any]) -> tuple[float, float, str] | None:
    """Recognize only explicit body-weight percentage used as a feed basis."""
    text = str(evidence.get("text") or "")
    pattern = re.compile(
        r"(?:魚體(?:當時)?體重|魚體重|魚體)[\s\S]{0,35}?"
        r"(\d+(?:\.\d+)?)\s*[~～至-]\s*(\d+(?:\.\d+)?)\s*%"
        r"[\s\S]{0,45}?(?:作為|投料基準|投餌基準)"
    )
    match = pattern.search(text)
    if not match:
        return None
    low, high = float(match.group(1)), float(match.group(2))
    if low <= 0 or high <= low or high > 100:
        return None
    quote = match.group(0).strip()
    return low, high, quote


def build_calculation_answer(biomass_kg: int, low_percent: float, high_percent: float) -> dict[str, Any]:
    if biomass_kg <= 0 or low_percent <= 0 or high_percent < low_percent:
        raise ValueError("invalid deterministic calculation inputs")
    low = biomass_kg * low_percent / 100.0
    high = biomass_kg * high_percent / 100.0
    return {
        "formula": "biomass_kg * rate_percent / 100",
        "biomass_kg": biomass_kg,
        "rate_percent": [low_percent, high_percent],
        "result_kg": [low, high],
        "reference_answer": (
            f"依據證據中的魚體重量投料比例 {low_percent:g}%–{high_percent:g}%，"
            f"{biomass_kg} kg × {low_percent:g}%–{high_percent:g}% = {low:g}–{high:g} kg。"
        ),
    }


def _normalized_text(text: str) -> str:
    return re.sub(r"[^\w\u3400-\u9fff]+", "", text.casefold())


def _number_tokens(text: str) -> set[str]:
    return {token.replace(",", "") for token in re.findall(r"(?<![A-Za-z])\d+(?:,\d{3})*(?:\.\d+)?", text)}


def validate_grounded_question(question: dict[str, Any], corpus_by_id: dict[str, dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    if not str(question.get("question") or "").strip():
        errors.append("question_empty")
    if not str(question.get("reference_answer") or "").strip():
        errors.append("answer_empty")
    chunk_ids = list(question.get("required_chunks") or [])
    if not chunk_ids:
        errors.append("missing_required_chunk")
    snapshots = question.get("evidence_snapshot") or []
    if len(snapshots) != len(chunk_ids):
        errors.append("snapshot_count_mismatch")
    resolved: list[dict[str, Any]] = []
    for chunk_id in chunk_ids:
        source = corpus_by_id.get(str(chunk_id))
        if source is None:
            errors.append("missing_chunk")
            continue
        if source.get("retrieval_role") != "retrieval":
            errors.append("required_chunk_not_retrieval")
        if source.get("duplicate_status") not in {"none", "canonical"}:
            errors.append("required_chunk_noncanonical_duplicate")
        if source.get("risk_level") != "normal":
            errors.append("required_chunk_not_normal_risk")
        resolved.append(source)
    required_docs = set(str(value) for value in (question.get("required_documents") or []))
    source_docs = {str(row.get("canonical_document_id") or row.get("document_id")) for row in resolved}
    if not required_docs or required_docs != source_docs:
        errors.append("required_document_mismatch")
    required_pages = {(str(item.get("document_id")), int(item.get("page")))
                      for item in (question.get("required_pages") or [])
                      if item.get("page") is not None}
    actual_pages = set()
    for source in resolved:
        spans = source.get("source_spans") or []
        for span in spans:
            if span.get("page_number") is not None:
                actual_pages.add((str(span.get("document_id") or source.get("document_id")), int(span["page_number"])))
    if not required_pages or not required_pages.issubset(actual_pages):
        errors.append("required_page_mismatch")
    snapshot_by_id = {str(item.get("chunk_id")): item for item in snapshots}
    for source in resolved:
        chunk_id = str(source.get("chunk_id"))
        snapshot = snapshot_by_id.get(chunk_id)
        if snapshot is None:
            errors.append("missing_snapshot")
            continue
        text = str(snapshot.get("text_snapshot") or "")
        checksum = sha256_text(text)
        if snapshot.get("content_checksum") != source.get("content_checksum") or checksum != source.get("content_checksum"):
            errors.append("snapshot_checksum_mismatch")
        if text != str(source.get("text") or ""):
            errors.append("snapshot_text_mismatch")
        if snapshot.get("document_id") != (source.get("canonical_document_id") or source.get("document_id")):
            errors.append("snapshot_document_mismatch")
        expected_pages = {int(span["page_number"]) for span in (source.get("source_spans") or [])
                          if span.get("page_number") is not None}
        if snapshot.get("page") not in expected_pages:
            errors.append("snapshot_page_mismatch")
    all_text = "\n".join(str(row.get("text") or "") for row in resolved)
    if question.get("calculation_spec"):
        allowed_numbers = _number_tokens(all_text) | {
            str(question["calculation_spec"].get("input", {}).get("biomass_kg")),
            *[str(value).removesuffix(".0") for value in question["calculation_spec"].get("rate_percent", [])],
            *[str(value).removesuffix(".0") for value in question["calculation_spec"].get("result_kg", [])],
        }
    else:
        allowed_numbers = _number_tokens(all_text)
    for candidate_text in (str(question.get("question") or ""), str(question.get("reference_answer") or "")):
        if not _number_tokens(candidate_text).issubset(allowed_numbers):
            errors.append("unsupported_numeric_value")
        if re.search(r"(?i)\bevidence\s+[ab]\b", candidate_text):
            errors.append("internal_evidence_label_in_text")
        for other_chunk_id, other in corpus_by_id.items():
            other_document_id = str(other.get("canonical_document_id") or other.get("document_id") or "")
            if other_document_id and other_document_id not in required_docs and other_document_id in candidate_text:
                errors.append("unsupported_document_reference")
    text_species = _species_mentions(all_text)
    for candidate_text in (str(question.get("question") or ""), str(question.get("reference_answer") or "")):
        if not _species_mentions(candidate_text).issubset(text_species):
            errors.append("unsupported_species_mention")
    for quote in question.get("supporting_quotes") or []:
        chunk_id = str(quote.get("chunk_id") or "")
        source = corpus_by_id.get(chunk_id)
        supporting_quote = str(quote.get("quote") or "")
        if source is None or len(_normalized_text(supporting_quote)) < 8:
            errors.append("invalid_supporting_quote")
        elif _normalized_text(supporting_quote) not in _normalized_text(str(source.get("text") or "")):
            errors.append("supporting_quote_not_in_evidence")
    if question.get("multi_document") and len(source_docs) < 2:
        errors.append("multi_document_requires_two_documents")
    if not question.get("multi_document") and len(source_docs) != 1:
        errors.append("single_document_requires_one_document")
    return sorted(set(errors))


def make_evidence_snapshot(evidence: dict[str, Any]) -> dict[str, Any]:
    return {
        "chunk_id": evidence["chunk_id"],
        "document_id": evidence["document_id"],
        "page": evidence["page"],
        "content_checksum": evidence["content_checksum"],
        "text_snapshot": evidence["text"],
    }


def make_question_record(*, question_id: str, question: str, answer: str,
                         evidences: list[dict[str, Any]], style: str, category: str,
                         corpus_sha256: str, generation_model: str,
                         generation_config: dict[str, Any], supporting_quotes: list[dict[str, str]],
                         calculation_spec: dict[str, Any] | None = None,
                         reference_answer_source: str = "ai_generated_from_evidence") -> dict[str, Any]:
    chunks = [row["chunk_id"] for row in evidences]
    documents = sorted({row["document_id"] for row in evidences})
    pages = sorted({(row["document_id"], int(page)) for row in evidences for page in row.get("pages", [])})
    species_values = {row.get("species") for row in evidences if row.get("species")}
    species = next(iter(species_values)) if len(species_values) == 1 else None
    snapshots = [make_evidence_snapshot(row) for row in evidences]
    return {
        "question_id": question_id,
        "benchmark_type": "silver",
        "generation_source": "corpus_grounded_ai",
        "question": question.strip(),
        "reference_answer": answer.strip(),
        "species": species,
        "category": category,
        "difficulty": STYLE_DIFFICULTY[style],
        "query_style": style,
        "risk_level": "normal",
        "required_chunks": chunks,
        "mapping_status": "exact_by_construction",
        "required_pages": [{"document_id": doc, "page": page} for doc, page in pages],
        "required_documents": documents,
        "evidence_snapshot": snapshots,
        "multi_document": len(documents) > 1,
        "lexical_overlap": lexical_overlap(question, "\n".join(row["text"] for row in evidences)),
        "supporting_quotes": supporting_quotes,
        "reference_answer_source": reference_answer_source,
        "calculation_spec": calculation_spec,
        "generation_model": generation_model,
        "generation_config": dict(generation_config),
        "evaluation_corpus_sha256": corpus_sha256,
    }


def _ngrams(text: str, size: int = 3) -> set[str]:
    norm = _normalized_text(text)
    return {norm[i:i + size] for i in range(max(0, len(norm) - size + 1))}


def duplicate_analysis(questions: list[dict[str, Any]], near_threshold: float = 0.9) -> dict[str, Any]:
    exact: list[dict[str, str]] = []
    near: list[dict[str, Any]] = []
    seen: dict[str, str] = {}
    for row in questions:
        norm = _normalized_text(str(row.get("question") or ""))
        if norm in seen:
            exact.append({"question_id": row["question_id"], "duplicate_of": seen[norm]})
        else:
            seen[norm] = row["question_id"]
    for i, left in enumerate(questions):
        a = _ngrams(str(left.get("question") or ""))
        if not a:
            continue
        for right in questions[i + 1:]:
            if set(left.get("required_chunks") or []) == set(right.get("required_chunks") or []):
                # Direct/paraphrase/contextual variants from one evidence item are intentional.
                continue
            b = _ngrams(str(right.get("question") or ""))
            if not b:
                continue
            score = len(a & b) / len(a | b)
            if score >= near_threshold:
                near.append({"question_id": left["question_id"], "candidate_question_id": right["question_id"],
                             "similarity": round(score, 6)})
    return {"exact_duplicates": exact, "near_duplicate_candidates": near}


def distribution_report(questions: list[dict[str, Any]], evidence_pool: list[dict[str, Any]],
                        corpus_sha256: str) -> dict[str, Any]:
    def count_values(key: str) -> dict[str, int]:
        return dict(sorted(Counter(str(row.get(key) or "unknown") for row in questions).items()))
    docs: Counter[str] = Counter()
    for question in questions:
        docs.update(question.get("required_documents") or [])
    sources: Counter[str] = Counter()
    for question in questions:
        for item in question.get("evidence_snapshot") or []:
            matching = next((evidence for evidence in evidence_pool if evidence["chunk_id"] == item["chunk_id"]), None)
            if matching:
                sources[str(matching.get("document_title") or item["document_id"])] += 1
    style = count_values("query_style")
    multi = sum(bool(row.get("multi_document")) for row in questions)
    by_species = {species: 0 for species in SPECIES_ORDER}
    species_counts = count_values("species")
    by_species.update({key: value for key, value in species_counts.items()
                       if key not in {"unknown", "None"}})
    by_species["unknown"] = species_counts.get("unknown", 0) + species_counts.get("None", 0)
    return {
        "benchmark_type": "Corpus-Grounded AI-generated Silver; not human Gold",
        "evaluation_corpus_sha256": corpus_sha256,
        "total_questions": len(questions),
        "by_species": by_species,
        "by_category": count_values("category"),
        "by_document_id_reference_count": dict(sorted(docs.items())),
        "by_query_style": style,
        "direct": style.get("direct", 0),
        "paraphrase": style.get("paraphrase", 0),
        "contextual": style.get("contextual", 0),
        "single_document": len(questions) - multi,
        "multi_document": multi,
        "evidence_source_distribution": dict(sorted(sources.items())),
        "evidence_pool_total": len(evidence_pool),
        "evidence_pool_accepted": sum(row.get("evidence_quality_status") == "accepted" for row in evidence_pool),
    }


def quality_report(questions: list[dict[str, Any]], all_generated: list[dict[str, Any]],
                   validation_errors: list[dict[str, Any]], duplicate_report: dict[str, Any],
                   evidence_pool: list[dict[str, Any]], generation_request_failures: int = 0) -> dict[str, Any]:
    overlaps = [float(row.get("lexical_overlap", 0.0)) for row in questions]
    by_style: dict[str, list[float]] = defaultdict(list)
    for row in questions:
        by_style[str(row.get("query_style"))].append(float(row.get("lexical_overlap", 0.0)))
    def summary(values: list[float]) -> dict[str, float | int | None]:
        return {"count": len(values), "mean": round(statistics.mean(values), 6) if values else None,
                "median": round(statistics.median(values), 6) if values else None,
                "min": round(min(values), 6) if values else None, "max": round(max(values), 6) if values else None}
    errors = Counter(error for row in validation_errors for error in row.get("errors", []))
    pool_status = Counter(str(row.get("evidence_quality_status")) for row in evidence_pool)
    return {
        "benchmark_type": "AI-generated Silver; automated checks do not establish human correctness",
        "generation_success": len(all_generated),
        "generation_accepted": len(questions),
        "generation_rejected": max(0, len(all_generated) - len(questions)) + generation_request_failures,
        "generation_request_failures": generation_request_failures,
        "evidence_validation_failure_count": len(validation_errors),
        "evidence_validation_errors": dict(sorted(errors.items())),
        "missing_chunk": errors.get("missing_chunk", 0),
        "missing_page": errors.get("required_page_mismatch", 0),
        "missing_document": errors.get("required_document_mismatch", 0),
        "snapshot_mismatch": errors.get("snapshot_checksum_mismatch", 0) + errors.get("snapshot_text_mismatch", 0),
        "evidence_quality_status": dict(sorted(pool_status.items())),
        "lexical_overlap": summary(overlaps),
        "lexical_overlap_by_query_style": {key: summary(values) for key, values in sorted(by_style.items())},
        "duplicate_questions": duplicate_report["exact_duplicates"],
        "duplicate_question_count": len(duplicate_report["exact_duplicates"]),
        "near_duplicate_questions": duplicate_report["near_duplicate_candidates"],
        "near_duplicate_candidate_count": len(duplicate_report["near_duplicate_candidates"]),
    }


def benchmark_readiness(questions: list[dict[str, Any]], corpus_by_id: dict[str, dict[str, Any]],
                        corpus_sha256: str, minimum_questions: int = 120) -> dict[str, Any]:
    errors = [(row.get("question_id"), validate_grounded_question(row, corpus_by_id)) for row in questions]
    unresolved = [(qid, row_errors) for qid, row_errors in errors if row_errors]
    species = {row.get("species") for row in questions if row.get("species")}
    categories = {row.get("category") for row in questions if row.get("category")}
    styles = {row.get("query_style") for row in questions}
    checks = {
        "minimum_question_count": len(questions) >= minimum_questions,
        "all_required_evidence_resolves": not unresolved,
        "at_least_four_species": len(species) >= 4,
        "at_least_four_categories": len(categories) >= 4,
        "all_query_styles_present": set(ALLOWED_QUERY_STYLES).issubset(styles),
    }
    return {
        "benchmark_type": "Corpus-Grounded AI-generated Silver; not human Gold",
        "grounded_silver_ready": all(checks.values()),
        "question_count": len(questions),
        "minimum_questions": minimum_questions,
        "species_count": len(species),
        "species": sorted(species),
        "category_count": len(categories),
        "categories": sorted(categories),
        "query_styles": sorted(styles),
        "required_evidence_validation_failures": len(unresolved),
        "checks": checks,
        "evaluation_corpus_sha256": corpus_sha256,
    }
