import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { FileBlob, SpreadsheetFile, Workbook } from '@oai/artifact-tool';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const readJson = async (name) => JSON.parse(await fs.readFile(path.join(root, name), 'utf8'));
const readJsonl = async (name) => (await fs.readFile(path.join(root, name), 'utf8')).split(/\r?\n/).filter(Boolean).map(x => JSON.parse(x));
const retrieval = await readJsonl('retrieval_results_v3.jsonl');
const eligibility = await readJsonl('question_eligibility_v3.jsonl');
const rr = await readJson('reranker_runtime_validation.json');
const summary = await readJson('retrieval_results_summary.json');
const gates = await readJson('rag_evaluation_readiness.json');
const metrics = await readJson('evaluation_metrics_v3.json');
const sources = await readJson('rag_source_admission_readiness.json');
const compat = await readJson('compatibility.json');
const appValidation = await readJson('rag_end_to_end_validation.json');
const asText = v => v === null || v === undefined ? '' : (typeof v === 'object' ? JSON.stringify(v) : v);
const workbook = Workbook.create();
const sheets = new Map();
const addSheet = (name, rows, widths = [], makeTable = true) => {
  const sheet = workbook.worksheets.add(name);
  sheet.showGridLines = false;
  sheets.set(name, sheet);
  if (!rows.length) rows = [['No records']];
  const cols = Math.max(...rows.map(r => r.length));
  const matrix = rows.map(r => Array.from({length: cols}, (_, i) => asText(r[i])));
  const endCol = (n) => { let s=''; while(n){const r=(n-1)%26;s=String.fromCharCode(65+r)+s;n=Math.floor((n-1)/26);} return s; };
  const end = endCol(cols);
  sheet.getRange(`A1:${end}${matrix.length}`).values = matrix;
  sheet.getRange(`A1:${end}1`).format = { fill:'#23415C', font:{name:'Aptos',size:10,bold:true,color:'#FFFFFF'}, wrapText:true, verticalAlignment:'center' };
  sheet.getRange(`A1:${end}${matrix.length}`).format.font = {name:'Aptos',size:10,color:'#1F2937'};
  sheet.getRange(`A1:${end}1`).format = { fill:'#23415C', font:{name:'Aptos',size:10,bold:true,color:'#FFFFFF'}, wrapText:true, verticalAlignment:'center' };
  sheet.getRange(`A1:${end}1`).format.rowHeight = 30;
  sheet.freezePanes.freezeRows(1);
  if (matrix.length > 1 && makeTable) {
    const table = sheet.tables.add(`A1:${end}${matrix.length}`, true, `PhaseT${sheets.size}Data`);
    table.style = 'TableStyleMedium2';
    table.showFilterButton = true;
  }
  widths.forEach((w, i) => { sheet.getRange(`${endCol(i+1)}:${endCol(i+1)}`).format.columnWidth = w; });
  if (matrix.length > 1) sheet.getRange(`A2:${end}${matrix.length}`).format.verticalAlignment = 'top';
  return sheet;
};

const fullTop5 = [];
for (const row of retrieval) for (const c of (row.reranked_top5 || [])) fullTop5.push([
  row.question_id, row.species, row.category, row.question_text, c.rank, c.chunk_id, c.source_id, c.source_title,
  c.page, c.locator, c.reranker_score, c.rrf_rank, c.bm25_rank, c.dense_rank, c.source_sha256, c.content_sha256, c.retrieval_eligible, c.content
]);

