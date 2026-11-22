"""Independent Streamlit app for human annotation and review operations.

This tool only writes development annotations and evaluation reports. It has no
production retriever integration and never writes the frozen corpora.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.evaluation.annotation import (  # noqa: E402
    atomic_write_jsonl,
    make_evidence_snapshot,
    records_for_queue,
    sha256_file,
    utc_now,
    validate_annotation_transition,
)
from src.evaluation.corpus import read_jsonl  # noqa: E402
from src.evaluation.development import refresh_reports  # noqa: E402
from src.evaluation.gold_lint import lint_question  # noqa: E402
from src.evaluation.question_bank_import import (  # noqa: E402
    build_first_batch_priority_queue,
    make_draft_from_candidate,
    mark_unsupported,
    refresh_mapping_report,
)


QUESTIONS_PATH = ROOT / "data" / "gold" / "development" / "questions.jsonl"
CORPUS_PATH = ROOT / "data" / "evaluation" / "corpus_v1.jsonl"
CANDIDATES_PATH = ROOT / "reports" / "evaluation" / "question_candidates.jsonl"
QUESTION_BANK_PATH = ROOT / "data" / "gold" / "question_bank_candidates.jsonl"
MIN_SMOKE = 24
MIN_BASELINE = 48
CATEGORIES = ["fact", "water_quality", "disease", "climate", "sop", "multi_document", "regulation", "drug", "withdrawal_period", "calculation", "insufficient_information", "conflicting_sources", "ambiguous", "safety_boundary"]
SPECIES = ["吳郭魚", "虱目魚", "石斑魚", "鱸魚", "烏魚", "鰻魚"]
REVIEW_CHECKS = {
    "question_supported": "題目受到 evidence 支持",
    "gold_answer_supported": "Gold answer 受到 evidence 支持",
    "required_chunks_reasonable": "required chunks 合理且必要",
    "acceptable_chunks_reasonable": "acceptable chunks 合理",
    "species_within_evidence": "species 沒有超出 evidence",
    "category_reasonable": "category 合理",
    "difficulty_reasonable": "difficulty 合理",
}


@st.cache_data(show_spinner=False)
def load_corpus() -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    rows = read_jsonl(CORPUS_PATH)
    return rows, {row["chunk_id"]: row for row in rows if row.get("chunk_id")}


def format_chunk(row: dict[str, Any]) -> str:
    return f"{row.get('chunk_id')} | p.{row.get('page_start')} | {row.get('chunk_type')} | {str(row.get('text') or '')[:90]}"


def eligible_corpus(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in rows if row.get("benchmark_eligible") is True and row.get("risk_level") == "normal" and row.get("retrieval_role") == "retrieval" and row.get("duplicate_status") not in {"exact_duplicate", "duplicate_source"}]


def queue_for_status(questions: list[dict[str, Any]], queue: str) -> list[dict[str, Any]]:
    return records_for_queue(questions, queue)


def choices(rows: list[dict[str, Any]], roles: set[str]) -> tuple[list[str], dict[str, str]]:
    selected = [row for row in rows if row.get("retrieval_role") in roles and row.get("duplicate_status") not in {"exact_duplicate", "duplicate_source"}]
    selected.sort(key=lambda row: (row.get("page_start") or 0, row.get("section") or "", row.get("chunk_id") or ""))
    ids = [str(row["chunk_id"]) for row in selected]
    return ids, {str(row["chunk_id"]): format_chunk(row) for row in selected}


def main() -> None:
    st.set_page_config(page_title="Human Gold Annotation Workbench", layout="wide")
    st.title("Development Gold Annotation Workbench")
    st.caption("人工標註與審核工具。候選不是 Gold evidence；工具不連接 production RAG，也不修改 frozen corpus。")

    corpus_rows, corpus_by_id = load_corpus()
    candidates = read_jsonl(CANDIDATES_PATH)
    question_bank = read_jsonl(QUESTION_BANK_PATH)
    questions = read_jsonl(QUESTIONS_PATH)
    eligible = eligible_corpus(corpus_rows)
    evidence_browse_rows = [row for row in corpus_rows if row.get("benchmark_eligible") is True and row.get("risk_level") == "normal" and row.get("retrieval_role") in {"retrieval", "context_only"} and row.get("duplicate_status") not in {"exact_duplicate", "duplicate_source"}]
    eligible_ids = {row["chunk_id"] for row in eligible}
    candidate_by_chunk = {row.get("chunk_id"): row for row in candidates if row.get("chunk_id") in eligible_ids}

    bank_by_id = {str(row.get("candidate_id")): row for row in question_bank}
    linked_bank_ids = {str(row.get("question_bank_candidate_id")) for row in questions if row.get("question_bank_candidate_id")}
    priority_rows, _priority_fulfillment = build_first_batch_priority_queue(question_bank)
    priority_ids = {str(row.get("candidate_id")) for row in priority_rows}
    with st.expander(f"Question Bank Candidates · {len(question_bank)} 筆候選", expanded=False):
        st.caption("Excel 題目與答案只是候選。匯入不會建立 Gold；corpus chunk 僅為人工搜尋建議。高風險題不進第一批 24 題。")
        if question_bank:
            qf1, qf2, qf3, qf4 = st.columns(4)
            bank_queue = qf1.selectbox("題庫範圍", ["24 題優先 queue", "全部候選"], key="qb-queue")
            bank_species = qf2.selectbox("魚種候選", ["All", *SPECIES], key="qb-species")
            bank_category_values = sorted({str(row.get("category_candidate") or "unknown") for row in question_bank})
            bank_category = qf3.selectbox("候選 category", ["All", *bank_category_values], key="qb-category")
            bank_status = qf4.selectbox("匯入狀態", ["All", "candidate", "needs_review", "unsupported"], key="qb-status")
            visible_bank = [
                row for row in question_bank
                if (bank_queue != "24 題優先 queue" or str(row.get("candidate_id")) in priority_ids)
                and (bank_species == "All" or row.get("species") == bank_species)
                and (bank_category == "All" or (row.get("category_candidate") or "unknown") == bank_category)
                and (bank_status == "All" or row.get("import_status") == bank_status)
            ]
            if visible_bank:
                bank_labels = {
                    str(row["candidate_id"]): f"{row.get('species') or '魚種未標'} · {row.get('category_candidate') or 'category未分類'} · row {row.get('source_row')} · {row.get('import_status')}"
                    for row in visible_bank
                }
                selected_bank_id = st.selectbox("Question Bank Candidate", [str(row["candidate_id"]) for row in visible_bank], format_func=lambda key: bank_labels[key], key="qb-candidate")
                bank_candidate = bank_by_id[selected_bank_id]
                already_linked = selected_bank_id in linked_bank_ids
                st.markdown("**Question candidate**")
                st.write(bank_candidate.get("question_candidate"))
                st.markdown("**Excel candidate answer · reference only**")
                st.info(bank_candidate.get("answer_candidate") or "題庫未提供答案候選")
                st.write({
                    "species_candidate_only": bank_candidate.get("species"),
                    "category_candidate": bank_candidate.get("category_candidate"),
                    "difficulty_candidate": bank_candidate.get("difficulty_candidate"),
                    "risk_level": bank_candidate.get("risk_level"),
                    "annotation_eligible": bank_candidate.get("annotation_eligible"),
                    "first_batch_eligible": bank_candidate.get("first_batch_eligible"),
                    "source_workbook": bank_candidate.get("source_workbook"),
                    "source_sheet": bank_candidate.get("source_sheet"),
                    "source_row": bank_candidate.get("source_row"),
                    "import_status": bank_candidate.get("import_status"),
                    "corpus_source_gate": bank_candidate.get("corpus_source_gate"),
                })
                st.caption("來源 gate 只比對既有 Evaluation Corpus metadata；本工作台沒有驗證來源網址或法律效力。")
                suggestions = bank_candidate.get("evidence_search_candidates") or []
                st.markdown(f"**Corpus search suggestions · {len(suggestions)} · 尚未人工確認，不是 evidence**")
                for suggestion in suggestions[:8]:
                    suggestion_row = corpus_by_id.get(str(suggestion.get("chunk_id")), {})
                    st.caption(f"建議 {suggestion.get('chunk_id')} · document={suggestion.get('document_id')} · page={suggestion.get('page')} · overlap={suggestion.get('overlap_score')}")
                    st.text(str(suggestion_row.get("text") or "")[:700])
                if not suggestions:
                    st.caption("未找到詞彙重疊的 corpus 候選；可在建立草稿後使用全 corpus 手動搜尋。")
                draft_col, unsupported_col = st.columns([1, 2])
                if already_linked:
                    draft_col.info("此候選已連結到 development 草稿。")
                elif draft_col.button("Use as draft question", key=f"qb-use-{selected_bank_id}", disabled=selected_bank_id not in priority_ids or bank_candidate.get("import_status") == "unsupported"):
                    if selected_bank_id not in priority_ids or bank_candidate.get("import_status") == "unsupported":
                        st.error("此題不在第一批 24 題人工標註 queue，或已被人工標記 unsupported。")
                    else:
                        draft = make_draft_from_candidate(bank_candidate, corpus_sha256=sha256_file(CORPUS_PATH))
                        atomic_write_jsonl(QUESTIONS_PATH, [*questions, draft])
                        refresh_reports(ROOT, [*questions, draft])
                        refresh_mapping_report(ROOT)
                        st.success("已新增 draft question；Gold answer 與 Gold evidence 保持空白。")
                        st.rerun()
                unsupported_reason = unsupported_col.text_input("人工判定 unsupported 的原因", key=f"qb-unsupported-reason-{selected_bank_id}")
                if unsupported_col.button("Mark unsupported candidate", key=f"qb-unsupported-{selected_bank_id}", disabled=not unsupported_reason.strip() or bank_candidate.get("import_status") == "unsupported"):
                    updated_candidate = mark_unsupported(bank_candidate, unsupported_reason)
                    question_bank = [updated_candidate if str(row.get("candidate_id")) == selected_bank_id else row for row in question_bank]
                    atomic_write_jsonl(QUESTION_BANK_PATH, question_bank)
                    refresh_mapping_report(ROOT)
                    refresh_reports(ROOT, questions)
                    st.success("已記錄人工 unsupported 判斷。")
                    st.rerun()
            else:
                st.info("目前篩選條件沒有候選題。")
        else:
            st.info("尚未匯入題庫候選；執行 scripts/import_question_bank.py 後會出現在這裡。")

    if not questions:
        st.warning("尚無 development work items。先執行 scripts/prepare_development_annotation.py。")
        return

    counts = {status: sum(row.get("annotation_status", "draft") == status for row in questions) for status in ("draft", "annotated", "reviewed", "blocked")}
    report_bundle = refresh_reports(ROOT, questions)
    progress = report_bundle["progress"]
    sprint = report_bundle["sprint"]
    readiness = report_bundle["readiness"]
    counts["reviewed"] = sprint["phase_9a_readiness"]["reviewed_gold_count"]
    dashboard = st.container(border=True)
    with dashboard:
        st.subheader("Progress dashboard")
        m = st.columns(5)
        for col, label, value in zip(m, ("Target questions", "Draft", "Annotated", "Reviewed", "Blocked"), (48, counts["draft"], counts["annotated"], counts["reviewed"], counts["blocked"])):
            col.metric(label, value)
        readiness_cols = st.columns(2)
        readiness_cols[0].metric("Phase 9 smoke-test readiness", "Ready" if readiness["smoke_test_ready"] else f"Not ready ({counts['reviewed']}/{MIN_SMOKE})")
        readiness_cols[1].metric("Phase 9 baseline readiness", "Ready" if readiness["baseline_ready"] else f"Not ready ({counts['reviewed']}/{MIN_BASELINE})")
        st.caption("Readiness is informational only; it never starts a benchmark.")
        c1, c2, c3 = st.columns(3)
        c1.write({"Category coverage": progress.get("by_category", {})})
        c2.write({"Species coverage": progress.get("by_species", {})})
        c3.write({"Answerable / Abstention": {"answerable": progress.get("answerable"), "abstention": progress.get("abstention")}})
        c1.write({"Single / Multi document": {"single": progress.get("single_document"), "multi": progress.get("multi_document")}})
        c2.write({"Evidence verified": progress.get("evidence_verified", 0)})
        c3.write({"Coverage gaps": len(progress.get("coverage_gaps", [])) + progress.get("species_category_gap_count", 0)})

    with st.expander("Annotation sprint report"):
        candidate_metrics = sprint["candidate_metrics"]
        req_counts = sprint["required_evidence"]["all_development"]
        acceptable_counts = sprint["acceptable_evidence"]["all_development"]
        sprint_cols = st.columns(5)
        sprint_cols[0].metric("Candidate reviewed", candidate_metrics["candidate_reviewed_count"])
        sprint_cols[1].metric("Candidate → reviewed Gold", f"{candidate_metrics['candidate_to_reviewed_gold_conversion_rate']:.1%}")
        sprint_cols[2].metric("Unsupported candidates", candidate_metrics["unsupported_candidate_count"])
        sprint_cols[3].metric("Required evidence refs", req_counts["references"])
        sprint_cols[4].metric("Acceptable evidence refs", acceptable_counts["references"])
        st.write({
            "unsupported_reason_distribution": candidate_metrics["unsupported_reason_distribution"],
            "category_distribution": sprint["category_distribution"],
            "species_distribution": sprint["species_distribution"],
            "single_multi_document_distribution": sprint["document_scope_distribution"],
            "annotator_reviewer_completeness": sprint["annotator_reviewer_completeness"],
            "question_verified": sprint["question_verified"],
            "evidence_verified": sprint["evidence_verified"],
            "Phase 9A readiness": sprint["phase_9a_readiness"],
        })

    queue_name = st.sidebar.selectbox("Queue", ["annotation_queue", "review_queue", "completed_queue"], format_func=lambda x: {"annotation_queue": "Annotation queue · draft", "review_queue": "Review queue · annotated", "completed_queue": "Completed queue · reviewed"}[x])
    subset = queue_for_status(questions, queue_name)
    filters = st.sidebar.container()
    with filters:
        st.subheader("Filters")
        cat_values = sorted({str(row.get("target_category") or row.get("category") or "") for row in subset if row.get("target_category") or row.get("category")})
        category_filter = st.selectbox("Category", ["All", *cat_values])
        species_filter = st.selectbox("Species", ["All", "未確認", *SPECIES])
        difficulty_values = sorted({str(row.get("difficulty")) for row in subset if row.get("difficulty")})
        difficulty_filter = st.selectbox("Difficulty", ["All", *difficulty_values])
        document_values = sorted({str((corpus_by_id.get((row.get("candidate_chunk_ids") or [None])[0]) or {}).get("document_id") or "unknown") for row in subset})
        document_filter = st.selectbox("Document", ["All", *document_values])
        status_filter = st.selectbox("Status", ["All", *sorted({str(row.get("annotation_status") or "draft") for row in subset})])
    filtered = []
    for row in subset:
        seed_row = corpus_by_id.get((row.get("candidate_chunk_ids") or [None])[0], {})
        if category_filter != "All" and (row.get("target_category") or row.get("category")) != category_filter: continue
        if species_filter == "未確認" and row.get("species"): continue
        if species_filter not in {"All", "未確認"} and row.get("species") != species_filter: continue
        if difficulty_filter != "All" and row.get("difficulty") != difficulty_filter: continue
        if document_filter != "All" and seed_row.get("document_id") != document_filter: continue
        if status_filter != "All" and row.get("annotation_status") != status_filter: continue
        filtered.append(row)
    if not filtered:
        st.info("此 queue/filter 組合目前沒有項目。")
        return
    label_map = {row["question_id"]: f"{row['question_id']} · {row.get('target_category')} · {row.get('annotation_status')}" for row in filtered}
    question_id = st.selectbox("Question", [row["question_id"] for row in filtered], format_func=lambda key: label_map[key])
    original = next(row for row in questions if row["question_id"] == question_id)
    record = dict(original)
    seed = candidate_by_chunk.get((record.get("candidate_chunk_ids") or [None])[0])
    seed_row = corpus_by_id.get((record.get("candidate_chunk_ids") or [None])[0])
    bank_candidate = bank_by_id.get(str(record.get("question_bank_candidate_id") or ""))
    if seed_row and seed_row.get("chunk_id") not in eligible_ids:
        st.error("Candidate 不符合 frozen development filter，禁止標註。")
        return

    seed_row = seed_row or {}
    related = [row for row in evidence_browse_rows if seed_row.get("document_id") and row.get("document_id") == seed_row.get("document_id")]
    same_page = [row for row in related if seed_row.get("page_start") is not None and row.get("page_start") == seed_row.get("page_start")]
    same_section = [row for row in related if seed_row.get("section") and row.get("section") == seed_row.get("section")]
    bank_suggestions = (bank_candidate or {}).get("evidence_search_candidates") or []
    suggestion_rows = [corpus_by_id[str(item.get("chunk_id"))] for item in bank_suggestions if str(item.get("chunk_id")) in corpus_by_id]
    scope_options = (["Question Bank suggestions", "同頁", "同 section", "同 document", "所有 eligible documents"] if bank_candidate else ["同頁", "同 section", "同 document", "所有 eligible documents"])
    scope_index = 0 if bank_candidate or seed_row else len(scope_options) - 1
    scope = st.radio("Evidence browser scope", scope_options, index=scope_index, horizontal=True)
    if scope == "Question Bank suggestions":
        visible = suggestion_rows
    elif scope == "同頁":
        visible = same_page
    elif scope == "同 section":
        visible = same_section
    elif scope == "同 document":
        visible = related
    else:
        visible = evidence_browse_rows
    search_text = st.text_input("搜尋目前範圍的 chunk 文字 / section / ID")
    if search_text.strip():
        needle = search_text.strip().casefold()
        visible = [row for row in visible if needle in " ".join(str(row.get(key) or "") for key in ("text", "section", "chunk_id", "topic")).casefold()]

    left, right = st.columns([1, 1])
    with left:
        st.subheader("Candidate 與來源 provenance")
        if bank_candidate:
            st.write({"question_bank_candidate_id": bank_candidate.get("candidate_id"), "source_workbook": bank_candidate.get("source_workbook"), "source_sheet": bank_candidate.get("source_sheet"), "source_row": bank_candidate.get("source_row"), "workbook_species_hint_only": bank_candidate.get("species"), "species_basis": bank_candidate.get("species_basis"), "category_candidate": bank_candidate.get("category_candidate"), "difficulty_candidate": bank_candidate.get("difficulty_candidate"), "risk_level": bank_candidate.get("risk_level"), "source_url_candidate": bank_candidate.get("original_metadata", {}).get("來源網址")})
            st.markdown("**Excel candidate answer · reference only**")
            st.info(bank_candidate.get("answer_candidate") or "題庫未提供答案候選")
            st.caption("Human Gold Answer 必須獨立根據人工選定的 evidence 撰寫；Excel candidate answer 不會自動帶入。")
        else:
            st.write({"candidate_id": seed.get("candidate_id") if seed else None, "document_title": seed_row.get("source_title"), "document_id": seed_row.get("document_id"), "page": seed_row.get("page_start"), "candidate_species_hint": record.get("candidate_species"), "species_basis": record.get("candidate_species_basis"), "topic": seed_row.get("topic"), "target_category": record.get("target_category"), "file_checksum": seed_row.get("source_checksum"), "source_url": seed_row.get("source_url"), "parser": seed_row.get("parser_name"), "parser_version": seed_row.get("parser_version"), "extraction_method": seed_row.get("extraction_method"), "source_verified": seed_row.get("source_verified"), "legal_status": seed_row.get("legal_status")})
        if seed_row.get("text"):
            st.text_area("Candidate child chunk（非 Gold）", str(seed_row.get("text") or ""), height=220, disabled=True)
        parent_id = seed_row.get("parent_chunk_id")
        if parent_id and parent_id in corpus_by_id:
            with st.expander("Parent context（context-only）"):
                st.write(parent_id)
                st.text_area("Parent text", str(corpus_by_id[parent_id].get("text") or ""), height=180, disabled=True, key=f"parent-{question_id}")
        with st.expander("可選 chunks"):
            for row in visible:
                st.markdown(f"**{format_chunk(row)}**")
                st.caption(f"role={row.get('retrieval_role')} · section={row.get('section')} · source spans={row.get('source_span_ids')}")
                st.text(row.get("text") or "")

    if queue_name == "annotation_queue":
        with right:
            st.subheader("人工標註")
            required_ids, required_labels = choices(visible, {"retrieval"})
            acceptable_ids, acceptable_labels = choices(visible, {"retrieval", "context_only"})
            with st.form(f"annotation-{question_id}"):
                question = st.text_area("question", record.get("question") or "", height=90)
                gold_answer = st.text_area("Human Gold Answer（必須根據人工選定 evidence 撰寫）", record.get("gold_answer") or "", height=120)
                category = st.selectbox("category（人工確認）", CATEGORIES, index=CATEGORIES.index(record.get("category")) if record.get("category") in CATEGORIES else 0)
                category_verified = st.checkbox("我已確認 category", value=bool(record.get("category_verified")))
                species_opts = ["未確認", *SPECIES]
                species_value = record.get("species") or "未確認"
                species = st.selectbox("species（不得只依候選自動確認）", species_opts, index=species_opts.index(species_value) if species_value in species_opts else 0)
                species_verified = st.checkbox("我已從選定 evidence 確認 species", value=bool(record.get("species_verified")))
                difficulty_opts = ["未標註", "easy", "medium", "hard", "unknown"]
                difficulty_value = record.get("difficulty") or "未標註"
                difficulty = st.selectbox("difficulty", difficulty_opts, index=difficulty_opts.index(difficulty_value) if difficulty_value in difficulty_opts else 0)
                difficulty_verified = st.checkbox("我已確認 difficulty", value=bool(record.get("difficulty_verified")))
                answerable_opts = ["未標註", "true", "false"]
                answerable_value = "未標註" if record.get("answerable") is None else str(record.get("answerable")).lower()
                abstention_value = "未標註" if record.get("expected_abstention") is None else str(record.get("expected_abstention")).lower()
                answerable = st.selectbox("answerable", answerable_opts, index=answerable_opts.index(answerable_value))
                expected_abstention = st.selectbox("expected_abstention", answerable_opts, index=answerable_opts.index(abstention_value))
                required = st.multiselect("required_chunks（人工選取；retrieval role）", required_ids, default=[x for x in record.get("required_chunks", []) if x in required_ids], format_func=lambda value: required_labels[value])
                acceptable = st.multiselect("acceptable_chunks（人工選取；可含 parent context）", acceptable_ids, default=[x for x in record.get("acceptable_chunks", []) if x in acceptable_ids], format_func=lambda value: acceptable_labels[value])
                conflict_ids, conflict_labels = choices(visible, {"retrieval", "context_only"})
                conflicts = st.multiselect("conflicting_chunks（人工選取）", conflict_ids, default=[x for x in record.get("conflicting_chunks", []) if x in conflict_ids], format_func=lambda value: conflict_labels[value])
                claims_text = st.text_area("supporting_claims JSON（每項 claim 明列 chunk_ids）", json.dumps(record.get("supporting_claims", []), ensure_ascii=False, indent=2), height=100)
                notes = st.text_area("notes", record.get("notes") or "")
                annotator = st.text_input("annotator", record.get("annotator") or "")
                target_status = st.selectbox("狀態", ["draft", "annotated", "blocked"], index=["draft", "annotated", "blocked"].index(record.get("annotation_status", "draft")) if record.get("annotation_status", "draft") in {"draft", "annotated", "blocked"} else 0)
                submitted = st.form_submit_button("Save annotation")
            if submitted:
                try:
                    claims = json.loads(claims_text or "[]")
                    if not isinstance(claims, list): raise ValueError("supporting_claims 必須是 JSON array")
                    selected_ids = list(dict.fromkeys([*required, *acceptable]))
                    selected_rows = [corpus_by_id[key] for key in selected_ids]
                    record.update({"question": question.strip() or None, "gold_answer": gold_answer.strip() or None, "answerable": None if answerable == "未標註" else answerable == "true", "expected_abstention": None if expected_abstention == "未標註" else expected_abstention == "true", "category": category, "category_verified": category_verified, "species": None if species == "未確認" else species, "species_verified": species != "未確認" and species_verified, "difficulty": None if difficulty == "未標註" else difficulty, "difficulty_verified": difficulty != "未標註" and difficulty_verified, "required_chunks": list(required), "acceptable_chunks": list(acceptable), "conflicting_chunks": list(conflicts), "gold_chunks": selected_ids, "gold_documents": sorted({row["document_id"] for row in selected_rows}), "gold_pages": [{"document_id": doc, "page": page} for doc, page in sorted({(row["document_id"], row["page_start"]) for row in selected_rows})], "gold_evidence_snapshot": make_evidence_snapshot(corpus_by_id, selected_ids), "supporting_claims": claims, "notes": notes or None, "annotator": annotator.strip() or None, "annotation_status": target_status, "reviewer": None, "review_notes": None, "question_verified": False, "evidence_verified": False})
                    corpus_sha = sha256_file(CORPUS_PATH)
                    if corpus_sha != record.get("evaluation_corpus_sha256"):
                        st.error("Evaluation Corpus checksum 已變更；拒絕儲存以保護標註 provenance。")
                        return
                    errors = validate_annotation_transition(record, target_status, annotator=record.get("annotator"), reviewer=None, question_verified=False, evidence_verified=False)
                    lint_errors = lint_question(record, corpus_by_id, current_corpus_version="evaluation-corpus-v1", current_corpus_sha256=corpus_sha)
                    if errors or (target_status == "annotated" and lint_errors):
                        st.error("無法套用此狀態：" + "；".join(errors + [item["message"] for item in lint_errors]))
                    else:
                        atomic_write_jsonl(QUESTIONS_PATH, [record if row["question_id"] == question_id else row for row in questions])
                        updated = read_jsonl(QUESTIONS_PATH)
                        refresh_reports(ROOT, updated)
                        refresh_mapping_report(ROOT)
                        st.success("已保存人工標註。")
                        st.rerun()
                except (ValueError, json.JSONDecodeError) as exc:
                    st.error(f"輸入格式錯誤：{exc}")
    elif queue_name == "review_queue":
        with right:
            st.subheader("Second-person review")
            st.write({key: record.get(key) for key in ("question", "gold_answer", "category", "species", "difficulty", "answerable", "expected_abstention", "required_chunks", "acceptable_chunks", "gold_evidence_snapshot", "annotator")})
            reviewer = st.text_input("reviewer（必須不同於 annotator）", key=f"reviewer-{question_id}")
            confirmations: dict[str, bool] = {}
            for name, label in REVIEW_CHECKS.items():
                confirmations[name] = st.checkbox(label, key=f"{question_id}-{name}")
            review_notes = st.text_area("review_notes（記錄覆核判斷）", key=f"review-notes-{question_id}")
            question_verified = st.checkbox("question_verified", key=f"{question_id}-qv")
            evidence_verified = st.checkbox("evidence_verified（已比對 snapshot checksum）", key=f"{question_id}-ev")
            if st.button("Save review as reviewed", key=f"review-{question_id}"):
                corpus_sha = sha256_file(CORPUS_PATH)
                candidate = dict(record)
                candidate.update({"reviewer": reviewer.strip() or None, "review_notes": review_notes.strip() or None, "reviewer_confirmations": confirmations, "question_verified": question_verified, "evidence_verified": evidence_verified, "reviewed_at": utc_now()})
                errors = validate_annotation_transition(candidate, "reviewed", annotator=candidate.get("annotator"), reviewer=candidate.get("reviewer"), question_verified=question_verified, evidence_verified=evidence_verified, reviewer_confirmations=confirmations, review_notes=review_notes)
                candidate["annotation_status"] = "reviewed"
                lint_errors = lint_question(candidate, corpus_by_id, current_corpus_version="evaluation-corpus-v1", current_corpus_sha256=corpus_sha)
                if errors or lint_errors:
                    st.error("無法完成覆核：" + "；".join(errors + [item["message"] for item in lint_errors]))
                else:
                    atomic_write_jsonl(QUESTIONS_PATH, [candidate if row["question_id"] == question_id else row for row in questions])
                    updated = read_jsonl(QUESTIONS_PATH)
                    refresh_reports(ROOT, updated)
                    refresh_mapping_report(ROOT)
                    st.success("已記錄第二人覆核。")
                    st.rerun()
    else:
        with right:
            st.subheader("Completed review · read only")
            st.json(record)


if __name__ == "__main__":
    main()
