import fs from "node:fs/promises";
import path from "node:path";
import { FileBlob, SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const out = path.resolve("reports/evaluation/fish_test_phase_u_20261018_195823");
const root = path.resolve(".");
const readJson = async (rel) => JSON.parse(await fs.readFile(path.join(out, rel), "utf8"));
const readJsonl = async (rel) => (await fs.readFile(path.join(out, rel), "utf8")).split(/\r?\n/).filter(Boolean).map((x) => JSON.parse(x));
const safe = (v) => v == null ? "" : (typeof v === "string" || typeof v === "number" || typeof v === "boolean" ? v : JSON.stringify(v));
const colName = (n) => { let s=""; while(n){const r=(n-1)%26;s=String.fromCharCode(65+r)+s;n=Math.floor((n-1)/26);} return s; };

function addTable(sheet, tableName, headers, rows, widths = []) {
  const cleanCell = (v) => {
    if (v == null) return null;
    if (typeof v === "string") return v.replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F]/g, " ");
    if (typeof v === "number" && !Number.isFinite(v)) return null;
    if (Array.isArray(v) || typeof v === "object") return JSON.stringify(v).replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F]/g, " ");
    return v;
  };
  const matrix = [headers, ...rows].map((row) => row.map(cleanCell));
  const end = colName(headers.length);
  const area = `A1:${end}${matrix.length}`;
  sheet.showGridLines = false;
  sheet.freezePanes.freezeRows(1);
  sheet.getRange(area).values = matrix;
  sheet.getRange(area).format.font = { name: "Aptos", size: 10, color: "#263238" };
  sheet.getRange(area).format.verticalAlignment = "center";
  sheet.getRange(area).format.wrapText = true;
  sheet.getRange(`A1:${end}1`).format = { fill: "#17365D", font: { name: "Aptos", size: 10, bold: true, color: "#FFFFFF" }, verticalAlignment: "center", wrapText: true };
  for (const [col, width] of widths) sheet.getRange(`${col}:${col}`).format.columnWidth = width;
  if (matrix.length > 1) sheet.tables.add(area, true, tableName);
  return { area, rows: rows.length, cols: headers.length };
}

function addSummary(sheet, title, note, rows, widths = [["A", 42], ["B", 86]]) {
  sheet.showGridLines = false;
  sheet.getRange("A1").values = [[title]];
  sheet.getRange("A1").format = { font: { name: "Aptos", size: 15, bold: true, color: "#17365D" }, verticalAlignment: "center" };
  sheet.getRange("A2").values = [[note]];
  sheet.getRange("A2").format = { font: { name: "Aptos", size: 10, italic: true, color: "#52616B" }, wrapText: true };
  const matrix = [["項目", "實際結果"], ...rows];
  sheet.getRange(`A4:B${3 + matrix.length}`).values = matrix;
  sheet.getRange(`A4:B${3 + matrix.length}`).format = { font: { name: "Aptos", size: 10, color: "#263238" }, verticalAlignment: "center", wrapText: true };
  sheet.getRange("A4:B4").format = { fill: "#DCE6F1", font: { name: "Aptos", size: 10, bold: true, color: "#17365D" }, verticalAlignment: "center" };
  for (const [col, width] of widths) sheet.getRange(`${col}:${col}`).format.columnWidth = width;
}

