import fs from 'node:fs/promises';
import { FileBlob, SpreadsheetFile, Workbook } from '@oai/artifact-tool';

const outputDir = 'C:/my project/115_marine_project/reports/evaluation/fish_test_phase_o_ai_adjudication_20261016_211742';
const readJson = async (name) => JSON.parse(await fs.readFile(`${outputDir}/${name}`, 'utf8'));
const readJsonl = async (name) => (await fs.readFile(`${outputDir}/${name}`, 'utf8')).split(/\r?\n/).filter(Boolean).map((x) => JSON.parse(x));
const payload = await readJson('workbook_payload_v5.json');
const fullContexts = await readJsonl('context_adjudication_900_status.jsonl');
const judgeA = await readJsonl('judge_a_results.jsonl');
const judgeB = await readJsonl('judge_b_results.jsonl');
const judgeC = await readJsonl('arbiter_results.jsonl');
const profiles = await readJsonl('question_requirement_profiles.jsonl');

const wb = Workbook.create();
const sheetNames = [
  'Dashboard', 'AI_Adjudication', 'Context_900', 'P5_180', 'Profiles_180',
  'Support_Checks', 'Judge_Calls', 'Reference_Verification', 'Accuracy_Status', 'Limitations_Provenance',
];
const sheets = Object.fromEntries(sheetNames.map((n) => [n, wb.worksheets.add(n)]));
const jsonCell = (x) => x == null ? null : (typeof x === 'object' ? JSON.stringify(x) : x);
const colLetter = (n) => { let s = ''; while (n > 0) { const r = (n - 1) % 26; s = String.fromCharCode(65 + r) + s; n = Math.floor((n - 1) / 26); } return s; };
const writeTable = (sheet, title, headers, rows, tableName, widths = {}) => {
  sheet.showGridLines = false;
  sheet.getRange('A1').values = [[title]];
  sheet.getRange('A1').format.font = { name: 'Arial', size: 14, bold: true, color: '#17365D' };
  const headerRow = 3;
  const lastCol = colLetter(headers.length);
  sheet.getRange(`A${headerRow}:${lastCol}${headerRow}`).values = [headers];
  if (rows.length) sheet.getRange(`A${headerRow + 1}:${lastCol}${headerRow + rows.length}`).values = rows;
  sheet.getRange(`A${headerRow}:${lastCol}${headerRow}`).format = {
    fill: '#1F4E78', font: { name: 'Arial', size: 10, bold: true, color: '#FFFFFF' },
    horizontalAlignment: 'center', verticalAlignment: 'center', wrapText: true,
  };
  sheet.getRange(`A${headerRow}:${lastCol}${headerRow}`).format.rowHeight = 32;
  const used = sheet.getRange(`A${headerRow}:${lastCol}${Math.max(headerRow + rows.length, headerRow)}`);
  used.format.font = { name: 'Arial', size: 10, color: '#1F2937' };
  used.format.verticalAlignment = 'center';
  for (const [col, width] of Object.entries(widths)) sheet.getRange(`${col}:${col}`).format.columnWidth = width;
  if (rows.length) {
    const tbl = sheet.tables.add(`A${headerRow}:${lastCol}${headerRow + rows.length}`, true, tableName);
    tbl.showFilterButton = true;
    tbl.showBandedColumns = false;
  }
  sheet.freezePanes.freezeRows(headerRow);
};

