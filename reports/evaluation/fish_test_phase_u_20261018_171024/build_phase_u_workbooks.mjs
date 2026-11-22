import fs from "node:fs/promises";
import path from "node:path";
import { FileBlob, SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const out = path.resolve("reports/evaluation/fish_test_phase_u_20261018_171024");

async function json(name) {
  return JSON.parse(await fs.readFile(path.join(out, name), "utf8"));
}
async function jsonl(name) {
  const txt = await fs.readFile(path.join(out, name), "utf8");
  return txt.split(/\r?\n/).filter(Boolean).map((line) => JSON.parse(line));
}
function clean(v) {
  if (v === undefined) return null;
  if (v === null || ["string", "number", "boolean"].includes(typeof v)) return v;
  return JSON.stringify(v);
}
function rowsFor(records, cols) {
  return [cols.map((x) => x.label), ...records.map((r) => cols.map((x) => clean(x.get(r))))];
}
function putTable(sheet, name, matrix, widths = []) {
  const height = matrix.length;
  const width = matrix[0]?.length ?? 1;
  const endCol = colName(width);
  const range = `A1:${endCol}${height}`;
  sheet.getRange(range).values = matrix;
  sheet.showGridLines = false;
  sheet.freezePanes.freezeRows(1);
  sheet.getRange(`A1:${endCol}${height}`).format.font = { name: "Aptos", size: 10, color: "#263238" };
  sheet.getRange(`A1:${endCol}${height}`).format.verticalAlignment = "center";
  sheet.getRange(`A1:${endCol}1`).format.fill = "#17365D";
  sheet.getRange(`A1:${endCol}1`).format.font = { bold: true, color: "#FFFFFF", name: "Aptos", size: 10 };
  sheet.getRange(range).format.wrapText = true;
  sheet.getRange(range).format.autofitRows();
  for (const [col, widthValue] of widths) {
    sheet.getRange(`${col}:${col}`).format.columnWidth = widthValue;
  }
  if (height > 1) sheet.tables.add(range, true, name);
}
function colName(n) {
  let s = "";
  while (n > 0) {
    const rem = (n - 1) % 26;
    s = String.fromCharCode(65 + rem) + s;
    n = Math.floor((n - 1) / 26);
  }
  return s;
}
function putSummary(sheet, title, note, matrix) {
  sheet.showGridLines = false;
  sheet.getRange("A1").values = [[title]];
  sheet.getRange("A1").format.font = { name: "Aptos", size: 15, bold: true, color: "#17365D" };
  sheet.getRange("A2").values = [[note]];
  sheet.getRange("A2").format.font = { name: "Aptos", size: 10, italic: true, color: "#52616B" };
  const width = matrix[0]?.length ?? 1;
  const end = colName(width);
  const range = `A4:${end}${3 + matrix.length}`;
  sheet.getRange(range).values = matrix;
  sheet.getRange(`A4:${end}4`).format.fill = "#DCE6F1";
  sheet.getRange(`A4:${end}4`).format.font = { name: "Aptos", size: 10, bold: true, color: "#17365D" };
  sheet.getRange(range).format.wrapText = true;
  sheet.getRange(range).format.verticalAlignment = "center";
  sheet.getRange(range).format.autofitRows();
  sheet.getRange("A:A").format.columnWidth = 42;
  sheet.getRange("B:B").format.columnWidth = 70;
}
async function exportAndVerify(workbook, filename, expectedSheets, checks = []) {
  const target = path.join(out, filename);
  const xlsx = await SpreadsheetFile.exportXlsx(workbook);
  await xlsx.save(target);
  const reopened = await SpreadsheetFile.importXlsx(await FileBlob.load(target));
  const inspection = await reopened.inspect({ kind: "sheet", include: "id,name", maxChars: 6000 });
  const str = inspection.ndjson ?? JSON.stringify(inspection);
  for (const sheet of expectedSheets) {
    if (!str.includes(sheet)) throw new Error(`${filename}: missing sheet ${sheet} after reopen`);
  }
  for (const check of checks) {
    const sheet = reopened.worksheets.getItem(check.sheet);
    const values = sheet.getRange(check.range).values;
    if (!check.test(values)) throw new Error(`${filename}: reopened content validation failed at ${check.sheet}!${check.range}`);
  }
  return { file: filename, bytes: (await fs.stat(target)).size, reopened: true, sheets: expectedSheets };
}

const [inventory, matrix, gov, species, baseline, eligibility, retrieval, readiness, metrics, crosswalk] = await Promise.all([
  jsonl("source_inventory_records.jsonl"),
  jsonl("source_admission_approval_matrix.jsonl"),
  jsonl("government_data_source_records.jsonl"),
  json("species_source_coverage.json"),
  json("baseline_reconciliation.json"),
  jsonl("question_eligibility_v3.jsonl"),
  jsonl("retrieval_results_v3_final.jsonl"),
  json("rag_evaluation_readiness.json"),
  json("evaluation_metrics_v3_final.json"),
  json("source_crosswalk_overlay.json"),
]);

const speciesLookup = Object.fromEntries(species.species.map((x) => [x.species, x]));
const inventoryWb = Workbook.create();
let sh = inventoryWb.worksheets.add("Summary");
const dup = new Set(inventory.filter((x) => x.duplicate_sha256_group).map((x) => x.duplicate_sha256_group)).size;
putSummary(sh, "六魚種既有來源盤點", "內容訊號只用於定位候選段落。未完成來源核准、版本及適用性審查的資料不列為可索引證據。", [
  ["項目", "實際盤點"],
  ["來源檔案", inventory.length],
  ["不同 SHA-256", new Set(inventory.map((x) => x.checksum_sha256).filter(Boolean)).size],
  ["重複 checksum 群組", dup],
  ["Publisher 未核實", inventory.filter((x) => !x.publisher).length],
  ["來源版本未核實", inventory.filter((x) => !x.version).length],
  ["URL 未核實", inventory.filter((x) => !x.url).length],
  ["新增來源 Admission", 0],
  ["新版 Corpus v3", "未建立"],
  ["新版 RAG 可用之魚種專屬技術來源", "0 份已核准"],
  ["既有 DGBAS 2020 Admission", "保留原限縮範圍；尚未進入 Corpus"],
]);
sh = inventoryWb.worksheets.add("Source_Inventory");
const invCols = [
  { label: "記錄 ID", get: (x) => x.source_record_id }, { label: "Source ID", get: (x) => x.source_id },
  { label: "文件／資源名稱", get: (x) => x.title }, { label: "發布者", get: (x) => x.publisher || "UNVERIFIED" },
  { label: "原始路徑", get: (x) => x.original_path }, { label: "來源 URL", get: (x) => x.url },
  { label: "版本", get: (x) => x.version || "UNVERIFIED" }, { label: "生效／統計日期", get: (x) => x.effective_date },
  { label: "SHA-256", get: (x) => x.checksum_sha256 }, { label: "格式", get: (x) => x.content_parse?.file_format },
  { label: "大小 bytes", get: (x) => x.file_size_bytes }, { label: "頁數", get: (x) => x.content_parse?.page_count },
  { label: "可抽取頁", get: (x) => x.content_parse?.nonempty_pages }, { label: "空白／不可抽取頁", get: (x) => x.content_parse?.empty_pages },
  { label: "解析文字字元", get: (x) => x.content_parse?.total_extracted_characters },
  { label: "魚種內容定位訊號", get: (x) => x.content_species_signals },
  { label: "類別內容定位訊號", get: (x) => x.content_category_signals },
  { label: "使用／准入狀態", get: (x) => x.admission_status }, { label: "Parser", get: (x) => x.content_parse?.parser },
  { label: "解析警示", get: (x) => x.content_parse?.parse_error || x.parsing_quality?.scope },
];
putTable(sh, "SourceInventory", rowsFor(inventory, invCols), [["A", 18], ["B", 28], ["C", 48], ["D", 24], ["E", 55], ["F", 55], ["G", 32], ["H", 24], ["I", 68], ["P", 38], ["Q", 30], ["R", 48], ["T", 50]]);
sh = inventoryWb.worksheets.add("Species_Coverage");
const speciesRows = species.species.map((x) => [x.species, x.candidate_source_records, x.verified_species_specific_admitted_sources,
  x.sources.map((s) => `${s.source_id || "unverified"} | ${s.title} | pages=${(s.content_pages || []).join(",")} | ${s.admission_status}`).join("\n"),
  "候選文字/標題定位；非適用性核驗"]);
putTable(sh, "SpeciesCoverage", [["目標魚種", "候選來源檔", "新版已准入專屬技術來源", "定位候選及狀態", "判讀限制"], ...speciesRows], [["A", 18], ["B", 16], ["C", 18], ["D", 90], ["E", 46]]);
sh = inventoryWb.worksheets.add("Government_Data");
const govCols = [
  { label: "Source ID", get: (x) => x.source_id }, { label: "名稱", get: (x) => x.title },
  { label: "發布者", get: (x) => x.publisher }, { label: "官方資料集頁", get: (x) => x.landing_url },
  { label: "資源 URL", get: (x) => (x.resource_urls || []).join("\n") }, { label: "下載狀態", get: (x) => x.download_status },
  { label: "授權", get: (x) => x.license }, { label: "授權依據 URL", get: (x) => x.license_url },
  { label: "Metadata 更新", get: (x) => x.metadata_updated }, { label: "資源範圍", get: (x) => x.scope },
  { label: "版本限制", get: (x) => x.version_limitations }, { label: "已正式 Admission", get: (x) => x.formal_admitted },
  { label: "阻塞", get: (x) => x.blocker },
];
putTable(sh, "GovernmentData", rowsFor(gov, govCols), [["A", 34], ["B", 48], ["C", 32], ["D", 50], ["E", 74], ["F", 28], ["G", 36], ["H", 45], ["I", 28], ["J", 70], ["K", 62], ["L", 18], ["M", 58]]);
sh = inventoryWb.worksheets.add("Parse_Quality");
const parseCols = [
  { label: "記錄 ID", get: (x) => x.source_record_id }, { label: "名稱", get: (x) => x.title },
  { label: "路徑", get: (x) => x.original_path }, { label: "格式", get: (x) => x.content_parse?.file_format },
  { label: "頁數", get: (x) => x.content_parse?.page_count }, { label: "可抽取頁", get: (x) => x.content_parse?.nonempty_pages },
  { label: "空白／不可抽取頁", get: (x) => x.content_parse?.empty_pages }, { label: "解析字元", get: (x) => x.content_parse?.total_extracted_characters },
  { label: "候選魚種頁", get: (x) => x.content_parse?.species_candidate_pages },
  { label: "CSV 欄位", get: (x) => x.content_parse?.csv_columns },
  { label: "Parser／錯誤", get: (x) => `${x.content_parse?.parser || ""} ${x.content_parse?.parse_error || ""}` },
  { label: "解析限制", get: (x) => x.parsing_quality?.scope || "Not a semantic, table or rights validation" },
];
putTable(sh, "ParseQuality", rowsFor(inventory, parseCols), [["A", 18], ["B", 48], ["C", 55], ["D", 18], ["I", 40], ["J", 55], ["K", 42], ["L", 50]]);

const inventoryWorkbookResult = await exportAndVerify(inventoryWb, "source_inventory_six_species.xlsx",
  ["Summary", "Source_Inventory", "Species_Coverage", "Government_Data", "Parse_Quality"], [
    { sheet: "Source_Inventory", range: "A1:A2", test: (v) => v[1][0] === inventory[0].source_record_id },
  ]);

const approvalWb = Workbook.create();
sh = approvalWb.worksheets.add("Summary");
const decisions = await jsonl("source_admission_decisions.jsonl");
const dCounts = new Map();
for (const d of matrix) dCounts.set(d.new_corpus_admission_decision, (dCounts.get(d.new_corpus_admission_decision) || 0) + 1);
putSummary(sh, "來源准入決策矩陣", "本表是逐件核准資料，不代表來源已准入。DGBAS 2020 僅保留既有狹義 Admission。", [
  ["決策狀態", "檔案數"], ...[...dCounts.entries()].map(([k, v]) => [k, v]),
  ["新來源已准入", 0], ["DGBAS 2020 已准入範圍", "2020 單年度描述性 Fact；Corpus inclusion = not_ingested"],
  ["Corpus v3 建置核准", "未核准；本輪未建置"], ["Owner Decision 欄", "請研究負責人逐件填寫；目前狀態 Pending"]
]);
sh = approvalWb.worksheets.add("Admission_Matrix");
const matrixCols = [
  { label: "來源記錄", get: (x) => x.source_record_id }, { label: "Source ID", get: (x) => x.source_id },
  { label: "來源名稱", get: (x) => x.title }, { label: "發布者", get: (x) => x.publisher },
  { label: "檔案路徑", get: (x) => x.original_path }, { label: "官方 URL", get: (x) => x.url },
  { label: "版本／日期", get: (x) => x.version }, { label: "SHA-256", get: (x) => x.checksum_sha256 },
  { label: "授權／使用依據", get: (x) => `${x.attribution_or_license || ""} ${x.license_url || ""}` },
  { label: "候選魚種", get: (x) => x.expected_species_and_categories?.species_candidates },
  { label: "候選類別", get: (x) => x.expected_species_and_categories?.category_candidates },
  { label: "准入現況", get: (x) => x.current_admission_status },
  { label: "新增 Corpus 決策狀態", get: (x) => x.new_corpus_admission_decision },
  { label: "待補條件", get: (x) => x.risk_and_blockers }, { label: "建議可處理範圍", get: (x) => x.candidate_allowed_processing_scope },
  { label: "Owner Decision", get: (x) => x.owner_decision },
];
putTable(sh, "AdmissionMatrix", rowsFor(matrix, matrixCols), [["A", 18], ["B", 28], ["C", 48], ["D", 28], ["E", 58], ["F", 54], ["G", 30], ["H", 68], ["I", 60], ["J", 38], ["K", 28], ["L", 48], ["M", 48], ["N", 76], ["O", 64], ["P", 40]]);
sh = approvalWb.worksheets.add("Crosswalk_Overlay");
const fixes = crosswalk.phase_u_applied_corrections || [];
putTable(sh, "CrosswalkOverlay", [["Source key", "Source ID", "正確資源身分", "URL", "拆離錯誤文件", "Phase U 修正", "准入狀態", "限制"],
  ...fixes.map((x) => [x.source_key, x.source_id, x.registered_resource, x.url, x.detached_wrong_document, x.correction, x.admission_status, x.content_version_status])], [["A", 58], ["C", 46], ["D", 56], ["E", 50], ["F", 80], ["G", 22], ["H", 48]]);
sh = approvalWb.worksheets.add("Decision_Guide");
putTable(sh, "DecisionGuide", [
  ["核准欄位", "審查問題", "本輪狀態"],
  ["來源身分", "原始文件／資源、發布者、版本與 checksum 是否可追溯？", "逐來源記錄；缺項標示 UNVERIFIED"],
  ["處理依據", "授權或法律依據是否涵蓋保存、解析、索引、展示及研究用途？", "不以公開可讀或研究決策代替授權判定"],
  ["內容範圍", "明確允許納入哪些內容、頁面、欄位與用途？", "待研究負責人逐項決策"],
  ["適用性", "文件原文支持哪些物種、情境、類別與題目？", "候選定位不代表已驗證"],
  ["Corpus 建置", "來源是否可正式 Admission，且 Corpus v3 建置另行核准？", "兩者為不同決策；目前均未批准新來源／建置"],
  ["DGBAS 2020", "是否維持原核准範圍？", "是；2020 Fact only，not_ingested"],
]);
const approvalWorkbookResult = await exportAndVerify(approvalWb, "source_admission_approval_matrix.xlsx",
  ["Summary", "Admission_Matrix", "Crosswalk_Overlay", "Decision_Guide"], [
    { sheet: "Admission_Matrix", range: "A1:A2", test: (v) => v[1][0] === matrix[0].source_record_id },
  ]);

const evalWb = Workbook.create();
sh = evalWb.worksheets.add("Gate_Status");
const phaseGateRows = [
  ["Gate", "狀態", "實際結果"],
  ["1 Reranker", "歷史 PASS；本輪未重跑", "Phase T 已驗證正確模型 revision"],
  ["2 Source coverage", "FAIL", "新來源 Admission 0；DGBAS 2020 不足以支援六魚種專業題"],
  ["3 System integration", "PARTIAL / 新版 E2E 未執行", "tests/ suite pass；新 Corpus 未建，無新 retrieval/generation"],
  ["4 Question eligibility", "FAIL", "Phase T 指定 Corpus eligibility 0/180，Phase U 未重算成 pass"],
  ["180 questions", "NOT READY", "180 ineligible for answer-scored run"],
  ["New retrieval", "NOT RUN", "0/180"],
  ["New generation", "NOT RUN", "0/720"],
  ["Model metrics", "NOT EVALUATED", "all N=0; no weighted score or winner"],
];
putTable(sh, "GateStatus", phaseGateRows, [["A", 28], ["B", 34], ["C", 92]]);
sh = evalWb.worksheets.add("Question_Eligibility");
const qCols = [
  { label: "Question ID", get: (x) => x.question_id }, { label: "魚種", get: (x) => x.species },
  { label: "類別", get: (x) => x.category }, { label: "問題", get: (x) => x.question_text },
  { label: "答案已核驗", get: (x) => x.answer_verified }, { label: "指定 Corpus 證據", get: (x) => x.evidence_in_designated_corpus },
  { label: "歷史 T Gate", get: (x) => x.gate_status }, { label: "歷史檢索結果", get: (x) => x.retrieval_outcome },
  { label: "U 新資格", get: (x) => x.phase_u_benchmark_eligible }, { label: "U 狀態", get: (x) => x.phase_u_status },
  { label: "阻塞原因", get: (x) => x.failed_gate_reasons },
];
putTable(sh, "QuestionEligibility", rowsFor(eligibility, qCols), [["A", 24], ["B", 16], ["C", 22], ["D", 64], ["G", 38], ["H", 38], ["J", 48], ["K", 78]]);
sh = evalWb.worksheets.add("Metrics");
const metricRows = Object.entries(metrics.metrics).map(([name, value]) => [name, value.value, value.n, value.status, value.reason]);
putTable(sh, "MetricStatus", [["指標", "結果", "N", "狀態", "原因"], ...metricRows], [["A", 36], ["B", 18], ["C", 12], ["D", 24], ["E", 92]]);
sh = evalWb.worksheets.add("Historical_Reference");
putTable(sh, "HistoricalReference", [["Phase T 歷史欄位", "值", "解讀"],
  ["候選 chunks", 1502, "不是正式 Corpus v3"], ["有完整 reranked Top-5 題數", 20, "歷史候選檢索；不作為 Phase U 新結果"],
  ["無候選題數", 160, "Phase T 來源範圍門控"], ["Gate v3 eligible", 0, "Phase T 基線，未追溯改寫"],
  ["Historical RAG-ready", 25, "維持原始歷史定義"], ["新 Corpus v3", "未建立", "本輪准入／建置門停止"],
  ["Human Gold", 0, "未執行人工審查"], ["Winner", null, "不進行模型比較"]]);
const evalWorkbookResult = await exportAndVerify(evalWb, "fish_test_evaluation_v3_final.xlsx",
  ["Gate_Status", "Question_Eligibility", "Metrics", "Historical_Reference"], [
    { sheet: "Question_Eligibility", range: "A1:A2", test: (v) => v[1][0] === eligibility[0].question_id },
    { sheet: "Metrics", range: "A1:A2", test: (v) => v[1][0] === "faithfulness" },
  ]);

const result = { status: "PASS", workbooks: [inventoryWorkbookResult, approvalWorkbookResult, evalWorkbookResult],
  verification: "Each workbook was exported, reopened through artifact-tool, worksheet names checked, and representative cells read back.",
  no_formulas_required: true, no_model_scores_fabricated: true };
await fs.writeFile(path.join(out, "workbook_validation.json"), JSON.stringify(result, null, 2) + "\n", "utf8");
console.log(JSON.stringify(result, null, 2));
