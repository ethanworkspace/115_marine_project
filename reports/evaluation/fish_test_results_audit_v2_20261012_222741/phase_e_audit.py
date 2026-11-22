import collections
import datetime as dt
import hashlib
import json
import math
import re
import statistics
import urllib.request
from decimal import Decimal, InvalidOperation
from pathlib import Path

ROOT = Path.cwd()
RUN = ROOT / "reports/evaluation/fish_test_run_20261012_152244"
OUT = ROOT / "reports/evaluation/fish_test_results_audit_v2_20261012_222741"
PHASE_A = ROOT / "reports/evaluation/fish_test_phase_a_20261012"
PROTECTED = PHASE_A / "protected_files_manifest.json"
SQLITE = ROOT / "rag_store.sqlite3"
EXPECTED_SQLITE = "d7d06d4d2a57d0a57d05bcb6131ffb24aefb226c6bd36349dbc5118d33b11087"
BGE_TAG = "bge-m3:latest"
BGE_DIGEST = "7907646426070047a77226ac3e684fbbe8410524f7b4a74d02837e43f2146bab"
MODEL_IDS = ["M1", "M2", "M3", "M4"]
RAW_NAMES = [
    "fish_test_questions_normalized.jsonl", "retrieval_trace.jsonl",
    "generation_outputs.jsonl", "judge_results.jsonl",
    "per_question_metrics.jsonl", "efficiency_metrics.jsonl",
]


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def read_jsonl(path):
    with path.open("r", encoding="utf-8-sig") as f:
        return [json.loads(line) for line in f if line.strip()]


def write_json(name, value):
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(name, rows):
    with (OUT / name).open("w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def sha256_file(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def protected_snapshot():
    manifest = read_json(PROTECTED)
    entries = manifest.get("files", [])
    mismatches, checked, matched = [], 0, 0
    for entry in entries:
        rel = str(entry.get("path", ""))
        p = ROOT / rel
        if not rel or not p.is_file():
            mismatches.append({"path": rel, "status": "missing"})
            continue
        try:
            actual_sha = sha256_file(p)
            actual_size = p.stat().st_size
            checked += 1
            ok = actual_sha == entry.get("sha256") and actual_size == entry.get("size_bytes")
            matched += int(ok)
            if not ok:
                mismatches.append({"path": rel, "status": "mismatch", "expected_sha256": entry.get("sha256"), "actual_sha256": actual_sha, "expected_size": entry.get("size_bytes"), "actual_size": actual_size})
        except Exception as exc:
            mismatches.append({"path": rel, "status": "unreadable", "exception_type": type(exc).__name__, "message": str(exc)})
    sqlite_sha = sha256_file(SQLITE) if SQLITE.is_file() else None
    return {"expected_count": 636, "manifest_count": len(entries), "checked_count": checked, "matching_count": matched, "mismatches": mismatches, "complete": len(entries) == 636 and checked == 636 and matched == 636 and not mismatches, "sqlite_sha256": sqlite_sha, "sqlite_matches_expected": sqlite_sha == EXPECTED_SQLITE}


def local_json(endpoint, payload=None, timeout=120):
    url = "http://127.0.0.1:11434" + endpoint
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"} if data else {}, method="GET" if data is None else "POST")
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read())


def l2_normalize(v):
    norm = math.sqrt(sum(float(x) * float(x) for x in v))
    if norm == 0:
        raise ValueError("zero_vector")
    return [float(x) / norm for x in v], norm