// Dashboard: concise, auditable stop decision and core counts.
const dash = sheets.Dashboard;
dash.showGridLines = false;
dash.getRange('A1').values = [['Phase O — AI Evidence Adjudication & Remaining Metrics']];
dash.getRange('A1').format.font = { name: 'Arial', size: 15, bold: true, color: '#17365D' };
dash.getRange('A2').values = [['執行標記：AI_ADJUDICATED；NOT_HUMAN_GOLD；探索性，非正式模型評分']];
dash.getRange('A2').format.font = { name: 'Arial', size: 10, italic: true, color: '#5B6573' };
const p5 = payload.p5;
const comp = payload.compatibility;
const dashRows = [
  ['項目', '實際結果', '說明'],
  ['題目／檢索段落', '180 題／900 段', '身分／Chunk／Rank／文字 checksum 900/900；來源 metadata verified 且 retrieval-eligible 389/900；511 pending'],
  ['來源適用性預檢', '389/900 可檢索', '439 筆 source-scope conflict candidates（可能與其他狀態重疊）；checksum 對帳不代表適用性已通過'],
  ['去重深審案例', '123', 'Phase M 28、Phase N 高風險 63、固定試點 60 去重後'],
  ['Judge A / B', `${payload.summary.judge_a_valid_unique}/123；${payload.summary.judge_b_valid_unique}/123 有效`, `A/B 共同有效 120；分歧 80（${(payload.summary.a_b_disagreement_rate * 100).toFixed(1)}%）`],
  ['第三模型仲裁', `${payload.summary.arbiter_completed}/114`, '首批 10 筆後出現可重現無證據 Relevant，依停止條件停批'],
  ['Accepted Relevant', '0', '所有 Relevant 候選未通過反向證據／魚種適用性 Gate'],
  ['可計算精確 P@5', `${p5.exact_p5_question_count}/180`, '沒有足夠的五段有效二元標籤；平均 N/A'],
  ['Logical Accuracy 新增有效 N', '0', '沒有來源支持且可重現的 Logical Rubric'],
  ['Arithmetic verified N 新增', '0', '既有公式來源核驗數為 0；不升格舊診斷分數'],
  ['Human Gold', '0', '全部 AI 輔助／AI 仲裁，沒有人工覆核'],
  ['900 段擴大', '未執行', '因第三模型在明確物種不符段落誤判 Relevant 而停止'],
  ['Frozen Manifest', `${comp.frozen_status_counts?.unchanged ?? 0}/636 unchanged`, `SQLite SHA-256 match: ${comp.sqlite_matches_expected}`],
  ['Winner', '未選擇', '未執行正式模型評分或加權排名'],
];
dash.getRange(`A4:C${3 + dashRows.length}`).values = dashRows;
dash.getRange(`A4:C4`).format = { fill: '#1F4E78', font: { name: 'Arial', size: 10, bold: true, color: '#FFFFFF' }, horizontalAlignment: 'center' };
dash.getRange(`A4:C${3 + dashRows.length}`).format.font = { name: 'Arial', size: 10, color: '#1F2937' };
dash.getRange('A4:C4').format = { fill: '#1F4E78', font: { name: 'Arial', size: 10, bold: true, color: '#FFFFFF' }, horizontalAlignment: 'center' };
dash.getRange('A:A').format.columnWidth = 28;
dash.getRange('B:B').format.columnWidth = 34;
dash.getRange('C:C').format.columnWidth = 84;
dash.getRange(`A4:C${3 + dashRows.length}`).format.verticalAlignment = 'center';
dash.getRange(`C5:C${3 + dashRows.length}`).format.wrapText = true;
dash.freezePanes.freezeRows(4);


// Case-level final adjudication with raw judge replies embedded for traceability.
const adjHeaders = ['question_id','chunk_id','rank','case_sets','question_text','target_species','category','source_id','source_title','source_version','source_verified','corpus_version','retrieval_eligible','judge_a_label','judge_b_label','arbiter_label','final_label','decision_status','a_b_disagreement','final_reason','reverse_support_gate','judge_a_model','judge_a_digest','judge_a_prompt_id','judge_a_raw_reply','judge_b_model','judge_b_digest','judge_b_prompt_id','judge_b_raw_reply','arbiter_model','arbiter_digest','arbiter_prompt_id','arbiter_raw_reply','context_sha256','human_gold_reviewed'];
const adjRows = payload.adjudications.map((x) => [x.question_id,x.chunk_id,x.rank,jsonCell(x.case_sets),x.question_text,x.target_species,x.category,x.source_id,x.source_title,x.source_version,x.source_verified,x.corpus_version,x.retrieval_eligible_in_corpus,x.judge_a_label,x.judge_b_label,x.arbiter_label,x.final_label,x.decision_status,x.a_b_disagreement,x.final_reason,x.reverse_support_gate ? JSON.stringify(x.reverse_support_gate) : null,x.judge_a_model,x.judge_a_model_digest,x.judge_a_prompt_id,x.judge_a_raw_reply,x.judge_b_model,x.judge_b_model_digest,x.judge_b_prompt_id,x.judge_b_raw_reply,x.arbiter_model,x.arbiter_model_digest,x.arbiter_prompt_id,x.arbiter_raw_reply,x.context_text_sha256,x.human_gold_reviewed]);
writeTable(sheets.AI_Adjudication, '去重案例 AI 仲裁與停止後狀態', adjHeaders, adjRows, 'AIAdjudicationTable', {A:20,B:34,D:48,E:58,F:14,G:22,H:24,I:44,J:32,N:18,O:18,P:18,Q:20,R:42,T:68,U:56,Y:60,AC:60,AG:64,AH:68});