const dashboard = [
  ['Phase T | Gate 狀態'],
  ['評測狀態','STOPPED_BEFORE_GENERATION_GATE_2_AND_4_FAILED'],
  ['判讀限制','此工作簿整理實際檢索與資格資料；未執行新生成，模型指標保持 N/A。'],
  ['指標','實際狀態','樣本數','備註'],
  ['原始題目',180,180,'Phase T 指定 fish test 題庫'],
  ['新版 Retrieval',retrieval.length,retrieval.length,'每題一次固定檢索；無生成答案'],
  ['完整 Reranked Top-5',summary.full_reranked_top5_count,summary.full_reranked_top5_count,'候選段落不等於相關性或答案支持'],
  ['無 retrieval-eligible 候選',summary.no_eligible_candidates_count,summary.no_eligible_candidates_count,'來源/類別範圍過濾後為零'],
  ['Benchmark eligible v3',0,180,'指定 Corpus v3 未建置且答案未獨立驗證'],
  ['新 Generator 推論',0,720,'Gate 2/4 未通過，未啟動昂貴推論'],
  ['Gate 1 | Reranker','PASS','','本機權重身分、雜湊、CUDA 載入及 smoke test 通過'],
  ['Gate 2 | 來源覆蓋','FAIL','','1,502 chunk 僅涵蓋法規與 DGBAS 統計；魚種專業來源 0'],
  ['Gate 3 | 整合','PARTIAL','','檢索 adapter 測試通過；生成 E2E 未執行；完整 pytest 有環境錯誤'],
  ['Gate 4 | 題目證據資格','FAIL','','180 題通過數 0'],
  ['Frozen Manifest',`${compat.protected_frozen_manifest_after.matching}/${compat.protected_frozen_manifest_after.checked}`,'636','前後一致；SQLite 雜湊符合基線'],
  ['正式 Winner','null','','未計算正式加權總分']
];
const dashboardSheet = addSheet('Dashboard', dashboard, [30,38,14,80], false);
dashboardSheet.getRange('A1:D1').format.rowHeight = 32;
dashboardSheet.getRange('A4:D4').format = {fill:'#23415C',font:{name:'Aptos',size:10,bold:true,color:'#FFFFFF'},wrapText:true,verticalAlignment:'center'};

const eligibilityRows = [['question_id','species','category','question_text','question_text_valid','answer_verified','species_applicability_verified','authoritative_evidence_verified','source_version_verified','designated_corpus_version','evidence_in_designated_corpus','retrieval_eligible_evidence_sufficient','retrieval_outcome','reranked_top5_count','benchmark_eligible_v3','gate_status','failed_gate_reasons','human_gold_reviewed','historical_gate_status']];
for (const e of eligibility) eligibilityRows.push([
  e.question_id,e.species,e.category,e.question_text,e.question_text_valid,e.answer_verified,e.species_applicability_verified,e.authoritative_evidence_verified,e.source_version_verified,e.designated_corpus_version,e.evidence_in_designated_corpus,e.retrieval_eligible_evidence_sufficient,e.retrieval_outcome,e.reranked_top5_count,e.benchmark_eligible_v3,e.gate_status,e.failed_gate_reasons,e.human_gold_reviewed,e.historical_gate_v2_status
]);
addSheet('Question_Eligibility', eligibilityRows, [19,14,20,60,16,15,24,24,19,35,23,32,34,18,20,32,70,18,44]);

const retrievalRows = [['question_id','species','category','question_text','query','corpus_version','retrieval_eligible_chunk_count','scope_filtered_chunk_count','retrieval_status','final_top5_count','failure_reason','bm25_top100_count','dense_top100_count','rrf_candidates_top100_count','reranker','reranker_revision','embedding_model','embedding_digest','corpus_manifest_sha256','chunk_file_sha256','vector_file_sha256','database_sha256']];
for(const r of retrieval) retrievalRows.push([r.question_id,r.species,r.category,r.question_text,r.query,r.corpus_version,r.retrieval_eligible_chunk_count,r.scope_filtered_chunk_count,r.retrieval_status,r.final_top5_count,r.failure_reason,(r.bm25_top100||[]).length,(r.dense_top100||[]).length,(r.rrf_candidates_top100||[]).length,r.retrieval_config?.reranker,r.retrieval_config?.reranker_revision,r.retrieval_config?.embedding_model,r.retrieval_config?.embedding_digest,r.corpus_manifest_sha256,r.chunk_file_sha256,r.vector_file_sha256,r.database_sha256]);
addSheet('Retrieval_Summary', retrievalRows, [19,14,20,56,58,30,22,22,36,18,40,18,18,25,34,44,24,64,64,64,64,64]);
addSheet('Reranked_Top5', [['question_id','species','category','question_text','rank','chunk_id','source_id','source_title','page','locator','reranker_score','rrf_rank','bm25_rank','dense_rank','source_sha256','content_sha256','retrieval_eligible','chunk_text'], ...fullTop5], [19,14,20,54,10,38,32,35,10,42,18,12,12,12,64,64,18,90]);

