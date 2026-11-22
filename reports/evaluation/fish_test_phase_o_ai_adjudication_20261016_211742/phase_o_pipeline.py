from __future__ import annotations

import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
RUN = ROOT / "reports/evaluation/fish_test_run_20261012_152244"
G = ROOT / "reports/evaluation/fish_test_auto_annotation_phase_g_20261014_174009"
M = ROOT / "reports/evaluation/fish_test_phase_m_20261016_195819"
N = ROOT / "reports/evaluation/fish_test_phase_n_20261016_205314"
CORPUS = ROOT / "data/evaluation/corpus_v2.jsonl"
ALIASES = ROOT / "data/evaluation/source_alias_registry_v3.jsonl"

SPECIES = ["虱目魚", "吳郭魚", "石斑魚", "鱸魚", "烏魚", "鰻魚"]
SPECIES_ALIASES = {
    "虱目魚": ["虱目魚", "milkfish", "Chanos chanos"],
    "吳郭魚": ["吳郭魚", "台灣鯛", "羅非魚", "tilapia", "Oreochromis"],
    "石斑魚": ["石斑魚", "groupers", "grouper", "Epinephelus"],
    "鱸魚": ["鱸魚", "金目鱸", "七星鱸", "seabass", "barramundi", "Lates calcarifer"],
    "烏魚": ["烏魚", "鯔魚", "mullet", "Mugil cephalus"],
    "鰻魚": ["鰻魚", "鰻", "eel", "Anguilla"],
}
NUM_RANGE_RE = re.compile(r"(?<!\w)\d+(?:\.\d+)?\s*(?:至|到|[-–—~～])\s*\d+(?:\.\d+)?\s*(?:°\s*C|℃|°C|ppm|mg/L|mg／L|%|‰|公分|厘米|公尺|米|尾|公斤|公克|小時|天|月|年|度)?", re.I)
NUM_UNIT_RE = re.compile(r"(?<!\w)\d+(?:\.\d+)?\s*(?:°\s*C|℃|°C|ppm|mg/L|mg／L|%|‰|公分|厘米|公尺|米|尾|公斤|公克|小時|天|月|年|度|\bIU\b|\bCFU\b)", re.I)
UNIT_RE = re.compile(r"°\s*C|℃|°C|ppm|mg/L|mg／L|%|‰|公分|厘米|公尺|米|尾|公斤|公克|小時|天|月|年|度|\bIU\b|\bCFU\b", re.I)


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open("r", encoding="utf-8-sig") as f:
        for line_no, line in enumerate(f, 1):
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except Exception as e:
                raise ValueError(f"Invalid JSONL {path}:{line_no}: {e}") from e
    return rows


def write_json(path: Path, obj: Any) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def text_field(q: dict[str, Any], *names: str) -> str:
    for name in names:
        value = q.get(name)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def unique_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result = []
    for item in values:
        s = re.sub(r"\s+", " ", str(item)).strip()
        if s and s not in seen:
            seen.add(s)
            result.append(s)
    return result