const ctxHeaders = ['question_id','chunk_id','rank','final_label','adjudication_status','judge_a_label','judge_b_label','arbiter_label','annotation_method','human_gold_reviewed','context_sha256'];
const ctxRows = fullContexts.map((x) => [x.question_id,x.chunk_id,x.rank,x.final_label,x.adjudication_status,x.judge_a_label,x.judge_b_label,x.arbiter_label,x.annotation_method,x.human_gold_reviewed,x.context_sha256]);
writeTable(sheets.Context_900, '900 段狀態；未執行者保留空白標籤', ctxHeaders, ctxRows, 'ContextStatus900', {A:20,B:34,D:22,E:48,K:68});

const p5Rows = payload.questions.map((x) => [x.question_id,x.species,x.category,x.context_count,x.relevant_count,x.uncertain_count,x.unrun_count,x.p_at_5,x.lower_bound,x.upper_bound,x.status,x.human_gold]);
writeTable(sheets.P5_180, 'Question-level AI-adjudicated P@5（未完成不填0）', ['question_id','species','category','top5_rows','relevant_n','uncertain_n','not_run_n','P@5','lower_bound','upper_bound','status','human_gold'], p5Rows, 'P5QuestionTable', {A:20,B:14,C:24,K:34});

const profileHeaders = ['question_id','target_species','category','question_text','required_answer_elements','required_values_or_ranges','required_units','required_conditions','applicability_constraints','source_version_requirements','profile_method','candidate_cues_status','needs_review'];
const profileRows = profiles.map((x) => [x.question_id,x.target_species,x.question_category,x.question_text,jsonCell(x.required_answer_elements),jsonCell(x.required_values_or_ranges),jsonCell(x.required_units),jsonCell(x.required_conditions),jsonCell(x.applicability_constraints),x.source_version_requirements,x.requirement_profile_method,x.candidate_scoring_cues_status,x.profile_needs_review]);
writeTable(sheets.Profiles_180, '180 題 Requirement Profiles（未參考 M1–M4 生成答案）', profileHeaders, profileRows, 'QuestionProfiles180', {A:20,B:14,C:24,D:66,E:48,F:38,G:26,H:32,I:60,J:58,K:52,L:40});

const supHeaders = ['question_id','chunk_id','rank','arbiter_label','span_ids','span_ids_valid','selected_span_text','profile_complete','required_elements','required_values','exact_matches','matched_claims_locatable','target_species','source_species_labels','other_species_terms','scope_conflict','species_mismatch','source_verified','source_version','direct_support_gate','reason'];
const supRows = payload.support_checks.map((x) => [x.question_id,x.chunk_id,x.rank,x.arbiter_label,jsonCell(x.span_ids),x.span_ids_valid,x.selected_span_text,x.question_requirement_profile_complete,jsonCell(x.required_answer_elements),jsonCell(x.required_values_or_ranges),jsonCell(x.exact_requirement_matches),jsonCell(x.matched_claims_locatable_verbatim),x.target_species,jsonCell(x.source_species_labels_detected),jsonCell(x.explicit_other_species_terms_in_chunk),x.source_scope_conflict_candidate,x.species_specific_mismatch_candidate,x.source_verified,x.source_version,x.direct_support_gate,x.reason]);
writeTable(sheets.Support_Checks, '所有 Relevant 候選的反向原文支持檢查', supHeaders, supRows, 'SupportChecksTable', {A:20,B:34,G:60,I:42,J:34,K:42,L:48,U:80});

