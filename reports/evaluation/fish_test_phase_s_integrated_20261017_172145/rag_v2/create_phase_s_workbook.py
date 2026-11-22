from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.chart import BarChart, Reference
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.table import Table, TableStyleInfo

RUN = Path(__file__).resolve().parents[1]
ROOT = Path(__file__).resolve().parents[4]
OUTPUT = RUN / "fish_test_integrated_rag_evaluation_v2.xlsx"
QUESTION_FILE = ROOT / "reports/evaluation/fish_test_run_20261012_152244/fish_test_questions_normalized.jsonl"
OLD_METRICS = ROOT / "reports/evaluation/fish_test_run_20261012_152244/model_comparison_summary.json"


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def read_jsonl(path: Path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]


def safe_json(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")) if value is not None else "N/A"


def add_sheet(wb, title, headers, rows):
    ws = wb.create_sheet(title)
    ws.append(headers)
    for row in rows:
        ws.append([safe_json(v) if isinstance(v, (dict, list, tuple)) else v for v in row])
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="174A63")
        cell.alignment = Alignment(vertical="center", wrap_text=True)
    ws.row_dimensions[1].height = 28
    for col in ws.columns:
        values = [str(c.value or "") for c in list(col)[:120]]
        width = min(max(max((len(v) for v in values), default=10) + 2, 12), 48)
        ws.column_dimensions[col[0].column_letter].width = width
    if ws.max_row > 1 and ws.max_column > 0:
        name = "T_" + "".join(ch for ch in title if ch.isalnum())[:20]
        tab = Table(displayName=name, ref=ws.dimensions)
        tab.tableStyleInfo = TableStyleInfo(name="TableStyleMedium2", showFirstColumn=False, showLastColumn=False, showRowStripes=True, showColumnStripes=False)
        ws.add_table(tab)
    return ws