async function exportVerify(wb, filename, expectedSheets, checks = []) {
  console.log(`export start ${filename}`);
  wb.recalculate();
  console.log(`recalculated ${filename}`);
  const target = path.join(out, filename);
  const xlsx = await SpreadsheetFile.exportXlsx(wb);
  console.log(`exported ${filename}`);
  await xlsx.save(target);
  const reopened = await SpreadsheetFile.importXlsx(await FileBlob.load(target));
  const sheetInspection = await reopened.inspect({ kind: "sheet", include: "id,name", maxChars: 10000 });
  const rendered = [];
  for (const sheetName of expectedSheets) {
    console.log(`render ${filename}/${sheetName}`);
    const sheet = reopened.worksheets.getItem(sheetName);
    const used = sheet.getUsedRange();
    const end = used?.address?.split("!").pop() || "A1";
    const preview = await reopened.render({ sheetName, autoCrop: "all", scale: 0.8, format: "png" });
    const imgPath = path.join(out, "workbook_previews", `${filename.replace(/\.xlsx$/i, "")}_${sheetName}.png`);
    await fs.mkdir(path.dirname(imgPath), { recursive: true });
    await fs.writeFile(imgPath, new Uint8Array(await preview.arrayBuffer()));
    rendered.push({ sheet: sheetName, preview: path.relative(root, imgPath) });
  }
  const inspectionText = sheetInspection.ndjson ?? JSON.stringify(sheetInspection);
  const missingSheets = expectedSheets.filter((name) => !inspectionText.includes(name));
  if (missingSheets.length) throw new Error(`${filename}: missing sheets ${missingSheets.join(", ")}`);
  const checkResults = [];
  for (const c of checks) {
    const vals = reopened.worksheets.getItem(c.sheet).getRange(c.range).values;
    const ok = c.test(vals);
    checkResults.push({ sheet: c.sheet, range: c.range, ok, values: vals });
    if (!ok) throw new Error(`${filename}: content check failed at ${c.sheet}!${c.range}`);
  }
  return { file: filename, bytes: (await fs.stat(target)).size, reopened: true, sheets: expectedSheets, checks: checkResults, rendered };
}

const inventory = await readJsonl("source_admission_decision_records_57.jsonl");
const ownerUpdates = await readJsonl("source_owner_decision_update_57.jsonl");
const rights = await readJsonl("source_rights_version_scope_audit_57_final.jsonl");
const sourceRegistry = await readJsonl("source_admission_registry_v3_final.jsonl");
const corpusManifest = await readJson("corpus_v3_manifest.json");
const corpusChunks = await readJsonl("corpus_v3_final/corpus_chunks_v3_final.jsonl");
const speciesCoverage = await readJson("species_source_coverage_v3.json");
const readiness = await readJson("rag_evaluation_readiness.json");
const metrics = await readJson("evaluation_metrics_v3_final.json");
const retrieval = await readJsonl("retrieval_results_v3_final.jsonl");
const eligibility = await readJsonl("question_eligibility_v3.jsonl");
const models = await readJson("model_alignment_v3.json");
const validation = await readJson("phase_u_isolated_validation.json");
const frozen = await readJson("frozen_baseline_recheck.json");
const checksumRows = await readJsonl("source_checksum_recheck_57.jsonl");

const chunksBySource = new Map();
for (const c of corpusChunks) {
  const x = chunksBySource.get(c.source_id) || { total: 0, eligible: 0, context: 0 };
  x.total += 1; x[c.retrieval_eligible ? "eligible" : "context"] += 1; chunksBySource.set(c.source_id, x);
}
const retrievalBySpecies = new Map();
for (const r of retrieval) if (r.final_top5_count === 5) retrievalBySpecies.set(r.species, (retrievalBySpecies.get(r.species) || 0) + 1);
const uniqueHashes = new Set(inventory.map((x) => x.source_sha256).filter(Boolean));
const dupeMap = new Map();
for (const x of inventory) if (x.source_sha256) dupeMap.set(x.source_sha256, [...(dupeMap.get(x.source_sha256) || []), x.source_record_id]);
const duplicateRows = [...dupeMap.entries()].filter(([, ids]) => ids.length > 1).map(([sha, ids]) => ({ sha, ids }));

