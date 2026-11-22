import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { SpreadsheetFile, Workbook } from '@oai/artifact-tool';

const outDir = path.dirname(fileURLToPath(import.meta.url));
const payload = JSON.parse(await fs.readFile(path.join(outDir, 'workbook_payload.json'), 'utf8'));
const wb = Workbook.create();
const sheets = new Map();
const color = { navy: '#174A7E', stripe: '#EEF3F8', text: '#1F2937' };

function colLetter(n) {
  let s = '';
  while (n > 0) { const r = (n - 1) % 26; s = String.fromCharCode(65 + r) + s; n = Math.floor((n - 1) / 26); }
  return s;
}
function safeTableName(name) { return `T_${name.replace(/[^A-Za-z0-9]/g, '').slice(0, 24)}`; }
function defaultWidth(header) {
  const h = String(header).toLowerCase();
  if (h.includes('sha256') || h.includes('digest') || h.includes('checksum')) return 68;
  if (h.includes('url') || h.includes('locator') || h.includes('source')) return 46;
  if (/question_text|generated_answer|reference_answer|support_quote|reason|rubric|limitation|criteria|unsupported|error|labels|operands|numeric_parse/.test(h)) return 54;
  if (/id|model_tag|version|status|category|species|annotator|method|protocol|formula/.test(h)) return 25;
  return 18;
}

for (const spec of payload.sheets) {
  const sheet = wb.worksheets.add(spec.name);
  sheets.set(spec.name, sheet);
  sheet.showGridLines = false;
  sheet.freezePanes.freezeRows(1);
  const headers = spec.headers;
  const matrix = [headers, ...spec.rows];
  const endCol = colLetter(headers.length);
  const endRow = matrix.length;
  sheet.getRange(`A1:${endCol}${endRow}`).values = matrix;
  sheet.getRange(`A1:${endCol}1`).format = {
    fill: color.navy,
    font: { name: 'Arial', size: 10, bold: true, color: '#FFFFFF' },
    horizontalAlignment: 'center',
    verticalAlignment: 'center',
    wrapText: true,
  };
  if (endRow > 1) {
    sheet.getRange(`A2:${endCol}${endRow}`).format = {
      font: { name: 'Arial', size: 10, color: color.text },
      verticalAlignment: 'top',
      wrapText: true,
    };
    sheet.getRange(`A2:${endCol}${endRow}`).format.rowHeight = 36;
  }
  sheet.getRange(`A1:${endCol}1`).format.rowHeight = 42;
  const custom = spec.widths || {};
  headers.forEach((h, i) => {
    const col = colLetter(i + 1);
    sheet.getRange(`${col}1:${col}${Math.max(endRow, 2)}`).format.columnWidth = Number(custom[col] || defaultWidth(h));
  });
  if (endRow > 1) {
    const table = sheet.tables.add(`A1:${endCol}${endRow}`, true, safeTableName(spec.name));
    table.style = 'TableStyleMedium2';
    table.showFilterButton = true;
  }
}

