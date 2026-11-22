from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import sys
import time
from pathlib import Path
from typing import Any
from dataclasses import replace

import requests

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
Y = ROOT / "reports/evaluation/fish_test_phase_y_20261019_165045"
MODEL_TABLE = {
    "M1": ("deepseek-r1:7b", "755ced02ce7befdb13b7ca74e1e4d08cddba4986afdb63a480f2c93d3140383f"),
    "M2": ("qwen2.5-coder:7b", "dae161e27b0e90dd1856c8bb3209201fd6736d8eb66298e75ed87571486f4364"),
    "M3": ("hf.co/bartowski/DeepSeek-R1-Distill-Llama-8B-GGUF:Q4_K_M", "aab87d0e8a585cc6260d3a448e3f66ff2057d1cd6975c834151deeb1eae94b42"),
    "M4": ("gemma2:9b", "ff02c3702f322b9e075e9568332d96c0a7028002f1a5a056e0a6784320a4db0b"),
}
SCHEMA = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": ["answered", "abstain"]},
        "answer": {"type": "string"},
        "citations": {"type": "array", "items": {"type": "object", "properties": {"chunk_id": {"type": "string"}, "source_id": {"type": "string"}}, "required": ["chunk_id", "source_id"]}},
        "evidence_sufficiency": {"type": "string", "enum": ["sufficient", "partial", "insufficient"]},
        "abstention_reason": {"type": ["string", "null"]},
    },
    "required": ["status", "answer", "citations", "evidence_sufficiency", "abstention_reason"],
}