// Workbook 1: source inventory, species coverage and Corpus contents.
const inventoryWb = Workbook.create();
let sh = inventoryWb.worksheets.add("Summary");
addSummary(sh, "六魚種來源與 Corpus 盤點", "Owner Decision、第三方權利依據與 Corpus inclusion 分開記錄。", [
  ["來源登錄紀錄", inventory.length], ["不同原始檔 SHA-256", uniqueHashes.size], ["重複 SHA-256 群組", duplicateRows.length],
  ["重新核對來源 checksum", `${checksumRows.filter((x) => x.status === "MATCH").length}/${checksumRows.length} MATCH`],
  ["研究負責人 Owner Decision", `${ownerUpdates.filter((x) => x.owner_decision === "APPROVED").length}/57 APPROVED`],
  ["正式納入隔離 Corpus 的來源原件", sourceRegistry.length], ["Corpus chunks", corpusManifest.total_chunk_count],
  ["可檢索 chunks", corpusManifest.retrieval_eligible_chunk_count], ["Context-only chunks", corpusManifest.context_only_chunk_count],
  ["六魚種已核實專屬養殖技術來源", 0], ["Corpus 版本", corpusManifest.corpus_version], ["正式環境切換", "未執行"],
]);
sh = inventoryWb.worksheets.add("Source_Inventory");
addTable(sh, "SourceInventory", ["Source record ID", "Source ID", "文件名稱", "發布者", "原始檔路徑", "官方 URL", "版本／日期", "SHA-256", "Checksum 重核", "Owner Decision", "權利狀態", "准入狀態", "Corpus inclusion", "魚種範圍", "類別／使用限制", "未解阻塞"], inventory.map((x) => [
  x.source_record_id, x.source_id || "UNVERIFIED", x.source_title || x.source_title || "", x.publisher || "UNVERIFIED", x.original_path || x.local_file || "", x.source_url || x.url || "", x.source_version || x.version || "UNVERIFIED", x.source_sha256 || x.checksum_sha256 || "", x.sha256_recheck_status, x.owner_decision, x.rights_status || "", x.admission_execution_status || "", x.corpus_v3_inclusion_status || "", x.species_scope || x.scope_signals_not_verified || "", x.approved_usage_scope || x.category_scope || "", x.remaining_blocker || x.blocker_reason || "",
]), [["A",22],["B",31],["C",56],["D",35],["E",62],["F",56],["G",50],["H",68],["I",17],["J",18],["K",48],["L",34],["M",38],["N",58],["O",78],["P",82]]);
sh = inventoryWb.worksheets.add("Species_Coverage");
addTable(sh, "SpeciesCoverage", ["目標魚種", "Fish Test 題數", "V3 Gate 合格", "有 reranked Top-5", "已核准專屬養殖技術來源", "可用來源說明"], speciesCoverage.species.map((x) => [x.species, x.question_count, x.benchmark_eligible_v3, retrievalBySpecies.get(x.species) || 0, x.species_specific_admitted_husbandry_sources, x.interpretation]), [["A",18],["B",18],["C",18],["D",18],["E",30],["F",88]]);
sh = inventoryWb.worksheets.add("Corpus_Sources");
addTable(sh, "CorpusSources", ["Source ID", "標題", "發布者", "核准用途", "版本", "SHA-256", "Inclusion", "Chunks", "Retrieval-eligible", "Context-only", "來源 cluster", "排除／適用限制"], sourceRegistry.map((x) => {
  const counts = chunksBySource.get(x.source_id) || { total: 0, eligible: 0, context: 0 };
  return [x.source_id, x.source_title, x.publisher, x.approved_usage_scope, x.publication_version, x.source_sha256, x.corpus_v3_inclusion_status, counts.total, counts.eligible, counts.context, x.source_cluster_id, x.prohibited_usage_scope || x.limitations || ""];
}), [["A",36],["B",58],["C",34],["D",76],["E",46],["F",68],["G",35],["H",14],["I",19],["J",18],["K",30],["L",80]]);
sh = inventoryWb.worksheets.add("Duplicate_Hashes");
addTable(sh, "DuplicateHashes", ["SHA-256", "Duplicate source record IDs", "Duplicate count"], duplicateRows.map((x) => [x.sha, x.ids.join(", "), x.ids.length]), [["A",70],["B",48],["C",20]]);
const inventoryResult = await exportVerify(inventoryWb, "source_inventory_six_species.xlsx", ["Summary","Source_Inventory","Species_Coverage","Corpus_Sources","Duplicate_Hashes"], [
  { sheet: "Source_Inventory", range: "A1:A2", test: (v) => v[1][0] === inventory[0].source_record_id },
  { sheet: "Species_Coverage", range: "A2:C2", test: (v) => v[0][0] === "虱目魚" && v[0][1] === 30 && v[0][2] === 0 },
]);