// Formula rechecks are independent spreadsheet calculations over the populated detail sheets.
const dashboard = sheets.get('Dashboard');
const comparison = sheets.get('Model_Comparison');
const existing = sheets.get('Existing_Metrics');
const ctx = sheets.get('Context_Precision');
const arithmetic = sheets.get('Arithmetic_Accuracy');
const logical = sheets.get('Logical_Accuracy');
const specsByName = Object.fromEntries(payload.sheets.map(s => [s.name, s]));
const modelRows = specsByName.Model_Comparison.rows;
const modelIndex = specsByName.Model_Comparison.headers.indexOf('model_id');
const metricIndex = specsByName.Model_Comparison.headers.indexOf('metric');
const compMetricRow = (metric, model) => {
  const i = modelRows.findIndex(r => r[metricIndex] === metric && r[modelIndex] === model);
  return i >= 0 ? i + 2 : null;
};
const eRows = specsByName.Existing_Metrics.rows.length + 1;
const cRows = specsByName.Context_Precision.rows.length + 1;
const aRows = specsByName.Arithmetic_Accuracy.rows.length + 1;
const lRows = specsByName.Logical_Accuracy.rows.length + 1;
const eHeads = specsByName.Existing_Metrics.headers;
const eCol = name => colLetter(eHeads.indexOf(name) + 1);
const aHeads = specsByName.Arithmetic_Accuracy.headers;
const aCol = name => colLetter(aHeads.indexOf(name) + 1);
const lHeads = specsByName.Logical_Accuracy.headers;
const lCol = name => colLetter(lHeads.indexOf(name) + 1);
const dashRows = payload.sheets.find(s => s.name === 'Dashboard').rows;
const dHeaders = payload.sheets.find(s => s.name === 'Dashboard').headers;
const dMetric = dHeaders.indexOf('Metric');
const dModel = dHeaders.indexOf('Model');
for (let i = 0; i < dashRows.length; i++) {
  const row = dashRows[i];
  const metric = row[dMetric];
  const model = row[dModel];
  const excelRow = i + 2;
  let formula = null;
  if (metric === 'Shared Context Precision@5') {
    formula = `=IFERROR(AVERAGE(Context_Precision!$H$2:$H$${cRows}),"")`;
  } else if (['M1','M2','M3','M4'].includes(model)) {
    const modelCell = `$B${excelRow}`;
    if (metric === 'Judge Faithfulness') formula = `=IFERROR(AVERAGEIF(Existing_Metrics!$B$2:$B$${eRows},${modelCell},Existing_Metrics!$${eCol('judge_faithfulness')}$2:$${eCol('judge_faithfulness')}$${eRows}),"")`;
    if (metric === 'Judge Answer Relevance') formula = `=IFERROR(AVERAGEIF(Existing_Metrics!$B$2:$B$${eRows},${modelCell},Existing_Metrics!$${eCol('judge_answer_relevance')}$2:$${eCol('judge_answer_relevance')}$${eRows}),"")`;
    if (metric === 'BGE-M3 cosine') formula = `=IFERROR(AVERAGEIF(Existing_Metrics!$B$2:$B$${eRows},${modelCell},Existing_Metrics!$${eCol('bge_m3_answer_relevance_cosine')}$2:$${eCol('bge_m3_answer_relevance_cosine')}$${eRows}),"")`;
    if (metric === 'Structured output valid rate') formula = `=IFERROR(COUNTIFS(Existing_Metrics!$B$2:$B$${eRows},${modelCell},Existing_Metrics!$${eCol('schema_valid')}$2:$${eCol('schema_valid')}$${eRows},TRUE)/COUNTIF(Existing_Metrics!$B$2:$B$${eRows},${modelCell}),"")`;
    if (metric === 'TTFT visible content seconds') formula = `=IFERROR(AVERAGEIF(Existing_Metrics!$B$2:$B$${eRows},${modelCell},Existing_Metrics!$${eCol('ttft_seconds')}$2:$${eCol('ttft_seconds')}$${eRows}),"")`;
    if (metric === 'TPS') formula = `=IFERROR(AVERAGEIF(Existing_Metrics!$B$2:$B$${eRows},${modelCell},Existing_Metrics!$${eCol('tps')}$2:$${eCol('tps')}$${eRows}),"")`;
    if (metric === 'Arithmetic Accuracy — self-contained arithmetic diagnostic') formula = `=IFERROR(COUNTIFS(Arithmetic_Accuracy!$B$2:$B$${aRows},${modelCell},Arithmetic_Accuracy!$${aCol('arithmetic_status')}$2:$${aCol('arithmetic_status')}$${aRows},"correct")/(COUNTIFS(Arithmetic_Accuracy!$B$2:$B$${aRows},${modelCell},Arithmetic_Accuracy!$${aCol('arithmetic_status')}$2:$${aCol('arithmetic_status')}$${aRows},"correct")+COUNTIFS(Arithmetic_Accuracy!$B$2:$B$${aRows},${modelCell},Arithmetic_Accuracy!$${aCol('arithmetic_status')}$2:$${aCol('arithmetic_status')}$${aRows},"incorrect")),"")`;
    if (metric === 'Logical Accuracy') formula = `=IFERROR(COUNTIFS(Logical_Accuracy!$B$2:$B$${lRows},${modelCell},Logical_Accuracy!$${lCol('status')}$2:$${lCol('status')}$${lRows},"correct")/(COUNTIFS(Logical_Accuracy!$B$2:$B$${lRows},${modelCell},Logical_Accuracy!$${lCol('status')}$2:$${lCol('status')}$${lRows},"correct")+COUNTIFS(Logical_Accuracy!$B$2:$B$${lRows},${modelCell},Logical_Accuracy!$${lCol('status')}$2:$${lCol('status')}$${lRows},"incorrect")),"")`;
  }
  if (formula) dashboard.getRange(`F${excelRow}`).formulas = [[formula]];
}
dashboard.getRange(`C2:C${dashRows.length + 1}`).format.numberFormat = '0.0000';
dashboard.getRange(`F2:F${dashRows.length + 1}`).format.numberFormat = '0.0000';

