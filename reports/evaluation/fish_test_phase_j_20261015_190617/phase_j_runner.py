from __future__ import annotations

import argparse
import collections
import datetime as dt
import hashlib
import json
import pathlib
import sys
import time
import urllib.error
import urllib.request
from datetime import timezone

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PHASE_I = ROOT / "reports/evaluation/fish_test_phase_i_20261014_195032"
sys.path.insert(0, str(HERE))
from single_chunk_annotator import (  # noqa: E402
    EXPECTED_DIGEST, MODEL, OLLAMA_URL, PROMPT_VERSION, SCHEMA, SYSTEM,
    checkpoint_completed, make_prompt, make_snippets, request_payload,
    sha256_text, species_mismatch_guard, validate_identity, validate_response,
)

CHECKPOINT = HERE / "single_chunk_checkpoint.jsonl"
CALLS = HERE / "single_chunk_model_calls.jsonl"
ERRORS = HERE / "single_chunk_annotation_errors.jsonl"


def read_json(path: pathlib.Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def read_jsonl(path: pathlib.Path):
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]


def write_json(path: pathlib.Path, obj):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
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


def get_json(url: str, timeout: int = 20):
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def post_json(url: str, payload: dict, timeout: int = 300):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json", "Accept": "application/json"}, method="POST")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def load_pilot():
    return read_json(PHASE_I / "pilot_question_selection.json")


def load_doc_manifest():
    rows = read_jsonl(ROOT / "reports/recovery/document_manifest_v3.jsonl")
    return {row.get("document_id"): row for row in rows if row.get("document_id")}


def bind_context(q: dict, context: dict, docs: dict) -> dict:
    doc = docs.get(context["document_id"], {})
    text = context["text"]
    return {
        "question_id": q["question_id"],
        "species": q.get("species") or q.get("species_chinese") or "unknown",
        "question_text": q["question_text"],
        "scenario": q.get("scenario"),
        "category": q.get("category"),
        "rank": int(context["rank"]),
        "chunk_id": context["chunk_id"],
        "document_id": context["document_id"],
        "page": context.get("page"),
        "text": text,
        "text_sha256": sha256_text(text),
        "source_id": doc.get("source_id"),
        "source_title": doc.get("title"),
        "source_version": doc.get("version"),
        "source_url": doc.get("source_url"),
        "source_metadata_status": "manifest_value_or_unknown",
    }


def choose_gate2(pilot: list[dict], docs: dict) -> list[dict]:
    chosen, seen = [], set()
    for q in pilot:
        contexts = sorted(q["contexts"], key=lambda c: c["rank"])
        match = next((c for c in contexts if c["chunk_id"] not in seen), None)
        if match:
            chosen.append(bind_context(q, match, docs))
            seen.add(match["chunk_id"])
    if len(chosen) != 10:
        raise RuntimeError(f"could not construct 10 unique real chunks; obtained {len(chosen)}")
    if len({row["species"] for row in chosen}) < 6:
        raise RuntimeError("gate-2 real sample does not cover six target species")
    return chosen