// Workbook 2: owner approvals are shown beside independent technical/right decisions.
const approvalWb = Workbook.create();
sh = approvalWb.worksheets.add("Decision_Summary");
const admittedCount = inventory.filter((x) => x.admission_execution_status === "admitted_scope_limited" || x.admission_execution_status === "already_admitted_scope_limited").length;
const blockedRows = inventory.filter((x) => !(x.admission_execution_status === "admitted_scope_limited" || x.admission_execution_status === "already_admitted_scope_limited"));
addSummary(sh, "來源 Owner Decision 與正式准入狀態", "研究負責人已批准 57 筆 Owner Decision。正式使用仍受逐來源權利、版本、身分及範圍核實結果限制。", [
  ["Owner Decision APPROVED", 57], ["來源矩陣紀錄", 57], ["不同原始檔 SHA-256", uniqueHashes.size], ["重複 SHA-256 群組", duplicateRows.length],
  ["正式納入 V3 的來源紀錄", admittedCount], ["仍 blocked 的來源紀錄", blockedRows.length], ["隔離 V3 source files", sourceRegistry.length],
  ["Owner approval source", "使用者於 2026-10-18 的明確指示；非數位簽章、非第三方授權"],
  ["DGBAS 2020", "既有單年度描述性 Fact 限定範圍；不推論跨年趨勢或生物物種"],
  ["Corpus v3 build", "本輪隔離研究用途已建置；Production 切換未核准／未執行"],
]);
sh = approvalWb.worksheets.add("Source_Decisions_57");
addTable(sh, "SourceDecisions", ["Source record ID", "Source ID", "來源名稱", "發布者", "原始檔", "URL", "版本", "SHA-256", "Checksum 重核", "Owner Decision", "權利狀態", "准入執行", "Corpus 狀態", "准入／使用範圍", "剩餘阻塞"], inventory.map((x) => [
  x.source_record_id, x.source_id || "UNVERIFIED", x.source_title || "", x.publisher || "UNVERIFIED", x.original_path || "", x.source_url || x.url || "", x.source_version || "UNVERIFIED", x.source_sha256 || "", x.sha256_recheck_status, x.owner_decision, x.rights_status || "", x.admission_execution_status || "blocked", x.corpus_v3_inclusion_status || "excluded", x.approved_usage_scope || x.intended_use_scope || "", x.remaining_blocker || x.blocker_reason || "",
]), [["A",22],["B",30],["C",54],["D",34],["E",58],["F",58],["G",46],["H",68],["I",18],["J",18],["K",54],["L",34],["M",38],["N",86],["O",86]]);
sh = approvalWb.worksheets.add("Admitted_7");
addTable(sh, "AdmittedSources", ["Source ID", "來源名稱", "發布者", "核准用途", "排除用途／限制", "SHA-256", "版本", "Corpus inclusion", "Chunk 數", "可檢索 Chunk", "Context-only Chunk"], sourceRegistry.map((x) => {
  const counts = chunksBySource.get(x.source_id) || { total: 0, eligible: 0, context: 0 };
  return [x.source_id, x.source_title, x.publisher, x.approved_usage_scope, x.prohibited_usage_scope || x.limitations || "", x.source_sha256, x.publication_version, x.corpus_v3_inclusion_status, counts.total, counts.eligible, counts.context];
}), [["A",34],["B",56],["C",32],["D",82],["E",80],["F",68],["G",42],["H",18],["I",20],["J",20],["K",20]]);
sh = approvalWb.worksheets.add("Blocked_Sources");
addTable(sh, "BlockedSources", ["Source record ID", "Source ID", "來源名稱", "SHA-256", "權利狀態", "版本／來源身分", "阻塞原因", "Owner Decision"], blockedRows.map((x) => [x.source_record_id, x.source_id || "UNVERIFIED", x.source_title || "", x.source_sha256 || "", x.rights_status || "", x.source_version || "UNVERIFIED", x.remaining_blocker || "source-specific validation incomplete", x.owner_decision]), [["A",22],["B",30],["C",52],["D",68],["E",56],["F",52],["G",92],["H",18]]);
sh = approvalWb.worksheets.add("Duplicate_Hashes");
addTable(sh, "ApprovalDuplicateHashes", ["SHA-256", "Duplicate source record IDs", "Duplicate count"], duplicateRows.map((x) => [x.sha, x.ids.join(", "), x.ids.length]), [["A",70],["B",48],["C",20]]);
const approvalResult = await exportVerify(approvalWb, "source_admission_approval_matrix.xlsx", ["Decision_Summary","Source_Decisions_57","Admitted_7","Blocked_Sources","Duplicate_Hashes"], [
  { sheet: "Source_Decisions_57", range: "J1:J2", test: (v) => v[1][0] === "APPROVED" },
  { sheet: "Admitted_7", range: "A1:A2", test: (v) => v[1][0] === sourceRegistry[0].source_id },
]);