def make_profile(q: dict[str, Any]) -> dict[str, Any]:
    question = text_field(q, "question_text")
    category = text_field(q, "inferred_category", "category")
    species = text_field(q, "species_chinese", "species_label_in_test_data")
    key_points = text_field(q, "candidate_scoring_key_points")
    answer_candidate = text_field(q, "candidate_reference_answer")
    # The answer field is not sent as a model response. Scoring-key points are used only as
    # unverified requirement cues; their status is explicitly retained in the profile.
    requirement_cues = unique_strings(re.split(r"[|｜;；\n]+", key_points))
    source_text = " ".join([key_points, answer_candidate])
    required_ranges = unique_strings(NUM_RANGE_RE.findall(source_text))
    required_values = unique_strings(NUM_UNIT_RE.findall(source_text))
    units = unique_strings(UNIT_RE.findall(" ".join([question, source_text])))
    conditions = [term for term in [
        "成魚", "魚苗", "種魚", "繁殖", "越冬", "寒害", "低水溫", "淡水", "海水", "半淡鹹水",
        "養殖", "捕撈", "池塘", "放養", "催產", "孵化", "治療", "停藥期", "用藥", "法規",
        "溫度", "水質", "密度", "存活率", "飼料", "生長", "特定魚種", "統計年度",
    ] if term in question]
    if "Medication" in category or "Law" in category or "法規" in question or "用藥" in question:
        version_req = "需固定現行法規版本、生效日期、條文與適用對象；未給版次不得推定現行性。"
    else:
        version_req = "使用問題指定或來源實際記載的版本／日期；不得跨版本或年份推論。"
    explicit_species = species if species in SPECIES else "general_aquaculture"
    return {
        "question_id": q.get("question_id"),
        "target_species": species,
        "question_category": category,
        "question_text": question,
        "required_answer_elements": requirement_cues or ["以問題文字要求的事實為準；沒有可核對評分要點時需保守判定。"],
        "required_values_or_ranges": required_ranges + [v for v in required_values if v not in required_ranges],
        "required_units": units,
        "required_conditions": unique_strings(conditions),
        "applicability_constraints": {
            "requested_scope": explicit_species,
            "species_specific_question": explicit_species != "general_aquaculture",
            "rule": "不得以主題或魚種字詞重疊替代內容支持；魚種專屬數值不可跨魚種泛化。",
        },
        "source_version_requirements": version_req,
        "requirement_profile_method": "question_text_plus_unverified_question_bank_scoring_cues; no M1-M4 generated answer used",
        "candidate_answer_used_as_gold": False,
        "candidate_scoring_cues_status": "unverified_prompting_cues_only",
        "profile_needs_review": not bool(question and category and species),
    }


def source_species_labels(record: dict[str, Any]) -> list[str]:
    # Only structured metadata and document headings can create a deterministic
    # conflict candidate. Mentions buried in body text are not treated as the
    # document's applicable host species.
    text = " ".join(str(record.get(k) or "") for k in ("species", "source_title", "chapter", "section"))
    hits = []
    for fish, aliases in SPECIES_ALIASES.items():
        if any(alias.casefold() in text.casefold() for alias in aliases):
            hits.append(fish)
    return hits


def key_of(x: dict[str, Any]) -> tuple[str, str, int]:
    return (str(x.get("question_id") or x.get("Question ID") or ""), str(x.get("chunk_id") or x.get("Chunk ID") or ""), int(x.get("rank") or x.get("Rank") or 0))


