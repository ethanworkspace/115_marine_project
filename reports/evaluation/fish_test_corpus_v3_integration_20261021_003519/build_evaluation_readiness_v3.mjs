import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { Workbook, SpreadsheetFile } from "@oai/artifact-tool";

const base = path.dirname(fileURLToPath(import.meta.url));
const data = JSON.parse(await fs.readFile(path.join(base, "workbook_source_data.json"), "utf8"));
const outputPath = path.join(base, "evaluation_readiness_v3.xlsx");
const workbook = Workbook.create();
const navy = "#16324F";
const teal = "#0F766E";
const pale = "#E8F1F2";

function colName(n) {
  let s = "";
  while (n > 0) { const r = (n - 1) % 26; s = String.fromCharCode(65 + r) + s; n = Math.floor((n - 1) / 26); }
  return s;
}
function normalize(value) {
  if (value === undefined || value === null) return null;
  if (typeof value === "object") return JSON.stringify(value);
  return value;
}
function addTableSheet(name, headers, records, tableName, widths = {}) {
  const sheet = workbook.worksheets.add(name);
  const matrix = [headers, ...records.map(r => headers.map(h => normalize(r[h])))];
  const lastCol = colName(headers.length);
  const lastRow = Math.max(1, matrix.length);
  sheet.getRange(`A1:${lastCol}${lastRow}`).values = matrix;
  sheet.getRange(`A1:${lastCol}1`).format = {
    fill: teal,
    font: { bold: true, color: "#FFFFFF", size: 10 },
    wrapText: true,
    verticalAlignment: "center",
  };
  sheet.getRange(`A1:${lastCol}${lastRow}`).format.wrapText = true;
  sheet.getRange(`A1:${lastCol}${lastRow}`).format.verticalAlignment = "top";
  sheet.getRange(`A1:${lastCol}1`).format.rowHeight = 32;
  sheet.freezePanes.freezeRows(1);
  if (records.length) sheet.tables.add(`A1:${lastCol}${lastRow}`, true, tableName);
  for (const [col, width] of Object.entries(widths)) sheet.getRange(`${col}:${col}`).format.columnWidth = width;
  return sheet;
}

const dashRows = [
  ["Isolated research Corpus v3", data.dashboard.corpus_version, "Not production and not Evaluation Corpus v2"],
  ["Corpus database SHA-256", data.dashboard.database_sha256, "Binds retrieval outputs to this database version"],
  ["Admitted sources", data.dashboard.sources, "Three newly approved official data resources plus limited-admitted DGBAS 2020 XML"],
  ["Distinct source SHA-256", data.dashboard.distinct_source_sha256, "Original snapshot files"],
  ["Source records", data.dashboard.source_records, "Includes original records excluded from retrieval"],
  ["Chunks", data.dashboard.chunks, "All chunk rows retained in isolated corpus"],
  ["Retrieval-eligible chunks", data.dashboard.retrieval_eligible_chunks, "Subject to source and scope restrictions"],
  ["Context-only chunks", data.dashboard.context_only_chunks, "Eel stocking rows without a reference year"],
  ["Fish Test questions", data.dashboard.questions, "Original 180 question IDs retained"],
  ["Questions with at least one eligible context", data.dashboard.with_context, "Retrieval coverage, not answer support"],
  ["Questions with full Top-5", data.dashboard.full_top5, "No missing slots were filled"],
  ["Retrieved context rows", data.dashboard.context_rows, "Actual rows returned across 180 questions"],
  ["Full-support diagnostics", data.dashboard.full_support_diagnostics, "No chunk established as complete answer support"],
  ["Exact P@5 eligible questions", data.dashboard.eligible_p5_questions, "No reliable binary relevance gold"],
  ["Logical Accuracy eligible samples", data.dashboard.eligible_logical, "No frozen corpus-supported logical rubric subset"],
  ["Arithmetic Accuracy eligible samples", data.dashboard.eligible_arithmetic, "No verified formula/reference subset"],
  ["Human Gold reviewed", data.dashboard.human_gold, "All current evidence classifications are automated diagnostics"],
  ["Repository pytest", "Not run", "pytest is absent in available Python environments"],
];
const dashboard = workbook.worksheets.add("Dashboard");
dashboard.getRange("A1:C1").merge();
dashboard.getRange("A1").values = [["Corpus v3 evaluation readiness"]];
dashboard.getRange("A1:C1").format = { fill: navy, font: { bold: true, color: "#FFFFFF", size: 16 }, rowHeight: 34, verticalAlignment: "center" };
dashboard.getRange(`A3:C${dashRows.length + 3}`).values = [["Measure", "Result", "Interpretation"], ...dashRows];
dashboard.getRange("A3:C3").format = { fill: teal, font: { bold: true, color: "#FFFFFF" }, wrapText: true };
dashboard.getRange(`A3:C${dashRows.length + 3}`).format.wrapText = true;
dashboard.getRange("A:A").format.columnWidth = 38;
dashboard.getRange("B:B").format.columnWidth = 38;
dashboard.getRange("C:C").format.columnWidth = 72;
dashboard.tables.add(`A3:C${dashRows.length + 3}`, true, "ReadinessSummary");
dashboard.freezePanes.freezeRows(3);