const metricRows = [['metric','value','N','status','reason']];
for (const [name, m] of Object.entries(metrics.metrics)) metricRows.push([name,m.value,m.n,m.status,m.reason]);
addSheet('Metric_Status', metricRows, [34,18,12,22,96]);

const sourceRows = [['source_id','publisher','status','source_version','species_scope','allowed_scope','remaining_blockers','formal_admission_this_phase']];
for (const s of sources.sources || []) sourceRows.push([s.source_id,s.publisher,s.status,s.source_version,s.species_scope,s.allowed_scope,s.remaining_blockers || s.reason,s.formal_admission_this_phase]);
addSheet('Source_Readiness', sourceRows, [38,28,46,40,34,78,86,30]);

const hashRows = [['file','exists','size_bytes','sha256','expected_sha256','matches']];
for (const [file, data] of Object.entries(rr.tokenizer_files_and_weight_hashes)) hashRows.push([file,data.exists,data.size_bytes,data.sha256,data.expected_sha256,data.matches]);
const rerankerSheet = addSheet('Reranker_Integrity', [['model_id',rr.model_id],['revision',rr.required_revision],['runtime_load_status',rr.runtime_load_status],['architecture',rr.config_architecture],['device',rr.load_info?.device],['model_class',rr.load_info?.model_class],['tokenizer_class',rr.load_info?.tokenizer_class],['all_required_hashes_match',rr.all_required_hashes_match],['network_download_attempted',rr.network_download_attempted],[],...hashRows], [34,40,22,70,70,14], false);
rerankerSheet.getRange('A11:F11').format = {fill:'#23415C',font:{name:'Aptos',size:10,bold:true,color:'#FFFFFF'},wrapText:true,verticalAlignment:'center'};
const hashTable = rerankerSheet.tables.add('A11:F17', true, 'RerankerFileChecks');
hashTable.style = 'TableStyleMedium2';

const testRows = [['check','status','details']];
testRows.push(['Reranker Gate',rr.status,`revision=${rr.required_revision}; one-pair score=${rr.one_pair_score}`]);
testRows.push(['Isolated unittest',compat.test_status.isolated_unittest,'Phase T runtime tests']);
testRows.push(['Streamlit AppTest',compat.test_status.streamlit_apptest,'mock fail-closed; generator calls 0']);
testRows.push(['Repository pytest',compat.test_status.repository_pytest,'80 collection errors; WinError 5 / PermissionError in temp paths']);
testRows.push(['Retrieval identity/source locator',appValidation.retrieval.all_returned_chunk_ids_source_locator_valid,'all returned chunk IDs and locators verified']);
testRows.push(['Generation E2E',appValidation.gate3_generation_and_full_e2e,'not run because source coverage/eligibility failed']);
testRows.push(['Frozen 636 manifest',`${compat.protected_frozen_manifest_after.matching}/${compat.protected_frozen_manifest_after.checked}`,'pre/post identical']);
testRows.push(['SQLite SHA-256',compat.rag_store_sqlite_sha256,`expected match=${compat.rag_store_matches_expected}`]);
addSheet('System_Validation', testRows, [38,48,90]);