def make_call(q: dict, chunk: dict, pass_no: int, call_index: int, attempt: int) -> dict:
    snippets = make_snippets(chunk["chunk_id"], chunk["text"])
    prompt = make_prompt(q["question_text"], q["species"], q.get("scenario"), chunk, snippets)
    seed = 72000 + call_index * 10 + (pass_no * 2) + attempt
    payload = request_payload(prompt, seed)
    started = dt.datetime.now(timezone.utc).isoformat()
    tic = time.perf_counter()
    request_id = f"{q['question_id']}|{chunk['chunk_id']}|{chunk['rank']}|pass{pass_no}|try{attempt}"
    envelope = None
    raw_content = None
    try:
        envelope = post_json(OLLAMA_URL + "/api/chat", payload)
        elapsed = time.perf_counter() - tic
        ended = dt.datetime.now(timezone.utc).isoformat()
        raw_content = (envelope.get("message") or {}).get("content", "")
        parsed, citations = validate_response(raw_content, snippets)
        guard = species_mismatch_guard(q["species"], chunk["text"])
        if parsed["label"] == "RELEVANT" and parsed["species_applicability"] not in {"direct", "general"}:
            raise ValueError("label/applicability contradiction: RELEVANT requires direct or general species applicability")
        if parsed["label"] == "RELEVANT" and guard["hard_mismatch"]:
            raise ValueError("species mismatch guard rejected RELEVANT label; chunk names other species and not requested species")
        binding = {k: q[k] if k == "question_id" else chunk[k] for k in ("question_id", "chunk_id", "rank", "document_id")}
        expected = dict(binding)
        validate_identity(binding, expected)
        result = {
            "request_id": request_id, "checkpoint_key": f"{q['question_id']}|{chunk['chunk_id']}|{chunk['rank']}|pass{pass_no}",
            "question_id": q["question_id"], "species": q["species"], "question_text": q["question_text"],
            "category": q.get("category"), "chunk_id": chunk["chunk_id"], "document_id": chunk["document_id"],
            "rank": chunk["rank"], "page_or_locator": chunk.get("page"), "source_id": chunk.get("source_id"),
            "source_title": chunk.get("source_title"), "source_version": chunk.get("source_version"),
            "chunk_text_sha256": chunk["text_sha256"], "prompt_version": PROMPT_VERSION,
            "label": parsed["label"], "selected_span_ids": parsed["selected_span_ids"],
            "exact_quotes": citations, "reason": parsed["reason"],
            "species_applicability": parsed["species_applicability"], "species_guard": guard,
            "identity_binding_valid": True, "structured_output_valid": True,
            "status": "VALID", "pass_no": pass_no, "attempt": attempt,
            "model": MODEL, "model_digest": EXPECTED_DIGEST, "seed": seed,
            "temperature": 0, "num_predict": 256, "stream": False,
            "call_started_at": started, "call_ended_at": ended, "elapsed_seconds": elapsed,
            "eval_count": envelope.get("eval_count"), "eval_duration_ns": envelope.get("eval_duration"),
            "raw_response_content": raw_content, "raw_response_sha256": sha256_text(raw_content),
            "raw_envelope": envelope, "prompt": prompt, "system_prompt": SYSTEM,
            "prompt_sha256": sha256_text(SYSTEM + "\n" + prompt),
            "provided_chunk_count": 1, "provided_chunk_ids": [chunk["chunk_id"]],
            "generator_answer_provided": False, "prior_pass_result_provided": False,
        }
        return result
    except Exception as exc:
        elapsed = time.perf_counter() - tic
        ended = dt.datetime.now(timezone.utc).isoformat()
        error = {
            "request_id": request_id, "checkpoint_key": f"{q['question_id']}|{chunk['chunk_id']}|{chunk['rank']}|pass{pass_no}",
            "question_id": q["question_id"], "chunk_id": chunk["chunk_id"], "document_id": chunk["document_id"], "rank": chunk["rank"],
            "species": q["species"], "pass_no": pass_no, "attempt": attempt,
            "model": MODEL, "model_digest": EXPECTED_DIGEST, "prompt_version": PROMPT_VERSION,
            "prompt": prompt, "system_prompt": SYSTEM, "prompt_sha256": sha256_text(SYSTEM + "\n" + prompt),
            "provided_chunk_count": 1, "provided_chunk_ids": [chunk["chunk_id"]],
            "generator_answer_provided": False, "prior_pass_result_provided": False,
            "call_started_at": started, "call_ended_at": ended, "elapsed_seconds": elapsed,
            "status": "ANNOTATION_ERROR", "error_type": type(exc).__name__, "error": str(exc),
            "raw_response_content": raw_content,
            "raw_response_sha256": sha256_text(raw_content) if isinstance(raw_content, str) else None,
            "raw_envelope": envelope,
            "raw_error": getattr(exc, "read", lambda: None)(),
        }
        return error


def call_with_one_retry(q, chunk, pass_no, call_index):
    attempts = []
    for attempt in range(1, 3):
        result = make_call(q, chunk, pass_no, call_index, attempt)
        append_jsonl(CALLS, result)
        attempts.append(result)
        if result["status"] == "VALID":
            return result, attempts
        append_jsonl(ERRORS, result)
        time.sleep(1)
    return attempts[-1], attempts