addTableSheet("Source_Registry",
  ["source_id","dataset_id","title","publisher","dataset_url","resource_url","source_sha256","file_size_bytes","owner_admission_status","license_scope_status","identity_status","version_status","applicability_status","completeness_status","processing_scope","record_counts"],
  data.sources,"SourceRegistry",{"A":30,"C":42,"D":34,"E":36,"F":64,"G":68,"I":28,"J":44,"K":42,"L":38,"M":45,"N":38,"O":84,"P":40});

addTableSheet("Species_Coverage",
  ["species","question_count","with_any_context","full_top5","literal_source_chunk_count","eligibility_counts","diagnostic_evidence_status_counts","method"],
  data.species.map(r => ({...r, method:"Literal species-scope terms; not expert validation"})),"SpeciesCoverage",{"A":22,"E":28,"F":30,"G":48,"H":55});

addTableSheet("Question_Eligibility",
  ["question_id","species","category","eligibility_status","retrieval_top5_count","source_candidate_in_corpus","human_gold_status","reason"],
  data.questions,"QuestionEligibility",{"A":25,"B":18,"C":24,"D":34,"G":24,"H":100});

addTableSheet("Retrieval_Coverage",
  ["question_id","species","category","bm25_candidate_count","dense_candidate_count","rrf_candidate_count","rrf_after_record_dedupe","source_scope_pass","source_scope_excluded","reranker_candidate_count","final_top_k","empty_reason","corpus_sha256"],
  data.retrieval,"RetrievalCoverage",{"A":24,"B":18,"C":24,"L":48,"M":68});

addTableSheet("Evidence_Diagnostics",
  ["question_id","rank","chunk_id","source_id","source_record_id","evidence_status","matched_elements","missing_elements","source_applicability_reason","exact_locator","human_or_binary_gold"],
  data.evidence,"EvidenceDiagnostics",{"A":24,"C":34,"D":32,"E":40,"F":24,"I":48,"J":88});

addTableSheet("Prior_References_15",
  ["question_id","species","historical_verification_status","historical_source_id","historical_source_version","source_id_present_in_corpus_v3","revalidation_status","reference_answer_carried_forward","human_gold_status","reason"],
  data.references,"PriorReferenceRevalidation",{"A":24,"B":18,"C":38,"D":34,"E":45,"G":48,"I":22,"J":92});

addTableSheet("Smoke_Tests",
  ["scenario","model_id","model_tag","model_digest","answer_origin","evidence_state","generator_called","citation_status","final_answer_status","error"],
  data.smoke,"SmokeTests",{"A":38,"B":14,"C":54,"D":70,"E":42,"F":34,"H":28,"J":60});

addTableSheet("Quality_Checks",
  ["check","status","detail"],
  data.checks,"QualityChecks",{"A":62,"B":14,"C":110});