def main():
    questions = read_jsonl(QUESTION_FILE)
    retrieval = read_jsonl(RUN / "retrieval_results_v2.jsonl")
    eligibility = read_jsonl(RUN / "question_eligibility_v2.jsonl")
    source_registry = read_json(RUN / "source_registry_corrected.json")
    readiness = read_json(RUN / "rag_evaluation_readiness.json")
    integration = read_json(RUN / "rag_system_integration_test.json")
    preflight = read_json(RUN / "outputs/phase_s_execution_snapshot.json")
    metrics = read_json(RUN / "metrics_v2.json")
    old = read_json(OLD_METRICS)
    species_counts = Counter(q.get("species_chinese") or q.get("species_label_in_test_data") or "unknown" for q in questions)
    category_counts = Counter(q.get("inferred_category") or q.get("topic") or "UNCLASSIFIED" for q in questions)
    chunks = {r["chunk_id"]: r for r in read_jsonl(RUN / "corpus/phase_s_chunks_v1.jsonl")}

    wb = Workbook()
    wb.remove(wb.active)
    dash = wb.create_sheet("Research_Dashboard")
    dashboard_rows = [
        ("Phase S status", "BLOCKED_BEFORE_NEW_GENERATION", "new system has no final reranked Top-5"),
        ("Input question records", len(questions), "read from Phase E normalized file; original unchanged"),
        ("Species coverage", len(species_counts), "counts preserved exactly as workbook fish labels"),
        ("New isolated corpus version", "phase_s_integrated_kb_v1", "not formal Corpus v3"),
        ("New indexed chunks", int(read_json(RUN / "knowledge_base_build_manifest.json")["chunk_count"]), "MOA statute + scope-limited DGBAS XML only"),
        ("Candidate retrieval stage traces", len(retrieval), "BM25 + Dense + RRF; final reranker Top-5 absent"),
        ("Final Top-5 complete", 0, "blocked: exact BGE reranker weights unavailable locally"),
        ("New generator responses", 0, "720 calls not started due acceptance gate"),
        ("New evaluation metric values", 0, "all N=0 / N/A; no carried-forward scores"),
        ("Formal Gate v2 passes on this corpus", 0, "no answer gold / exact evidence eligibility established"),
        ("Human Gold", 0, "none in this run"),
        ("Formal weighted score / Winner", "NOT COMPUTED / null", "no scoring policy freeze or new outputs"),
        ("Frozen baseline", f"{integration.get('frozen_baseline_after',{}).get('matching_count',0)}/636", "see compatibility files"),
    ]
    dash.append(["Metric", "Value", "Interpretation"])
    for row in dashboard_rows:
        dash.append(list(row))
    dash.freeze_panes = "A2"
    for c in dash[1]:
        c.font = Font(bold=True, color="FFFFFF"); c.fill = PatternFill("solid", fgColor="174A63")
    dash.column_dimensions["A"].width = 42; dash.column_dimensions["B"].width = 44; dash.column_dimensions["C"].width = 90
    start = dash.max_row + 3
    dash.cell(start, 1, "輸入題庫推定類別計數（非資格數）")
    dash.cell(start + 1, 1, "Category"); dash.cell(start + 1, 2, "Question count")
    for i, (key, val) in enumerate(sorted(category_counts.items()), start + 2):
        dash.cell(i, 1, key); dash.cell(i, 2, val)
    chart = BarChart(); chart.title = "Input questions by inferred category"; chart.y_axis.title = "Questions"; chart.x_axis.title = "Category"
    chart.add_data(Reference(dash, min_col=2, min_row=start + 1, max_row=start + 1 + len(category_counts)), titles_from_data=True)
    chart.set_categories(Reference(dash, min_col=1, min_row=start + 2, max_row=start + 1 + len(category_counts)))
    chart.height = 7; chart.width = 15; dash.add_chart(chart, "E2")

    models = preflight.get("models", [])
    model_by_id = {m.get("model_id"): m for m in models if m.get("model_id")}
    model_ids = ["M1", "M2", "M3", "M4"]
    model_rows = []
    metric_names = ["Faithfulness", "Judge Answer Relevance", "BGE-M3 Cosine", "Structured IFR", "TTFT", "TPS", "System RAM", "Dedicated VRAM", "Context Precision@5", "Logical Accuracy", "Arithmetic Accuracy", "Citation Support"]
    for m in model_ids:
        for metric in metric_names:
            model_rows.append((m, metric, None, 0, "NOT RUN", "no new final Top-5 / no new generation"))
    add_sheet(wb, "Model_Comparison", ["Model", "Metric", "Value", "N", "Status", "Reason"], model_rows)

    settings_rows = []
    for m in model_ids:
        identity = model_by_id.get(m, {})
        settings_rows.append((m, identity.get("tag"), identity.get("actual_family"), identity.get("runtime_digest"), "verified" if identity.get("identity_pass") else identity.get("status"), "not run; no substitute model used"))
    settings_rows.extend([
        ("Embedding", "bge-m3:latest", "BGE-M3", preflight.get("models", [{}, {}, {}, {}, {}])[4].get("runtime_digest"), "verified; dimension 1024", "explicit L2 normalization"),
        ("Reranker", "BAAI/bge-reranker-v2-m3", "cross-encoder", None, "BLOCKED_MISSING_LOCAL_SNAPSHOT", "exact prior snapshot revision not found; no substitute"),
        ("Fusion", "RRF", None, None, "configured", "k=60, BM25 top100 + dense top100"),
    ])
    add_sheet(wb, "Experimental_Settings", ["Component", "Tag", "Architecture", "Digest", "Identity/status", "Evaluation note"], settings_rows)

    q_rows = []
    el_by_id = {r["question_id"]: r for r in eligibility}
    for q in questions:
        e = el_by_id[q["question_id"]]
        q_rows.append((q["question_id"], q.get("species_chinese"), q.get("inferred_category"), q.get("category_basis"), q.get("question_text"), q.get("candidate_reference_answer"), q.get("candidate_source_urls"), q.get("source_workbook"), q.get("question_bank_excel_row"), q.get("human_gold_reviewed"), e.get("benchmark_eligible_v2"), e.get("status"), e.get("answer_verification_status"), q.get("original_question_id")))
    add_sheet(wb, "Question_Eligibility", ["Question ID", "Species label", "Inferred category", "Category basis", "Question", "Candidate answer (not Gold)", "Candidate source URLs", "Workbook", "Source row", "Human Gold", "Gate v2 on Phase S corpus", "Status", "Answer verification status", "Original question ID"], q_rows)

    retrieval_rows = []
    for rec in retrieval:
        for stage in ("bm25_top100", "dense_top100", "rrf_candidates_top100"):
            for rank, hit in enumerate(rec.get(stage, [])[:20], 1):
                chunk = chunks.get(hit.get("chunk_id"), {})
                retrieval_rows.append((rec["question_id"], rec["corpus_version"], stage, rank, hit.get("chunk_id"), hit.get("source_id"), hit.get("source_title"), hit.get("page"), hit.get("locator"), hit.get("score"), hit.get("bm25_rank"), hit.get("dense_rank"), chunk.get("content_sha256")))
        retrieval_rows.append((rec["question_id"], rec["corpus_version"], "final_top5", None, None, None, None, None, rec.get("failure_reason"), None, None, None, "BLOCKED"))
    add_sheet(wb, "Retrieval_Results", ["Question ID", "Corpus version", "Stage", "Stage rank", "Chunk ID", "Source ID", "Document", "Page", "Exact locator / status", "Score", "BM25 rank", "Dense rank", "Chunk text SHA-256"], retrieval_rows)

    p_rows = [(q["question_id"], q.get("species_chinese"), q.get("inferred_category"), None, 0, "N/A", "Final shared Top-5 unavailable: reranker snapshot missing") for q in questions]
    add_sheet(wb, "Context_Precision", ["Question ID", "Species", "Inferred category", "P@5", "N", "Status", "Reason"], p_rows)
    for sheet, metric in [("Faithfulness", "Faithfulness"), ("Answer_Relevance", "Judge Answer Relevance"), ("BGE_M3_Similarity", "BGE-M3 cosine"), ("Structured_IFR", "Structured IFR"), ("TTFT_TPS", "TTFT/TPS"), ("RAM_VRAM", "RAM/VRAM"), ("Logical_Accuracy", "Logical Accuracy"), ("Arithmetic_Accuracy", "Arithmetic Accuracy"), ("Citation_Support", "Citation Support")]:
        add_sheet(wb, sheet, ["Metric", "Model", "Value", "N", "Status", "Reason"], [(metric, m, None, 0, "NOT RUN", "no new generation/final Top-5") for m in model_ids])

    species_rows = []
    for s, n in sorted(species_counts.items()):
        species_rows.append((s, n, 0, None, 0, "N/A", "input composition only; no new model evaluation"))
    add_sheet(wb, "Species_Comparison", ["Input species label", "Input N", "New generations", "New metric value", "Metric N", "Status", "Note"], species_rows)
    add_sheet(wb, "Category_Comparison", ["Inferred category", "Input N", "Gate v2 pass on Phase S corpus", "New metric value", "Metric N", "Classification note"], [(c, n, 0, None, 0, "category may be heuristic; preserved from normalized dataset") for c, n in sorted(category_counts.items())])

    missing_rows = [(e["question_id"], e.get("species"), e.get("category"), safe_json(e.get("candidate_source_urls")), safe_json(e.get("sources_present_in_phase_s_index_candidate")), e.get("status"), e.get("exact_support_locator_verified"), e.get("benchmark_eligible_v2")) for e in eligibility]
    add_sheet(wb, "Missing_Evidence", ["Question ID", "Species", "Category", "Candidate source URLs", "Sources present in candidate index", "Current blocker", "Exact support verified", "Gate v2 pass"], missing_rows)

    validation_rows = [("Isolated unit tests", "6/6 PASS", "species scope, law filter, exact citations, RRF and fail-closed reranker"),
                       ("Index artifact integrity", "PASS", "chunk/vector/DB hashes, DB row count, source allowlist and vector blob equality"),
                       ("Question retrieval stage", f"{len(retrieval)}/180", "BM25, dense, RRF candidates completed"),
                       ("Final rerank", "BLOCKED", "BGE reranker local snapshot unavailable"),
                       ("New generator calls", "0/720", "acceptance gate prevented calls"),
                       ("Frozen baseline", f"{integration.get('frozen_baseline_after',{}).get('matching_count',0)}/636", "verified after Phase S"),
                       ("Streamlit AppTest", "PASS_FAIL_CLOSED", "app loads, shows isolated run and missing reranker notice; no ungrounded answer"),
                       ("Full repository pytest", "NOT RUN", "known tempfile WinError 5; no pass claim")]
    add_sheet(wb, "Validation", ["Check", "Result", "Details"], validation_rows)
    add_sheet(wb, "Limitations", ["Limitation", "Impact", "Status"], [
        ("No local verified BGE reranker snapshot", "No final Top-5; blocks all new generation and end-to-end evaluation", "BLOCKER"),
        ("Candidate corpus limited to one statute and admitted DGBAS 2020 XML", "Does not cover six-species aquaculture knowledge broadly", "LIMITATION"),
        ("Annex I attachment-specific version unverified", "Excluded from new index", "QUARANTINED"),
        ("TFRIN full-text use scope not established for this run", "Excluded from new index", "EXCLUDED"),
        ("Reference answers remain candidates and no Human Gold exists", "No new Accuracy metrics", "BLOCKER"),
        ("Original 180 items have prior exposure", "Only regression/exploratory set; no fresh Holdout claim", "LIMITATION"),
        ("No approved total-score normalization", "No weighted total or Winner", "NOT COMPUTED"),
    ])

    prov_rows = []
    for doc in source_registry.get("source_document_audit", []):
        prov_rows.append((doc.get("document_id"), doc.get("corpus_source_id"), doc.get("source_title"), doc.get("corpus_source_url"), doc.get("manifest_file_path"), doc.get("corpus_sha256"), doc.get("actual_sha256"), doc.get("identity_status"), "Authority/version/rights/species may remain UNVERIFIED"))
    for source in read_json(RUN / "knowledge_base_build_manifest.json").get("included_sources", []):
        prov_rows.append((source.get("source_id"), source.get("legacy_corpus_source_id"), source.get("source_title"), source.get("source_url"), source.get("local_file"), source.get("source_sha256"), source.get("source_sha256"), source.get("status", "included in isolated candidate index"), source.get("usage_scope", source.get("included_scope"))))
    add_sheet(wb, "Provenance", ["Source/document ID", "Legacy source ID", "Title", "Official URL", "Local file", "Registered SHA-256", "Actual SHA-256", "Identity status", "Usage scope/limitation"], prov_rows)

    old_rows = []
    for model, data in old.get("model_summaries", {}).items():
        for metric, details in data.get("metrics", {}).items():
            old_rows.append(("Phase E historical only", model, metric, details.get("mean"), details.get("n"), "historical; not Phase S result"))
        old_rows.append(("Phase E historical only", model, "Structured IFR", data.get("structural_ifr", {}).get("rate"), data.get("structural_ifr", {}).get("n"), "historical; not Phase S result"))
    add_sheet(wb, "Historical_Phase_E", ["Dataset", "Model", "Metric", "Historical value", "Historical N", "Restriction"], old_rows)

    for ws in wb.worksheets:
        ws.sheet_view.showGridLines = False
        for row in ws.iter_rows(min_row=2):
            for cell in row:
                cell.alignment = Alignment(vertical="top", wrap_text=True)
    wb.save(OUTPUT)

    # Reopen verification: expected sheet set, question rows, and no fabricated new scores.
    check = load_workbook(OUTPUT, read_only=False, data_only=False)
    required = {"Research_Dashboard", "Model_Comparison", "Question_Eligibility", "Retrieval_Results", "Context_Precision", "Faithfulness", "Answer_Relevance", "BGE_M3_Similarity", "Structured_IFR", "TTFT_TPS", "RAM_VRAM", "Logical_Accuracy", "Arithmetic_Accuracy", "Citation_Support", "Species_Comparison", "Category_Comparison", "Missing_Evidence", "Validation", "Limitations", "Provenance"}
    assert required.issubset(set(check.sheetnames))
    assert check["Question_Eligibility"].max_row == 181
    assert check["Context_Precision"].max_row == 181
    assert check["Retrieval_Results"].max_row > 180
    assert all(check["Model_Comparison"].cell(r, 3).value is None and check["Model_Comparison"].cell(r, 4).value == 0 for r in range(2, check["Model_Comparison"].max_row + 1))
    check.close()
    print(json.dumps({"output": str(OUTPUT), "size": OUTPUT.stat().st_size, "sheets": len(required) + 1, "question_rows": 180, "retrieval_stage_rows": len(retrieval_rows), "reopen_validation": "PASS"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