def prepare() -> dict[str, Any]:
    questions = read_jsonl(RUN / "fish_test_questions_normalized.jsonl")
    contexts = read_jsonl(G / "context_auto_annotations_900.jsonl")
    corpus = read_jsonl(CORPUS)
    m28 = read_jsonl(M / "phase_m_relevance_content_support_audit.jsonl")
    n63 = read_jsonl(N / "human_review_queue_63.jsonl")
    n12 = read_jsonl(N / "pilot_12_questions_frozen.jsonl")
    n60 = read_jsonl(N / "pilot_60_contexts_frozen.jsonl")
    qmap = {q["question_id"]: q for q in questions}
    cmap = {c["chunk_id"]: c for c in corpus}
    gmap = {key_of(x): x for x in contexts}
    mkeys = {key_of(x) for x in m28}
    n63keys = {key_of(x) for x in n63}
    n60keys = {key_of(x) for x in n60}
    memberships: dict[tuple[str, str, int], list[str]] = defaultdict(list)
    for key in mkeys:
        memberships[key].append("phase_m_relevant_28_development and_failure_analysis")
    for key in n63keys:
        memberships[key].append("phase_n_high_risk_63_rule_development")
    for key in n60keys:
        memberships[key].append("phase_n_independent_frozen_12q60c_pilot")
    selected_keys = set(mkeys) | set(n63keys) | set(n60keys)
    profiles = [make_profile(q) for q in questions]
    pmap = {p["question_id"]: p for p in profiles}
    preflight = []
    case_rows = []
    identity_errors = []
    for x in contexts:
        key = key_of(x)
        q = qmap.get(key[0])
        c = cmap.get(key[1])
        if not q or not c:
            identity_errors.append({"key": list(key), "question_found": bool(q), "corpus_chunk_found": bool(c)})
            continue
        chunk_text = str(c.get("text") or "")
        chunk_hash = sha(chunk_text)
        text_hash_match = chunk_hash == x.get("context_text_sha256") == c.get("content_checksum")
        identity_match = (
            x.get("question_id") == q.get("question_id")
            and x.get("chunk_id") == c.get("chunk_id")
            and x.get("document_id") == c.get("document_id")
            and int(x.get("rank") or 0) in range(1, 6)
        )
        source_hash_match = x.get("source_sha256") == c.get("source_checksum")
        title_match = x.get("source_title") == c.get("source_title")
        species_hits = source_species_labels(c)
        qspecies = pmap[key[0]]["target_species"]
        source_scope_conflict = bool(len(species_hits) == 1 and qspecies in SPECIES and species_hits[0] != qspecies)
        source_verified = bool(c.get("source_verified")) and str(c.get("source_verification_status")) == "verified"
        eligibility = c.get("retrieval_role") == "retrieval" and bool(c.get("indexable")) and x.get("retrieval_eligibility") == "retrieval"
        row = {
            "question_id": key[0], "chunk_id": key[1], "rank": key[2],
            "identity_match": identity_match, "context_text_sha256_expected": x.get("context_text_sha256"),
            "context_text_sha256_recomputed": chunk_hash, "context_text_checksum_match": text_hash_match,
            "source_checksum_annotation": x.get("source_sha256"), "source_checksum_corpus": c.get("source_checksum"),
            "source_checksum_match": source_hash_match,
            "annotation_source_id": x.get("source_id"), "corpus_source_id": c.get("source_id"),
            "source_id_match": x.get("source_id") == c.get("source_id"),
            "source_title_annotation": x.get("source_title"), "source_title_corpus": c.get("source_title"),
            "source_title_match": title_match,
            "source_version_annotation": x.get("source_version"), "chunk_version": c.get("chunk_version"),
            "source_publication_version_verified": bool(x.get("source_version")),
            "source_metadata_verified": source_verified,
            "source_verification_status": c.get("source_verification_status"),
            "source_species_labels_detected": species_hits,
            "question_target_species": qspecies,
            "source_scope_conflict_candidate": source_scope_conflict,
            "retrieval_eligible_in_corpus": eligibility,
            "corpus_version": x.get("corpus_version"), "source_file_sha256": x.get("source_sha256"),
            "source_locator": x.get("evidence_locator"), "document_id": c.get("document_id"),
            "page_start": c.get("page_start"), "page_end": c.get("page_end"),
        }
        preflight.append(row)
        if key in selected_keys:
            case_rows.append({
                "question_id": key[0], "chunk_id": key[1], "rank": key[2],
                "case_sets": sorted(memberships[key]), "question_profile": pmap[key[0]],
                "question_category": pmap[key[0]]["question_category"], "question_species": qspecies,
                "question_text": pmap[key[0]]["question_text"], "source_id": c.get("source_id"),
                "source_title": c.get("source_title"), "source_url": c.get("source_url"),
                "source_checksum": c.get("source_checksum"), "source_verified": c.get("source_verified"),
                "source_verification_status": c.get("source_verification_status"),
                "source_version": x.get("source_version"), "chunk_version": c.get("chunk_version"),
                "document_id": c.get("document_id"), "page_start": c.get("page_start"), "page_end": c.get("page_end"),
                "retrieval_role": c.get("retrieval_role"), "indexable": c.get("indexable"),
                "context_text": chunk_text, "context_text_sha256": chunk_hash,
                "prior_ai_label": x.get("relevance_label"), "prior_ai_round1": x.get("round1_label"),
                "prior_ai_round2": x.get("round2_label"), "prior_ai_reason": x.get("relevance_reason"),
                "source_preflight": row,
            })
    # Enforce exact frozen Phase N sample identity.
    n60_loaded = {key_of(x) for x in n60}
    frozen_mismatch = sorted([list(k) for k in n60_loaded.symmetric_difference(set(key_of(x) for x in case_rows if "phase_n_independent_frozen_12q60c_pilot" in x["case_sets"]))])
    alias_rows = read_jsonl(ALIASES)
    models = {
        "judge_a": {"name": "gemma2:9b", "digest": "ff02c3702f322b9e075e9568332d96c0a7028002f1a5a056e0a6784320a4db0b", "family": "gemma2", "role": "requirement_match"},
        "judge_b": {"name": "qwen2.5-coder:7b", "digest": "dae161e27b0e90dd1856c8bb3209201fd6736d8eb66298e75ed87571486f4364", "family": "qwen2", "role": "independent_evidence_falsification; code-tuned domain limitation"},
        "arbiter": {"name": "mistral-nemo:12b-instruct-2407-q4_K_M", "digest": "daf6737417121831e572a9c482e92a221ee0c33537f35f1f857c7b4f7191df55", "family": "llama/Mistral-Nemo", "role": "third_model_independent_adjudicator"},
    }
    write_jsonl(OUT / "question_requirement_profiles.jsonl", profiles)
    write_jsonl(OUT / "source_preflight_900.jsonl", preflight)
    write_jsonl(OUT / "phase_o_case_registry.jsonl", sorted(case_rows, key=lambda r: (r["question_id"], r["rank"])))
    write_json(OUT / "model_registry.json", models)
    summary = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "phase_m_relevant_rows": len(m28), "phase_n_high_risk_rows": len(n63), "phase_n_frozen_pilot_questions": len(n12), "phase_n_frozen_pilot_contexts": len(n60),
        "overlap_m28_with_n63": len(mkeys & n63keys), "overlap_m28_with_n60": len(mkeys & n60keys), "overlap_n63_with_n60": len(n63keys & n60keys),
        "unique_case_contexts": len(case_rows), "complete_contexts": len(contexts), "unique_questions": len(questions), "corpus_chunks": len(corpus),
        "identity_errors": identity_errors, "phase_n_frozen_pilot_identity_mismatches": frozen_mismatch,
        "preflight_counts": {
            "identity_match": sum(bool(r["identity_match"]) for r in preflight),
            "context_text_checksum_match": sum(bool(r["context_text_checksum_match"]) for r in preflight),
            "source_checksum_match": sum(bool(r["source_checksum_match"]) for r in preflight),
            "source_metadata_verified": sum(bool(r["source_metadata_verified"]) for r in preflight),
            "retrieval_eligible": sum(bool(r["retrieval_eligible_in_corpus"]) for r in preflight),
            "source_scope_conflict_candidates": sum(bool(r["source_scope_conflict_candidate"]) for r in preflight),
        },
        "source_alias_registry_rows": len(alias_rows),
        "judge_models": models,
        "model_preflight_status": "Ollama API listing/digest checked; structured-JSON smoke passed for Gemma2/Mistral Nemo/Qwen2.5-Coder; DeepSeek-R1:7b JSON smoke produced no final JSON and is not selected",
        "notes": [
            "Question requirement profiles use only question text and unverified test-bank scoring cues; no M1-M4 generated answers are read.",
            "Source publication version is kept separate from corpus chunk version.",
            "Source unknown/conflict is not coerced to IRRELEVANT; unresolved scope remains eligible for UNCERTAIN or arbitration.",
            "Prior labels are retained for audit only and excluded from Judge prompts.",
        ],
    }
    write_json(OUT / "phase_o_preflight_summary.json", summary)
    return summary


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] == "prepare":
        print(json.dumps(prepare(), ensure_ascii=False, indent=2))
    else:
        raise SystemExit("Supported mode: prepare")

