import fs from "node:fs/promises";
import path from "node:path";
import { FileBlob, SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const root = process.cwd();
const outDir = path.join(root, "reports/evaluation/fish_test_phase_v_20261018_224918");
const corpusDir = path.join(outDir, "corpus_v3_final");
const outXlsx = path.join(outDir, "fish_test_evaluation_v3_final.xlsx");

const readJson = async (f) => JSON.parse(await fs.readFile(path.join(outDir, f), "utf8"));
const readJsonl = async (f) => (await fs.readFile(path.join(outDir, f), "utf8"))
  .split(/\r?\n/).filter((x) => x.trim()).map((x) => JSON.parse(x));
const retrieval = await readJsonl("retrieval_results_v3_final.jsonl");
const qualification = await readJsonl("question_eligibility_v3.jsonl");
const blockers = await readJsonl("source_blocker_resolution_50.jsonl");
const refSummary = await readJson("question_reference_qualification_summary.json");
const failSummary = await readJson("retrieval_failure_summary_180.json");
const corpus = await readJson("corpus_v3_final_quality_summary.json");
const metrics = await readJson("evaluation_metrics_v3_final.json");
const validation = await readJson("rag_end_to_end_validation.json");
const pytest = await readJson("repository_pytest_report.json");
const models = await readJson("model_runtime_alignment.json");
const protectedStatus = await readJson("protected_baseline_final_status.json");
const dbIntegrity = await readJson("corpus_v3_database_index_integrity.json");

const workbook = Workbook.create();
const navy = "#17365D";
const blue = "#D9EAF7";
const pale = "#F3F6FA";
const font = "Aptos";

function makeSheet(name, title, subtitle) {
  const sheet = workbook.worksheets.add(name);
  sheet.showGridLines = false;
  sheet.getRange("A1").values = [[title]];
  sheet.getRange("A1:H1").format = { fill: navy, font: { name: font, size: 15, bold: true, color: "#FFFFFF" } };
  sheet.getRange("A2").values = [[subtitle]];
  sheet.getRange("A2:H2").format = { fill: pale, font: { name: font, size: 10, italic: true, color: "#44546A" }, wrapText: true };
  sheet.getRange("A1:H2").format.rowHeight = 28;
  return sheet;
}

function writeTable(sheet, row, headers, rows, tableName, widths = []) {
  const data = [headers, ...rows];
  const lastCol = colName(headers.length);
  const lastRow = row + data.length - 1;
  const range = sheet.getRange(`A${row}:${lastCol}${lastRow}`);
  range.values = data;
  range.format.font = { name: font, size: 9 };
  range.format.wrapText = true;
  sheet.getRange(`A${row}:${lastCol}${row}`).format = {
    fill: navy,
    font: { name: font, size: 9, bold: true, color: "#FFFFFF" },
    wrapText: true,
  };
  sheet.getRange(`A${row}:${lastCol}${lastRow}`).format.rowHeight = 32;
  if (tableName) sheet.tables.add(`A${row}:${lastCol}${lastRow}`, true, tableName);
  if (widths.length) widths.forEach((w, i) => sheet.getRange(`${colName(i + 1)}:${colName(i + 1)}`).format.columnWidth = w);
  sheet.freezePanes.freezeRows(row);
  return { lastCol, lastRow };
}

function colName(n) {
  let s = "";
  while (n) {
    const r = (n - 1) % 26;
    s = String.fromCharCode(65 + r) + s;
    n = Math.floor((n - 1) / 26);
  }
  return s;
}

const statuses = failSummary.retrieval_status_counts;
const top5Rows = retrieval.map((r) => [
  r.question_id, r.species, r.category, r.intent,
  r.corpus_applicable_source_count, r.corpus_applicable_chunk_count,
  r.bm25_global_candidate_count, r.bm25_candidate_count,
  r.dense_global_candidate_count, r.dense_candidate_count,
  r.rrf_candidate_count, r.source_qualification_pass_count,
  r.species_applicability_pass_count, r.reranker_candidate_count,
  (r.reranked_top5 || []).length, r.retrieval_status, r.retrieval_failure_reason || "",
  (r.reranked_top5 || []).map((x) => `${x.rank}:${x.chunk_id}`).join(" | "),
]);

const eligRows = qualification.map((q) => [
  q.question_id, q.species, q.category, q.question_valid === true ? "true" : q.question_valid === false ? "false" : "unknown",
  q.answer_qualification_v3, q.source_status, q.reference_answer_candidate || "",
  (q.required_answer_elements || []).join("；"), (q.missing_elements || []).join("；"),
  q.applicability_status || "", q.expected_action || "", q.retrieval_outcome || "",
  q.retrieval_top5_count ?? "", q.formal_gate_v2_pass ? "true" : "false", q.human_gold_reviewed ? "true" : "false",
]);

const sourceRows = blockers.map((s) => [
  s.source_record_id, s.source_id, s.title, s.publisher || "UNVERIFIED", s.local_file,
  s.sha256_expected, s.sha256_actual, s.checksum_match ? "MATCH" : "MISMATCH",
  s.document_version || "UNVERIFIED", s.official_url || "MISSING",
  s.rights_status_fulltext || "UNVERIFIED", s.fulltext_index_status || "BLOCKED",
  (s.blocker_codes || []).join("; "), s.file_format || "", s.page_count ?? "",
  s.extracted_characters ?? "", s.empty_or_unextractable_pages ?? "", s.resolution || "",
]);

const speciesRows = Object.entries(refSummary.by_species).map(([sp, counts]) => {
  const r = Object.entries(failSummary.status_by_species || {}).find(([k]) => k === sp)?.[1] || {};
  return [sp, counts.SOURCE_VERIFIED_AUTOMATED_CANDIDATE || 0, counts.NOT_EVALUABLE || 0,
    r.reranked_top5_complete || 0, r.fewer_than_five_applicable_candidates || 0,
    r.no_applicable_retrieval_eligible_source || 0];
});

// Recompute species/category aggregates from the underlying retrieval rows.
const agg = new Map();
for (const r of retrieval) {
  const key = r.species;
  if (!agg.has(key)) agg.set(key, { total: 0, full: 0, some: 0, none: 0, candidate: 0 });
  const x = agg.get(key); x.total += 1;
  const n = (r.reranked_top5 || []).length;
  if (n === 5) x.full += 1; else if (n > 0) x.some += 1; else x.none += 1;
}
for (const q of qualification) if (q.answer_qualification_v3.startsWith("AI_ASSISTED")) agg.get(q.species).candidate += 1;
const speciesSummaryRows = [...agg.entries()].map(([sp, x]) => [sp, x.total, x.candidate, x.full, x.some, x.none]);
const cats = new Map();
for (const r of retrieval) {
  if (!cats.has(r.category)) cats.set(r.category, { total: 0, full: 0, some: 0, none: 0, candidate: 0 });
  const x = cats.get(r.category); x.total += 1;
  const n = (r.reranked_top5 || []).length;
  if (n === 5) x.full += 1; else if (n > 0) x.some += 1; else x.none += 1;
}
for (const q of qualification) if (q.answer_qualification_v3.startsWith("AI_ASSISTED")) cats.get(q.category).candidate += 1;
const catRows = [...cats.entries()].map(([cat, x]) => [cat, x.total, x.candidate, x.full, x.some, x.none]);

const metricNames = [
  "Faithfulness", "Judge Answer Relevance", "BGE-M3 Cosine Similarity", "Structured IFR", "TTFT", "TPS",
  "System RAM", "Dedicated VRAM", "Context Precision@5", "Logical Accuracy", "Arithmetic Accuracy",
];
const metricRows = metricNames.map((name) => {
  const detail = metrics.metrics[name.replaceAll(" ", "_")] || null;
  let reason = "未執行新版模型生成";
  if (name === "Context Precision@5") reason = "沒有可信的逐段二元相關性標籤；Top-5 命中數不能代替 P@5";
  if (name === "Logical Accuracy") reason = "沒有凍結且來源支持的 rubric";
  if (name === "Arithmetic Accuracy") reason = "沒有完整核驗公式、單位、條件及標準答案的參考集";
  return [name, "NOT_EVALUATED", 0, "N/A", reason];
});

const dashboard = makeSheet("Dashboard", "Fish Test — Phase V 整合評估狀態", "隔離研究 Corpus；本輪未執行四模型生成。所有模型分數為 N/A，未產生正式排名。") ;
dashboard.getRange("A4:B13").values = [
  ["Corpus version", corpus.corpus_version],
  ["Corpus chunks", corpus.chunks.total],
  ["Retrieval eligible", corpus.chunks.retrieval_eligible],
  ["Context only", corpus.chunks.context_only],
  ["Questions rerun", 180],
  ["Any returned candidates", failSummary.questions_with_any_returned_chunk],
  ["Complete Top-5", failSummary.questions_with_complete_top5],
  ["AI source-card candidates", 41],
  ["Answerable verified / frozen rubrics", 0],
  ["New generator calls", 0],
];
dashboard.getRange("A4:A13").format = { fill: blue, font: { name: font, bold: true, color: navy } };
dashboard.getRange("B5:B7").format.numberFormat = "#,##0";
dashboard.getRange("B8:B13").format.numberFormat = "#,##0";
dashboard.getRange("A15:B19").values = [
  ["Retrieval status", "Question count"],
  ["Complete Top-5", statuses.reranked_top5_complete || 0],
  ["Fewer than 5 applicable candidates", statuses.fewer_than_five_applicable_candidates || 0],
  ["No applicable retrieval-eligible source", statuses.no_applicable_retrieval_eligible_source || 0],
  ["Phase V 11 metrics", "NOT EVALUATED (N=0)"],
];
dashboard.getRange("A15:B15").format = { fill: navy, font: { name: font, bold: true, color: "#FFFFFF" } };
dashboard.getRange("A4:B19").format.font = { name: font, size: 10 };
dashboard.getRange("A4:A19").format.columnWidth = 42;
dashboard.getRange("B4:B19").format.columnWidth = 36;
dashboard.getRange("A21:B23").values = [
  ["Gate", "狀態"],
  ["Corpus / BM25 / Dense / RRF / Reranker / retrieval trace", "完成隔離研究建置與 180 題檢索"],
  ["Question answerability / rubric / generator integration", "未達門檻；停止 720 次生成"],
];
dashboard.getRange("A21:B21").format = { fill: navy, font: { name: font, bold: true, color: "#FFFFFF" } };
dashboard.getRange("A21:B23").format.wrapText = true;

const srcSheet = makeSheet("Source_Audit", "來源阻塞與核驗", "Owner Approval 是研究決策，不等同第三方全文索引授權；每筆列出原件、metadata 與使用阻塞。") ;
writeTable(srcSheet, 4,
  ["record_id", "source_id", "title", "publisher", "local_file", "sha256_expected", "sha256_actual", "checksum", "version", "official_url", "fulltext_rights", "fulltext_status", "blockers", "format", "pages", "extracted_chars", "unextractable_pages", "resolution"],
  sourceRows, "SourceBlockers", [18, 24, 42, 24, 54, 68, 68, 14, 40, 45, 38, 22, 46, 13, 10, 16, 20, 50]);

const corpusSheet = makeSheet("Corpus", "新版 Corpus 規模與追溯", "研究用隔離 Corpus，未切換 Production，也不是對六魚種專業內容已充分覆蓋的證明。") ;
corpusSheet.getRange("A4:B16").values = [
  ["Measure", "Value"],
  ["Corpus version", corpus.corpus_version],
  ["Total chunks", corpus.chunks.total],
  ["Retrieval eligible", corpus.chunks.retrieval_eligible],
  ["Context only", corpus.chunks.context_only],
  ["Duplicate content groups", corpus.duplicate_content_groups],
  ["Duplicate excess rows", corpus.duplicate_content_excess_rows],
  ["Phase U prefix retained", 17377],
  ["New authored fact cards", 25],
  ["New card source packages", 6],
  ["Blocked full-text packages", 50],
  ["Corpus SQLite SHA-256", corpus.sqlite_sha256],
  ["Chunk JSONL SHA-256", corpus.chunk_jsonl_sha256],
];
corpusSheet.getRange("A4:A16").format = { fill: blue, font: { name: font, bold: true, color: navy } };
corpusSheet.getRange("A4:B16").format.font = { name: font, size: 10 };
corpusSheet.getRange("A4:A16").format.columnWidth = 36;
corpusSheet.getRange("B4:B16").format.columnWidth = 90;
corpusSheet.getRange("A19").writeValues([["Source ID", "Chunk count"], ...Object.entries(corpus.source_counts_by_id || {}).sort((a,b)=>b[1]-a[1])]);
corpusSheet.getRange(`A19:B${19 + Object.keys(corpus.source_counts_by_id || {}).length}`).format.font = { name: font, size: 9 };
corpusSheet.getRange("A19:B19").format = { fill: navy, font: { name: font, size: 9, bold: true, color: "#FFFFFF" } };
corpusSheet.getRange("A19:A40").format.columnWidth = 42;
corpusSheet.getRange("B19:B40").format.columnWidth = 18;

const retrievalSheet = makeSheet("Retrieval_180", "180 題檢索階段數據", "候選數由最終檢索 JSONL 重算；Top-5 原文及來源追溯詳見 retrieval_results_v3_final.jsonl。") ;
writeTable(retrievalSheet, 4,
  ["question_id", "species", "category", "intent", "applicable_sources", "applicable_chunks", "bm25_global", "bm25_scoped", "dense_global", "dense_scoped", "rrf", "source_pass", "species_pass", "reranker_candidates", "final_top5", "status", "failure_reason", "top5_rank_chunk_ids"],
  top5Rows, "RetrievalRows", [20, 16, 22, 20, 15, 15, 14, 14, 14, 14, 12, 14, 14, 18, 12, 44, 34, 70]);

const eligSheet = makeSheet("Eligibility_180", "180 題答案資格與評分規準", "AI 輔助 source-card 映射候選不得視為 Human Gold 或正式 Gate pass。Top-5 是檢索結果，不是資格條件。") ;
writeTable(eligSheet, 4,
  ["question_id", "species", "category", "question_valid", "qualification", "source_status", "reference_answer_candidate", "required_answer_elements", "missing_elements", "applicability", "expected_action", "retrieval_outcome", "top5_count", "formal_gate_pass", "human_gold"],
  eligRows, "EligibilityRows", [20, 16, 22, 18, 44, 42, 75, 50, 44, 36, 38, 44, 14, 18, 16]);

const speciesSheet = makeSheet("Species_Coverage", "六魚種檢索與答案候選覆蓋", "候選答案數不是 Gate 合格題數；所有研究候選仍待 rubric／專家覆核。") ;
writeTable(speciesSheet, 4, ["species", "questions", "AI source candidates", "complete Top-5", "partial Top-5", "no chunk returned"], speciesSummaryRows, "SpeciesCoverage", [18, 14, 24, 18, 18, 20]);

const catSheet = makeSheet("Category_Coverage", "類別檢索與答案候選覆蓋", "類別不平衡及缺少可凍結答案來源，是阻止全面生成的主要因素。") ;
writeTable(catSheet, 4, ["category", "questions", "AI source candidates", "complete Top-5", "partial Top-5", "no chunk returned"], catRows, "CategoryCoverage", [30, 14, 24, 18, 18, 20]);

const metricSheet = makeSheet("Metrics", "Phase V 新版指標狀態", "本輪沒有執行 Generator；因此不以 Phase E 舊版分數冒充新版結果。") ;
writeTable(metricSheet, 4, ["metric", "status", "valid N", "result", "reason"], metricRows, "MetricStatus", [34, 20, 14, 20, 90]);

const validationSheet = makeSheet("Validation", "系統驗收與停止條件", "明確區分已驗證的研究檢索與尚未通過的新生成／正式整合流程。") ;
const validationRows = [
  ["Corpus isolated build", validation.corpus_build, "PASS"],
  ["BGE-M3 query embeddings", validation.query_embedding_runtime, "PASS"],
  ["BM25 SQLite FTS5 rowid map", validation.bm25, "PASS"],
  ["RRF k=60", validation.rrf, "PASS"],
  ["BGE reranker 180 queries", validation.reranker, "PASS"],
  ["Top-5 source traceback", validation.top5_traceback.status, "PASS"],
  ["SQLite chunks / sources", `${dbIntegrity.sqlite_chunk_count} / ${dbIntegrity.sqlite_source_count}`, "MATCH JSONL"],
  ["FTS row IDs / Dense vectors", `${dbIntegrity.fts5_row_count} / ${dbIntegrity.dense_vector_rows} × ${dbIntegrity.dense_dimensions}`, "MATCH ELIGIBLE ORDER"],
  ["Repository tests", pytest.status, `${pytest.passed}/${pytest.collected}`],
  ["Existing Production Streamlit AppTest", validation.streamlit_app_test.status, "READ-ONLY INITIAL RENDER"],
  ["New RAG generator/API integration", validation.full_system_end_to_end, "NOT PASSED"],
  ["New generator calls", "0", "STOPPED BY READINESS GATE"],
  ["Protected Manifest", `${protectedStatus.rechecked_records}/${protectedStatus.expected_manifest_records}`, protectedStatus.all_636_match ? "ALL MATCH" : "MISMATCH"],
  ["Production SQLite SHA-256", protectedStatus.production_sqlite_actual_sha256, protectedStatus.production_sqlite_status],
  ["Protected Production SQLite", "unchanged", "PASS"],
  ["Historical E4 / Corpus v2", "unchanged", "PASS"],
];
writeTable(validationSheet, 4, ["check", "result", "interpretation"], validationRows, "ValidationRows", [44, 64, 44]);

const prov = makeSheet("Provenance", "來源檔案與版本追溯", "此工作簿由 Phase V 新版 retrieval、reference mapping、source blocker、corpus manifest 與測試報告生成。") ;
const provRows = [
  ["Fish Test questions / retrieval prompt source", "Phase V retrieval JSONL; question text is used only as query, no answer/rubric leakage"],
  ["Owner decision records", "Phase U source_owner_decision_update_57.jsonl; derived manifest source_approval_manifest_v1.json"],
  ["Source blocker forensic audit", "source_blocker_resolution_50.jsonl; SHA and parser checks redone in Phase V"],
  ["Corpus records", "corpus_v3_final/corpus_chunks_v3_final.jsonl"],
  ["Corpus SQLite", "corpus_v3_final/corpus_v3_final.sqlite3"],
  ["Embedding vectors", "corpus_v3_final/dense_vectors_v3_final.f32; BGE-M3 1024 dimensions; L2 normalized"],
  ["Retriever", "BM25 SQLite FTS5 + BGE-M3 Dense + RRF k=60 + BAAI/bge-reranker-v2-m3; Top-K=5"],
  ["Reference candidates", "question_reference_answers_180.jsonl; AI_ASSISTED_SOURCE_TRACE_CANDIDATE; not Human Gold"],
  ["New model generation", "generator_results_v3_final.jsonl is empty; 0 new generator calls"],
  ["Repository tests", "pytest_full_mixed_env_root.log; 607 passed, composite local environment"],
  ["Historical model metrics", "Phase E run 20261012_152244; separate historical experiment, not pooled"],
  ["Protected manifest", "Phase U frozen_manifest_recheck_final_636.jsonl; refreshed Phase V rehash report"],
];
writeTable(prov, 4, ["artifact", "source / rule"], provRows, "ProvenanceRows", [42, 118]);

workbook.recalculate();
const preview = await workbook.render({ sheetName: "Dashboard", autoCrop: "all", scale: 1, format: "png" });
await fs.writeFile(path.join(outDir, "fish_test_evaluation_v3_dashboard_preview.png"), new Uint8Array(await preview.arrayBuffer()));
const file = await SpreadsheetFile.exportXlsx(workbook);
await file.save(outXlsx);

const reopened = await SpreadsheetFile.importXlsx(await FileBlob.load(outXlsx));
const sheetInfo = await reopened.inspect({ kind: "sheet", include: "id,name", maxChars: 5000 });
const dashboardCheck = await reopened.inspect({ kind: "region", sheetId: "Dashboard", range: "A4:B19", maxChars: 5000 });
const check = {
  workbook: outXlsx,
  exists: (await fs.stat(outXlsx)).size > 0,
  bytes: (await fs.stat(outXlsx)).size,
  sheet_names: ["Dashboard", "Source_Audit", "Corpus", "Retrieval_180", "Eligibility_180", "Species_Coverage", "Category_Coverage", "Metrics", "Validation", "Provenance"],
  sheet_inspection: sheetInfo.ndjson,
  dashboard_check: dashboardCheck.ndjson,
  retrieval_rows: retrieval.length,
  qualification_rows: qualification.length,
  source_rows: blockers.length,
  all_metric_n_zero: metricRows.every((r) => r[2] === 0 && r[3] === "N/A"),
  generator_calls: metrics.generator_calls,
  reopened_with_artifact_tool: true,
};
await fs.writeFile(path.join(outDir, "fish_test_evaluation_v3_workbook_validation.json"), JSON.stringify(check, null, 2) + "\n", "utf8");
console.log(JSON.stringify({ bytes: check.bytes, sheets: check.sheet_names, rows: [check.retrieval_rows, check.qualification_rows, check.source_rows], metricNAllZero: check.all_metric_n_zero }, null, 2));