def _load_engine():
    path = HERE / "grounded_answer_engine_v2.py"
    spec = importlib.util.spec_from_file_location("phase_z_grounded_engine", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load evidence engine")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


ENGINE = _load_engine()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def load_case(case_id: str) -> dict[str, Any]:
    rows = read_jsonl(HERE / "independent_test_set.jsonl")
    case = next((row for row in rows if row["test_id"] == case_id), None)
    if case is None:
        raise KeyError(case_id)
    refs = {row["question_id"]: row for row in read_jsonl(HERE / "reference_answers_frozen.jsonl")}
    source_ref = refs.get(case.get("source_reference_question_id")) if case.get("source_reference_question_id") else None
    spans = []
    if case.get("source_id") and source_ref:
        quote = str(source_ref["exact_evidence_span"])
        page_text = source_ref.get("_page_text")
        if page_text is None:
            try:
                import pymupdf
            except ImportError:
                import fitz as pymupdf
            source_file = Path(source_ref["source_file"])
            if not source_file.is_absolute():
                source_file = ROOT / source_file
            if not source_file.is_file() or hashlib.sha256(source_file.read_bytes()).hexdigest() != source_ref["source_sha256_actual"]:
                raise RuntimeError("original source file missing or checksum mismatch")
            page_no = int(source_ref["physical_page"])
            with pymupdf.open(source_file) as doc:
                page_text = doc[page_no - 1].get_text()
        offset = page_text.find(quote)
        if offset < 0:
            raise RuntimeError("source quote no longer resolves on its declared physical page")
        span_id = str(case["span_id"])
        chunk_id = "phase-z-card-" + hashlib.sha256((case["test_id"] + case["source_id"] + quote).encode("utf-8")).hexdigest()[:16]
        if case["test_id"] == "Z-NEG-MULLET-EVIDENCE-FOR-TILAPIA":
            span_scope = ("烏魚",)
        elif case["test_id"] == "Z-NEG-SPECIFIC-DRUG-DOSE":
            span_scope = ("烏魚",)
        else:
            span_scope = (str(source_ref.get("effective_target_species_from_question") or source_ref["species"]),)
        app_status = (case.get("species_applicability") or {}).get("status", "UNKNOWN")
        spans.append(ENGINE.EvidenceSpan(
            span_id=span_id,
            chunk_id=chunk_id,
            source_id=str(case["source_id"]),
            source_version=str(case["source_version"]),
            source_sha256=str(case["source_sha256"]),
            expected_source_sha256=str(source_ref["source_sha256_expected"]),
            locator=str(case["source_locator"]),
            quote=quote,
            source_page_text=page_text,
            start_char=offset,
            end_char=offset + len(quote),
            fact_card_text=str(case.get("fact_card_text") or ""),
            species_scope=span_scope,
            applicability_status=app_status,
            cross_species_basis=(case.get("species_applicability") or {}).get("basis"),
            processing_scope=str(case.get("processing_scope") or "RESEARCH_FACT_CARD_NONPUBLIC"),
            retrieval_eligible=True,
            formally_admitted_to_evaluation_corpus=False,
        ))
    profile = {
        "question_text": case["question_text"],
        "target_species": case["target_species"],
        "category": case.get("category"),
        "risk_class": case.get("risk_class", "UNCLASSIFIED"),
        "species_applicability": case.get("species_applicability") or {"status": "UNKNOWN"},
        "required_answer_elements": case.get("required_answer_elements", []),
        "pre_frozen_answer_text": None,
        "high_risk_authority_verified": bool(case.get("high_risk_authority_verified", False)),
    }
    return {"case": case, "source_reference": source_ref, "profile": profile, "spans": spans}


def check_model_identity(model_id: str) -> dict[str, str]:
    expected_tag, expected_digest = MODEL_TABLE[model_id]
    models = requests.get("http://127.0.0.1:11434/api/tags", timeout=10).json().get("models", [])
    actual = next((row for row in models if row.get("name") == expected_tag), None)
    if actual is None:
        raise RuntimeError(f"model missing: {model_id} / {expected_tag}")
    actual_digest = str(actual.get("digest", "")).removeprefix("sha256:")
    if actual_digest != expected_digest:
        raise RuntimeError(f"model digest mismatch: {model_id} {actual_digest} != {expected_digest}")
    return {"model_id": model_id, "model_tag": expected_tag, "digest": actual_digest}


def run_model_data(data: dict[str, Any], model_id: str, case_id: str | None = None) -> dict[str, Any]:
    identity = check_model_identity(model_id)
    profile, spans, case = data["profile"], data["spans"], data["case"]
    case_id = case_id or case["test_id"]
    decision = ENGINE.assess_evidence(profile, spans)
    base = {
        "case_id": case_id, "question_id": case["question_id"], "model_id": model_id,
        "model_tag": identity["model_tag"], "model_digest": identity["digest"],
        "question": case["question_text"], "target_species": case["target_species"],
        "research_context_type": "CONTROLLED_RESEARCH_FACT_CARD_NOT_FORMAL_EVALUATION_CORPUS",
        "corpus_formal_admission": False,
        "evidence_decision": decision,
        "answer_origin": None, "raw_model_response": None, "final_response": None,
        "evidence_span_ids": [], "support_validation": None, "abstention_reason": None,
        "generator_called": False, "timing": None,
        "retrieval_trace": data.get("retrieval_trace"),
        "retrieved_chunk_id": data.get("retrieved_chunk_id"),
        "retrieved_context_sha256": data.get("retrieved_context_sha256"),
    }
    if decision["state"] != "EVIDENCE_SUFFICIENT":
        final = {"status": "abstain", "answer": "目前沒有足以支持此回答的合格證據。", "citations": [], "evidence_sufficiency": decision["state"], "abstention_reason": decision["reason"]}
        base.update({"answer_origin": "ABSTAINED", "final_response": final, "support_validation": decision, "abstention_reason": decision["reason"], "system_action": "DETERMINISTIC_EVIDENCE_GATE_BLOCKED_GENERATOR"})
        return base
    messages = ENGINE.make_model_prompt(profile, spans, decision)
    started = time.perf_counter()
    first_token = None
    text_parts: list[str] = []
    events = 0
    stats: dict[str, Any] = {}
    response = requests.post(
        "http://127.0.0.1:11434/api/chat",
        json={"model": identity["model_tag"], "messages": messages, "format": SCHEMA, "think": False, "stream": True,
              "options": {"temperature": 0, "seed": 42, "num_predict": 512}, "keep_alive": "0"},
        stream=True, timeout=(30, 600),
    )
    response.raise_for_status()
    try:
        for line in response.iter_lines(decode_unicode=True):
            if not line:
                continue
            events += 1
            event = json.loads(line)
            content = (event.get("message") or {}).get("content") or ""
            if content and first_token is None:
                first_token = time.perf_counter() - started
            if content:
                text_parts.append(content)
            if event.get("done"):
                stats = {k: event.get(k) for k in ("eval_count", "eval_duration", "prompt_eval_count", "prompt_eval_duration", "total_duration", "load_duration")}
    finally:
        response.close()
    raw = "".join(text_parts)
    allowed = {(span.chunk_id, span.source_id) for span in spans}
    raw_payload = None
    raw_parse_error = None
    try:
        raw_payload = json.loads(raw)
    except Exception as exc:
        raw_parse_error = f"{type(exc).__name__}: {exc}"
    raw_validation_errors = ENGINE.validate_model_payload(raw_payload, allowed) if raw_payload is not None else ["JSON_PARSE_FAILED"]
    finished = ENGINE.finish_model_answer(profile, spans, raw, decision, allowed)
    elapsed = time.perf_counter() - started
    base.update({
        "raw_model_response": raw, "generator_called": True,
        "prompt": messages, "prompt_sha256": hashlib.sha256(json.dumps(messages, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest(),
        "answer_origin": finished["answer_origin"], "final_response": finished["final_response"],
        "evidence_span_ids": finished["evidence_span_ids"], "support_validation": finished["support_validation"],
        "abstention_reason": finished["abstention_reason"], "model_reported_status": None,
        "raw_json_parse_error": raw_parse_error, "raw_json_and_citation_validation_errors": raw_validation_errors,
        "raw_json_valid": raw_parse_error is None and isinstance(raw_payload, dict),
        "raw_citation_schema_valid": raw_parse_error is None and not raw_validation_errors,
        "timing": {"wall_seconds": elapsed, "ttft_visible_content_seconds": first_token, "stream_events": events,
                   "eval_count": stats.get("eval_count"), "eval_duration_ns": stats.get("eval_duration"),
                   "tps": stats.get("eval_count") / (stats.get("eval_duration") / 1e9) if stats.get("eval_count") and stats.get("eval_duration") else None,
                   "ram_peak_process": None, "dedicated_vram_peak": None,
                   "memory_measurement_reason": "not sampled by this bounded smoke runner"},
        "system_action": "MODEL_OUTPUT_VALIDATED_OR_GENERIC_EXTRACTIVE_FALLBACK",
        "model_direct_answer": finished["final_response"] if finished["answer_origin"] == "MODEL_GENERATED" else None,
        "system_final_answer": finished["final_response"],
    })
    try:
        parsed = json.loads(raw)
        base["model_reported_status"] = parsed.get("status")
    except Exception:
        pass
    return base


def run_model(case_id: str, model_id: str) -> dict[str, Any]:
    return run_model_data(load_case(case_id), model_id, case_id)


def run_phase_y_retrieval_smoke() -> list[dict[str, Any]]:
    spec = importlib.util.spec_from_file_location("phase_z_phase_y_core", Y / "phase_y_core.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load preserved Phase Y retrieval engine")
    core = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = core
    spec.loader.exec_module(core)
    # Extend the earlier narrow category overlay for exact-species Fact queries:
    # the Mullet chapter's source card is categorized as Calculation, though
    # it directly supports age-specific stocking facts. Keep species scope exact.
    old_applicable = core.chunk_applicable
    def z_chunk_applicable(chunk, question, profile):
        ok, reason = old_applicable(chunk, question, profile)
        if ok or reason != "CATEGORY_SCOPE_MISMATCH_NO_EXACT_SPECIES_TOPICAL_TEXT" or question.get("category") != "Fact":
            return ok, reason
        meta = json.loads(chunk.get("metadata_json") or "{}")
        scope = meta.get("species_scope", "")
        if isinstance(scope, list):
            scopes = set(scope)
        else:
            scopes = {x.strip() for x in str(scope).split("|") if x.strip()}
        body = str(chunk.get("text") or "")
        query = str(question.get("question_text") or "")
        if profile.get("species") in scopes and any(term in query and term in body for term in ("放養", "密度", "魚齡", "每公頃")):
            return True, "Z_FACT_TOPIC_MATCH_EXACT_SPECIES_SCOPE"
        return ok, reason
    core.chunk_applicable = z_chunk_applicable
    questions = [
        {"question_id": "Z-RETRIEVAL-MULLET-AGE2", "species": "烏魚", "category": "Fact", "question_text": "依手冊所指的烏魚章，2齡以上的建議放養密度是多少？"},
        {"question_id": "Z-RETRIEVAL-GROUPER-DENSITY", "species": "石斑魚", "category": "Calculation", "question_text": "鞍帶石斑一般建議放養密度範圍及單位為何？"},
        {"question_id": "Z-RETRIEVAL-GROUPER-TEMP", "species": "石斑魚", "category": "Water Quality", "question_text": "依手冊所指的石斑魚組別，最適成長及存活水溫範圍為何？"},
    ]
    results = core.retrieve_180(questions, output_path=HERE / "phase_z_retrieval_smoke.jsonl")
    core.chunk_applicable = old_applicable
    return results


def bind_retrieved_fact_card(data: dict[str, Any], retrieval_row: dict[str, Any]) -> dict[str, Any]:
    top = next((row for row in retrieval_row.get("reranked_top5", []) if row.get("retrieval_eligible") is True), None)
    if top is None:
        raise RuntimeError(f"no retrieval-eligible context for {retrieval_row.get('question_id')}")
    if not data["spans"]:
        raise RuntimeError("retrieved chunk cannot be bound without a frozen source span")
    old = data["spans"][0]
    if top.get("source_id") != old.source_id or top.get("source_sha256") != old.expected_source_sha256:
        raise RuntimeError("retrieval source identity/checksum does not match the frozen evidence record")
    if top.get("source_version") != old.source_version or top.get("page_or_locator") != old.locator:
        raise RuntimeError("retrieval version or page locator does not match the frozen evidence record")
    card_text = str(top.get("content") or "")
    if not card_text or hashlib.sha256(card_text.encode("utf-8")).hexdigest() != top.get("content_sha256"):
        raise RuntimeError("retrieved fact-card content checksum mismatch")
    linked_elements = [e for e in data["profile"].get("required_answer_elements", []) if old.span_id in e.get("evidence_span_ids", [])]
    normalized = ENGINE._normalise(card_text)
    missing = [literal for e in linked_elements for literal in e.get("required_literals", []) if ENGINE._normalise(literal) not in normalized]
    for element in linked_elements:
        for group in element.get("required_literal_groups", []):
            if not any(ENGINE._normalise(value) in normalized for value in group):
                missing.append(" | ".join(group))
    if missing:
        raise RuntimeError(f"retrieved card lacks a frozen required element: {missing}")
    new_span = replace(old, chunk_id=str(top["chunk_id"]), fact_card_text=card_text,
                       species_scope=(str(top.get("species_scope") or data["profile"]["target_species"]),),
                       applicability_status=data["profile"]["species_applicability"]["status"],
                       cross_species_basis=data["profile"]["species_applicability"].get("basis"))
    data = {**data, "spans": [new_span], "retrieval_trace": retrieval_row,
            "retrieved_context_sha256": top["content_sha256"], "retrieved_chunk_id": top["chunk_id"]}
    return data


def run_smoke(retrieval_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    retrieval_by_id = {row["question_id"]: row for row in retrieval_rows}
    # Freeze the known regression evidence before the first model call.
    density_data = load_known_grouper_density_regression()
    density_retrieval = retrieval_by_id["Z-RETRIEVAL-GROUPER-DENSITY"]
    density_data = bind_retrieved_fact_card(density_data, density_retrieval)
    known_case_freeze = json.loads((HERE / "known_grouper_regression_case_frozen.json").read_text(encoding="utf-8"))
    known_case_freeze["retrieval_row_sha256"] = hashlib.sha256((HERE / "phase_z_retrieval_smoke.jsonl").read_bytes()).hexdigest()
    known_case_freeze["retrieved_context_sha256"] = density_data["retrieved_context_sha256"]
    (HERE / "known_grouper_regression_case_frozen.json").write_text(json.dumps(known_case_freeze, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    # Update aggregate freeze hashes now that retrieval context is fixed, before
    # any generator runs. Reference answers and rubrics remain unchanged.
    freeze = {
        "frozen_before_first_generator_call": True,
        "test_set_sha256": hashlib.sha256((HERE / "independent_test_set.jsonl").read_bytes()).hexdigest(),
        "reference_answers_sha256": hashlib.sha256((HERE / "reference_answers_frozen.jsonl").read_bytes()).hexdigest(),
        "rubrics_sha256": hashlib.sha256((HERE / "evaluation_rubrics_frozen.jsonl").read_bytes()).hexdigest(),
        "retrieval_smoke_sha256": hashlib.sha256((HERE / "phase_z_retrieval_smoke.jsonl").read_bytes()).hexdigest(),
        "known_regression_case_sha256": hashlib.sha256((HERE / "known_grouper_regression_case_frozen.json").read_bytes()).hexdigest(),
        "formal_corpus_admission": False,
        "human_gold": 0,
    }
    (HERE / "phase_z_pre_generation_freeze.json").write_text(json.dumps(freeze, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    selected = [
        ("Z-IND-MULLET-AGE2-RATE", "Z-RETRIEVAL-MULLET-AGE2"),
        ("Z-IND-GROUPER-TEMP-RANGE", "Z-RETRIEVAL-GROUPER-TEMP"),
    ]
    results: list[dict[str, Any]] = []
    result_path = HERE / "real_generator_smoke_results.jsonl"
    existing = read_jsonl(result_path) if result_path.is_file() else []
    completed = {(row.get("case_id"), row.get("model_id")) for row in existing}
    # Model calls are sequential so only one generator needs to be resident.
    for case_id, retrieval_id in selected:
        data = bind_retrieved_fact_card(load_case(case_id), retrieval_by_id[retrieval_id])
        for model_id in MODEL_TABLE:
            if (case_id, model_id) in completed:
                prior = next(row for row in existing if (row.get("case_id"), row.get("model_id")) == (case_id, model_id))
                results.append(prior)
                continue
            row = run_model_data(data, model_id, case_id)
            row["retrieval_question_id"] = retrieval_id
            row["retrieved_context_sha256"] = data["retrieved_context_sha256"]
            results.append(row)
            with result_path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
                stream.flush()
            existing.append(row)
            completed.add((case_id, model_id))
    regression_key = ("KNOWN-REGRESSION-GROUPER-STOCKING-DENSITY", "M2")
    if regression_key in completed:
        density_row = next(row for row in existing if (row.get("case_id"), row.get("model_id")) == regression_key)
    else:
        density_row = run_model_data(density_data, "M2", regression_key[0])
        density_row["regression_scope_note"] = "Historical Phase X source span; not a prompt-independent benchmark item and not a formal corpus admission."
        with result_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(density_row, ensure_ascii=False, separators=(",", ":")) + "\n")
            stream.flush()
    results.append(density_row)
    negatives = ["Z-NEG-EEL-WATER-QUALITY", "Z-NEG-MULLET-EVIDENCE-FOR-TILAPIA", "Z-NEG-SPECIFIC-DRUG-DOSE"]
    gate_rows = []
    for case_id in negatives:
        data = load_case(case_id)
        for model_id in MODEL_TABLE:
            row = run_model_data(data, model_id, case_id)
            gate_rows.append(row)
    (HERE / "safety_gate_smoke_results.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False, separators=(",", ":")) + "\n" for r in gate_rows), encoding="utf-8")
    return results


def load_known_grouper_density_regression() -> dict[str, Any]:
    phase_x = ROOT / "reports/evaluation/fish_test_phase_x_20261019_162147/verified_reference_answer_candidates.jsonl"
    source_row = next(row for row in read_jsonl(phase_x) if row.get("question_id") == "FT-grouper-Q22" and row.get("source_id") == "TFRI-M17-GROUPER")
    source_file = Path(source_row["source_file"])
    if not source_file.is_absolute():
        source_file = ROOT / source_file
    actual_sha = hashlib.sha256(source_file.read_bytes()).hexdigest()
    if actual_sha != source_row.get("source_sha256_expected"):
        raise RuntimeError("known grouper source checksum mismatch")
    try:
        import pymupdf
    except ImportError:
        import fitz as pymupdf
    page_match = re.search(r"physical page\s+(\d+)", source_row["exact_source_locator"], re.I)
    if not page_match:
        raise RuntimeError("known grouper page locator missing")
    page_no = int(page_match.group(1))
    with pymupdf.open(source_file) as document:
        page_text = document[page_no - 1].get_text()
    quote = str(source_row["exact_source_text_span"])
    offset = page_text.find(quote)
    if offset < 0:
        raise RuntimeError("known grouper evidence quote not found at original page")
    case_id = "KNOWN-REGRESSION-GROUPER-STOCKING-DENSITY"
    span_id = "span-" + hashlib.sha256((case_id + quote).encode("utf-8")).hexdigest()[:16]
    chunk_id = "phase-z-regression-fact-card-" + hashlib.sha256((source_row["source_id"] + quote).encode("utf-8")).hexdigest()[:16]
    span = ENGINE.EvidenceSpan(
        span_id=span_id, chunk_id=chunk_id, source_id=source_row["source_id"],
        source_version=source_row["source_version"], source_sha256=actual_sha,
        expected_source_sha256=source_row["source_sha256_expected"], locator=source_row["exact_source_locator"],
        quote=quote, source_page_text=page_text, start_char=offset, end_char=offset + len(quote),
        fact_card_text=source_row["chunk_text"], species_scope=("石斑魚",), applicability_status="VERIFIED_GROUP",
        cross_species_basis="Manual-defined grouper-group statement. This is a source-bound answer to what the manual states, not a universal species recommendation.",
        processing_scope="RESEARCH_FACT_CARD_NONPUBLIC", retrieval_eligible=True, formally_admitted_to_evaluation_corpus=False,
    )
    profile = {
        "question_text": "依鞍帶石斑資料，放養密度建議範圍是多少尾/公頃？",
        "target_species": "石斑魚", "category": "Calculation", "risk_class": "LOW_RISK_FACT",
        "species_applicability": {"status": "VERIFIED_GROUP", "basis": span.cross_species_basis},
        "required_answer_elements": [{"element_id": "density_range_and_unit", "required": True,
                                      "required_literals": ["10,000", "30,000", "尾/公頃"], "evidence_span_ids": [span_id]}],
        "pre_frozen_answer_text": None,
    }
    case = {"test_id": case_id, "question_id": case_id, "question_text": profile["question_text"],
            "target_species": profile["target_species"], "category": profile["category"]}
    freeze = {
        "test_id": case_id, "question_text": profile["question_text"], "profile": profile,
        "source_id": source_row["source_id"], "source_version": source_row["source_version"],
        "source_sha256": actual_sha, "source_locator": source_row["exact_source_locator"],
        "exact_source_quote": quote, "quote_start_char": offset, "quote_end_char": offset + len(quote),
        "fact_card_text": source_row["chunk_text"], "chunk_id": chunk_id,
        "status": "KNOWN_REGRESSION_ONLY_NOT_IN_INDEPENDENT_TEST_SET", "not_human_gold": True,
    }
    freeze["freeze_sha256"] = hashlib.sha256(json.dumps(freeze, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    (HERE / "known_grouper_regression_case_frozen.json").write_text(json.dumps(freeze, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"case": case, "source_reference": source_row, "profile": profile, "spans": [span]}


def main() -> None:
    retrieval = run_phase_y_retrieval_smoke()
    # Treat Phase V/W retrieval as a diagnostic path only. Its chunks are not
    # relabeled as admitted source cards here.
    result_rows = run_smoke(retrieval)
    summary = {
        "real_retrieval_queries": len(retrieval),
        "retrieval_output": str(HERE / "phase_z_retrieval_smoke.jsonl"),
        "retrieval_rows": [{"question_id": r.get("question_id"), "applicable_candidate_count": r.get("corpus_applicable_chunk_count"), "top5_count": r.get("final_top5_count"), "top_chunk_ids": [c.get("chunk_id") for c in r.get("reranked_top5", [])]} for r in retrieval],
        "generator_rows": len(result_rows),
        "generator_calls": sum(bool(r.get("generator_called")) for r in result_rows),
        "model_digests": MODEL_TABLE,
        "formal_corpus_admission": False,
        "phase_z_scope": "bounded operational smoke; no full 720 generation and no Human Gold",
    }
    (HERE / "phase_z_runtime_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