const allCalls = [
  ...judgeA.map((x) => ({...x, role_for_sheet:'Judge A'})),
  ...judgeB.map((x) => ({...x, role_for_sheet:'Judge B'})),
  ...judgeC.map((x) => ({...x, role_for_sheet:'Third-model arbiter'})),
];
const callHeaders = ['role','question_id','chunk_id','rank','call_status','label','model','model_digest','prompt_id','prompt_version','attempt_count','validation_errors','call_error','raw_reply','created_at','context_text_sha256'];
const callRows = allCalls.map((x) => [x.role_for_sheet,x.question_id,x.chunk_id,x.rank,x.call_status,x.parsed_result?.relevance_label ?? null,x.model,x.model_digest,x.prompt_id,x.prompt_version,x.attempt_count,jsonCell(x.validation_errors),x.call_error,x.raw_reply,x.created_at,x.context_text_sha256]);
writeTable(sheets.Judge_Calls, 'AI Judge 原始呼叫紀錄（含錯誤與未通過解析的回覆）', callHeaders, callRows, 'JudgeCallsTable', {A:22,B:20,C:34,E:22,H:68,I:34,J:48,L:46,M:58,N:72,O:32,P:68});

const refHeaders = ['question_id','verification_status','source_id','source_title','source_url','source_version','answer_supported','exact_support_span','species_applicability','blocker_reason','phase_o_status','phase_o_new_source_verified','human_gold_reviewed'];
const refs = payload.reference_verification.map((x) => [x.question_id,x.verification_status,x.source_id,x.source_title,x.source_url,x.source_version,x.answer_supported,x.exact_support_span,x.species_applicability,x.blocker_reason,x.phase_o_answer_reverification_status,x.phase_o_new_source_verified,x.human_gold_reviewed]);
writeTable(sheets.Reference_Verification, '候選答案來源核驗（保留 Phase G 狀態；Phase O 未重核）', refHeaders, refs, 'ReferenceVerificationTable', {A:20,B:30,C:24,D:44,E:54,F:36,H:64,J:56,K:48});

const accRows = [
  ['指標','Phase O 新有效 N','Phase O 新正確 N','Phase O 新準確率','舊診斷／限制'],
  ['Logical Accuracy',0,0,null,'Phase G source-supported rubric = 0；Phase O 因標註品質停止未評分'],
  ['Source-verified Arithmetic Accuracy',0,0,null,'Phase G formula source verified = 0；不將題幹算術診斷升格'],
  ['M2 舊 Arithmetic diagnostic',null,null,null,'Phase G 曾列 N=23，15 correct；非本輪、非來源核驗 Gold，本輪不重算'],
  ['Human Gold',0,null,null,'尚無研究者人工覆核紀錄'],
];
writeTable(sheets.Accuracy_Status, 'Logical／Arithmetic 新評分狀態', accRows[0], accRows.slice(1), 'AccuracyStatusTable', {A:42,B:22,C:22,D:24,E:94});