def bge_relevance(questions, generations):
    tags = local_json("/api/tags")
    tagrow = next((m for m in tags.get("models", []) if m.get("name") == BGE_TAG), None)
    if tagrow is None or tagrow.get("digest") != BGE_DIGEST:
        reason = "BGE-M3 local tag missing or digest mismatch; no embeddings computed"
        return [{"question_id": g.get("question_id"), "model_id": g.get("model_id"), "bge_m3_answer_relevance_cosine": None, "status": "blocked_model_identity", "failure_reason": reason} for g in generations], {"status": "blocked", "expected_tag": BGE_TAG, "expected_digest": BGE_DIGEST, "actual_model": tagrow, "reason": reason}

    qmap = {q["question_id"]: q for q in questions}
    usable = []
    output = {}
    for g in generations:
        parsed = g.get("parsed_output")
        answer = parsed.get("answer") if isinstance(parsed, dict) else None
        failure = None
        if not isinstance(answer, str):
            failure = "parsed_output.answer_not_string; raw_output_not_parsed_as_fallback"
        else:
            answer = answer.strip()
            answer = re.sub(r"(?is)<think>.*?</think>", "", answer).strip()
            if not answer:
                failure = "empty_final_answer"
            elif re.search(r"(?is)</?think>", answer):
                failure = "unmatched_inline_thinking_marker"
        key = (g.get("question_id"), g.get("model_id"))
        output[key] = {"question_id": key[0], "model_id": key[1], "model_tag": g.get("model_tag"), "model_digest": g.get("model_digest"), "question_text": qmap.get(key[0], {}).get("question_text"), "generated_answer_text": answer if failure is None else None, "generated_answer_field": "parsed_output.answer", "schema_valid": g.get("schema_valid"), "embedding_model": BGE_TAG, "embedding_digest": BGE_DIGEST, "embedding_dimension": 1024, "normalization": "explicit L2 unit normalization; cosine is normalized dot product", "bge_m3_answer_relevance_cosine": None, "status": "pending" if failure is None else "not_computable", "failure_reason": failure}
        if failure is None:
            usable.append((key, qmap[key[0]]["question_text"], answer))

    # Batch 16 question-answer pairs (32 texts) per call; no Gold, Context, citations, or thinking channel is embedded.
    batch_size = 16
    embedding_errors = []
    for start in range(0, len(usable), batch_size):
        batch = usable[start:start + batch_size]
        texts = []
        for _, qtext, answer in batch:
            texts.extend([qtext, answer])
        try:
            response = local_json("/api/embed", {"model": BGE_TAG, "input": texts, "truncate": False, "dimensions": 1024, "keep_alive": "5m"}, timeout=300)
            vectors = response.get("embeddings", [])
            if len(vectors) != len(texts) or any(len(v) != 1024 for v in vectors):
                raise ValueError(f"unexpected_embedding_shape:{len(vectors)}:{[len(v) for v in vectors[:2]]}")
            for i, (key, _, _) in enumerate(batch):
                qv, qnorm = l2_normalize(vectors[i * 2])
                av, anorm = l2_normalize(vectors[i * 2 + 1])
                cosine = sum(a * b for a, b in zip(qv, av))
                output[key].update({"question_vector_norm_before_normalization": qnorm, "answer_vector_norm_before_normalization": anorm, "bge_m3_answer_relevance_cosine": cosine, "status": "scored", "failure_reason": None})
        except Exception as exc:
            # Retry each pair independently to preserve per-record diagnostics.
            batch_error = f"{type(exc).__name__}: {exc}"
            for key, qtext, answer in batch:
                try:
                    response = local_json("/api/embed", {"model": BGE_TAG, "input": [qtext, answer], "truncate": False, "dimensions": 1024, "keep_alive": "5m"}, timeout=300)
                    vectors = response.get("embeddings", [])
                    if len(vectors) != 2 or any(len(v) != 1024 for v in vectors):
                        raise ValueError("unexpected_embedding_shape")
                    qv, qnorm = l2_normalize(vectors[0]); av, anorm = l2_normalize(vectors[1])
                    output[key].update({"question_vector_norm_before_normalization": qnorm, "answer_vector_norm_before_normalization": anorm, "bge_m3_answer_relevance_cosine": sum(a*b for a,b in zip(qv,av)), "status": "scored_after_batch_retry", "failure_reason": None, "batch_error_recovered": batch_error})
                except Exception as exc2:
                    output[key].update({"status": "embedding_failed", "failure_reason": f"batch={batch_error}; single_pair={type(exc2).__name__}: {exc2}"})
                    embedding_errors.append({"question_id": key[0], "model_id": key[1], "reason": output[key]["failure_reason"]})
    rows = [output[(g.get("question_id"), g.get("model_id"))] for g in generations]
    meta = {"status": "completed" if not embedding_errors else "completed_with_record_errors", "model_tag": BGE_TAG, "model_digest": BGE_DIGEST, "runtime": "Ollama local /api/embed", "input_pairs": len(usable), "input_texts": len(usable) * 2, "dimension": 1024, "request_batch_pairs": batch_size, "truncate": False, "normalization": "explicit L2 normalization for each vector, followed by dot product", "score": "raw cosine similarity, not transformed to 0-1", "answer_extraction": "parsed_output.answer only; empty/unparseable answers omitted; no raw-output fallback; separate message.thinking channel excluded; inline <think> blocks removed, unmatched marker excluded", "context_or_gold_embedded": False, "embedding_errors": embedding_errors}
    return rows, meta


