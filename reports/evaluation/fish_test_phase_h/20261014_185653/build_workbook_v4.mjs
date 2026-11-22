import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { SpreadsheetFile, Workbook } from '@oai/artifact-tool';

const outDir = path.dirname(fileURLToPath(import.meta.url));
const payload = JSON.parse(await fs.readFile(path.join(outDir, 'workbook_payload_v4.json'), 'utf8'));
const wb = Workbook.create();
const sheets = new Map();
const color = { navy:'#174A7E', text:'#1F2937' };
function colLetter(n) { let s=''; while(n>0){const r=(n-1)%26;s=String.fromCharCode(65+r)+s;n=Math.floor((n-1)/26);}return s; }
function safeTableName(name){return `T_${name.replace(/[^A-Za-z0-9]/g,'').slice(0,24)}`;}
function defaultWidth(h){
 const x=String(h).toLowerCase();
 if(x.includes('sha256')||x.includes('digest')||x.includes('checksum'))return 68;
 if(x.includes('url')||x.includes('locator')||x.includes('source'))return 48;
 if(/question_text|context_text|raw_output|answer|reason|blocker|interpretation|limitation|provenance|rubric|evidence|excerpt/.test(x))return 58;
 if(/id|model|version|status|category|species|rank|page|count|_n$/.test(x))return 22;
 return 18;
}
for(const spec of payload.sheets){
 const sh=wb.worksheets.add(spec.name); sheets.set(spec.name,sh); sh.showGridLines=false; sh.freezePanes.freezeRows(1);
 const matrix=[spec.headers,...spec.rows]; const endCol=colLetter(spec.headers.length); const endRow=matrix.length;
 sh.getRange(`A1:${endCol}${endRow}`).values=matrix;
 sh.getRange(`A1:${endCol}1`).format={fill:color.navy,font:{name:'Arial',size:10,bold:true,color:'#FFFFFF'},horizontalAlignment:'center',verticalAlignment:'center',wrapText:true};
 sh.getRange(`A1:${endCol}1`).format.rowHeight=42;
 if(endRow>1){sh.getRange(`A2:${endCol}${endRow}`).format={font:{name:'Arial',size:9,color:color.text},verticalAlignment:'top',wrapText:true};sh.getRange(`A2:${endCol}${endRow}`).format.rowHeight=30;}
 const custom=spec.widths||{};
 spec.headers.forEach((h,i)=>{const c=colLetter(i+1);sh.getRange(`${c}1:${c}${Math.max(endRow,2)}`).format.columnWidth=Number(custom[c]||defaultWidth(h));});
 if(endRow>1){const table=sh.tables.add(`A1:${endCol}${endRow}`,true,safeTableName(spec.name));table.style='TableStyleMedium2';table.showFilterButton=true;}
}

// Independent formula check for every question: a P@5 value appears only when all five labels are binary.
const cp=sheets.get('Context_Precision');
const cpSpec=payload.sheets.find(x=>x.name==='Context_Precision');
const cpRows=cpSpec.rows.length+1;
for(let row=2;row<=cpRows;row++){
 cp.getRange(`S${row}`).formulas=[[`=IF(AND(COUNTIF(D${row}:H${row},"INCOMPLETE")+COUNTIF(D${row}:H${row},"ANNOTATION_ERROR")+COUNTIF(D${row}:H${row},"SOURCE_MISSING")+COUNTIF(D${row}:H${row},"UNCERTAIN")=0,COUNTIF(D${row}:H${row},"RELEVANT")+COUNTIF(D${row}:H${row},"IRRELEVANT")=5),COUNTIF(D${row}:H${row},"RELEVANT")/5,"")`]];
}
cp.getRange(`M2:O${cpRows}`).format.numberFormat='0.000';
cp.getRange(`S2:S${cpRows}`).format.numberFormat='0.000';

// Descriptive chart only; no composite score and no winner implication.
const dashboard=sheets.get('Dashboard');
const compSpec=payload.sheets.find(x=>x.name==='Model_Comparison');
const heads=compSpec.headers; const mi=heads.indexOf('model_id'); const mei=heads.indexOf('metric'); const vi=heads.indexOf('value');
const chartMetrics=['BGE-M3 Answer Relevance Cosine','Structured Output Valid Rate','Arithmetic Diagnostic Accuracy'];
const chartData=[['Exploratory metric','M1','M2','M3','M4']];
for(const metric of chartMetrics){
 const row=[metric];
 for(const mid of ['M1','M2','M3','M4']){
  const found=compSpec.rows.find(r=>r[mi]===mid&&r[mei]===metric);
  row.push(found?.[vi]??null);
 }
 chartData.push(row);
}
dashboard.getRange('F1:J4').values=chartData;
dashboard.getRange('F1:J1').format={fill:color.navy,font:{name:'Arial',size:10,bold:true,color:'#FFFFFF'},wrapText:true};
dashboard.getRange('F1:F20').format.columnWidth=40;
dashboard.getRange('G1:J20').format.columnWidth=14;
const chart=dashboard.charts.add('bar',dashboard.getRange('F1:J4'));
chart.title='Existing and diagnostic metrics (descriptive only; N differs)';
chart.setPosition('F6','N23');
chart.legend={position:'top',textStyle:{typeface:'Arial',fontSize:10}};
chart.xAxis={axisType:'textAxis',textStyle:{typeface:'Arial',fontSize:9}};
chart.yAxis={numberFormatCode:'0.0',numberFormatSourceLinked:false,textStyle:{typeface:'Arial',fontSize:9}};

await wb.recalculate();
const target=path.join(outDir,'fish_test_evaluation_results_v4.xlsx');
const xlsx=await SpreadsheetFile.exportXlsx(wb); await xlsx.save(target);
const previews=path.join(outDir,'previews_v4'); await fs.mkdir(previews,{recursive:true});
for(const spec of payload.sheets){const preview=await wb.render({sheetName:spec.name,range:'A1:H10',scale:0.7,format:'png'});await fs.writeFile(path.join(previews,`${spec.name}.png`),new Uint8Array(await preview.arrayBuffer()));}
await fs.writeFile(path.join(outDir,'artifact_tool_authoring_receipt_v4.json'),JSON.stringify({output:target,sheet_names:payload.sheets.map(x=>x.name),question_rows:cpSpec.rows.length,context_rows:payload.sheets.find(x=>x.name==='Context_Annotation_QA').rows.length,formula_rechecks:cpSpec.rows.length,chart_count:dashboard.charts.items.length,rendered_sheet_previews:payload.sheets.length,export_complete:true},null,2)+'\n','utf8');
console.log(JSON.stringify({output:target,sheets:payload.sheets.length,formulas:cpSpec.rows.length,chart_count:dashboard.charts.items.length,previews:payload.sheets.length}));