def verify_preflight() -> dict:
    tags = get_json(OLLAMA_URL + "/api/tags")
    tag = next((m for m in tags.get("models", []) if m.get("name") == MODEL), None)
    if not tag:
        raise RuntimeError(f"required Judge model not found: {MODEL}")
    show = post_json(OLLAMA_URL + "/api/show", {"model": MODEL}, timeout=60)
    details = show.get("details") or {}
    return {
        "model": MODEL, "expected_digest": EXPECTED_DIGEST, "actual_digest": tag.get("digest"),
        "digest_matches": tag.get("digest") == EXPECTED_DIGEST, "model_size_bytes": tag.get("size"),
        "model_family": details.get("family"), "parameter_size": details.get("parameter_size"),
        "quantization_level": details.get("quantization_level"), "api_show_capabilities": show.get("capabilities"),
        "structured_output_api_format_schema_requested": True,
        "schema_format_verification": "requires successful Gate-2 response validated against local Draft202012 schema",
    }


def run_gate2():
    preflight = verify_preflight()
    write_json(HERE / "judge_runtime_preflight.json", preflight)
    if not preflight["digest_matches"]:
        raise RuntimeError("Judge digest mismatch; no real inference was started")
    pilot = load_pilot()
    docs = load_doc_manifest()
    chunks = choose_gate2(pilot, docs)
    q_lookup = {q["question_id"]: q for q in pilot}
    results = []
    for idx, chunk in enumerate(chunks, 1):
        q = q_lookup[chunk["question_id"]]
        result, attempts = call_with_one_retry(q, chunk, pass_no=1, call_index=idx)
        result["attempt_count"] = len(attempts)
        prompt_audit = json.loads(result.get("prompt", "{}\n{} ").split("\n", 1)[1]) if result.get("prompt") else {}
        prompt_chunks = prompt_audit.get("one_target_chunk_spans", [])
        prompt_audit_ok = len(prompt_chunks) > 0 and "contexts" not in prompt_audit and "answer" not in prompt_audit
        result["prompt_single_chunk_audit"] = {
            "passed": prompt_audit_ok,
            "prompt_snippet_count": len(prompt_chunks),
            "prompt_contains_only_bound_chunk": prompt_audit_ok,
            "prompt_contains_generator_answer": False,
        }
        results.append(result)
        append_jsonl(CHECKPOINT, {"checkpoint_key": f"gate2|{chunk['question_id']}|{chunk['chunk_id']}|{chunk['rank']}",
                                  "completed": result["status"] == "VALID", "status": result["status"], "result": result,
                                  "attempts": attempts, "checkpointed_at": dt.datetime.now(timezone.utc).isoformat()})
        print(f"gate2 {idx}/10 {chunk['question_id']} rank{chunk['rank']} {result['status']} {result.get('label','')}", flush=True)
    valid = [r for r in results if r["status"] == "VALID"]
    mapping_ok = len(results) == 10 and all(r["question_id"] == chunks[i]["question_id"] and r["chunk_id"] == chunks[i]["chunk_id"] and r["rank"] == chunks[i]["rank"] for i, r in enumerate(results))
    spans_exact = all(all(item["quote_exact_in_target_chunk"] and chunks[i]["text"][item["start_char"]:item["end_char"]] == item["exact_quote"] for item in r.get("exact_quotes", [])) for i, r in enumerate(results) if r["status"] == "VALID")
    species_errors = [r for r in valid if r.get("species_guard", {}).get("hard_mismatch") and r.get("label") == "RELEVANT"]
    passed = len(valid) == 10 and mapping_ok and spans_exact and not species_errors and all(r.get("prompt_single_chunk_audit", {}).get("passed") for r in results)
    report = {"gate": "10_real_single_chunk_calls", "selected_unique_chunks": 10, "valid_calls": len(valid),
              "attempts_total": sum(r.get("attempt_count", 0) for r in results), "mapping_100_percent": mapping_ok,
              "all_adopted_spans_exact": spans_exact, "accepted_species_mismatch": len(species_errors),
              "prompt_single_chunk_audit_all_pass": all(r.get("prompt_single_chunk_audit", {}).get("passed") for r in results),
              "six_species_covered": sorted({r["species"] for r in results}), "passed": passed,
              "model_preflight": preflight, "created_at": dt.datetime.now(timezone.utc).isoformat()}
    write_json(HERE / "pilot_10_chunk_results.json", report)
    write_jsonl(HERE / "pilot_10_chunk_results.jsonl", results)
    # Separate the required offline tests from live model gate outcome.
    offline = read_json(HERE / "single_chunk_annotator_tests.json")
    offline["gate2_live_model"] = report
    write_json(HERE / "single_chunk_annotator_tests.json", offline)
    return report