const limitRows = [
  ['範圍','狀態／決策','細節'],
  ['AI 標籤層級','AI_ADJUDICATED；NOT_HUMAN_GOLD','A=Gemma2 9B；B=Qwen2.5-Coder 7B（code-tuned）；C=Mistral Nemo 12B local。不同模型家族非專家真值。'],
  ['評審獨立性','有限制','Judge A 與候選 M4 同 digest；Judge B 與候選 M2 同 digest；未提供任何生成答案，但模型角色重疊。C 為本機第三模型，非外部服務。'],
  ['第三模型停止','已觸發品質停止','FT-eel-Q11 問鰻魚，來源段落明確為午仔魚，來源 metadata 又偵測石斑魚；Mistral 誤稱鰻魚資料並給錯數值。'],
  ['900 段','未完成','只有123個去重深審案例有 A/B 呼叫；仲裁只完成10/114，其他777個原始 Context 未跑。'],
  ['來源適用性預檢','389/900 可檢索','511筆 metadata/eligibility pending；439筆 scope-conflict 候選（可能重疊）；checksum 不代表適用性通過。'],
  ['P@5','0/180 可精確計算','至少一個未判、Uncertain、Error 或 Relevant 尚未通過逆向支持檢查的題目，不會被填成0。'],
  ['Answer verification','未新增核驗','Phase G 180 題為78來源不可得、102證據不足、0來源自動核驗通過；Phase O 停止後未重新核驗答案。'],
  ['Logical / Arithmetic','新增有效 N=0','Logic rubric 仍缺；公式來源驗證仍為0。'],
  ['模型結果','未重跑 M1–M4','沿用原720生成，沒有正式總分或 Winner。'],
  ['Frozen baseline','636/636 unchanged','SQLite digest 符合既定值；Corpus/E4/Production 均未變。'],
];
writeTable(sheets.Limitations_Provenance, '方法、限制與追溯來源', limitRows[0], limitRows.slice(1), 'LimitationsTable', {A:28,B:40,C:110});

// Apply clean defaults only to populated regions, then render and export.
for (const name of sheetNames) {
  const sh = sheets[name];
  const used = sh.getUsedRange();
  if (used) used.format.font = { name: 'Arial', size: 10, color: '#1F2937' };
}
// Restore title/header emphasis after defaults.
for (const name of sheetNames.slice(1)) {
  const sh = sheets[name];
  sh.getRange('A1').format.font = { name: 'Arial', size: 14, bold: true, color: '#17365D' };
  const used = sh.getUsedRange();
  const cols = used?.columnCount ?? 1;
  const letter = colLetter(cols);
  sh.getRange(`A3:${letter}3`).format = { fill: '#1F4E78', font: { name: 'Arial', size: 10, bold: true, color: '#FFFFFF' }, horizontalAlignment: 'center', verticalAlignment: 'center', wrapText: true };
}
dash.getRange('A1').format.font = { name: 'Arial', size: 15, bold: true, color: '#17365D' };
dash.getRange('A2').format.font = { name: 'Arial', size: 10, italic: true, color: '#5B6573' };
dash.getRange('A4:C4').format = { fill: '#1F4E78', font: { name: 'Arial', size: 10, bold: true, color: '#FFFFFF' }, horizontalAlignment: 'center', verticalAlignment: 'center' };
wb.recalculate();
const preview = await wb.render({ sheetName: 'Dashboard', range: 'A1:C17', scale: 1, format: 'png' });
await fs.writeFile(`${outputDir}/dashboard_preview.png`, new Uint8Array(await preview.arrayBuffer()));
const xlsx = await SpreadsheetFile.exportXlsx(wb);
await xlsx.save(`${outputDir}/fish_test_evaluation_results_ai_v5.xlsx`);

// Reload and validate workbook structure and key record counts.
const reloaded = await SpreadsheetFile.importXlsx(await FileBlob.load(`${outputDir}/fish_test_evaluation_results_ai_v5.xlsx`));
const inspection = await reloaded.inspect({kind:'workbook,sheet,table',maxChars:12000,tableMaxRows:3,tableMaxCols:8,tableMaxCellChars:60});
await fs.writeFile(`${outputDir}/workbook_v5_reopen_validation.json`, JSON.stringify({sheet_names:sheetNames,adjudication_rows:adjRows.length,context_rows:ctxRows.length,p5_question_rows:p5Rows.length,profile_rows:profileRows.length,judge_call_rows:callRows.length,reference_rows:refs.length,inspection:inspection.ndjson ?? String(inspection)},null,2)+'\n','utf8');
console.log(JSON.stringify({output:`${outputDir}/fish_test_evaluation_results_ai_v5.xlsx`,sheets:sheetNames,adjudicationRows:adjRows.length,contextRows:ctxRows.length,p5Rows:p5Rows.length,judgeCalls:callRows.length}));
