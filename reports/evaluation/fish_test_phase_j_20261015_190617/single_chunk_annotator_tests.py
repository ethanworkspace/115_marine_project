from __future__ import annotations

import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from single_chunk_annotator import make_snippets, validate_response, validate_identity, checkpoint_completed


def run() -> dict:
    tests = []

    def check(name, fn):
        try:
            fn()
            tests.append({"test": name, "passed": True, "error": None})
        except Exception as exc:
            tests.append({"test": name, "passed": False, "error": f"{type(exc).__name__}: {exc}"})

    chunk_a = {"chunk_id": "chunk_A", "document_id": "doc_A", "rank": 1, "text": "烏魚適合生長水溫20～28℃。"}
    spans_a = make_snippets(chunk_a["chunk_id"], chunk_a["text"])
    valid_span = spans_a[0]["span_id"]
    chunk_b = {"chunk_id": "chunk_B", "document_id": "doc_B", "rank": 2, "text": "吳郭魚病害資料。"}
    spans_b = make_snippets(chunk_b["chunk_id"], chunk_b["text"])
    foreign_span = spans_b[0]["span_id"]

    check("relevant_exact_program_span", lambda: _assert_relevant(valid_span, spans_a, chunk_a["text"]))
    check("irrelevant_no_span", lambda: _assert_empty("IRRELEVANT", spans_a))
    check("mullet_tilapia_species_confusion_rejected", lambda: _assert_mismatch_guard())
    check("cross_rank_span_id_rejected", lambda: _assert_rejected({"label": "RELEVANT", "selected_span_ids": [foreign_span], "reason": "cross rank", "species_applicability": "direct"}, spans_a))
    check("nonexistent_span_id_rejected", lambda: _assert_rejected({"label": "RELEVANT", "selected_span_ids": ["sp_missing"], "reason": "missing", "species_applicability": "direct"}, spans_a))
    check("duplicate_span_ids_rejected", lambda: _assert_rejected({"label": "RELEVANT", "selected_span_ids": [valid_span, valid_span], "reason": "dup", "species_applicability": "direct"}, spans_a))
    check("invalid_json_rejected", lambda: _assert_invalid_json("{bad", spans_a))
    check("judge_quote_field_rejected", lambda: _assert_rejected({"label": "RELEVANT", "selected_span_ids": [valid_span], "reason": "extra quote", "species_applicability": "direct", "quoted_evidence": "made up"}, spans_a))
    check("relevant_species_mismatch_contradiction_rejected", lambda: _assert_rejected({"label": "RELEVANT", "selected_span_ids": [valid_span], "reason": "contradiction", "species_applicability": "mismatch"}, spans_a))
    check("identity_is_program_bound", lambda: _assert_identity_binding())
    check("checkpoint_resume_skips_only_valid_completed", lambda: _assert_checkpoint_resume())
    check("snippets_reconstruct_source_and_offsets", lambda: _assert_partition())
    return {"test_suite": "phase_j_single_chunk_offline_v1", "tests": tests,
            "passed": sum(1 for row in tests if row["passed"]), "failed": sum(1 for row in tests if not row["passed"]),
            "all_passed": all(row["passed"] for row in tests), "human_gold": False}


def _assert_relevant(span_id, spans, source):
    obj, refs = validate_response(json.dumps({"label": "RELEVANT", "selected_span_ids": [span_id], "reason": "direct source evidence", "species_applicability": "direct"}), spans)
    assert len(refs) == 1 and refs[0]["exact_quote"] == source[refs[0]["start_char"]:refs[0]["end_char"]]


def _assert_empty(label, spans):
    validate_response(json.dumps({"label": label, "selected_span_ids": [], "reason": "no applicable evidence", "species_applicability": "mismatch"}), spans)


def _assert_mismatch_guard():
    from single_chunk_annotator import species_mismatch_guard
    g = species_mismatch_guard("吳郭魚", "烏魚的適合生長水溫為20～28℃。")
    assert g["hard_mismatch"] and "烏魚" in g["other_species_named"]


def _assert_rejected(obj, spans):
    try:
        validate_response(json.dumps(obj), spans)
    except Exception:
        return
    raise AssertionError("expected response rejection")


def _assert_invalid_json(text, spans):
    try:
        validate_response(text, spans)
    except Exception:
        return
    raise AssertionError("expected invalid JSON rejection")


def _assert_identity_binding():
    expected = {"question_id": "q1", "chunk_id": "c1", "rank": 1, "document_id": "d1"}
    validate_identity(dict(expected), expected)
    altered = dict(expected, rank=2)
    try:
        validate_identity(altered, expected)
    except ValueError:
        return
    raise AssertionError("identity mutation was accepted")


def _assert_checkpoint_resume():
    rows = [{"checkpoint_key": "q1|c1|1|pass1", "completed": True, "status": "VALID"},
            {"checkpoint_key": "q1|c2|2|pass1", "completed": False, "status": "INCOMPLETE"}]
    assert checkpoint_completed(rows) == {"q1|c1|1|pass1"}


def _assert_partition():
    text = "第一段。" * 80 + "\n第二段，含原文。"
    spans = make_snippets("chunk_test", text, max_chars=90)
    assert "".join(x["text"] for x in spans) == text
    assert all(text[x["start"]:x["end"]] == x["text"] for x in spans)


if __name__ == "__main__":
    result = run()
    (HERE / "single_chunk_annotator_tests.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(0 if result["all_passed"] else 1)