// Workbook 3: readiness, actual reranked retrieval traces and NOT_EVALUATED metrics.
const evalWb = Workbook.create();
console.log("build evaluation workbook");
sh = evalWb.worksheets.add("Dashboard");
addSummary(sh, "Fish Test Phase U 評測狀態", "新版 Corpus 與 Retrieval 已在隔離工作區建置。答案資格 Gate 未通過，因此本輪不執行候選模型生成。", [
  ["Corpus V3", corpusManifest.corpus_version], ["題目數／唯一 ID", `${eligibility.length} / ${new Set(eligibility.map((x) => x.question_id)).size}`],
  ["Benchmark eligible V3", `${eligibility.filter((x) => x.benchmark_eligible_v3).length}/180`],
  ["完成 Reranked Top-5 的題目", retrieval.filter((x) => x.final_top5_count === 5).length], ["Top-5 Chunk 總數", retrieval.reduce((n, x) => n + x.final_top5_count, 0)],
  ["無適用 retrieval-eligible source", retrieval.filter((x) => x.retrieval_status === "no_applicable_retrieval_eligible_source").length],
  ["新 Generator calls", 0], ["新模型指標", "11 項皆 NOT_EVALUATED，N=0"], ["Human Gold", 0], ["Formal Winner", "None"],
  ["Frozen Manifest", `${frozen.fresh_recheck_status_counts.MATCH || 0}/${frozen.expected_manifest_entries} MATCH`],
  ["正式 SQLite SHA-256", frozen.protected_sqlite_matches ? "MATCH" : "MISMATCH"],
]);
sh = evalWb.worksheets.add("Question_Eligibility");
console.log("evaluation sheet eligibility");
addTable(sh, "QuestionEligibility", ["Question ID", "魚種", "類別", "問題全文", "答案已核驗", "物種適用性已核驗", "指定 Corpus 充分證據", "候選 Chunk ID", "Gate V3", "檢索結果", "阻塞原因", "Human Gold"], eligibility.map((x) => [x.question_id, x.species, x.category, x.question_text, x.answer_verified, x.species_applicability_verified, x.sufficient_corpus_support_span, (x.candidate_matching_chunk_ids || []).join("\n"), x.gate_status, x.retrieval_outcome, (x.failed_gate_reasons || []).join("; "), x.human_gold_reviewed]), [["A",25],["B",16],["C",22],["D",62],["E",18],["F",22],["G",24],["H",46],["I",18],["J",42],["K",74],["L",18]]);
sh = evalWb.worksheets.add("Retrieval_Questions");
console.log("evaluation sheet retrieval questions");
addTable(sh, "RetrievalQuestions", ["Question ID", "魚種", "類別", "問題全文", "Corpus 版本", "允許來源 ID", "範圍合格 chunks", "Top-5 數", "檢索狀態", "Top-5 Chunk IDs", "Query 不含答案／Rubric"], retrieval.map((x) => [x.question_id, x.species, x.category, x.question_text, x.corpus_version, (x.scope_allowed_source_ids || []).join(", "), x.scope_eligible_chunk_count, x.final_top5_count, x.retrieval_status, (x.reranked_top5 || []).map((c) => `${c.rank}:${c.chunk_id}`).join("\n"), x.query_excludes_candidate_answer_and_rubric]), [["A",25],["B",16],["C",22],["D",62],["E",46],["F",18],["G",20],["H",18],["I",22],["J",44],["K",28]]);
sh = evalWb.worksheets.add("Top5_Chunks");
const topRows = retrieval.flatMap((r) => (r.reranked_top5 || []).map((c) => [r.question_id, r.species, r.category, c.rank, c.chunk_id, c.source_id, c.source_title, c.source_version, c.page || "", c.locator || c.record_locator || "", c.rrf_rank, c.reranker_rank, c.reranker_score, c.content_sha256, c.content]));
console.log("evaluation sheet top5 chunks", topRows.length);
addTable(sh, "RerankedTop5", ["Question ID", "魚種", "類別", "Top-5 Rank", "Chunk ID", "Source ID", "Source Title", "Source Version", "Page", "原文 Locator", "RRF Rank", "Reranker Rank", "Reranker Score", "Context SHA-256", "Context Text"], topRows, [["A",25],["B",16],["C",22],["D",13],["E",36],["F",31],["G",52],["H",32],["I",18],["J",46],["K",14],["L",16],["M",22],["N",68],["O",100]]);
sh = evalWb.worksheets.add("Model_Settings");
console.log("evaluation sheet model settings");
addTable(sh, "ModelSettings", ["Model ID", "預期模型", "本機 Tag", "可用", "Ollama Digest", "Family", "參數量", "量化", "本輪生成呼叫"], models.models.map((m) => [m.model_id, m.expected_identity, m.installed_tag, m.present, m.digest, m.reported_family, m.parameter_size, m.quantization, m.called]), [["A",18],["B",44],["C",68],["D",16],["E",70],["F",18],["G",18],["H",18],["I",20]]);
sh = evalWb.worksheets.add("Metric_Status");
console.log("evaluation sheet metrics");
addTable(sh, "MetricStatus", ["指標", "值", "有效 N", "狀態", "原因"], Object.entries(metrics.metrics).map(([k,v]) => [k, v.value, v.n, v.status, v.reason]), [["A",36],["B",16],["C",14],["D",22],["E",104]]);
sh = evalWb.worksheets.add("Species_Comparison");
console.log("evaluation sheet species");
addTable(sh, "SpeciesComparison", ["魚種", "題數", "V3 Eligible", "Top-5 題數", "Top-5 Chunk 數", "限制"], speciesCoverage.species.map((x) => [x.species, x.question_count, x.benchmark_eligible_v3, retrievalBySpecies.get(x.species) || 0, retrieval.filter((r) => r.species === x.species).reduce((n,r) => n + r.final_top5_count, 0), x.interpretation]), [["A",18],["B",14],["C",16],["D",15],["E",15],["F",90]]);
sh = evalWb.worksheets.add("Category_Comparison");
console.log("evaluation sheet category");
const catNames = [...new Set(eligibility.map((x) => x.category))];
addTable(sh, "CategoryComparison", ["類別", "題數", "Gate V3 合格", "Reranked Top-5 題數", "主要阻塞"], catNames.map((category) => {
  const er = eligibility.filter((x) => x.category === category);
  const rr = retrieval.filter((x) => x.category === category);
  const reasons = [...new Set(er.flatMap((x) => x.failed_gate_reasons || []))];
  return [category, er.length, er.filter((x) => x.benchmark_eligible_v3).length, rr.filter((x) => x.final_top5_count === 5).length, reasons.join("; ")];
}), [["A",25],["B",14],["C",18],["D",22],["E",18]]);
sh = evalWb.worksheets.add("Validation");
console.log("evaluation sheet validation");
addTable(sh, "ValidationResults", ["Test ID", "Status", "Detail"], validation.tests.map((x) => [x.test_id, x.status, x.detail]), [["A",42],["B",16],["C",100]]);
sh = evalWb.worksheets.add("Limitations");
console.log("evaluation sheet limitations");
addTable(sh, "Limitations", ["項目", "實際狀態／限制"], [
  ["來源權利", "Owner approval is not third-party authorization. 50 source records remain blocked by source-specific identity, version, rights or scope evidence."],
  ["專業資料覆蓋", "No admitted fish-specific aquaculture technical source sufficient for Water Quality, Disease, Climate/Cold or Calculation."],
  ["法規範圍", "General Animal Drug Management Act only. The local 2019 use-standard annex is stale versus the official 2025-01-08 revision and excluded."],
  ["評測資格", "0/180 questions passed. Candidate answers and rubrics remain unverified; no Human Gold."],
  ["檢索", "19 Medication/Law questions returned 95 reranked chunks. 161 technical questions had no applicable retrieval-eligible source."],
  ["模型評估", "No generation was run. All 11 requested metrics are NOT_EVALUATED, N=0. No total score or winner."],
  ["App / pytest", "New corpus not wired to a new Streamlit application. Isolated tests 6/6 pass; repository test collection blocked by missing python-docx and PyMuPDF in the pytest interpreter."],
  ["基線", `636/636 Frozen Manifest files match. rag_store.sqlite3 SHA-256 ${frozen.protected_sqlite_actual_sha256}.`],
], [["A",24],["B",122]]);
sh = evalWb.worksheets.add("Provenance");
console.log("evaluation sheet provenance");
addTable(sh, "Provenance", ["資料", "版本／Checksum", "位置或說明"], [
  ["Corpus manifest", corpusManifest.corpus_version, corpusManifest.chunk_jsonl_sha256],
  ["Corpus SQLite", corpusManifest.sqlite_sha256, "isolated corpus_v3_final/corpus_v3_final.sqlite3"],
  ["Dense vectors", corpusManifest.embedding_index.model, corpusManifest.embedding_index.vector_file_sha256],
  ["BGE-M3", corpusManifest.embedding_index.model_digest, "1024-dim; L2 normalized"],
  ["BGE Reranker", corpusManifest.reranker.revision, "BAAI/bge-reranker-v2-m3; CUDA; full 180-query retrieval run"],
  ["Question inputs", "180 unique IDs", "Original Phase E run normalized Fish Test questions"],
  ["Source rights", "57 records", "Owner decisions are separate from license evidence; details in source admission workbook"],
  ["Frozen Manifest", `${frozen.fresh_recheck_status_counts.MATCH || 0}/${frozen.expected_manifest_entries}`, `SQLite SHA-256 ${frozen.protected_sqlite_actual_sha256}`],
  ["No generation", "0 calls", "No M1-M4 completion calls; output file intentionally empty due failed qualification gate"],
], [["A",30],["B",48],["C",98]]);
const evalResult = await exportVerify(evalWb, "fish_test_evaluation_v3_final.xlsx", ["Dashboard","Question_Eligibility","Retrieval_Questions","Top5_Chunks","Model_Settings","Metric_Status","Species_Comparison","Category_Comparison","Validation","Limitations","Provenance"], [
  { sheet: "Question_Eligibility", range: "A1:A2", test: (v) => v[1][0] === eligibility[0].question_id },
  { sheet: "Top5_Chunks", range: "A1:A2", test: (v) => v[1][0] === topRows[0][0] },
  { sheet: "Metric_Status", range: "A1:C2", test: (v) => v[1][2] === 0 },
]);

const workbookAudit = { generated_at_utc: new Date().toISOString(), workbooks: [inventoryResult, approvalResult, evalResult], all_reopened: true, all_expected_sheets_present: true };
await fs.writeFile(path.join(out, "workbook_validation.json"), JSON.stringify(workbookAudit, null, 2) + "\n", "utf8");
console.log(JSON.stringify(workbookAudit, null, 2));