def finite_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(float(v))


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    protected_before = protected_snapshot()
    raw_before = {name: sha256_file(RUN / name) for name in RAW_NAMES}
    questions = read_jsonl(RUN / "fish_test_questions_normalized.jsonl")
    retrieval = read_jsonl(RUN / "retrieval_trace.jsonl")
    generations = read_jsonl(RUN / "generation_outputs.jsonl")
    judges = read_jsonl(RUN / "judge_results.jsonl")
    metrics = read_jsonl(RUN / "per_question_metrics.jsonl")
    efficiency = read_jsonl(RUN / "efficiency_metrics.jsonl")
    qmap = {q["question_id"]: q for q in questions}
    rmap = {r["question_id"]: r for r in retrieval}
    gmap = {(g["question_id"], g["model_id"]): g for g in generations}
    jmap = {(j["question_id"], j["model_id"]): j for j in judges}
    mmap = {(m["question_id"], m["model_id"]): m for m in metrics}
    emap = {(e["question_id"], e["model_id"]): e for e in efficiency}

    # Question × model reconciliation and Judge/structure audit.
    consistency = []
    for g in generations:
        key = (g["question_id"], g["model_id"])
        j = jmap.get(key, {})
        parsed = g.get("parsed_output")
        answer = parsed.get("answer") if isinstance(parsed, dict) else None
        answer_readable = isinstance(answer, str) and bool(answer.strip())
        score_valid = j.get("status") == "scored" and finite_num(j.get("faithfulness")) and finite_num(j.get("answer_relevance")) and 0 <= float(j["faithfulness"]) <= 1 and 0 <= float(j["answer_relevance"]) <= 1
        failure_reason = None
        if not j:
            failure_reason = "judge_record_missing"
        elif not score_valid:
            failure_reason = j.get("reason") or j.get("execution_error") or j.get("parse_error") or j.get("status") or "invalid_or_missing_score"
        if score_valid and not g.get("schema_valid"):
            input_type = "parsed_output.answer_from_schema_invalid_but_parseable_object"
        elif score_valid:
            input_type = "parsed_output.answer_from_schema_valid_object"
        elif answer_readable:
            input_type = "parsed_output.answer_present_but_judge_not_valid"
        else:
            input_type = "no_parseable_nonempty_answer"
        consistency.append({"question_id": g["question_id"], "model_id": g["model_id"], "structure_valid": bool(g.get("schema_valid")), "schema_errors": g.get("schema_errors") or [], "judge_score_valid": score_valid, "judge_input_type": input_type, "judge_failure_reason": failure_reason, "parsed_answer_present": answer_readable, "judge_status": j.get("status", "missing"), "judge_faithfulness": j.get("faithfulness") if score_valid else None, "judge_answer_relevance": j.get("answer_relevance") if score_valid else None, "judge_request_sha256": j.get("judge_request_sha256"), "context_sha256_generation": g.get("context_sha256"), "context_sha256_judge": j.get("context_sha256"), "context_digest_matches": bool(j) and j.get("context_sha256") == g.get("context_sha256"), "candidate_answer_used": j.get("candidate_answer_used", False), "candidate_rubric_used": j.get("candidate_rubric_used", False)})
    write_jsonl("judge_structure_consistency_audit.jsonl", consistency)

    structure_by_model = {}
    for mid in MODEL_IDS:
        gr = [g for g in generations if g.get("model_id") == mid]
        jr = [x for x in consistency if x["model_id"] == mid]
        structure_by_model[mid] = {"generation_n": len(gr), "structure_valid_n": sum(bool(g.get("schema_valid")) for g in gr), "structure_invalid_n": sum(not bool(g.get("schema_valid")) for g in gr), "judge_valid_n": sum(x["judge_score_valid"] for x in jr), "judge_invalid_structure_but_scored_n": sum(x["judge_score_valid"] and not x["structure_valid"] for x in jr), "judge_not_valid_n": sum(not x["judge_score_valid"] for x in jr), "answer_text_parseable_n": sum(x["parsed_answer_present"] for x in jr)}

    # Validate all four model identities against run-time metadata, current Ollama tags, and output records.
    runtime_tags = local_json("/api/tags").get("models", [])
    runtime_by_name = {m.get("name"): m for m in runtime_tags}
    runtime_alignment = read_json(RUN / "model_runtime_alignment.json")
    alignment_rows = runtime_alignment.get("models", []) if isinstance(runtime_alignment, dict) else []
    model_identity = []
    for mid in MODEL_IDS:
        runrow = next((x for x in alignment_rows if x.get("model_id") == mid), {})
        tag = runrow.get("tag") or runrow.get("model_tag") or next((g.get("model_tag") for g in generations if g.get("model_id") == mid), None)
        digest = runrow.get("digest") or runrow.get("model_digest") or next((g.get("model_digest") for g in generations if g.get("model_id") == mid), None)
        local = runtime_by_name.get(tag, {})
        recorded_digests = sorted(set(g.get("model_digest") for g in generations if g.get("model_id") == mid))
        model_identity.append({"model_id": mid, "model_tag": tag, "run_digest": digest, "current_local_digest": local.get("digest"), "recorded_generation_digests": recorded_digests, "identity_matches_run_and_current_local": bool(digest and local.get("digest") == digest and recorded_digests == [digest]), "architecture": ((local.get("details") or {}).get("family")), "run_alignment_record": runrow})

    judge_tags = sorted(set(j.get("judge_tag") for j in judges))
    judge_digests = sorted(set(j.get("judge_digest") for j in judges))
    judge_audit = {
        "judge_model_tag": judge_tags, "judge_digest": judge_digests,
        "judge_scores_valid": sum(x["judge_score_valid"] for x in consistency),
        "judge_parse_failures": sum(bool(j.get("parse_error")) or j.get("status") == "judge_failed" for j in judges),
        "unscored_due_generator_answer_unavailable": sum(x["judge_status"] == "not_scored_generation_invalid" for x in consistency),
        "scored_with_schema_invalid_generation": sum(x["judge_score_valid"] and not x["structure_valid"] for x in consistency),
        "scored_valid_schema_generation": sum(x["judge_score_valid"] and x["structure_valid"] for x in consistency),
        "judge_input_method": "scripts/evaluation/fish_test/run_evaluation.py judge_phase: parsed_output.answer only, plus the question and the five saved Retrieval contexts; it does not pass raw_output, separate message.thinking, candidate answer, or scoring rubric.",
        "format_gate_behavior": "Judge stage requires parsed_output to be an object with a string answer, but does not require schema_valid; this explains parseable-answer scores on malformed structured responses.",
        "judge_prompt_system": "You are an independent evaluator. Do not reveal hidden reasoning. Return only schema-conforming JSON.",
        "judge_prompt_user_template": "請獨立評估下列 RAG 回答，只依問題與 Context 評分。不要使用外部知識，不要使用或推測題庫候選答案／評分規準；本次只評估忠實度、問題相關性及 Context 是否足以回答。Faithfulness 以 Context 對回答事實主張的支持比例評 0–1；Answer Relevance 以是否直接回答問題評 0–1。Context Sufficiency 判斷不看回答表現，只看 Context 是否包含足以作答的資訊。若不確定，應保守評分並在 rationale 說明。\n\n問題：{question}\n\nContext：{top5_contexts}\n\n回答：{parsed_output.answer}",
        "prompt_persistence": "Generation prompts are saved; Judge prompt text is reconstructable from the audited code and inputs, but the exact Judge prompt body was not persisted. Judge request SHA-256 is persisted for each scored row.",
        "score_scope": "Custom 0-1 exploratory Judge scores; faithfulness is support by Retrieved Context, not candidate-answer match and not validated RAGAS.",
        "candidate_answer_or_rubric_used_any": any(j.get("candidate_answer_used") or j.get("candidate_rubric_used") for j in judges),
        "faithfulness_recalculation": "No formula defect found in the recorded Judge rubric; preserve original values as judge_faithfulness. Recomputed strict-schema-valid sensitivity means are supplied separately; no Judge rerun or history overwrite.",
    }
    faith_means = {}
    for mid in MODEL_IDS:
        all_scored = [j for j in judges if j.get("model_id") == mid and j.get("status") == "scored" and finite_num(j.get("faithfulness"))]
        strict = [j for j in all_scored if gmap.get((j["question_id"], mid), {}).get("schema_valid") is True]
        faith_means[mid] = {"all_parseable_answer_judge_n": len(all_scored), "all_parseable_answer_judge_mean": statistics.mean(j["faithfulness"] for j in all_scored) if all_scored else None, "schema_valid_only_n": len(strict), "schema_valid_only_mean": statistics.mean(j["faithfulness"] for j in strict) if strict else None}
    judge_audit["faithfulness_population_sensitivity"] = faith_means
    relevance_means = {}
    for mid in MODEL_IDS:
        all_scored = [j for j in judges if j.get("model_id") == mid and j.get("status") == "scored" and finite_num(j.get("answer_relevance"))]
        strict = [j for j in all_scored if gmap.get((j["question_id"], mid), {}).get("schema_valid") is True]
        relevance_means[mid] = {"all_parseable_answer_judge_n": len(all_scored), "all_parseable_answer_judge_mean": statistics.mean(j["answer_relevance"] for j in all_scored) if all_scored else None, "schema_valid_only_n": len(strict), "schema_valid_only_mean": statistics.mean(j["answer_relevance"] for j in strict) if strict else None}
    judge_audit["judge_answer_relevance_population_sensitivity"] = relevance_means
    write_json("faithfulness_judge_audit.json", judge_audit)

    # BGE-M3 embeddings for question and final parsed answer only.
    bge_rows, bge_meta = bge_relevance(questions, generations)
    write_jsonl("bge_m3_answer_relevance.jsonl", bge_rows)
    write_json("bge_m3_embedding_method.json", bge_meta)

    # Missing TTFT audit: preserve N/A; event timestamps are server timestamps, not client monotonic request latency.
    ttft_rows = []
    for g in generations:
        m = mmap.get((g["question_id"], g["model_id"]), {})
        if m.get("ttft_seconds") is not None:
            continue
        events = g.get("stream_events") or []
        def first_event(channel):
            for ix, ev in enumerate(events):
                msg = ev.get("message") or {}
                value = msg.get(channel) or ""
                if value:
                    return {"event_index_1_based": ix + 1, "created_at_server": ev.get("created_at"), "character_count": len(value), "elapsed_client_seconds": None}
            return None
        raw = g.get("raw_output") or ""
        inline = "<think>" in raw or "</think>" in raw
        ttft_rows.append({"question_id": g["question_id"], "model_id": g["model_id"], "stream_event_count_recorded": g.get("stream_event_count"), "stream_event_count_list": len(events), "first_content_event": first_event("content"), "first_thinking_event": first_event("thinking"), "eval_count": (g.get("final_event") or {}).get("eval_count"), "eval_duration_ns": (g.get("final_event") or {}).get("eval_duration"), "first_any_token_elapsed_seconds": g.get("ttft_first_any_token_seconds"), "ttft_final_content_elapsed_seconds": None, "inline_thinking_marker_detected": inline, "missing_reason": "Original runner intentionally nulled final-content TTFT because inline <think> markup makes content-vs-thinking timing ambiguous; stream events preserve server created_at but not the client monotonic receipt/request-start time needed for exact TTFT recovery." if inline else "No saved client monotonic first-content latency; event server timestamps alone cannot reconstruct accepted-request TTFT without approximation."})
    write_jsonl("ttft_missingness_audit.jsonl", ttft_rows)

    # Recalculate all TPS directly from Ollama done-event counters.
    tps_rows = []
    tps_check = collections.Counter()
    for g in generations:
        fe = g.get("final_event") or {}
        n, ns = fe.get("eval_count"), fe.get("eval_duration")
        calc = float(n) / (float(ns) / 1e9) if isinstance(n, (int, float)) and isinstance(ns, (int, float)) and ns > 0 else None
        saved = g.get("tokens_per_second")
        close = calc is not None and saved is not None and math.isclose(calc, float(saved), rel_tol=1e-12, abs_tol=1e-12)
        tps_check["checked"] += 1
        tps_check["match"] += int(close)
        tps_rows.append({"question_id": g["question_id"], "model_id": g["model_id"], "eval_count": n, "eval_duration_raw": ns, "eval_duration_unit": "nanoseconds (Ollama API specification)", "recalculated_tps": calc, "saved_tps": saved, "matches_saved": close, "status": "verified_match" if close else "missing_engine_counter" if calc is None else "mismatch"})
    write_jsonl("tps_recalculation.jsonl", tps_rows)

    # Calculation audit. Decimal checks the workbook's explicit arithmetic formula only; this does not certify an authoritative formula or Gold.
    calc_rows = []
    def dnum(x):
        if x is None or isinstance(x, bool): return None
        try: return Decimal(str(x))
        except (InvalidOperation, ValueError): return None
    for q in questions:
        if q.get("inferred_category") != "Calculation":
            continue
        rec = q.get("calculation_record")
        status, calculated, error = "not_recomputed", None, None
        formula = rec.get("公式說明") if isinstance(rec, dict) else None
        vals = [dnum(rec.get(k)) for k in ("值1", "值2", "值3")] if isinstance(rec, dict) else []
        answer = dnum(rec.get("人工核對")) if isinstance(rec, dict) else None
        a, b, c = (vals + [None, None, None])[:3]
        try:
            if formula == "(下限+上限)/2" and a is not None and b is not None: calculated = (a+b)/Decimal(2)
            elif formula in ("上限-下限", "目標-原值", "標準-目前", "前者－後者", "前者-後者", "實際重量－允許重量") and a is not None and b is not None: calculated = (b-a) if formula == "上限-下限" else (a-b)
            elif formula == "門檻-實測" and a is not None and b is not None: calculated = a-b
            elif formula == "下限-實測" and a is not None and b is not None: calculated = a-b
            elif formula == "實測-上界" and a is not None and b is not None: calculated = a-b
            elif formula in ("面積×密度", "水體積×密度上限", "水量×密度上限", "總重×攝食率", "分地×kg/分地", "分地×水車數") and a is not None and b is not None: calculated = a*b
            elif formula == "符合項目數/總項目" and a is not None and b not in (None, Decimal(0)): calculated = a/b
            elif formula in ("總月數/間隔", "總天數/間隔") and a is not None and b not in (None, Decimal(0)): calculated = a/b
            elif formula in ("介於上下限則為1", "角度<上限則為1") and a is not None and b is not None and c is not None: calculated = Decimal(1) if b <= a <= c else Decimal(0)
            elif formula in ("最後使用日+停藥日數+1", "最後使用日＋停藥日數＋1"):
                datev = rec.get("值1") if isinstance(rec, dict) else None
                if isinstance(datev, str) and b is not None:
                    last = dt.date.fromisoformat(datev[:10]); calculated = (last + dt.timedelta(days=int(b)+1)).isoformat()
            if calculated is None:
                status = "not_recomputed_formula_or_inputs_unhandled"
            elif isinstance(calculated, Decimal) and answer is not None:
                status = "mechanical_match" if calculated == answer else "mechanical_mismatch"
            elif isinstance(calculated, str) and rec.get("人工核對"):
                status = "mechanical_match" if calculated == str(rec.get("人工核對"))[:10] else "mechanical_mismatch"
            else:
                status = "computed_candidate_answer_unparseable"
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"; status = "recompute_error"
        calc_rows.append({"question_id": q["question_id"], "species": q.get("species_chinese"), "question_text": q.get("question_text"), "candidate_answer": q.get("candidate_reference_answer"), "candidate_calculation_record": rec, "formula_from_workbook": formula, "decimal_recalculation": str(calculated) if isinstance(calculated, Decimal) else calculated, "workbook_manual_check_value": str(answer) if answer is not None else (rec.get("人工核對") if isinstance(rec, dict) else None), "mechanical_consistency_status": status, "recalculation_error": error, "source_ids": q.get("source_ids"), "source_urls": q.get("candidate_source_urls"), "formula_source_verified": False, "conditions_verified": False, "rounding_and_tolerance_verified": False, "human_gold_reviewed": bool(q.get("human_gold_reviewed")), "arithmetic_accuracy_eligible": False, "qualification_reason": "Workbook calculation metadata/candidate answer is not independent formula Gold; source applicability, formula protocol, rounding/tolerance and Human Gold are not verified."})
    write_jsonl("arithmetic_gold_candidate_review.jsonl", calc_rows)

    # Context Precision annotation queue: all 180 questions, each with its stored Top-5; relevance remains unannotated.
    cp_queue = []
    for q in questions:
        r = rmap.get(q["question_id"], {})
        contexts = r.get("contexts") or []
        cp_queue.append({"question_id": q["question_id"], "species": q.get("species_chinese"), "category": q.get("inferred_category"), "top5_chunk_ids": [c.get("chunk_id") for c in contexts], "document_ids": list(dict.fromkeys(c.get("document_id") for c in contexts if c.get("document_id"))), "evidence_sufficiency": "not_independently_annotated", "relevance_labels": [{"rank": c.get("top5_rank", i+1), "chunk_id": c.get("chunk_id"), "document_id": c.get("document_id"), "relevance_label": None} for i,c in enumerate(contexts)], "annotation_source": None, "reviewer": None, "annotation_status": "pending_human_relevance_annotation", "corpus_version": r.get("corpus_version"), "index_checksum": r.get("index_checksum")})
    write_jsonl("context_precision_annotation_queue.jsonl", cp_queue)

    # Paired common-sample tables and per-model available-sample summaries.
    bge_map = {(x["question_id"], x["model_id"]): x for x in bge_rows}
    metric_defs = {
        "judge_faithfulness": lambda q,m: jmap.get((q,m),{}).get("faithfulness") if jmap.get((q,m),{}).get("status")=="scored" else None,
        "judge_answer_relevance": lambda q,m: jmap.get((q,m),{}).get("answer_relevance") if jmap.get((q,m),{}).get("status")=="scored" else None,
        "bge_m3_answer_relevance_cosine": lambda q,m: bge_map.get((q,m),{}).get("bge_m3_answer_relevance_cosine"),
        "structured_output_valid": lambda q,m: 1.0 if gmap.get((q,m),{}).get("schema_valid") is True else (0.0 if gmap.get((q,m),{}).get("schema_valid") is False else None),
        "ttft_final_content_seconds": lambda q,m: mmap.get((q,m),{}).get("ttft_seconds"),
        "tps_ollama_eval_rate": lambda q,m: tps_rows_by_key.get((q,m),{}).get("recalculated_tps"),
        "system_level_sampled_ram_peak_bytes": lambda q,m: mmap.get((q,m),{}).get("system_ram_peak_bytes_sampled"),
        "system_level_sampled_dedicated_vram_peak_bytes": lambda q,m: mmap.get((q,m),{}).get("dedicated_vram_peak_bytes_sampled"),
    }
    tps_rows_by_key = {(x["question_id"],x["model_id"]):x for x in tps_rows}
    paired = {"all_available_samples": {}, "paired_common_samples": {}, "pairwise_differences": {}, "paired_policy": "same question_id valid in all four models for each metric; duplicates/near-duplicates remain dependent, so comparisons are descriptive only", "question_count": len(questions)}
    qids = [q["question_id"] for q in questions]
    for name, getter in metric_defs.items():
        values = {mid: {qid: getter(qid, mid) for qid in qids} for mid in MODEL_IDS}
        paired["all_available_samples"][name] = {mid: {"n": sum(finite_num(v) for v in values[mid].values()), "mean": statistics.mean(float(v) for v in values[mid].values() if finite_num(v)) if any(finite_num(v) for v in values[mid].values()) else None} for mid in MODEL_IDS}
        common = [qid for qid in qids if all(finite_num(values[mid][qid]) for mid in MODEL_IDS)]
        paired["paired_common_samples"][name] = {"n": len(common), "question_ids": common, "means": {mid: statistics.mean(float(values[mid][qid]) for qid in common) if common else None for mid in MODEL_IDS}}
        diffs = []
        for i, ma in enumerate(MODEL_IDS):
            for mb in MODEL_IDS[i+1:]:
                d = [float(values[ma][qid])-float(values[mb][qid]) for qid in common]
                diffs.append({"model_a": ma, "model_b": mb, "difference": f"{ma} minus {mb}", "n": len(d), "mean_difference": statistics.mean(d) if d else None})
        paired["pairwise_differences"][name] = diffs
    write_json("paired_sample_comparison.json", paired)

    # Historical and proposed scoring formula audit, no composite total emitted.
    phase_a_spec = read_json(PHASE_A / "research_plan_metric_spec.json")
    scoring = {
        "phase_a_standalone_research_proposal_found": phase_a_spec.get("proposal_document",{}).get("standalone_research_proposal_found"),
        "historical_scoring_formula": "0.70 * 0.175 * sum(Faithfulness, Judge Answer Relevance, Arithmetic Accuracy, Structured Output IFR) + 0.30 * 0.10 * sum(TTFT_score, TPS_score, Memory_Pressure_score)",
        "historical_max_score_double_weighting": 0.58,
        "proposed_corrected_formula": "0.175 * (Faithfulness + relevance_metric + Arithmetic Accuracy + Structured Output IFR) + 0.10 * (TTFT_score + TPS_score + Memory_Pressure_score)",
        "corrected_formula_max_if_all_components_normalized_0_1": 1.0,
        "formula_arithmetic_check": {"historical_max": 0.70*0.175*4 + 0.30*0.10*3, "proposed_max": 0.175*4 + 0.10*3},
        "scoring_policy_approval_status": "unconfirmed_not_frozen",
        "answer_relevance_specification": "Research direction requires BGE-M3 cosine(question, generated_answer); historical custom Judge answer_relevance is retained separately as judge_answer_relevance.",
        "memory_pressure_normalization": "undefined; no approved formula or bounds located",
        "ttft_tps_normalization": "undefined; no approved score mapping to 0-1 located",
        "ram_vram_weights": "no separate approved weights located; memory values remain diagnostics",
        "context_precision_weight": 0,
        "winner_or_composite_score": None,
        "no_missing_metric_filled_with_zero": True,
    }
    write_json("scoring_policy_status.json", scoring)

    # Baseline reconciliation.
    qids_unique = len({q.get("question_id") for q in questions})
    per_model_counts = {mid: structure_by_model[mid] for mid in MODEL_IDS}
    ctx_groups = collections.defaultdict(set)
    for g in generations: ctx_groups[g["question_id"]].add(g.get("context_sha256"))
    ctx_consistent = len(ctx_groups) == 180 and all(len(s)==1 for s in ctx_groups.values()) and all(next(iter(ctx_groups[qid])) == rmap[qid].get("context_sha256") for qid in rmap if qid in ctx_groups)
    judge_scored = sum(x["judge_score_valid"] for x in consistency)
    structure_valid = sum(bool(g.get("schema_valid")) for g in generations)
    answer_parseable = sum(x["parsed_answer_present"] for x in consistency)
    run_recon = {
        "run_id": "fish_test_run_20261012_152244", "phase_a_reference": str((PHASE_A / "phase_a_summary.md").relative_to(ROOT)),
        "question_records": len(questions), "unique_question_ids": qids_unique,
        "retrieval_records": len(retrieval), "generation_records": len(generations), "generator_calls_expected": 180*4,
        "generation_status_success": sum(g.get("generation_status")=="success" for g in generations),
        "structure_valid_records": structure_valid, "judge_records": len(judges), "judge_score_valid_records": judge_scored,
        "judge_not_valid_records": len(judges)-judge_scored, "parseable_nonempty_answer_records": answer_parseable,
        "context_digest_equal_across_models_and_retrieval": ctx_consistent,
        "model_counts": per_model_counts, "model_identity_reconciliation": model_identity,
        "ttft_missing_records": len(ttft_rows), "tps_recalculation": dict(tps_check),
        "exact_duplicate_sensitivity": "all 180 retained in main analysis; Phase A has 175 distinct stems (five excess registrations) in sensitivity analysis; cross-species same stems retained.",
        "suspected_near_duplicate_pairs": 15,
        "raw_file_sha256_before_phase_e": raw_before,
        "phase_b_c_final_results_modified": False,
    }
    write_json("raw_run_reconciliation.json", run_recon)

    # Data-quality list and formulas summary used by workbook.
    per_model_derived = {}
    for mid in MODEL_IDS:
        records = [x for x in consistency if x["model_id"]==mid]
        per_model_derived[mid] = {"generation_n": len(records), "structure_valid_n": sum(x["structure_valid"] for x in records), "judge_scored_n": sum(x["judge_score_valid"] for x in records), "judge_scored_invalid_structure_n": sum(x["judge_score_valid"] and not x["structure_valid"] for x in records), "judge_not_scored_n": sum(not x["judge_score_valid"] for x in records)}

    # Compatibility after all reads/analysis; new output directory is intentionally outside frozen manifest.
    raw_after = {name: sha256_file(RUN / name) for name in RAW_NAMES}
    protected_after = protected_snapshot()
    compatibility = {"phase_e_run_id": OUT.name, "phase_b_d_raw_results_sha256_before": raw_before, "phase_b_d_raw_results_sha256_after": raw_after, "raw_phase_b_d_unchanged": raw_before == raw_after, "protected_manifest_before": protected_before, "protected_manifest_after": protected_after, "sqlite_expected_sha256": EXPECTED_SQLITE, "sqlite_unchanged_and_matches_expected": protected_before.get("sqlite_sha256") == protected_after.get("sqlite_sha256") == EXPECTED_SQLITE, "fish_test_originals_modified": False, "production_modified": False, "corpus_v2_modified": False, "historical_e4_modified": False, "model_weights_modified": False, "judge_modified": False, "cleanup_or_deletion_performed": False, "winner": None}
    compatibility["protected_baseline_ok"] = protected_before.get("complete") and protected_after.get("complete") and compatibility["sqlite_unchanged_and_matches_expected"] and compatibility["raw_phase_b_d_unchanged"]
    write_json("compatibility.json", compatibility)

    # Aggregate machine-readable summary for report/workbook.
    model_metrics = {}
    for mid in MODEL_IDS:
        judge = [j for j in judges if j.get("model_id")==mid and j.get("status")=="scored"]
        bge = [r for r in bge_rows if r.get("model_id")==mid and r.get("status","").startswith("scored")]
        gen = [g for g in generations if g.get("model_id")==mid]
        vals = lambda rows, key: [float(r[key]) for r in rows if finite_num(r.get(key))]
        model_metrics[mid] = {
            "model_tag": gen[0].get("model_tag") if gen else None,
            "model_digest": gen[0].get("model_digest") if gen else None,
            "generation_calls": len(gen), "generation_success": sum(g.get("generation_status")=="success" for g in gen),
            "structure_valid_n": sum(bool(g.get("schema_valid")) for g in gen), "structure_valid_rate": sum(bool(g.get("schema_valid")) for g in gen)/len(gen) if gen else None,
            "judge_faithfulness": {"n": len(vals(judge,"faithfulness")), "mean": statistics.mean(vals(judge,"faithfulness")) if vals(judge,"faithfulness") else None},
            "judge_answer_relevance": {"n": len(vals(judge,"answer_relevance")), "mean": statistics.mean(vals(judge,"answer_relevance")) if vals(judge,"answer_relevance") else None},
            "bge_m3_answer_relevance_cosine": {"n": len([r for r in bge if finite_num(r.get("bge_m3_answer_relevance_cosine"))]), "mean": statistics.mean(vals(bge,"bge_m3_answer_relevance_cosine")) if vals(bge,"bge_m3_answer_relevance_cosine") else None},
            "ttft_final_content": {"n": len(vals([mmap[(g["question_id"],mid)] for g in gen if (g["question_id"],mid) in mmap],"ttft_seconds")), "mean": statistics.mean(vals([mmap[(g["question_id"],mid)] for g in gen if (g["question_id"],mid) in mmap],"ttft_seconds")) if vals([mmap[(g["question_id"],mid)] for g in gen if (g["question_id"],mid) in mmap],"ttft_seconds") else None},
            "tps_ollama_eval_rate": {"n": len(vals([tps_rows_by_key[(g["question_id"],mid)] for g in gen],"recalculated_tps")), "mean": statistics.mean(vals([tps_rows_by_key[(g["question_id"],mid)] for g in gen],"recalculated_tps")) if vals([tps_rows_by_key[(g["question_id"],mid)] for g in gen],"recalculated_tps") else None},
            "system_level_sampled_ram_peak_bytes": {"n": len(vals([mmap[(g["question_id"],mid)] for g in gen if (g["question_id"],mid) in mmap],"system_ram_peak_bytes_sampled")), "mean": statistics.mean(vals([mmap[(g["question_id"],mid)] for g in gen if (g["question_id"],mid) in mmap],"system_ram_peak_bytes_sampled")) if vals([mmap[(g["question_id"],mid)] for g in gen if (g["question_id"],mid) in mmap],"system_ram_peak_bytes_sampled") else None},
            "system_level_sampled_dedicated_vram_peak_bytes": {"n": len(vals([mmap[(g["question_id"],mid)] for g in gen if (g["question_id"],mid) in mmap],"dedicated_vram_peak_bytes_sampled")), "mean": statistics.mean(vals([mmap[(g["question_id"],mid)] for g in gen if (g["question_id"],mid) in mmap],"dedicated_vram_peak_bytes_sampled")) if vals([mmap[(g["question_id"],mid)] for g in gen if (g["question_id"],mid) in mmap],"dedicated_vram_peak_bytes_sampled") else None},
            "shared_gpu_memory": {"n": len(vals([mmap[(g["question_id"],mid)] for g in gen if (g["question_id"],mid) in mmap],"shared_gpu_memory_peak_counter_bytes_sampled")), "mean": statistics.mean(vals([mmap[(g["question_id"],mid)] for g in gen if (g["question_id"],mid) in mmap],"shared_gpu_memory_peak_counter_bytes_sampled")) if vals([mmap[(g["question_id"],mid)] for g in gen if (g["question_id"],mid) in mmap],"shared_gpu_memory_peak_counter_bytes_sampled") else None},
        }
    write_json("model_metrics_v2.json", {"models": model_metrics, "context_precision_at_5": {"n":0,"value":None,"reason":"No independently verified per-question relevance labels for returned Top-5 chunks."}, "arithmetic_accuracy": {"n":0,"value":None,"reason":"No independent formula/source/applicability/rounding/tolerance Gold; workbook calculation metadata remains candidate only."}, "logical_accuracy": {"n":0,"value":None,"reason":"No independent reproducible logical-accuracy rubric."}, "semantic_instruction_following": {"status":"not_evaluated","reason":"No semantic instruction-following rubric; structured output validity is reported separately."}, "human_gold":0,"formal_winner":None})

    print(json.dumps({"run_dir": str(OUT), "question_count": len(questions), "generation_count": len(generations), "schema_valid": structure_valid, "judge_valid": judge_scored, "answer_parseable": answer_parseable, "ttft_missing": len(ttft_rows), "tps": dict(tps_check), "bge": bge_meta, "calc_candidates": len(calc_rows), "calc_mechanical_status": dict(collections.Counter(r["mechanical_consistency_status"] for r in calc_rows)), "protected_ok": compatibility["protected_baseline_ok"], "model_metrics": model_metrics}, ensure_ascii=False))


if __name__ == "__main__":
    main()