// A compact descriptive chart highlights accuracy/format measures without implying a winner.
const chartMatrix = [['Exploratory metric','M1','M2','M3','M4']];
for (const metric of ['Structured output valid rate','Arithmetic Accuracy — self-contained arithmetic diagnostic','BGE-M3 cosine']) {
  const values = ['M1','M2','M3','M4'].map(mid => {
    const row = compMetricRow(metric, mid);
    return row ? `=Model_Comparison!$C$${row}` : null;
  });
  chartMatrix.push([metric, ...values]);
}
dashboard.getRange('H1:L4').values = chartMatrix.map(r => r.map(v => typeof v === 'string' && v.startsWith('=') ? null : v));
dashboard.getRange('I2:L4').formulas = chartMatrix.slice(1).map(r => r.slice(1));
dashboard.getRange('H1:L1').format = { fill: color.navy, font: { name:'Arial', size:10, bold:true, color:'#FFFFFF' }, wrapText:true };
dashboard.getRange('H1:L4').format.wrapText = true;
dashboard.getRange('H1:H50').format.columnWidth = 34;
dashboard.getRange('I1:L50').format.columnWidth = 13;
const chart = dashboard.charts.add('bar', dashboard.getRange('H1:L4'));
chart.title = 'Exploratory accuracy and format rates (N differs; descriptive only)';
chart.setPosition('H6','Q23');
chart.legend = { position:'top', textStyle:{ typeface:'Arial', fontSize:10 } };
chart.xAxis = { axisType:'textAxis', textStyle:{ typeface:'Arial', fontSize:10 } };
chart.yAxis = { numberFormatCode:'0%', numberFormatSourceLinked:false, textStyle:{ typeface:'Arial', fontSize:10 } };

await wb.recalculate();
const target = path.join(outDir, 'fish_test_evaluation_results_v3.xlsx');
const xlsx = await SpreadsheetFile.exportXlsx(wb);
await xlsx.save(target);
const previewsDir = path.join(outDir, 'previews');
await fs.mkdir(previewsDir, { recursive:true });
for (const spec of payload.sheets) {
  const sh = sheets.get(spec.name);
  const preview = await wb.render({ sheetName:spec.name, range:'A1:H10', scale:0.7, format:'png' });
  await fs.writeFile(path.join(previewsDir, `${spec.name}.png`), new Uint8Array(await preview.arrayBuffer()));
}
await fs.writeFile(path.join(outDir, 'artifact_tool_authoring_receipt.json'), JSON.stringify({
  output:target,
  sheet_names:payload.sheets.map(s=>s.name),
  formula_rechecks:dashRows.length,
  chart_count:dashboard.charts.items.length,
  rendered_sheet_previews:payload.sheets.length,
  export_complete:true,
},null,2)+'\n','utf8');
console.log(JSON.stringify({output:target, sheets:payload.sheets.length, chart_count:dashboard.charts.items.length, rendered_previews:payload.sheets.length}));