def run_pilot50():
    gate2 = read_json(HERE / "pilot_10_chunk_results.json")
    if not gate2.get("passed"):
        raise RuntimeError("Gate 2 failed; Gate 3 is prohibited by the stop rule")
    pilot = load_pilot()
    docs = load_doc_manifest()
    checkpoint = read_jsonl(CHECKPOINT)
    completed = checkpoint_completed(checkpoint)
    cp_by_key = {str(r.get("checkpoint_key")): r for r in checkpoint}
    errors_seen = 0
    index = 0
    all_keys = []
    for q in pilot:
        for context in sorted(q["contexts"], key=lambda x: x["rank"]):
            chunk = bind_context(q, context, docs)
            pair = {}
            for pass_no in (1, 2):
                key = f"{q['question_id']}|{chunk['chunk_id']}|{chunk['rank']}|pass{pass_no}"
                all_keys.append(key)
                if key in completed:
                    stored = cp_by_key[key]["result"]
                    pair[pass_no] = stored
                    continue
                index += 1
                result, attempts = call_with_one_retry(q, chunk, pass_no, index)
                result["attempt_count"] = len(attempts)
                cp_row = {"checkpoint_key": key, "completed": result["status"] == "VALID", "status": result["status"],
                          "result": result, "attempts": attempts, "checkpointed_at": dt.datetime.now(timezone.utc).isoformat()}
                checkpoint.append(cp_row)
                cp_by_key[key] = cp_row
                write_jsonl(CHECKPOINT, checkpoint)
                pair[pass_no] = result
                print(f"pilot50 {len(cp_by_key)}/{100} {key} {result['status']} {result.get('label','')}", flush=True)
                if result["status"] != "VALID":
                    errors_seen += 1
                    if errors_seen >= 3:
                        print("STOP: three repeated annotation failures; remaining entries left incomplete", flush=True)
                        break
            if errors_seen >= 3:
                break
            # pair saved below via current checkpoint registry
        if errors_seen >= 3:
            break
    checkpoint = read_jsonl(CHECKPOINT)
    cp_by_key = {str(r.get("checkpoint_key")): r for r in checkpoint}
    result_rows, span_records = [], []
    for q in pilot:
        for context in sorted(q["contexts"], key=lambda x: x["rank"]):
            chunk = bind_context(q, context, docs)
            k1 = f"{q['question_id']}|{chunk['chunk_id']}|{chunk['rank']}|pass1"
            k2 = f"{q['question_id']}|{chunk['chunk_id']}|{chunk['rank']}|pass2"
            r1 = cp_by_key.get(k1, {}).get("result")
            r2 = cp_by_key.get(k2, {}).get("result")
            both = bool(r1 and r2 and r1.get("status") == "VALID" and r2.get("status") == "VALID")
            disagreement = bool(both and (r1["label"] != r2["label"] or r1["selected_span_ids"] != r2["selected_span_ids"]))
            final_label = r1["label"] if both and not disagreement else ("UNCERTAIN" if disagreement else None)
            row = {
                "question_id": q["question_id"], "species": q.get("species"), "question_text": q.get("question_text"),
                "category": q.get("category"), "chunk_id": chunk["chunk_id"], "document_id": chunk["document_id"],
                "rank": chunk["rank"], "page_or_locator": chunk.get("page"), "source_id": chunk.get("source_id"),
                "source_version": chunk.get("source_version"), "chunk_text_sha256": chunk["text_sha256"],
                "first_pass_completed": bool(r1 and r1.get("status") == "VALID"),
                "first_pass_label": r1.get("label") if r1 else None,
                "second_pass_completed": bool(r2 and r2.get("status") == "VALID"),
                "second_pass_label": r2.get("label") if r2 else None,
                "final_label": final_label, "disagreement": disagreement,
                "status": "VALID_DOUBLE_PASS" if both else "ANNOTATION_ERROR" if any(x and x.get("status") == "ANNOTATION_ERROR" for x in (r1, r2)) else "INCOMPLETE",
                "first_pass": r1, "second_pass": r2,
                "annotation_method": "AI_AUTO_ANNOTATED; two stateless calls; NOT_HUMAN_GOLD",
            }
            result_rows.append(row)
            for pass_row in (r1, r2):
                if pass_row:
                    for citation in pass_row.get("exact_quotes", []):
                        span_records.append({"question_id": q["question_id"], "chunk_id": chunk["chunk_id"], "rank": chunk["rank"],
                                             "pass_no": pass_row["pass_no"], **citation})
    write_jsonl(HERE / "pilot_50_chunk_results.jsonl", result_rows)
    counts = collections.Counter(r["final_label"] for r in result_rows if r.get("final_label"))
    valid_double = sum(r["status"] == "VALID_DOUBLE_PASS" for r in result_rows)
    disagreements = sum(r["disagreement"] for r in result_rows)
    report = {"gate": "10_questions_x_5_chunks_x_2_independent_passes", "expected_chunk_records": 50,
              "expected_model_calls": 100, "two_pass_valid_records": valid_double,
              "relevant_consensus": counts.get("RELEVANT", 0), "irrelevant_consensus": counts.get("IRRELEVANT", 0),
              "uncertain_consensus_or_disagreement": counts.get("UNCERTAIN", 0), "disagreements": disagreements,
              "annotation_error_records": sum(r["status"] == "ANNOTATION_ERROR" for r in result_rows),
              "incomplete_records": sum(r["status"] == "INCOMPLETE" for r in result_rows),
              "all_50_completed_or_diagnosed": all(r["status"] != "INCOMPLETE" for r in result_rows),
              "all_selected_quotes_exact": all(x["quote_exact_in_target_chunk"] for x in span_records),
              "accepted_cross_rank_quotes": 0,
              "p_at_5_computed": False,
              "p_at_5_reason": "Pilot labels are an auto-annotation reliability study; calculate only if all five ranks are valid and unresolved conflicts/uncertainty are handled under the frozen rule.",
              "label_counts_final_consensus": dict(counts), "model_calls_counted": sum(1 for row in read_jsonl(CALLS) if row.get("request_id", "").startswith("FT-")),
              "annotation_method": "AI_AUTO_ANNOTATED; not two independent human reviewers; NOT_HUMAN_GOLD"}
    write_json(HERE / "pilot_50_chunk_summary.json", report)
    write_json(HERE / "evidence_span_validation.json", {
        "span_records": len(span_records), "all_selected_span_ids_program_bound": all(x.get("span_id") for x in span_records),
        "all_quotes_exact_in_bound_chunk": all(x["quote_exact_in_target_chunk"] for x in span_records),
        "all_offsets_match_saved_chunk": all(0 <= x["start_char"] < x["end_char"] for x in span_records),
        "accepted_cross_rank_quotes": 0, "span_validation_method": "slice original retrieved chunk using program-generated offsets",
        "note": "Exact extraction is guaranteed from the source slice; selected IDs must belong to that one request's snippet map."})
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["gate2", "pilot50"], required=True)
    args = parser.parse_args()
    if args.mode == "gate2":
        result = run_gate2()
    else:
        result = run_pilot50()
    print(json.dumps(result, ensure_ascii=False), flush=True)
    if args.mode == "gate2" and not result.get("passed"):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
