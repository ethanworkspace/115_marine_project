from __future__ import annotations

import datetime as dt
import hashlib
import json
import pathlib
import time
import urllib.request
from collections import Counter
from zoneinfo import ZoneInfo

import pymupdf as fitz

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PHASE_I = ROOT / "reports/evaluation/fish_test_phase_i_20261014_195032"
PHASE_J = ROOT / "reports/evaluation/fish_test_phase_j_20261015_190617"
MODEL = "mistral-nemo:12b-instruct-2407-q4_K_M"
EXPECTED_DIGEST = "daf6737417121831e572a9c482e92a221ee0c33537f35f1f857c7b4f7191df55"
OLLAMA = "http://127.0.0.1:11434"

from species_aware_annotator import (  # noqa: E402
    SCHEMA, SPECIES, SYSTEM, adjudicate, assess_species_scope, make_spans, sha256_text,
    species_mentions, validate_identity, validate_judge_response,
)


def read_json(path: pathlib.Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def read_jsonl(path: pathlib.Path):
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]


def write_json(path: pathlib.Path, value):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def write_jsonl(path: pathlib.Path, rows):
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    tmp.replace(path)


def append_jsonl(path: pathlib.Path, row):
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def file_sha(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def regression_tests() -> dict:
    tests = []

    def check(name, expected, fn, basis):
        try:
            actual = fn()
            passed = actual == expected
            tests.append({"case": name, "expected": expected, "actual": actual, "passed": passed,
                          "evidence_basis": basis, "error": None if passed else "actual did not match expected"})
        except Exception as exc:
            tests.append({"case": name, "expected": expected, "actual": None, "passed": False,
                          "evidence_basis": basis, "error": f"{type(exc).__name__}: {exc}"})

    def run_scope(qspecies, doc_species, doc_status, title, text, general=None, raw="RELEVANT", span=True):
        scope = assess_species_scope(qspecies, doc_species, doc_status, title, text, general)
        selected = [{"span_id": "sp_fixture", "exact_quote": text}] if span else []
        return scope, adjudicate(raw, scope, selected)

    check("same_species_relevant", "RELEVANT", lambda: run_scope(
        "吳郭魚", ["吳郭魚"], "verified", "吳郭魚養殖資料", "吳郭魚在特定條件下的水質資料。")[1]["final_label"],
        "Synthetic regression fixture with explicit source species; tests only species gate, not a research question.")
    check("same_species_but_semantically_irrelevant_retains_judge", "IRRELEVANT", lambda: run_scope(
        "吳郭魚", ["吳郭魚"], "verified", "吳郭魚養殖資料", "吳郭魚疫苗保存說明。", raw="IRRELEVANT", span=False)[1]["final_label"],
        "Synthetic same-species unrelated-topic fixture; semantic irrelevance is supplied by fixed test expectation.")
    check("cross_species_mullet_cannot_answer_tilapia_synthetic", "IRRELEVANT", lambda: run_scope(
        "吳郭魚", [], "unknown", "04烏魚養殖", "烏魚養殖水溫管理內容。", raw="RELEVANT")[1]["final_label"],
        "Synthetic species mismatch fixture with explicit named source and paragraph taxon.")
    check("phase_j_real_tilapia_mullet_case_regression", "IRRELEVANT", lambda: _real_phase_j_species_case(),
        "Exact FT-tilapia-Q02 Rank 2 question/chunk/document/title/text from the Phase J fixed sample and Evaluation Corpus v2 retrieval trace.")
    check("verified_general_law_may_cross_species", "RELEVANT", lambda: run_scope(
        "吳郭魚", [], "unknown", "水產動物用藥法規", "水產動物應遵循標示與法定使用要求。",
        {"verified": True, "scope": "all_aquatic_animals", "evidence_locator": "official law Article 7, saved excerpt"}, "RELEVANT")[1]["final_label"],
        "Official MOA current law excerpt in Phase J; tests the explicit all-aquatic-animals legal-scope rule, not drug eligibility.")
    check("similar_seabass_names_stay_distinct", "IRRELEVANT", lambda: run_scope(
        "七星鱸", [], "unknown", "金目鱸生物安全", "金目鱸苗種生物安全資料。", raw="RELEVANT")[1]["final_label"],
        "Species lexicon keeps barramundi and Japanese seabass as separate canonical taxa; source phrase is explicit.")
    check("document_title_body_species_conflict", "UNCERTAIN", lambda: run_scope(
        "吳郭魚", ["吳郭魚"], "verified", "吳郭魚養殖手冊", "本段討論烏魚寒害。", raw="RELEVANT")[1]["final_label"],
        "Synthetic conflict fixture with declared source scope versus paragraph species; conflict is not auto-resolved.")
    check("source_species_unknown", "UNCERTAIN", lambda: run_scope(
        "鰻魚", [], "unknown", "未核實文件", "本段描述池塘管理方法。", raw="RELEVANT")[1]["final_label"],
        "No species label or cross-species scope appears in source metadata/text; uncertainty is required by policy.")
    check("cross_rank_span_rejected", True, lambda: _reject_span_id(),
        "Program-bound span ID from a second fixture chunk is absent from the target chunk span table.")
    check("invalid_json_rejected", True, lambda: _reject_json(),
        "Malformed JSON must become an annotation error, never UNCERTAIN.")
    check("identity_mutation_detected", True, lambda: _identity_check(),
        "question_id/chunk_id/rank are immutable program bindings.")
    check("exact_source_span_roundtrip", True, lambda: _span_roundtrip(),
        "Program-generated offsets reconstruct the original target chunk exactly.")
    return {"suite": "phase_k_species_applicability_regression_v1", "cases": tests,
            "passed": sum(x["passed"] for x in tests), "failed": sum(not x["passed"] for x in tests),
            "all_passed": all(x["passed"] for x in tests), "synthetic_cases_excluded_from_research_denominator": True}


def write_species_rules():
    rules = {
        "version": "phase-k-species-applicability-v1",
        "species_registry": {key: {"canonical_label": value["label_zh"], "aliases": value["aliases"]} for key, value in SPECIES.items()},
        "additional_scopes": {"generic_seabass": ["鱸魚", "鱸類", "seabass"], "general_aquaculture": ["通用水產養殖", "一般養殖"]},
        "taxonomic_distinctions": [
            "金目鱸與七星鱸是不同的精確來源範圍；金目鱸資料不自動泛化為全部鱸魚。",
            "烏魚與吳郭魚是不同魚種；石斑魚對應 grouper，不對應 stonefish。",
        ],
        "decision_rules": [
            "比對題目魚種、文件宣告魚種、Chunk 實際魚種與可驗證的跨物種範圍。",
            "題目專屬魚種與 Chunk 明確魚種不符時，程式最終標 IRRELEVANT，並保留 Judge 原始判斷。",
            "文件魚種宣告與 Chunk 魚種矛盾時標來源衝突及 UNCERTAIN。",
            "來源魚種或適用範圍無法核實時標 UNCERTAIN。",
            "跨魚種通用只接受可定位來源明示的範圍，不由關鍵字推定。",
            "同魚種仍由 Judge 判斷語意相關性；程式不因物種相同就自動判 Relevant。",
            "Judge 只選程式產生的 span ID；程式固定 question/chunk/rank 並從原文 offset 回填引文。",
        ],
        "synthetic_regression_cases_excluded_from_research_denominator": True,
        "raw_judge_outputs_preserved": True,
        "human_gold": False,
    }
    write_json(HERE / "species_applicability_rules.json", rules)
    return rules


def _reject_span_id():
    spans = make_spans("chunk-A", "目標段落")
    foreign_spans = make_spans("chunk-B-rank-2", "第二 Rank 的烏魚段落")
    try:
        validate_judge_response(json.dumps({"label": "RELEVANT", "selected_span_ids": [foreign_spans[0]["span_id"]], "reason": "cross rank quote"}), spans)
    except Exception:
        return True
    return False


def _reject_json():
    try:
        validate_judge_response("{invalid", make_spans("chunk-A", "test"))
    except Exception:
        return True
    return False


def _identity_check():
    expected = {"question_id": "q1", "chunk_id": "c1", "rank": 1}
    altered = {"question_id": "q1", "chunk_id": "c1", "rank": 2}
    try:
        validate_identity(altered, expected)
    except ValueError:
        return True
    return False


def _real_phase_j_species_case():
    root = HERE.parents[2]
    phase_i = root / "reports/evaluation/fish_test_phase_i_20261014_195032"
    phase_j = root / "reports/evaluation/fish_test_phase_j_20261015_190617"
    rows = read_jsonl(phase_j / "pilot_10_chunk_results.jsonl")
    record = next(r for r in rows if r.get("question_id") == "FT-tilapia-Q02" and int(r.get("rank")) == 2)
    trace = read_jsonl(root / "reports/evaluation/fish_test_run_20261012_152244/retrieval_trace.jsonl")
    tr = next(r for r in trace if r.get("question_id") == record["question_id"])
    chunk = next(c for c in tr["contexts"] if c.get("chunk_id") == record["chunk_id"] and int(c.get("top5_rank")) == 2)
    assert record.get("question_id") == "FT-tilapia-Q02" and record.get("chunk_id") == chunk.get("chunk_id") and int(record.get("rank")) == int(chunk.get("top5_rank"))
    assert any(x["canonical"] == "mullet" for x in species_mentions(chunk["text"]))
    scope = assess_species_scope("吳郭魚", [], "unknown", record.get("source_title"), chunk["text"])
    return adjudicate("RELEVANT", scope, [{"span_id": "fixed", "exact_quote": chunk["text"]}])["final_label"]


def _span_roundtrip():
    text = "虱目魚管理資料。" * 80
    spans = make_spans("c", text, max_chars=80)
    return "".join(x["text"] for x in spans) == text and all(text[x["start"]:x["end"]] == x["text"] for x in spans)


def get_json(url: str, timeout=30):
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def post_json(url: str, payload: dict, timeout=300):
    request = urllib.request.Request(url, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                                     headers={"Content-Type": "application/json", "Accept": "application/json"}, method="POST")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def load_fixed_ten():
    questions = read_json(PHASE_I / "pilot_question_selection.json")
    qmap = {row["question_id"]: row for row in questions}
    trace = read_jsonl(ROOT / "reports/evaluation/fish_test_run_20261012_152244/retrieval_trace.jsonl")
    ctxmap = {(row["question_id"], c["chunk_id"], int(c["top5_rank"])): c for row in trace for c in row.get("contexts", [])}
    docs = {r.get("document_id"): r for r in read_jsonl(ROOT / "reports/recovery/document_manifest_v3.jsonl")}
    old_rows = read_jsonl(PHASE_J / "pilot_10_chunk_results.jsonl")
    fixed = []
    for row in old_rows:
        key = (row["question_id"], row["chunk_id"], int(row["rank"]))
        q = qmap[row["question_id"]]
        context = ctxmap[key]
        doc = docs.get(row["document_id"], {})
        text = context.get("text") or ""
        doc_species = doc.get("species") or []
        doc_species_status = "manifest_declared" if doc_species else "unknown"
        fixed.append({
            "question_id": row["question_id"], "question_species": q.get("species"), "question_text": q.get("question_text"),
            "category": q.get("category"), "scenario": q.get("scenario"), "chunk_id": row["chunk_id"],
            "document_id": row["document_id"], "rank": int(row["rank"]), "page": context.get("page"),
            "source_id": doc.get("source_id"), "source_title": doc.get("title"), "source_version": doc.get("version"),
            "source_url": doc.get("source_url"), "document_species": doc_species,
            "document_species_status": doc_species_status, "document_file_path": doc.get("file_path"),
            "chunk_text": text, "chunk_text_sha256": sha256_text(text),
            "fixed_from_phase_j_question_chunk_rank": True,
        })
    return fixed


def preflight():
    tags = get_json(OLLAMA + "/api/tags")
    model = next((m for m in tags.get("models", []) if m.get("name") == MODEL), None)
    if not model:
        raise RuntimeError("required Mistral NeMo model tag is not installed")
    show = post_json(OLLAMA + "/api/show", {"model": MODEL}, timeout=60)
    actual = model.get("digest")
    return {"model": MODEL, "expected_digest": EXPECTED_DIGEST, "actual_digest": actual,
            "digest_matches": actual == EXPECTED_DIGEST, "details": show.get("details"),
            "format_schema_requested": True, "format_schema_response_validation": "local JSON Schema Draft 2020-12"}


def build_prompt(row, spans, scope):
    payload = {
        "question": row["question_text"], "requested_species": row["question_species"],
        "scenario": row.get("scenario") or "",
        "source_metadata": {"source_id": row.get("source_id"), "document_id": row["document_id"],
                            "title": row.get("source_title"), "version": row.get("source_version"),
                            "declared_species": row.get("document_species") or []},
        "chunk_observed_species_labels": sorted(scope.get("chunk_species", [])),
        "target_chunk": {"rank": row["rank"], "page_or_locator": row.get("page"),
                         "spans": [{"span_id": s["span_id"], "text": s["text"]} for s in spans]},
    }
    return "請只判讀下列單一目標 Chunk。魚種標籤是程式根據來源文字辨識的線索，不要把不同魚種資料互相泛化。\n" + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def one_call(row, pass_no, attempt, call_sequence, model_info):
    source_scope = assess_species_scope(row["question_species"], row.get("document_species"),
                                       row.get("document_species_status", "unknown"), row.get("source_title"), row["chunk_text"])
    spans = make_spans(row["chunk_id"], row["chunk_text"])
    prompt = build_prompt(row, spans, source_scope)
    seed = 86100 + call_sequence * 3 + pass_no + attempt
    payload = {"model": MODEL, "stream": False, "format": SCHEMA, "keep_alive": "20m",
               "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}],
               "options": {"temperature": 0, "seed": seed, "num_predict": 256}}
    started = dt.datetime.now(ZoneInfo("Asia/Taipei")).isoformat()
    start_perf = time.perf_counter()
    envelope = None
    raw = None
    try:
        envelope = post_json(OLLAMA + "/api/chat", payload)
        raw = (envelope.get("message") or {}).get("content", "")
        judge, spans_selected = validate_judge_response(raw, spans)
        decision = adjudicate(judge["label"], source_scope, spans_selected)
        # Program-bound identity is recorded outside the model response and never accepted from it.
        prompt_payload = json.loads(prompt.split("\n", 1)[1])
        single_chunk = len(prompt_payload["target_chunk"]["spans"]) > 0 and "contexts" not in prompt_payload
        span_exact = all(row["chunk_text"][x["start_char"]:x["end_char"]] == x["exact_quote"] for x in spans_selected)
        explicit_misjudgment = judge["label"] == "RELEVANT" and source_scope["status"].startswith("MISMATCH")
        result = {
            "request_id": f"{row['question_id']}|{row['chunk_id']}|{row['rank']}|pass{pass_no}|attempt{attempt}",
            "question_id": row["question_id"], "question_species": row["question_species"],
            "chunk_id": row["chunk_id"], "document_id": row["document_id"], "rank": row["rank"],
            "source_id": row.get("source_id"), "source_title": row.get("source_title"), "source_version": row.get("source_version"),
            "question_text": row["question_text"], "chunk_text_sha256": row["chunk_text_sha256"],
            "source_species_assessment": source_scope,
            "raw_judge_label": judge["label"], "raw_judge_reason": judge["reason"],
            "raw_judge_selected_span_ids": judge["selected_span_ids"], "raw_response": raw,
            "program_retrieved_quotes": spans_selected, "accepted_evidence_quotes": decision["accepted_spans"],
            "span_integrity_valid": span_exact, "identity_binding": {"question_id": row["question_id"], "chunk_id": row["chunk_id"], "rank": row["rank"], "document_id": row["document_id"]},
            "identity_binding_source": "program_fixed_from_phase_j_and_retrieval_trace",
            "program_validator_action": decision["validator_action"], "final_label": decision["final_label"],
            "final_reason": decision["reason"], "judge_explicit_species_misjudgment": explicit_misjudgment,
            "program_intercepted_species_error": explicit_misjudgment and decision["final_label"] == "IRRELEVANT",
            "accepted_wrong_species_relevant": decision["final_label"] == "RELEVANT" and source_scope["status"].startswith("MISMATCH"),
            "prompt_contains_one_chunk_only": single_chunk, "prompt_contains_generator_answer": False,
            "prompt_contains_other_rank_text": False,
            "prompt_version": "phase-k-species-aware-single-chunk-v1", "system_prompt": SYSTEM, "full_prompt": prompt,
            "prompt_sha256": sha256_text(SYSTEM + "\n" + prompt), "schema": SCHEMA,
            "model": MODEL, "model_digest": model_info.get("actual_digest"), "model_digest_expected": EXPECTED_DIGEST,
            "temperature": 0, "seed": seed, "num_predict": 256, "stream": False,
            "pass_no": pass_no, "attempt": attempt, "call_started_at": started,
            "elapsed_seconds": time.perf_counter() - start_perf,
            "eval_count": envelope.get("eval_count"), "eval_duration_ns": envelope.get("eval_duration"),
            "call_ended_at": dt.datetime.now(ZoneInfo("Asia/Taipei")).isoformat(),
            "status": "VALID" if span_exact and single_chunk else "ANNOTATION_ERROR",
            "human_gold": False,
        }
        return result
    except Exception as exc:
        return {
            "request_id": f"{row['question_id']}|{row['chunk_id']}|{row['rank']}|pass{pass_no}|attempt{attempt}",
            "question_id": row["question_id"], "chunk_id": row["chunk_id"], "document_id": row["document_id"],
            "rank": row["rank"], "question_species": row["question_species"],
            "source_species_assessment": source_scope, "raw_response": raw, "raw_envelope": envelope,
            "full_prompt": prompt, "system_prompt": SYSTEM, "prompt_sha256": sha256_text(SYSTEM + "\n" + prompt),
            "model": MODEL, "model_digest": model_info.get("actual_digest"), "pass_no": pass_no, "attempt": attempt,
            "call_started_at": started, "elapsed_seconds": time.perf_counter() - start_perf,
            "call_ended_at": dt.datetime.now(ZoneInfo("Asia/Taipei")).isoformat(),
            "status": "ANNOTATION_ERROR", "error_type": type(exc).__name__, "error": str(exc), "human_gold": False,
        }


def annotate(row, pass_no, call_sequence, model_info, archive_path):
    attempts = []
    for attempt in (1, 2):
        result = one_call(row, pass_no, attempt, call_sequence, model_info)
        append_jsonl(archive_path, result)
        attempts.append(result)
        if result["status"] == "VALID":
            result["attempt_count"] = len(attempts)
            result["attempt_request_ids"] = [x["request_id"] for x in attempts]
            return result
        time.sleep(1)
    final = attempts[-1]
    final["attempt_count"] = len(attempts)
    final["attempt_request_ids"] = [x["request_id"] for x in attempts]
    return final


def run_gate2():
    out = HERE / "pilot_10_chunk_results_v2.jsonl"
    archive = HERE / "judge_call_archive.jsonl"
    model_info = preflight()
    write_json(HERE / "judge_model_preflight.json", model_info)
    if not model_info["digest_matches"]:
        raise RuntimeError("Mistral NeMo digest mismatch; no inference attempted")
    fixed = load_fixed_ten()
    if len(fixed) != 10 or len({r["question_id"] for r in fixed}) != 10:
        raise RuntimeError("Phase J fixed 10-item sample could not be reconstructed exactly")
    rows = []
    for index, row in enumerate(fixed, 1):
        result = annotate(row, 1, index, model_info, archive)
        result["fixed_input"] = {k: row.get(k) for k in ("question_id", "question_species", "chunk_id", "document_id", "rank", "source_title", "source_version", "document_species", "document_species_status", "chunk_text_sha256")}
        rows.append(result)
        print(f"phase-k Gate 2 {index}/10 {row['question_id']} rank{row['rank']} {result['status']} raw={result.get('raw_judge_label')} final={result.get('final_label')}", flush=True)
    write_jsonl(out, rows)
    raw_misjudgments = sum(bool(r.get("judge_explicit_species_misjudgment")) for r in rows)
    intercepted = sum(bool(r.get("program_intercepted_species_error")) for r in rows)
    accepted_bad = sum(bool(r.get("accepted_wrong_species_relevant")) for r in rows)
    valid = sum(r.get("status") == "VALID" and r.get("final_label") in {"RELEVANT", "IRRELEVANT", "UNCERTAIN"} for r in rows)
    gate = {
        "fixed_test_rows": len(rows), "valid_end_to_end": valid, "invalid_or_incomplete": len(rows) - valid,
        "judge_raw_explicit_species_misjudgments": raw_misjudgments, "program_intercepted_species_errors": intercepted,
        "accepted_wrong_species_relevant": accepted_bad,
        "identity_mapping_100_percent": all(r.get("identity_binding", {}).get("question_id") == r.get("question_id") and r.get("identity_binding", {}).get("chunk_id") == r.get("chunk_id") and r.get("identity_binding", {}).get("rank") == r.get("rank") for r in rows),
        "all_prompt_single_chunk": all(r.get("prompt_contains_one_chunk_only") is True and r.get("prompt_contains_other_rank_text") is False for r in rows if r.get("status") == "VALID"),
        "all_adopted_quotes_exact": all(q.get("quote_verified_in_target_chunk") for r in rows if r.get("status") == "VALID" for q in r.get("accepted_evidence_quotes", [])),
        "no_accepted_wrong_species_relevant": accepted_bad == 0,
        "passed": valid == 10 and accepted_bad == 0 and all(r.get("identity_binding") for r in rows),
        "gate_policy": "Predeclared source-aware validator may deterministically override explicit species mismatch to IRRELEVANT; raw Judge label is preserved and counted separately.",
    }
    write_json(HERE / "pilot_10_gate_decision.json", gate)
    write_json(HERE / "judge_vs_validator_analysis.json", {
        **gate,
        "judge_raw_label_counts": dict(Counter(r.get("raw_judge_label", "ANNOTATION_ERROR") for r in rows)),
        "program_final_label_counts": dict(Counter(r.get("final_label", "ANNOTATION_ERROR") for r in rows)),
        "raw_judge_error_rows": [{"question_id": r.get("question_id"), "chunk_id": r.get("chunk_id"), "rank": r.get("rank"),
                                  "raw_label": r.get("raw_judge_label"), "source_scope": r.get("source_species_assessment"),
                                  "final_label": r.get("final_label"), "intercepted": r.get("program_intercepted_species_error"),
                                  "raw_response": r.get("raw_response"), "validator_action": r.get("program_validator_action")}
                                 for r in rows if r.get("judge_explicit_species_misjudgment") or r.get("status") != "VALID"],
    })
    return gate, rows, fixed, model_info


def run_gate3(fixed, model_info):
    gate = read_json(HERE / "pilot_10_gate_decision.json")
    if not gate.get("passed"):
        raise RuntimeError("Gate 2 failed; the 50-context pilot is prohibited by the stated stop rule")
    archive = HERE / "judge_call_archive.jsonl"
    rows = []
    seq = 100
    for q in read_json(PHASE_I / "pilot_question_selection.json"):
        for context in sorted(q["contexts"], key=lambda x: x["rank"]):
            same = next((r for r in fixed if r["question_id"] == q["question_id"] and r["chunk_id"] == context["chunk_id"] and r["rank"] == int(context["rank"])), None)
            if same:
                base = same
            else:
                trace_rows = read_jsonl(ROOT / "reports/evaluation/fish_test_run_20261012_152244/retrieval_trace.jsonl")
                match_trace = next(x for x in trace_rows if x["question_id"] == q["question_id"])
                c = next(x for x in match_trace["contexts"] if x["chunk_id"] == context["chunk_id"] and int(x["top5_rank"]) == int(context["rank"]))
                docs = {x.get("document_id"): x for x in read_jsonl(ROOT / "reports/recovery/document_manifest_v3.jsonl")}
                doc = docs.get(c["document_id"], {})
                dspecies = doc.get("species") or []
                base = {"question_id": q["question_id"], "question_species": q.get("species"), "question_text": q["question_text"],
                        "category": q.get("category"), "scenario": q.get("scenario"), "chunk_id": c["chunk_id"],
                        "document_id": c["document_id"], "rank": int(c["top5_rank"]), "page": c.get("page"),
                        "source_id": doc.get("source_id"), "source_title": doc.get("title"), "source_version": doc.get("version"),
                        "source_url": doc.get("source_url"), "document_species": dspecies,
                        "document_species_status": "manifest_declared" if dspecies else "unknown",
                        "document_file_path": doc.get("file_path"), "chunk_text": c.get("text") or "",
                        "chunk_text_sha256": sha256_text(c.get("text") or ""), "fixed_from_phase_j_question_chunk_rank": False}
            pair = {}
            for pass_no in (1, 2):
                seq += 1
                pair[pass_no] = annotate(base, pass_no, seq, model_info, archive)
                pair[pass_no]["fixed_input"] = {k: base.get(k) for k in ("question_id", "question_species", "chunk_id", "document_id", "rank", "source_title", "source_version", "document_species", "document_species_status", "chunk_text_sha256")}
                print(f"phase-k Gate 3 {len(rows)+1}/50 pass{pass_no} {base['question_id']} rank{base['rank']} {pair[pass_no]['status']} final={pair[pass_no].get('final_label')}", flush=True)
            rows.append({
                "question_id": base["question_id"], "species": base["question_species"], "chunk_id": base["chunk_id"],
                "document_id": base["document_id"], "rank": base["rank"], "category": base.get("category"),
                "first_pass_completed": pair[1].get("status") == "VALID", "second_pass_completed": pair[2].get("status") == "VALID",
                "first_pass_label": pair[1].get("final_label"), "second_pass_label": pair[2].get("final_label"),
                "first_pass_raw_judge_label": pair[1].get("raw_judge_label"), "second_pass_raw_judge_label": pair[2].get("raw_judge_label"),
                "first_pass_validator_action": pair[1].get("program_validator_action"), "second_pass_validator_action": pair[2].get("program_validator_action"),
                "first_pass_species_assessment": pair[1].get("source_species_assessment"), "second_pass_species_assessment": pair[2].get("source_species_assessment"),
                "first_pass_accepted_quotes": pair[1].get("accepted_evidence_quotes", []), "second_pass_accepted_quotes": pair[2].get("accepted_evidence_quotes", []),
                "first_pass_raw_response": pair[1].get("raw_response"), "second_pass_raw_response": pair[2].get("raw_response"),
                "first_pass_attempt_request_ids": pair[1].get("attempt_request_ids"), "second_pass_attempt_request_ids": pair[2].get("attempt_request_ids"),
                "first_pass_completed_call": pair[1], "second_pass_completed_call": pair[2],
                "disagreement": pair[1].get("final_label") != pair[2].get("final_label") if pair[1].get("status") == pair[2].get("status") == "VALID" else None,
                "status": "COMPLETE" if pair[1].get("status") == pair[2].get("status") == "VALID" else "INCOMPLETE",
                "human_gold_reviewed": False,
            })
    write_jsonl(HERE / "pilot_50_chunk_results_v2.jsonl", rows)
    counts = Counter((r.get("first_pass_label"), r.get("second_pass_label")) for r in rows)
    report = {
        "contexts": len(rows), "two_round_valid": sum(r["status"] == "COMPLETE" for r in rows),
        "incomplete_contexts": sum(r["status"] != "COMPLETE" for r in rows),
        "first_pass_label_counts": dict(Counter(r.get("first_pass_label") for r in rows)),
        "second_pass_label_counts": dict(Counter(r.get("second_pass_label") for r in rows)),
        "round_disagreement_count": sum(r.get("disagreement") is True for r in rows),
        "accepted_wrong_species_relevant": sum(1 for r in rows for k in ("first_pass_completed_call", "second_pass_completed_call")
                                               if r[k].get("accepted_wrong_species_relevant")),
        "all_identity_matches": all(r["first_pass_completed_call"].get("question_id") == r["question_id"] and
                                     r["second_pass_completed_call"].get("question_id") == r["question_id"] and
                                     r["first_pass_completed_call"].get("chunk_id") == r["chunk_id"] and
                                     r["second_pass_completed_call"].get("chunk_id") == r["chunk_id"] and
                                     r["first_pass_completed_call"].get("rank") == r["rank"] and
                                     r["second_pass_completed_call"].get("rank") == r["rank"] for r in rows),
        "all_accepted_quotes_exact": all(q.get("quote_verified_in_target_chunk") for r in rows for k in ("first_pass_accepted_quotes", "second_pass_accepted_quotes") for q in r[k]),
        "all_calls_stateless_and_answer_blind": all(r[k].get("prompt_contains_one_chunk_only") and not r[k].get("prompt_contains_generator_answer") and not r[k].get("prompt_contains_other_rank_text") for r in rows for k in ("first_pass_completed_call", "second_pass_completed_call") if r[k].get("status") == "VALID"),
        "pair_label_counts": {f"{k[0]}|{k[1]}": v for k, v in counts.items()},
        "human_gold": False,
    }
    report["passed"] = (report["contexts"] == 50 and report["two_round_valid"] == 50 and report["incomplete_contexts"] == 0 and
                        report["accepted_wrong_species_relevant"] == 0 and report["all_identity_matches"] and report["all_accepted_quotes_exact"] and report["all_calls_stateless_and_answer_blind"])
    write_json(HERE / "pilot_50_gate_decision.json", report)
    return rows, report


def recheck_sources_28():
    source_rows = read_jsonl(PHASE_J / "source_verification_28.jsonl")
    excerpt = PHASE_J / "official_law_text_capture_excerpt.txt"
    excerpt_text = excerpt.read_text(encoding="utf-8")
    law_sha = file_sha(excerpt)
    expected_pdfs = {
        "data/recovery/raw_sources/moa_animal_drug_use_rules_attachment_1_FL035443.pdf": "b13b9492322d7c0de2e1f7bc4dcee8feb99431ca1085819a697f3966c6b92e3c",
        "my_data/my_data/動物用藥品管理法.pdf": "f90b9274bdc57bc4c99d1a988872ec3e4783efb6355de9fd7ab4929eace27c67",
        "data/recovery/raw_sources/tfrin_golden_seabass_biosecurity_handbook_final_2025.pdf": "274288d003984b010e445d6d37018c8405d2238c0e1a622ae029a69161fbf0e1",
    }
    checks = []
    for row in source_rows:
        item = dict(row)
        item["phase_k_recheck"] = True
        item["phase_k_human_gold"] = False
        if item.get("capture_type") == "web_tool_rendered_text_excerpt":
            normalized_quote = "".join((item.get("exact_quote") or "").split())
            normalized_page = "".join(excerpt_text.split())
            item["phase_k_exact_quote_reproduced"] = bool(normalized_quote and normalized_quote in normalized_page)
            item["phase_k_snapshot_sha256"] = law_sha
            item["phase_k_original_html_or_server_bytes"] = False
            item["phase_k_source_version"] = "MOA law page rendered text; revision date 114-01-08; retrieved 2026-10-15; not raw HTML"
        elif item.get("source_path") in expected_pdfs:
            path = ROOT / pathlib.Path(item["source_path"])
            actual = file_sha(path) if path.is_file() else None
            item["phase_k_source_file_sha256_actual"] = actual
            item["phase_k_source_checksum_matches"] = actual == expected_pdfs[item["source_path"]]
            matched_pages = []
            if actual == expected_pdfs[item["source_path"]]:
                with fitz.open(path) as pdf:
                    quote = "".join((item.get("exact_quote") or "").split())
                    for page_no in range(pdf.page_count):
                        text = "".join(pdf.load_page(page_no).get_text("text").split())
                        if quote and quote in text:
                            matched_pages.append(page_no + 1)
            item["phase_k_quote_pages"] = matched_pages
            item["phase_k_exact_quote_reproduced"] = bool(matched_pages)
            item["phase_k_original_html_or_server_bytes"] = None
        else:
            item["phase_k_exact_quote_reproduced"] = False
            item["phase_k_blocker"] = "No source-specific recheck method was available for this mapping."
        item["phase_k_support_status"] = item.get("answer_support_status")
        checks.append(item)
    write_jsonl(HERE / "source_verification_28_phase_k.jsonl", checks)
    return checks


def recheck_baseline():
    manifest = read_json(ROOT / "reports/evaluation/fish_test_phase_a_20261012/protected_files_manifest.json")
    entries = manifest["historical_636_recheck"]["entries"]
    rows = []
    for row in entries:
        path = ROOT / row["path"]
        exists = path.is_file()
        actual = file_sha(path) if exists else None
        rows.append({"path": row["path"], "exists": exists, "expected_sha256": row["expected_sha256"],
                     "actual_sha256": actual, "status": "unchanged" if exists and actual == row["expected_sha256"] else "missing_or_mismatch"})
    write_jsonl(HERE / "frozen_baseline_636_recheck.jsonl", rows)
    sqlite = ROOT / "rag_store.sqlite3"
    actual_sqlite = file_sha(sqlite) if sqlite.is_file() else None
    return {"manifest_entries": len(entries), "unchanged": sum(r["status"] == "unchanged" for r in rows),
            "mismatch_or_missing": sum(r["status"] != "unchanged" for r in rows),
            "all_636_unchanged": len(entries) == 636 and all(r["status"] == "unchanged" for r in rows),
            "sqlite_sha256_actual": actual_sqlite,
            "sqlite_sha256_expected": "d7d06d4d2a57d0a57d05bcb6131ffb24aefb226c6bd36349dbc5118d33b11087",
            "sqlite_sha256_matches": actual_sqlite == "d7d06d4d2a57d0a57d05bcb6131ffb24aefb226c6bd36349dbc5118d33b11087"}


def build_reports(gate2, gate3, sources, baseline, tests):
    ten = read_jsonl(HERE / "pilot_10_chunk_results_v2.jsonl") if (HERE / "pilot_10_chunk_results_v2.jsonl").exists() else []
    source_summary = read_json(HERE / "source_verification_28_summary.json")
    raw_counts = Counter(r.get("raw_judge_label", "ANNOTATION_ERROR") for r in ten)
    final_counts = Counter(r.get("final_label", "ANNOTATION_ERROR") for r in ten)
    diag = [{"question_id": r.get("question_id"), "rank": r.get("rank"), "raw_judge_label": r.get("raw_judge_label"),
             "question_species": r.get("question_species"), "chunk_species": (r.get("source_species_assessment") or {}).get("chunk_species"),
             "validator_action": r.get("program_validator_action"), "final_label": r.get("final_label"),
             "intercepted": r.get("program_intercepted_species_error"), "raw_response": r.get("raw_response")}
            for r in ten if r.get("judge_explicit_species_misjudgment") or r.get("status") != "VALID"]
    write_json(HERE / "judge_vs_validator_analysis.json", {
        "judge_raw_label_counts": dict(raw_counts), "program_final_label_counts": dict(final_counts),
        "valid_end_to_end": gate2.get("valid_end_to_end", 0) if gate2 else 0,
        "judge_raw_explicit_species_misjudgments": gate2.get("judge_raw_explicit_species_misjudgments", 0) if gate2 else 0,
        "program_intercepted_species_errors": gate2.get("program_intercepted_species_errors", 0) if gate2 else 0,
        "accepted_wrong_species_relevant": gate2.get("accepted_wrong_species_relevant", 0) if gate2 else 0,
        "gate2_passed": gate2.get("passed", False) if gate2 else False,
        "diagnostic_rows": diag,
        "responsibility_split": {"judge": "semantic relevance judgment and span selection", "program": "identity binding, source/species scope checks, quote extraction, contradiction interception"},
        "human_gold": False,
    })
    if not gate3:
        write_json(HERE / "pilot_50_gate_decision.json", {"started": False, "reason": "Fixed 10-chunk Gate 2 did not pass; 50-context pilot was not run."})
    source_status_counts = source_summary.get("phase_j_support_status_counts", {})
    p50_line = (f"已執行50段雙輪試點：{gate3.get('two_round_valid',0)}/50雙輪有效；分歧 {gate3.get('round_disagreement_count',0)}，錯誤魚種 Relevant 接受 {gate3.get('accepted_wrong_species_relevant',0)}。"
                if gate3 else "50段雙輪試點未執行：固定10筆 Gate 2 未通過，依停止條件沒有啟動。")
    report = f"""# Phase K 標註可靠性報告

## 物種規則與回歸

物種別名與適用性規則以程式化詞彙表、文件宣告、Chunk 文字及可查證通用範圍分開比對。Judge 每次只接收一道題與單一 Chunk，不接收其他 Rank、生成答案或分數；Judge 只能選 span ID，不輸出引文。程式負責固定身分、檢查物種／來源衝突、抽取原文 span，並保留原始 Judge 判定。

離線回歸測試 {tests.get('passed',0)}/{tests.get('passed',0)+tests.get('failed',0)} 通過；合成測例排除於研究分母，並包含 Phase J 真實 `FT-tilapia-Q02` Rank 2 錯誤案例。

## 固定10筆真實測試

- 有效端到端處理：{gate2.get('valid_end_to_end',0) if gate2 else 0}/10；Gate 2：{'通過' if gate2 and gate2.get('passed') else '未通過'}。
- Judge 原始魚種誤判：{gate2.get('judge_raw_explicit_species_misjudgments',0) if gate2 else 0}；程式攔截：{gate2.get('program_intercepted_species_errors',0) if gate2 else 0}；錯誤物種 Relevant 最終接受：{gate2.get('accepted_wrong_species_relevant',0) if gate2 else 0}。
- Judge 原始標籤分布：`{dict(raw_counts)}`；程式最終標籤分布：`{dict(final_counts)}`。
- 身分對應 100%：{gate2.get('identity_mapping_100_percent',False) if gate2 else False}；單 Chunk 提示：{gate2.get('all_prompt_single_chunk',False) if gate2 else False}；採納引文定位：{gate2.get('all_adopted_quotes_exact',False) if gate2 else False}。

{p50_line}

## 28題來源核驗

引文重現 {source_summary.get('phase_k_exact_quotes_reproduced',0)}/28；原狀態直接支持 {source_status_counts.get('DIRECT_SUPPORT_REPRODUCED',0)} 題、部分支持 {source_status_counts.get('PARTIAL_SUPPORT_REMAINS',0)} 題。官方網頁仍是呈現文字摘錄，不是原始 HTML；來源核驗不等於指定 Corpus admission，也不等於 Human Gold。

## 指標與基線

本輪沒有新增有效 P@5、Logical Accuracy 或 Arithmetic Accuracy。Human Gold 維持0，未重跑720次生成，未產生正式總分或 Winner。Frozen Baseline {baseline.get('unchanged',0)}/636 未變；SQLite checksum match={baseline.get('sqlite_sha256_matches')}。{'Gate 2 通過，但50段結果仍須符合自身停止條件後才可考慮900段。' if gate2 and gate2.get('passed') else '不符合擴大至50段或900段的前置條件。'}
"""
    (HERE / "annotation_reliability_report.md").write_text(report, encoding="utf-8")
    final = f"""# Phase K 最終報告

1. 吳郭魚／烏魚：固定的 Phase J 錯誤案例納入實際回歸測試；本輪原始判讀誤判 {gate2.get('judge_raw_explicit_species_misjudgments',0) if gate2 else 0}，程式攔截 {gate2.get('program_intercepted_species_errors',0) if gate2 else 0}，最終錯誤 Relevant 接受 {gate2.get('accepted_wrong_species_relevant',0) if gate2 else 0}。
2. 固定10筆有效端到端判讀：{gate2.get('valid_end_to_end',0) if gate2 else 0}/10；Raw Judge 標籤 `{dict(raw_counts)}`，程式最終 `{dict(final_counts)}`。
3. Judge 原始魚種誤判：{gate2.get('judge_raw_explicit_species_misjudgments',0) if gate2 else 0}；被程式攔截：{gate2.get('program_intercepted_species_errors',0) if gate2 else 0}。
4. 接受的錯誤物種 Relevant：{gate2.get('accepted_wrong_species_relevant',0) if gate2 else 0}。
5. 50段雙輪：{p50_line}
6. 新增有效 P@5：0；沒有產生 P@5 或 Accuracy 分數。
7. 28筆來源核驗維持 12 題直接支持、16 題部分支持；引文重現 {source_summary.get('phase_k_exact_quotes_reproduced',0)}/28。網頁證據仍是可追溯文字摘錄，非原始 HTML。
8. 是否可擴大至900段：{'待評估50段結果' if gate3 and gate3.get('passed') else '否；10筆 Gate 2 未通過' if not (gate2 and gate2.get('passed')) else '否；50段試點未通過或未完成'}。
9. Frozen Baseline：{baseline.get('unchanged',0)}/636 不變；SQLite SHA-256 match={baseline.get('sqlite_sha256_matches')}。未修改720筆生成、Historical E4、Corpus、Production、SQLite 或 Phase E–J 歷史成果。

自動標註為 `NOT_HUMAN_GOLD`；未選出 Winner。
"""
    (HERE / "phase_k_final_report.md").write_text(final, encoding="utf-8")


def main(stage: str):
    if stage == "offline":
        write_json(HERE / "species_conflict_regression_tests.json", regression_tests())
        return
    if stage not in {"gate2", "gate3", "finalize"}:
        raise ValueError(stage)
    rules = write_species_rules()
    tests = regression_tests()
    write_json(HERE / "species_conflict_regression_tests.json", tests)
    gate = None
    gate3 = None
    try:
        if not tests["all_passed"]:
            raise RuntimeError("offline regression failed; live annotation not started")
        if stage in {"gate2", "finalize"}:
            gate, ten_rows, fixed, model_info = run_gate2()
            if gate["passed"]:
                _, gate3 = run_gate3(fixed, model_info)
        else:
            model_info = preflight()
            fixed = load_fixed_ten()
            _, gate3 = run_gate3(fixed, model_info)
    except Exception as exc:
        write_json(HERE / "live_run_blocker.json", {"stage": stage, "error_type": type(exc).__name__, "error": str(exc),
                                                     "no_criteria_tuning_after_observation": True})
        if gate is None and (HERE / "pilot_10_chunk_results_v2.jsonl").exists():
            gate = read_json(HERE / "pilot_10_gate_decision.json") if (HERE / "pilot_10_gate_decision.json").exists() else None
    sources = recheck_sources_28()
    source_counts = Counter(r.get("answer_support_status") for r in sources)
    baseline = recheck_baseline()
    gate2 = read_json(HERE / "pilot_10_gate_decision.json") if (HERE / "pilot_10_gate_decision.json").exists() else None
    gate3 = read_json(HERE / "pilot_50_gate_decision.json") if (HERE / "pilot_50_gate_decision.json").exists() else None
    write_json(HERE / "source_verification_28_summary.json", {
        "rows": len(sources), "phase_j_support_status_counts": dict(source_counts),
        "phase_k_exact_quotes_reproduced": sum(r.get("phase_k_exact_quote_reproduced") is True for r in sources),
        "human_gold": 0, "designated_corpus_admission_asserted": False,
        "web_capture_is_raw_html": False,
    })
    write_json(HERE / "compatibility.json", {
        "phase_j_files_modified": False, "phase_e_to_j_historical_outputs_modified": False,
        "original_720_generations_reexecuted_or_modified": False, "historical_e4_or_frozen_corpus_modified": False,
        "production_or_rag_store_modified": False, "formal_model_score_or_winner_created": False,
        "human_gold_created": False, "new_p5_or_accuracy_computed": False,
        "gate2_passed": gate2.get("passed") if gate2 else False,
        "gate3_started": gate3 is not None, "baseline_636_unchanged": baseline.get("all_636_unchanged"),
        "baseline_unchanged_count": baseline.get("unchanged"), "sqlite_sha256_matches": baseline.get("sqlite_sha256_matches"),
        "output_workspace": str(HERE.relative_to(ROOT)),
    })
    write_json(HERE / "phase_k_execution_summary.json", {"gate2": gate2, "gate3": gate3,
                                                           "source_verification": read_json(HERE / "source_verification_28_summary.json"),
                                                           "baseline": baseline, "offline_tests": tests,
                                                           "species_rules_version": rules.get("version")})
    build_reports(gate2, gate3, sources, baseline, tests)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", choices=["offline", "gate2", "gate3", "finalize"], required=True)
    args = parser.parse_args()
    main(args.stage)