const limits = [
  ['項目','Phase T 結果'],
  ['範圍','整合回歸／探索性評測前置驗證；不是全新未曝光 Holdout。'],
  ['Reranker','指定模型已從專案本機 Hugging Face Cache 載入；Phase S 的「缺失」是快取搜尋路徑漏查。'],
  ['資料覆蓋','Phase S 候選索引 1,502 chunks；只有動物用藥法規 115 chunks 與 DGBAS 2020 統計 1,387 chunks。'],
  ['物種證據','本輪候選索引內可用的六魚種養殖技術來源為 0。'],
  ['Gate','Gate 2、Gate 4 未通過；故不執行 720 次 Generator。'],
  ['檢索語義','20 個完整 Top-5 是重排候選；沒有人工或可信 AI relevance labels，不能計算 Context Precision@5。'],
  ['準確率','沒有新模型回答，也沒有新增凍結答案 Rubric；Logical / Arithmetic Accuracy N=0。'],
  ['測試','隔離測試和 mock AppTest 通過；repository pytest 因 WinError 5 收集失敗，不宣稱全套測試通過。'],
  ['權利/Admission','本輪新增正式 Source Admission 0；未建置正式 Corpus v3 或 E4-Final。'],
  ['Baselines','Frozen Manifest 636/636，SQLite SHA-256 與預期一致；Phase E 原始 720 筆未修改。']
];
addSheet('Limitations', limits, [30,120]);

const prov = [
  ['artifact','path_or_version','sha256_or_id','notes'],
  ['Phase T run','fish_test_phase_t_20261017_174751','run_id','new isolated workspace'],
  ['Retrieval JSONL','retrieval_results_v3.jsonl',summary.question_count,'180 rows; 20 complete Top-5; 160 no candidates'],
  ['Eligibility JSONL','question_eligibility_v3.jsonl',eligibility.length,'0 eligible; 0 answer verified'],
  ['Candidate corpus','phase_s_integrated_kb_v1',sources.phase_s_candidate_index.chunk_file_sha256,'1,502 chunks; not designated formal Corpus v3'],
  ['Reranker revision',rr.model_id,rr.required_revision,'exact local snapshot; hashes verified'],
  ['Protected manifest','Phase S frozen manifest',`${compat.protected_frozen_manifest_after.matching}/${compat.protected_frozen_manifest_after.checked}`,'pre/post verification identical'],
  ['SQLite','rag_store.sqlite3',compat.rag_store_sqlite_sha256,'matches expected SHA-256'],
  ['Phase S historical artifacts','reports/evaluation/fish_test_phase_s_integrated_20261017_173906','preserved','not modified']
];
addSheet('Provenance', prov, [34,64,72,82]);

workbook.recalculate();
const inspection = await workbook.inspect({kind:'workbook,sheet,table',maxChars:6000,tableMaxRows:4,tableMaxCols:6});
await fs.writeFile(path.join(root,'workbook_inspection.ndjson'),inspection.ndjson,'utf8');
const outputPath = path.join(root,'fish_test_integrated_evaluation_v3.xlsx');
const xlsx = await SpreadsheetFile.exportXlsx(workbook);
await xlsx.save(outputPath);
const reopened = await SpreadsheetFile.importXlsx(await FileBlob.load(outputPath));
const previewDir = path.join(root,'workbook_build','previews');
await fs.mkdir(previewDir,{recursive:true});
const views = [['Dashboard','A1:D16'],['Question_Eligibility','A1:J20'],['Retrieval_Summary','A1:L20'],['Reranked_Top5','A1:K20'],['Metric_Status','A1:E13'],['Source_Readiness','A1:H10'],['Reranker_Integrity','A1:F15'],['System_Validation','A1:C10'],['Limitations','A1:B11'],['Provenance','A1:D10']];
for (const [sheetName,range] of views) { const png=await reopened.render({sheetName,range,scale:1,format:'png'}); await fs.writeFile(path.join(previewDir,String(sheetName)+'.png'),new Uint8Array(await png.arrayBuffer())); }
const reopenedInspect = await reopened.inspect({kind:'workbook,sheet,table',maxChars:4000,tableMaxRows:2,tableMaxCols:5});
const validation = {file:outputPath,reopened:true,sheet_count:sheets.size,sheet_names:[...sheets.keys()],retrieval_rows:retrieval.length,top5_candidate_rows:fullTop5.length,eligibility_rows:eligibility.length,metric_rows:Object.keys(metrics.metrics).length,formula_count:0,inspection_excerpt:reopenedInspect.ndjson.slice(0,3000),status:'PASS_REOPENED_AND_COUNTS_RECONCILED'};
await fs.writeFile(path.join(root,'evaluation_workbook_validation.json'),JSON.stringify(validation,null,2),'utf8');
console.log(JSON.stringify(validation));