const limitations = [
  {issue:"Context Precision@5",status:"NOT_EVALUABLE",reason:"No reliable independent binary relevance labels; deterministic evidence diagnostics and reranker scores are not relevance gold."},
  {issue:"Logical Accuracy",status:"NOT_EVALUABLE",reason:"No corpus-v3 reference answer and frozen source-grounded rubric subset."},
  {issue:"Arithmetic Accuracy",status:"NOT_EVALUABLE",reason:"No corpus-v3 formula, conditions, units, deterministic reference answer and tolerance set verified as a subset."},
  {issue:"Prior 13 automated reference candidates",status:"NOT_REVALIDATED",reason:"Their TFRI manual or FA-385 source IDs are not among the four admitted sources in this Corpus v3. Historical results remain unchanged."},
  {issue:"Animal drug data completeness",status:"UNKNOWN",reason:"The saved official API response contains 9,999 records; the complete dataset extent is not established. No dose or withdrawal inference is allowed."},
  {issue:"Eel stocking data time scope",status:"CONTEXT_ONLY",reason:"The original rows contain no verified reference year; no trends or husbandry facts are inferred."},
  {issue:"Species coverage",status:"LIMITED",reason:"Coverage counts are literal-scope record/chunk indicators, not expert validation of all six species or all requested categories."},
  {issue:"Repository pytest",status:"NOT_RUN",reason:"pytest package is missing from project, reranker, system and bundled Python environments. Collection or pass count is unavailable."},
  {issue:"Model smoke",status:"EXPLORATORY",reason:"One supported real call per model and four pre-generation negative probes; no full 720-call evaluation."},
  {issue:"Human Gold",status:"0",reason:"No human review records were created in this phase."},
];
addTableSheet("Limitations",["issue","status","reason"],limitations,"Limitations",{"A":42,"B":25,"C":110});

const provenanceRows = [
  {item:"Source integrity",value:"official_raw_data_integrity_report.json",detail:"Three original JSON SHA-256 values match the supplied verified snapshots; DGBAS XML revalidated separately."},
  {item:"Source admission",value:"source_admission_v3.json",detail:"Owner admission, OGL v1 scope, identity, version, applicability and retrieval eligibility are separate fields."},
  {item:"Corpus manifest",value:"corpus_v3_manifest.json",detail:"Corpus database SHA-256: " + data.dashboard.database_sha256},
  {item:"Question source",value:"fish_test original normalized question set",detail:"180 IDs retained; question and answers were not inserted as corpus sources."},
  {item:"Retrieval trace",value:"retrieval_results_v3_180.jsonl",detail:"BM25, dense, RRF, reranker, source scope and final Top-5 per question."},
  {item:"Evidence diagnostics",value:"retrieved_context_relevance_labels.jsonl",detail:"792 rows; automated deterministic screening, not Human Gold."},
  {item:"Question qualification",value:"question_eligibility_180.jsonl",detail:"180 rows; 1 partially supported and 179 not evaluable."},
  {item:"Original smoke results",value:"generator_smoke_results.jsonl",detail:"Four real model calls and four negative safety probes; original raw logs retained."},
  {item:"Streamlit check",value:"streamlit_v3_validation.json",detail:"AppTest used Corpus v3 and one real M2 call."},
  {item:"Repository test status",value:"repository_pytest_results.json",detail:"pytest unavailable; no repository pytest pass is claimed."},
  {item:"Frozen baseline",value:"protected_manifest_recheck_post.json",detail:"636/636 unchanged; formal SQLite checksum unchanged."},
  {item:"Evaluation boundary",value:"No 720 generation; no model winner",detail:"Context Precision@5, Logical Accuracy and Arithmetic Accuracy remain N=0."},
];
addTableSheet("Provenance",["item","value","detail"],provenanceRows,"Provenance",{"A":32,"B":52,"C":105});

workbook.recalculate();
const xlsx = await SpreadsheetFile.exportXlsx(workbook);
await xlsx.save(outputPath);
const stats = {
  output: outputPath,
  sheets: workbook.worksheets.items.map(s => s.name),
  sheet_rows: Object.fromEntries(workbook.worksheets.items.map(s => [s.name, s.getUsedRange()?.rowCount ?? 0])),
  question_rows: data.questions.length,
  retrieval_rows: data.retrieval.length,
  evidence_rows: data.evidence.length,
  checks_passed: data.checks.filter(c => c.status === "PASS").length,
};
await fs.writeFile(path.join(base, "workbook_export_validation.json"), JSON.stringify(stats, null, 2) + "\n", "utf8");
console.log(JSON.stringify(stats));
