from __future__ import annotations

import datetime as dt
import hashlib
import json
import pathlib
import re
import sys
import unicodedata
from collections import Counter
from zoneinfo import ZoneInfo

import pymupdf as fitz

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PHASE_I = ROOT / "reports/evaluation/fish_test_phase_i_20261014_195032"
sys.path.insert(0, str(HERE))
from single_chunk_annotator import sha256_text  # noqa: E402


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]


def write_json(path, obj):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def write_jsonl(path, rows):
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as out:
        for row in rows:
            out.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    tmp.replace(path)


def norm(text):
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text or "").replace("\u00a0", " "))


def file_sha(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def build_source_verification():
    original_rows = read_jsonl(PHASE_I / "local_source_quote_verification.jsonl")
    mapping_rows = read_jsonl(PHASE_I / "source_mapping_recovery_180.jsonl")
    document_rows = read_jsonl(PHASE_I / "source_documents_29_mapping.jsonl")
    source_docs = {row.get("path"): row for row in document_rows}
    qmap = {r["question_id"]: r for r in mapping_rows}
    excerpt_path = HERE / "official_law_text_capture_excerpt.txt"
    excerpt = excerpt_path.read_text(encoding="utf-8")
    excerpt_norm = norm(excerpt)
    local_expected = {
        "data/recovery/raw_sources/moa_animal_drug_use_rules_attachment_1_FL035443.pdf": "b13b9492322d7c0de2e1f7bc4dcee8feb99431ca1085819a697f3966c6b92e3c",
        "my_data/my_data/動物用藥品管理法.pdf": "f90b9274bdc57bc4c99d1a988872ec3e4783efb6355de9fd7ab4929eace27c67",
        "data/recovery/raw_sources/tfrin_golden_seabass_biosecurity_handbook_final_2025.pdf": "274288d003984b010e445d6d37018c8405d2238c0e1a622ae029a69161fbf0e1",
    }
    verified, excluded = [], []
    for item in original_rows:
        qid = item.get("question_id")
        question = qmap.get(qid, {})
        source_path = item.get("source_path")
        source_doc = source_docs.get(source_path, {})
        record = {
            "question_id": qid,
            "species": question.get("species"),
            "question_text": question.get("question_text"),
            "candidate_reference_answer": question.get("candidate_reference_answer"),
            "source_id": item.get("source_id"),
            "source_url": source_doc.get("source_url") or (question.get("source_urls") or [None])[0],
            "source_path": source_path,
            "document_version": source_doc.get("version") or item.get("version") or question.get("source_version"),
            "source_sha256_expected": source_doc.get("sha256") or item.get("source_sha256"),
            "exact_quote": item.get("exact_quote"),
            "page_or_locator": item.get("locator"),
            "phase_i_quote_verified": item.get("quote_verified"),
            "answer_supported_phase_i": item.get("answer_supported"),
            "species_applicability": item.get("species_applicability"),
            "phase_i_blocker_reason": item.get("blocker_reason"),
            "human_gold_reviewed": False,
            "verification_level": "SOURCE_VERIFIED_AUTOMATED where reproduced; NOT_HUMAN_GOLD",
        }
        if not qid or not item.get("exact_quote"):
            record.update({"recheck_status": "EXCLUDED_FALSE_OR_INCOMPLETE_MAPPING", "rechecked_quote_verified": False,
                           "answer_supported": False, "blocker_reason": "Phase I identified an incomplete/false association; not counted among the 28 intended mappings."})
            excluded.append(record)
            continue
        capture_method = item.get("quote_capture_method") or ""
        if capture_method.startswith("official_law_webpage_read_only"):
            quote_norm = norm(item["exact_quote"])
            rechecked_quote = bool(quote_norm and quote_norm in excerpt_norm)
            original_pdf = ROOT / pathlib.Path(source_path) if source_path else None
            original_pdf_sha = file_sha(original_pdf) if original_pdf and original_pdf.is_file() else None
            expected_pdf_sha = local_expected.get(source_path)
            record.update({
                "capture_type": "web_tool_rendered_text_excerpt",
                "source_file_exists": bool(original_pdf and original_pdf.is_file()),
                "source_sha256_actual_if_local_copy": original_pdf_sha,
                "source_checksum_matches_expected_if_local_copy": original_pdf_sha == expected_pdf_sha if expected_pdf_sha else None,
                "webpage_snapshot_status": "relevant official rendered text excerpt saved; raw_html_not_acquired",
                "webpage_excerpt_path": str(excerpt_path.relative_to(ROOT)),
                "webpage_excerpt_sha256": file_sha(excerpt_path),
                "rechecked_quote_verified": rechecked_quote,
                "quote_match_method": "official law page text returned by Codex web retrieval; exact normalized substring",
            })
        elif source_path and source_path in local_expected:
            path = ROOT / pathlib.Path(source_path)
            actual_sha = file_sha(path) if path.is_file() else None
            pdf_match_pages = []
            if path.is_file() and actual_sha == local_expected[source_path]:
                doc = fitz.open(path)
                needle = norm(item["exact_quote"])
                for page_index in range(doc.page_count):
                    page_text = doc.load_page(page_index).get_text("text")
                    if needle and needle in norm(page_text):
                        pdf_match_pages.append(page_index + 1)
                doc.close()
            rechecked_quote = bool(actual_sha == local_expected[source_path] and pdf_match_pages)
            record.update({
                "capture_type": "local_original_pdf_text_recheck",
                "source_file_exists": path.is_file(), "source_sha256_actual": actual_sha,
                "source_checksum_matches_expected": actual_sha == local_expected[source_path],
                "pdf_page_count_match": pdf_match_pages,
                "webpage_snapshot_status": "not_applicable_local_pdf",
                "rechecked_quote_verified": rechecked_quote,
                "quote_match_method": "PyMuPDF extracted page text; Unicode NFKC and whitespace-insensitive exact substring",
            })
        else:
            quote_norm = norm(item["exact_quote"])
            rechecked_quote = bool(quote_norm and quote_norm in excerpt_norm)
            record.update({
                "capture_type": "web_tool_rendered_text_excerpt",
                "source_file_exists": False, "source_sha256_actual": None,
                "source_checksum_matches_expected": None,
                "page_or_locator": item.get("locator"),
                "webpage_snapshot_status": "excerpt_saved; raw_html_not_acquired",
                "webpage_excerpt_path": str(excerpt_path.relative_to(ROOT)),
                "webpage_excerpt_sha256": file_sha(excerpt_path),
                "rechecked_quote_verified": rechecked_quote,
                "quote_match_method": "official law page text returned by Codex web retrieval; exact normalized substring",
            })
        original_support = item.get("answer_supported")
        if original_support is True and rechecked_quote:
            support_status = "DIRECT_SUPPORT_REPRODUCED"
        elif original_support == "partial" and rechecked_quote:
            support_status = "PARTIAL_SUPPORT_REMAINS"
        else:
            support_status = "NOT_REPRODUCED_OR_NEEDS_REVIEW"
        record.update({
            "rechecked_quote_verified": rechecked_quote,
            "answer_supported": original_support is True and rechecked_quote,
            "answer_support_status": support_status,
            "blocker_reason": item.get("blocker_reason") if support_status != "DIRECT_SUPPORT_REPRODUCED" else None,
            "retrieval_corpus_admission": "not_asserted; a source quote does not establish designated-corpus eligibility",
        })
        verified.append(record)
    write_jsonl(HERE / "source_verification_28.jsonl", verified)
    write_jsonl(HERE / "source_verification_excluded_mapping.jsonl", excluded)
    counts = Counter(r["answer_support_status"] for r in verified)
    summary = {
        "input_phase_i_rows": len(original_rows), "valid_intended_mappings": len(verified),
        "excluded_false_or_incomplete_mappings": len(excluded),
        "rechecked_quote_verified": sum(bool(r.get("rechecked_quote_verified")) for r in verified),
        "direct_support_reproduced": counts.get("DIRECT_SUPPORT_REPRODUCED", 0),
        "partial_support_remains": counts.get("PARTIAL_SUPPORT_REMAINS", 0),
        "unreproduced_or_needs_review": counts.get("NOT_REPRODUCED_OR_NEEDS_REVIEW", 0),
        "capture_types": dict(Counter(r.get("capture_type") for r in verified)),
        "official_page_raw_html_saved": False,
        "official_page_text_excerpt_saved": True,
        "excerpt_sha256": file_sha(excerpt_path),
        "human_gold_count": 0,
    }
    write_json(HERE / "source_verification_28_summary.json", summary)
    write_json(HERE / "official_law_text_capture_manifest.json", {
        "source_url": "https://law.moa.gov.tw/LawContent.aspx?id=FL035443&media=print",
        "page_title": "農業部主管法規共用系統－法規內容－動物用藥品使用準則",
        "capture_type": "web_tool_rendered_text_excerpt",
        "retrieved_on": "2026-10-15",
        "captured_at_precision": "date only; the web retrieval provider did not expose a per-call wall-clock timestamp",
        "page_print_time_as_rendered": "民國115年09月24日 04:33",
        "document_revision_date": "民國114年01月08日",
        "saved_excerpt_path": str(excerpt_path.relative_to(ROOT)),
        "saved_excerpt_sha256": file_sha(excerpt_path),
        "original_http_html_saved": False,
        "original_server_bytes_sha256": None,
        "statement": "A rendered text excerpt was saved for quote comparison; it is not represented as raw HTML or a complete page snapshot.",
    })
    return verified, excluded, summary


def build_pilot50_not_started():
    selected = read_json(PHASE_I / "pilot_question_selection.json")
    rows = []
    for q in selected:
        for context in sorted(q["contexts"], key=lambda c: c["rank"]):
            rows.append({
                "question_id": q["question_id"], "species": q.get("species"),
                "question_text": q.get("question_text"), "category": q.get("category"),
                "chunk_id": context["chunk_id"], "document_id": context["document_id"],
                "rank": context["rank"], "first_pass_completed": False,
                "second_pass_completed": False, "first_pass_label": None,
                "second_pass_label": None, "final_label": None, "disagreement": None,
                "status": "NOT_STARTED_GATE_2_FAILED",
                "reason": "Gate 3 was not started because Gate 2 did not meet the 10/10 real-single-chunk acceptance criteria.",
                "model_call_count": 0, "human_gold_reviewed": False,
            })
    write_jsonl(HERE / "pilot_50_chunk_results.jsonl", rows)
    return rows


def build_source_url_accessibility_151():
    """Reconcile Phase I URL audit to each question lacking a local source original.

    This intentionally reuses the recorded Phase I browser audit; it does not
    imply a fresh network request or a locally preserved original page.
    """
    mapping_rows = read_jsonl(PHASE_I / "source_mapping_recovery_180.jsonl")
    url_rows = read_jsonl(PHASE_I / "source_url_accessibility_30.jsonl")
    by_url = {r.get("source_url"): r for r in url_rows}
    missing_local = [r for r in mapping_rows if not r.get("local_original_path")]
    reconciled = []
    for q in missing_local:
        urls = q.get("source_urls") or []
        url_audits = []
        for url in urls:
            audit = by_url.get(url)
            if audit is None:
                url_audits.append({
                    "source_url": url,
                    "prior_audit_found": False,
                    "browser_access_status": "not_in_phase_i_url_audit",
                    "original_http_bytes_saved_locally": False,
                    "source_file_integrity_verified": False,
                    "version_or_page_content_verified": False,
                    "limitation": "No corresponding URL audit record was found; no fresh network access was attempted in this reconciliation.",
                })
                continue
            url_audits.append({
                "source_url": url,
                "prior_audit_found": True,
                "browser_access_status": audit.get("browser_access_status"),
                "captured_at": audit.get("captured_at"),
                "capture_method": audit.get("capture_method"),
                "original_http_bytes_saved_locally": audit.get("original_http_bytes_saved_locally"),
                "source_file_integrity_verified": audit.get("source_file_integrity_verified"),
                "version_or_page_content_verified": audit.get("version_or_page_content_verified"),
                "shell_direct_http_probe": audit.get("shell_direct_http_probe"),
                "limitation": audit.get("limitation"),
            })
        readable_count = sum(r.get("browser_access_status") == "browser_page_readable" for r in url_audits)
        error_count = sum(r.get("browser_access_status") == "browser_tool_internal_error" for r in url_audits)
        reconciled.append({
            "question_id": q.get("question_id"),
            "species": q.get("species"),
            "source_id": q.get("source_id"),
            "reported_source_version_or_locator": q.get("source_version"),
            "source_urls": urls,
            "url_audits": url_audits,
            "url_count": len(urls),
            "readable_url_count": readable_count,
            "browser_error_url_count": error_count,
            "source_content_readable_in_prior_browser_audit": bool(url_audits) and readable_count == len(url_audits),
            "can_reproduce_original_content_from_saved_local_bytes": False,
            "source_file_integrity_verified": False,
            "source_version_pinned": False,
            "license_or_indexing_rights_verified": False,
            "phase_j_check_type": "reconciled_prior_phase_i_audit_not_refetched",
            "access_audit_date": "2026-10-14",
            "blocker_reason": (
                "Prior browser readability does not provide saved original bytes, a pinned complete version, or verified processing rights."
                if readable_count else
                "No URL was readable in the prior audit or no URL mapping was available; original content is not locally preserved."
            ),
        })
    write_jsonl(HERE / "source_url_accessibility_151_reconciled.jsonl", reconciled)
    readable_questions = sum(r["source_content_readable_in_prior_browser_audit"] for r in reconciled)
    has_any_readable = sum(r["readable_url_count"] > 0 for r in reconciled)
    no_readable = sum(r["readable_url_count"] == 0 for r in reconciled)
    all_urls_audited = sum(all(u.get("prior_audit_found") for u in r["url_audits"]) for r in reconciled)
    summary = {
        "phase_i_source_mapping_records": len(mapping_rows),
        "questions_without_local_source_original": len(reconciled),
        "question_records_with_all_mapped_urls_previously_readable": readable_questions,
        "question_records_with_at_least_one_previously_readable_url": has_any_readable,
        "question_records_with_no_previously_readable_url": no_readable,
        "question_records_with_all_urls_in_prior_audit": all_urls_audited,
        "prior_unique_urls_audited": len(url_rows),
        "unique_prior_readable_urls": sum(r.get("browser_access_status") == "browser_page_readable" for r in url_rows),
        "unique_prior_browser_error_urls": sum(r.get("browser_access_status") == "browser_tool_internal_error" for r in url_rows),
        "local_original_bytes_saved_for_these_question_records": 0,
        "fresh_network_requests_made": 0,
        "direct_http_block": "WinError 10013 in Phase I normal socket route; no policy or proxy bypass attempted",
        "interpretation": "Browser-readable means page visibility only. It does not establish a saved original, full reproducibility, version pinning, or license for indexing.",
    }
    write_json(HERE / "source_url_accessibility_151_summary.json", summary)
    return reconciled, summary


def audit_context_input_integrity():
    """Read-only verification of the 180x5 saved retrieval inputs and legacy mapping."""
    retrieval_path = ROOT / "reports/evaluation/fish_test_run_20261012_152244/retrieval_trace.jsonl"
    phase_g_path = ROOT / "reports/evaluation/fish_test_auto_annotation_phase_g_20261014_174009/context_auto_annotations_900.jsonl"
    phase_h_path = ROOT / "reports/evaluation/fish_test_phase_h/20261014_185653/context_annotations_recovered_900.jsonl"
    retrieval_rows = read_jsonl(retrieval_path)
    phase_g_rows = read_jsonl(phase_g_path)
    phase_h_rows = read_jsonl(phase_h_path)
    context_rows = []
    for row in retrieval_rows:
        for context in row.get("contexts") or []:
            context_rows.append({
                "question_id": row.get("question_id"),
                "chunk_id": context.get("chunk_id"),
                "rank": context.get("top5_rank"),
                "document_id": context.get("document_id"),
                "text": context.get("text") or "",
                "text_sha256_expected": context.get("text_sha256"),
            })
    source_keys = [(r["question_id"], r["chunk_id"], r["rank"]) for r in context_rows]
    source_key_set = set(source_keys)
    def row_key(row):
        return (row.get("question_id"), row.get("chunk_id"), row.get("rank"))
    phase_g_keys = [row_key(r) for r in phase_g_rows]
    phase_h_keys = [row_key(r) for r in phase_h_rows]
    bad_hashes = [r for r in context_rows if not r["text"] or hashlib.sha256(r["text"].encode("utf-8")).hexdigest() != r["text_sha256_expected"]]
    bad_g = [key for key in phase_g_keys if key not in source_key_set]
    bad_h = [key for key in phase_h_keys if key not in source_key_set]
    report = {
        "retrieval_source": str(retrieval_path.relative_to(ROOT)),
        "phase_g_annotation_source": str(phase_g_path.relative_to(ROOT)),
        "phase_h_annotation_source": str(phase_h_path.relative_to(ROOT)),
        "retrieval_question_records": len(retrieval_rows),
        "retrieval_unique_question_ids": len({r.get("question_id") for r in retrieval_rows}),
        "expected_contexts_per_question": 5,
        "retrieval_context_rows": len(context_rows),
        "empty_context_text_count": sum(not r["text"].strip() for r in context_rows),
        "text_sha256_mismatch_or_missing_count": len(bad_hashes),
        "phase_g_annotation_rows": len(phase_g_rows),
        "phase_g_identity_rows_not_found_in_retrieval": len(bad_g),
        "phase_g_duplicate_identity_rows": len(phase_g_keys) - len(set(phase_g_keys)),
        "phase_h_annotation_rows": len(phase_h_rows),
        "phase_h_identity_rows_not_found_in_retrieval": len(bad_h),
        "phase_h_duplicate_identity_rows": len(phase_h_keys) - len(set(phase_h_keys)),
        "phase_g_exact_identity_set_match": len(phase_g_keys) == len(source_keys) and set(phase_g_keys) == source_key_set,
        "phase_h_exact_identity_set_match": len(phase_h_keys) == len(source_keys) and set(phase_h_keys) == source_key_set,
        "all_contexts_nonempty_and_hash_valid": len(context_rows) > 0 and not bad_hashes,
        "note": "Context text is read from the saved retrieval trace; annotation rows match by question_id, chunk_id, and rank. Hash validity establishes trace integrity, not source truth or relevance.",
    }
    write_json(HERE / "context_input_integrity_audit.json", report)
    return report


def recheck_protected_baseline():
    manifest_path = ROOT / "reports/evaluation/fish_test_phase_a_20261012/protected_files_manifest.json"
    manifest = read_json(manifest_path)
    entries = manifest["historical_636_recheck"]["entries"]
    results = []
    for idx, row in enumerate(entries, 1):
        path = ROOT / row["path"]
        exists = path.is_file()
        actual = file_sha(path) if exists else None
        results.append({"path": row["path"], "exists": exists,
                        "expected_sha256": row["expected_sha256"], "actual_sha256": actual,
                        "status": "unchanged" if exists and actual == row["expected_sha256"] else "mismatch" if exists else "missing_or_unreadable"})
        if idx % 100 == 0:
            print(f"protected baseline recheck {idx}/{len(entries)}", flush=True)
    write_jsonl(HERE / "frozen_baseline_636_recheck.jsonl", results)
    sqlite_path = ROOT / "rag_store.sqlite3"
    sqlite_actual = file_sha(sqlite_path) if sqlite_path.is_file() else None
    sqlite_expected = "d7d06d4d2a57d0a57d05bcb6131ffb24aefb226c6bd36349dbc5118d33b11087"
    summary = {
        "checked_at": dt.datetime.now(ZoneInfo("Asia/Taipei")).isoformat(),
        "manifest_source": str(manifest_path.relative_to(ROOT)), "expected_entries": len(entries),
        "unchanged": sum(r["status"] == "unchanged" for r in results),
        "mismatched": sum(r["status"] == "mismatch" for r in results),
        "missing_or_unreadable": sum(r["status"] == "missing_or_unreadable" for r in results),
        "all_636_unchanged": len(entries) == 636 and all(r["status"] == "unchanged" for r in results),
        "sqlite_sha256_actual": sqlite_actual, "sqlite_sha256_expected": sqlite_expected,
        "sqlite_sha256_matches": sqlite_actual == sqlite_expected,
        "phase_i_outputs_modified": False, "original_720_generations_modified_or_reexecuted": False,
        "production_corpus_or_historical_e4_modified": False, "model_or_judge_weights_modified": False,
        "cleanup_delete_or_archive_operations": False,
    }
    write_json(HERE / "frozen_baseline_compatibility.json", summary)
    return summary


def main():
    verified, excluded, source_summary = build_source_verification()
    source_access_rows, source_access_summary = build_source_url_accessibility_151()
    context_input_audit = audit_context_input_integrity()
    unstarted50 = build_pilot50_not_started()
    baseline = recheck_protected_baseline()

    gate2 = read_json(HERE / "pilot_10_chunk_results.json")
    gate2_rows = read_jsonl(HERE / "pilot_10_chunk_results.jsonl")
    selected_spans = [span for row in gate2_rows if row.get("status") == "VALID" for span in row.get("exact_quotes", [])]
    schema_report = read_json(HERE / "single_chunk_annotator_tests.json")
    span_summary = {
        "offline_span_identity_tests_passed": schema_report.get("passed"),
        "offline_span_identity_tests_failed": schema_report.get("failed"),
        "gate2_real_chunks": len(gate2_rows), "gate2_valid_label_results": sum(r.get("status") == "VALID" for r in gate2_rows),
        "gate2_program_retrieved_quotes": len(selected_spans),
        "gate2_all_quotes_sliced_from_exact_target_chunk": all(s.get("quote_exact_in_target_chunk") for s in selected_spans),
        "gate2_identity_binding_100_percent": gate2.get("mapping_100_percent"),
        "gate2_accepted_cross_rank_quote_count": 0,
        "note": "A model can choose only program-generated IDs from one target chunk. Invalid/cross-chunk IDs are rejected; exact quote text is extracted from that chunk by offsets.",
    }
    write_json(HERE / "evidence_span_validation.json", span_summary)

    phase_i_call_archive = read_jsonl(PHASE_I / "pilot_v4_model_call_archive.jsonl")
    phase_i_errors = read_jsonl(PHASE_I / "pilot_v4_annotation_errors.jsonl")
    phase_i_prompts = read_jsonl(PHASE_I / "pilot_v4_prompt_archive.jsonl")
    v1_rows = read_jsonl(HERE / "pilot_10_chunk_results_v1.jsonl")
    v1_species_contradictions = sum(1 for r in v1_rows if r.get("status") == "VALID" and r.get("label") == "RELEVANT" and r.get("species_applicability") in {"mismatch", "uncertain"})
    root_report = f"""# Phase J 標註根因與單 Chunk 試點診斷

## Phase I 的跨 Rank 錯引

Phase I v4 的 2 筆失敗呼叫原始回覆含 `passages` 五元素陣列，每次模型呼叫的輸入是同一題的五個 Rank；程式再依陣列位置把內容綁到 Rank。兩次回覆的引文不在程式指定的 Rank 原文內，因此被逐字驗證拒絕。這確認了**多 Rank 同提示下的跨段落歸因／位置綁定風險**，但不是完整歷史因果證明：v4 完整 Prompt 封存為空（{len(phase_i_prompts)} 筆），無法重建失敗時的完整 Prompt。

檢視的 v4 呼叫是序列呼叫；每次建立新的 Ollama `/api/chat` 請求，未見共用對話歷史或非同步回覆的程式路徑。現有證據不支持請求競態或共享歷史是根因。程式按陣列位置映射是風險放大器，驗證器則確實拒絕了不在目標 Chunk 的引文。Phase I 記錄了 {len(phase_i_errors)} 筆失敗呼叫。

Phase G/H 的895筆第二輪缺失，Phase I 原始診斷記錄為批次回覆含錯置序號 ID、無效 JSON／重複結構並導致管線提前停止；finalizer 又將未執行的輪次誤標成 U。這和本輪看到的跨 Rank 引文歸因是不同層次的問題：前者是批次結構與狀態處理，後者是多段上下文下的內容歸屬。

另對原始 retrieval trace 做了唯讀完整性核對：{context_input_audit['retrieval_question_records']} 題、{context_input_audit['retrieval_context_rows']} 段；空段落 {context_input_audit['empty_context_text_count']}，文字 SHA-256 缺漏或不符 {context_input_audit['text_sha256_mismatch_or_missing_count']}。Phase G/H 的900列均以 question_id、chunk_id、rank 對回原始 trace（G={context_input_audit['phase_g_exact_identity_set_match']}；H={context_input_audit['phase_h_exact_identity_set_match']}）。這只確認保存的上下文與列身分一致，不代表內容來源真實性或標註正確性。

## Phase J 修正

新程式一次只把一道問題與一個 Chunk 的原文切片、來源中繼資料及程式產生的 Span ID 傳給 Judge。Judge 不輸出引文，也不輸出題目、Chunk 或 Rank ID。程式驗證 JSON Schema、只接受當次 Span ID，並由原文 offset 回填引文。兩輪使用無狀態獨立呼叫，不共用上一輪結果。

離線身分、偏移、錯誤輸出、跨 Chunk ID、物種守門及 Checkpoint 測試：{schema_report.get('passed', 0)}/{schema_report.get('passed', 0) + schema_report.get('failed', 0)} 通過。

## 真實 Gate 2

第一次設定（Prompt v1）有 {read_json(HERE / 'pilot_10_chunk_results_v1.json').get('valid_calls', 0)}/10 個有效結果；其中鰻魚一筆連續兩次在 JSON 的長理由欄位截斷，另有 {v1_species_contradictions} 筆輸出雖選 Relevant 卻把物種適用性標為 mismatch/uncertain，v1 的一致性檢查未攔截。第二版設定縮短理由、提高生成 token 上限並加入物種一致性硬檢查，得到 {gate2.get('valid_calls', 0)}/10 個有效結果。剩餘吳郭魚題對應的 Rank 2 實際文字屬烏魚，模型兩次都聲稱該 Chunk 是吳郭魚資料，程式的來源物種守門拒收。這是重複的實質魚種誤判，因此 Gate 2 未通過，依規則沒有啟動 50 段雙輪試點。

新版 10 筆的題目／Chunk／Rank 綁定率為 {100 if gate2.get('mapping_100_percent') else 0}%；所有被保留的引文都由指定 Chunk 原文切片，跨 Rank 引文接受數為 0。這只能證明程式來源定位可靠，不能證明標註判斷已達批次可靠性。
"""
    (HERE / "phase_j_root_cause_report.md").write_text(root_report, encoding="utf-8")

    direct = source_summary["direct_support_reproduced"]
    partial = source_summary["partial_support_remains"]
    source_report = f"""# Phase J 來源證據回查

重新處理 Phase I 的 29 筆來源對應列：{len(verified)} 筆是有效的既有來源關聯，{len(excluded)} 筆保留為排除紀錄。有效列中 {source_summary['rechecked_quote_verified']}/{len(verified)} 筆的引文可在原始來源或當前官方網頁文字摘錄中重現。

## 直接支持：{direct} 題

12 題為水產動物用藥規則的實足日數及多藥併用取最長停藥期題型（六種魚各兩題）。在官方法規頁面目前顯示修正日期民國114年1月8日的版本中，條文第7條第2項的原文可重現，且題目本身提供假設條件。這些題目只支持題目設定下的規則理解，不表示任何指定藥品可用、可併用或其實際停藥期已被確認。

## 部分支持：{partial} 題

16 題仍是部分支持。常見缺口是題目要求的完整管理或診斷結論超出單一引文；手冊引文只支持金目鱸的特定條件，不能移用到七星鱸。引用可重現不等於答案全貌獲證實，也不代表指定 Corpus v2 已收錄此證據。

## 網頁摘錄與原件限制

本輪透過已授權的網頁讀取工具重新讀取農業部法規頁，將供核對用的 Article 2、3、7 文字摘錄保存於 `official_law_text_capture_excerpt.txt`，另計算該摘錄檔雜湊。這是 `web_tool_rendered_text_excerpt`，不是原始 HTTP HTML 或伺服器 bytes；不宣稱已保存完整官方 HTML。五筆本機 PDF 引文以目前原檔 SHA-256 與逐頁抽取文字回查。

`FT-milkfish-Q12` 的原先來源連結被 Phase I 判定為錯誤關聯；本輪維持排除，不計入上述28題。

## 其餘無本機原件題目的 URL 對帳

已將 Phase I 的來源 URL 可讀性紀錄逐題連回 {source_access_summary['questions_without_local_source_original']} 筆無本機來源原件的題目。這是對 {source_access_summary['prior_unique_urls_audited']} 個既有 URL 紀錄的對帳，並非本輪重新抓取。{source_access_summary['question_records_with_at_least_one_previously_readable_url']} 題至少有一個 URL 曾在瀏覽器中可讀，{source_access_summary['question_records_with_no_previously_readable_url']} 題沒有可讀 URL；但這些題目本地原始 bytes 均為0，不能重現完整原件或固定版本。另有 {source_access_summary['unique_prior_browser_error_urls']} 個 URL 曾回報瀏覽器內部錯誤；一般 HTTP 探測受 WinError 10013 阻擋，未嘗試繞過。
"""
    (HERE / "source_evidence_recovery_report.md").write_text(source_report, encoding="utf-8")

    call_rows = read_jsonl(HERE / "single_chunk_model_calls.jsonl")
    prompt_checks = []
    for call in call_rows:
        prompt_text = call.get("prompt") or ""
        prompt_payload = {}
        try:
            prompt_payload = json.loads(prompt_text.split("\n", 1)[1])
        except Exception:
            pass
        snippets = prompt_payload.get("one_target_chunk_spans", [])
        prompt_checks.append({
            "request_id": call.get("request_id"),
            "provided_chunk_count_recorded": call.get("provided_chunk_count"),
            "prompt_has_one_chunk_metadata": isinstance(prompt_payload.get("target_chunk_metadata"), dict) and "contexts" not in prompt_payload,
            "prompt_span_count": len(snippets),
            "generator_answer_provided": call.get("generator_answer_provided"),
            "prior_pass_result_provided": call.get("prior_pass_result_provided"),
            "full_prompt_saved": bool(prompt_text),
            "raw_response_saved": call.get("raw_response_content") is not None,
            "model_digest_saved": bool(call.get("model_digest")),
            "parameters_and_timestamps_saved": bool(call.get("seed") is not None and call.get("call_started_at") and call.get("call_ended_at")),
        })
    write_json(HERE / "single_chunk_call_audit.json", {
        "total_attempts": len(call_rows),
        "all_attempts_bound_to_one_chunk": all(r.get("provided_chunk_count_recorded") == 1 and r.get("prompt_has_one_chunk_metadata") for r in prompt_checks),
        "all_attempts_excluded_generator_answers": all(r.get("generator_answer_provided") is False for r in prompt_checks),
        "all_attempts_excluded_prior_pass_outputs": all(r.get("prior_pass_result_provided") is False for r in prompt_checks),
        "full_prompt_saved_per_attempt": all(r.get("full_prompt_saved") for r in prompt_checks),
        "raw_response_saved_per_attempt": all(r.get("raw_response_saved") for r in prompt_checks),
        "model_digest_saved_per_attempt": all(r.get("model_digest_saved") for r in prompt_checks),
        "parameters_and_timestamps_saved_per_attempt": all(r.get("parameters_and_timestamps_saved") for r in prompt_checks),
        "per_attempt": prompt_checks,
        "note": "Every inference was a new sequential stateless Ollama request; no shared history or concurrent call mapping was used.",
    })

    compat = {
        "phase_j_output": str(HERE.relative_to(ROOT)), "offline_tests_passed": schema_report.get("passed"),
        "gate2_passed": gate2.get("passed"), "gate3_started": False,
        "historical_636_unchanged": baseline.get("all_636_unchanged"),
        "historical_636_unchanged_count": baseline.get("unchanged"),
        "rag_store_sha256_matches": baseline.get("sqlite_sha256_matches"),
        "phase_i_outputs_modified": False, "source_url_access_block_bypass_used": False,
        "original_720_generations_rerun_or_modified": False, "historical_e4_or_corpus_modified": False,
        "production_or_sqlite_modified": False, "human_gold_created": False,
        "context_precision_or_accuracy_newly_computed": False,
    }
    write_json(HERE / "compatibility.json", compat)

    final = f"""# Phase J 最終報告

## 結果

- **跨 Rank 風險**：Phase I v4 的模型一次收到五個 Rank 並按輸出位置綁回 Chunk；兩筆 raw reply 的引文與程式綁定 Rank 不符，驗證器拒收。完整歷史 Prompt 未保存，故不能再分辨所有提示細節。未發現非同步或共用對話歷史證據。
- **單 Chunk 離線檢查**：{schema_report.get('passed', 0)}/{schema_report.get('passed', 0) + schema_report.get('failed', 0)} 通過。模型只能選程式建立的片段 ID，引文由原文 offset 取回。
- **真實 10 Chunk Gate 2**：新版 {gate2.get('valid_calls', 0)}/10 結構與資料檢查有效，題目／Chunk／Rank 綁定為 {100 if gate2.get('mapping_100_percent') else 0}%，選取引文皆精確來自目標 Chunk，沒有接受跨 Rank 引文；但有一筆吳郭魚題的烏魚 Chunk 被模型錯稱為吳郭魚內容，錯誤經硬性守門攔截並重現兩次，因此 Gate 2 **未通過**。Prompt v1 曾有 {v1_species_contradictions} 筆 Relevant 與物種 mismatch/uncertain 自相矛盾輸出被初版驗證器放行；Prompt v2 已加入拒收規則，這些沒有進入本輪有效判讀。
- **50 段雙輪試點**：0/50 完成；Gate 3 未啟動。`pilot_50_chunk_results.jsonl` 的50列均標示 `NOT_STARTED_GATE_2_FAILED`，不是模型判讀結果。
- **原始 Context 完整性**：{context_input_audit['retrieval_context_rows']} 段均非空且文字雜湊相符；Phase G/H 的900筆列身分都能對回 retrieval trace，沒有重複或錯配。這不會把既有不完整標註變成有效判讀。
- **來源回查**：28 個有效來源關聯中 {source_summary['rechecked_quote_verified']} 筆原文引文可重現；其中 {direct} 題直接支持，{partial} 題維持部分支持。錯誤的 `FT-milkfish-Q12` 映射仍排除。23 筆網頁引文以網頁工具呈現文字摘錄比對，不冒充原始 HTML；本機 PDF 則重算 checksum 並逐頁搜尋。
- **其餘來源 URL**：{source_access_summary['questions_without_local_source_original']} 題已與 Phase I 的 {source_access_summary['prior_unique_urls_audited']} 個 URL 可讀性紀錄逐題對帳；{source_access_summary['question_records_with_at_least_one_previously_readable_url']} 題至少有一個曾可在瀏覽器閱讀的頁面，{source_access_summary['question_records_with_no_previously_readable_url']} 題沒有可讀 URL。這些題目都沒有保存本機原始 bytes，故仍無法核實完整內容與固定版本；本輪沒有重試網路存取。
- **新指標**：沒有新增有效 Context Precision@5、Logical Accuracy 或 Arithmetic Accuracy。缺少50段有效雙輪判讀，且本輪不是答案／邏輯評分試點。
- **擴大條件**：目前不符合擴大至900段的條件。單 Chunk 的程式化身分與引文抽取可運作，但模型仍有重複魚種誤判，且另一版曾有兩次 JSON 截斷。
- **Frozen Baseline**：{baseline.get('unchanged')}/{baseline.get('expected_entries')} 筆相同，SQLite SHA-256 {baseline.get('sqlite_sha256_actual')}（預期 {baseline.get('sqlite_sha256_expected')}）。未重跑四模型，未改寫 Phase E/G/H/I、Corpus、E4、Production 或歷史索引。

## 下一個必要技術條件

在任何50段或900段批次前，需修復並重驗 Mistral NeMo 的魚種語意誤判（優先使用明確來源物種特徵／規則攔截，或改用能穩定遵守來源身分的人工審核流程），並確保長段落回覆在結構化輸出下不截斷。單靠提高生成長度不能消除判讀錯誤。完成新的10 Chunk Gate 2 並達到10/10有效、無錯誤物種判斷後，再評估50段雙輪試點。

全部機器標註均為 AI-assisted，**NOT_HUMAN_GOLD**；未形成任何正式模型排名或 Winner。
"""
    (HERE / "phase_j_final_report.md").write_text(final, encoding="utf-8")
    write_json(HERE / "phase_j_execution_summary.json", {
        "gate1_offline": schema_report,
        "gate2_live": gate2,
        "gate3_started": False,
        "pilot50_planned_rows_not_run": len(unstarted50),
        "source_verification": source_summary,
        "source_url_accessibility_reconciliation": source_access_summary,
        "context_input_integrity_audit": context_input_audit,
        "baseline": baseline,
    })

    outputs = [p for p in HERE.iterdir() if p.is_file() and p.name not in {"artifact_inventory.json"}]
    inventory = [{"path": str(p.relative_to(ROOT)), "bytes": p.stat().st_size, "sha256": file_sha(p)} for p in sorted(outputs)]
    write_json(HERE / "artifact_inventory.json", inventory)
    print(json.dumps({"source_verification": source_summary, "source_url_accessibility": source_access_summary, "baseline": baseline, "gate2_passed": gate2.get("passed"),
                      "gate2_valid": gate2.get("valid_calls"), "gate3_started": False,
                      "output_file_count": len(inventory)}, ensure_ascii=True), flush=True)


if __name__ == "__main__":
    main()
