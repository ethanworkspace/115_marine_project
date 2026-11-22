import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {Workbook, SpreadsheetFile} from '@oai/artifact-tool';

const dir = path.dirname(fileURLToPath(import.meta.url));
const source = JSON.parse(await fs.readFile(path.join(dir, 'weighted_model_selection.json'), 'utf8'));
const wb = Workbook.create();
const rank = wb.worksheets.add('Model_Ranking');
const detail = wb.worksheets.add('Scoring_Detail');
const policy = wb.worksheets.add('Policy_Sensitivity');
const blue = '#243F59';
function base(s, area, title, subtitle) {
  s.showGridLines = false;
  s.getRange(area).format.font = {name:'Arial',size:10,color:'#1E293B'};
  s.getRange(area).format.rowHeight = 22;
  s.getRange('A1').values = [[title]];
  s.getRange('A1').format.font = {name:'Arial',size:16,bold:true,color:blue};
  s.getRange('A2').values = [[subtitle]];
  s.getRange('A2').format.font = {name:'Arial',size:10,color:'#526477'};
  s.freezePanes.freezeRows(4);
}
function header(s, range) {
  s.getRange(range).format = {fill:blue,font:{name:'Arial',bold:true,color:'#FFFFFF'},wrapText:true,horizontalAlignment:'center',verticalAlignment:'center',rowHeight:38};
}
base(rank,'A1:H30','四模型綜合加權選型','品質70%／效能30%｜既有720次結果重算｜探索性選型，非正確率百分比');
base(detail,'A1:K48','分項數值、正規化與加權貢獻','所有最終權重只乘一次；原始分數與有效N保留，未補造缺值');
base(policy,'A1:F31','計分政策與敏感度檢查','70/30由使用者確認；正規化與記憶體代理是本次揭露的選型假設');

detail.getRange('A4:K4').values = [['Metric','Group','Weight','Model','Raw Value','Valid N','Direction','Normalization','Score 0–1','Points /100','Sample Scope']];
const metrics = [...new Set(source.primary.metric_contributions.map(r=>r.metric_id))];
const rows = [];
for (const metric of metrics) for (const model of ['M1','M2','M3','M4']) {
  const r = source.primary.metric_contributions.find(r=>r.model_id===model && r.metric_id===metric);
  const scope = ['logical_task_success','arithmetic_task_success'].includes(metric) ? 'Fixed tasks; content + output validation' : metric==='structured_ifr' ? 'Original JSON; fixed 180' : metric==='context_precision' ? 'Shared exploratory retrieval; weight 0' : metric==='ram' ? 'Sampled system peak mean; GiB' : metric==='vram' ? 'Sampled device peak mean; GiB' : 'Four-model common samples';
  rows.push([r.metric,r.group,r.weight,r.model_id,r.raw_value,r.valid_n,r.direction,r.normalization,null,null,scope]);
}
detail.getRange('A5:K48').values = rows;
for(let i=0;i<rows.length;i++) {
  const rr=i+5, first=Math.floor(i/4)*4+5, last=first+3;
  const mode=rows[i][7];
  const f=mode==='min_over_value' ? `=MIN($E$${first}:$E$${last})/E${rr}` : mode==='value_over_max' ? `=E${rr}/MAX($E$${first}:$E$${last})` : `=MAX(0,MIN(1,E${rr}))`;
  detail.getRange(`I${rr}:J${rr}`).formulas=[[f,`=100*C${rr}*I${rr}`]];
}
detail.getRange('A4:A48').format.columnWidth=35;
detail.getRange('B4:B48').format.columnWidth=15;
detail.getRange('C4:D48').format.columnWidth=10;
detail.getRange('E4:E48').format.columnWidth=14;
detail.getRange('F4:G48').format.columnWidth=10;
detail.getRange('H4:H48').format.columnWidth=22;
detail.getRange('I4:J48').format.columnWidth=14;
detail.getRange('K4:K48').format.columnWidth=45;
detail.getRange('C5:C48').setNumberFormat('0.00%');
detail.getRange('E5:E48').setNumberFormat('0.0000');
detail.getRange('F5:F48').setNumberFormat('0');
detail.getRange('I5:I48').setNumberFormat('0.0000');
detail.getRange('J5:J48').setNumberFormat('0.00');
detail.tables.add('A4:K48',true,'WeightedDetails');
header(detail,'A4:K4');

rank.getRange('A4:G4').values=[['Rank','Model','Model Name','Quality /70','Efficiency /30','Total /100','Weight Check']];
const names={M1:'DeepSeek Qwen 7B',M2:'Qwen2.5-Coder 7B',M3:'DeepSeek Llama 8B',M4:'Gemma2 9B'};
for(let i=0;i<4;i++) {
  const rr=i+5,m=source.primary.ranking[i].model_id;
  rank.getRange(`B${rr}:C${rr}`).values=[[m,names[m]]];
  rank.getRange(`A${rr}`).formulas=[[`=1+COUNTIF($F$5:$F$8,">"&F${rr})`]];
  rank.getRange(`D${rr}:G${rr}`).formulas=[[
    `=SUMIFS(Scoring_Detail!$J$5:$J$48,Scoring_Detail!$D$5:$D$48,B${rr},Scoring_Detail!$B$5:$B$48,"quality")`,
    `=SUMIFS(Scoring_Detail!$J$5:$J$48,Scoring_Detail!$D$5:$D$48,B${rr},Scoring_Detail!$B$5:$B$48,"performance")`,
    `=SUM(D${rr}:E${rr})`,
    `=SUMIF(Scoring_Detail!$D$5:$D$48,B${rr},Scoring_Detail!$C$5:$C$48)`
  ]];
}
rank.getRange('A4:B30').format.columnWidth=10;
rank.getRange('C4:C30').format.columnWidth=24;
rank.getRange('D4:G30').format.columnWidth=17;
rank.getRange('D5:F8').setNumberFormat('0.00');
rank.getRange('G5:G8').setNumberFormat('0%');
rank.tables.add('A4:G8',true,'WeightedRanking');
header(rank,'A4:G4');
rank.getRange('A10').values=[['M2在本次70/30政策排名第一；M4的品質貢獻較高，效能貢獻較低。']];
rank.getRange('A11').values=[['Human Gold＝0；50題依賴10個來源群組／3份原件，不是獨立專家驗證。']];
const chart=rank.charts.add('bar',[rank.getRange('B4:B8'),rank.getRange('F4:F8')]);
chart.setPosition('A13','H28');
chart.title='綜合加權分數（滿分100）';
chart.titleTextStyle.fontSize=12;
chart.titleTextStyle.typeface='Arial';
chart.series.items[0].fill='#315D85';

policy.getRange('A4:F4').values=[['Scoring Check','M1','M2','M3','M4','Top Model']];
const labels={primary:'本次主要70/30政策',content_criterion:'改用來源內容符合率',memory_excluded:'移除記憶體代理分數',minmax_performance:'效能改用min-max正規化'};
const variants=[source.primary,...source.sensitivity];
policy.getRange('A5:F8').values=variants.map(v=>[labels[v.variant],...['M1','M2','M3','M4'].map(m=>v.ranking.find(r=>r.model_id===m).total_out_of_100),v.winner]);
policy.getRange('A4:A31').format.columnWidth=36;
policy.getRange('B4:F31').format.columnWidth=15;
policy.getRange('B5:E8').setNumberFormat('0.00');
policy.tables.add('A4:F8',true,'SensitivityChecks');
header(policy,'A4:F4');
const notes=[
  '品質70%：Faithfulness 17.5%、BGE 17.5%、固定50題任務成功17.5%、原始JSON IFR 17.5%。',
  '固定50題任務成功：37題Logical＋13題Arithmetic；拒答、內容或原始輸出未過判準皆未成功。',
  '效能30%：TTFT 10%、TPS 10%、RAM 5%、VRAM 5%；記憶體僅為系統／設備採樣代理。',
  '低值較佳項目＝本批最低平均值／模型平均值；TPS＝模型平均值／本批最高平均值。',
  'BGE與Faithfulness使用各自四模型共同有效樣本；TTFT共同179題，TPS／RAM／VRAM共同180題。',
  'Judge Relevance保留獨立指標但不加權；P@5為共用檢索成績，僅12題探索性子集，不加權。',
  '70/30已由使用者確認；內部分配、相對正規化及記憶體拆分未冒稱為原研究已凍結的政策。',
  '總分最高100；沒有重複套用70/30。80.29分不表示80.29%的專業答案正確率。',
  '三種計分敏感度均維持M2第一；不代表所有權重、機器或獨立題庫均有相同結果。',
  '來源：'+source.source_run,
  '只讀既有推論；未重跑模型、未改Corpus、未覆寫歷史報表、未切換Production。'
];
for(let i=0;i<notes.length;i++) policy.getRange(`A${11+i}`).values=[[notes[i]]];
await wb.recalculate();
const inspection=await wb.inspect({kind:'region',sheetId:'Model_Ranking',range:'A4:G8',maxChars:5000});
await fs.writeFile(path.join(dir,'weighted_workbook_inspection.json'),JSON.stringify(inspection,null,2));
for (const [s,range,file] of [[rank,'A1:H28','weighted_ranking_preview.png'],[detail,'A1:K16','weighted_details_preview.png'],[policy,'A1:J23','weighted_policy_preview.png']]) {
  const img=await wb.render({sheetName:s.name,range,scale:1,format:'png'});
  await fs.writeFile(path.join(dir,file),new Uint8Array(await img.arrayBuffer()));
}
await (await SpreadsheetFile.exportXlsx(wb)).save(path.join(dir,'weighted_model_selection.xlsx'));
console.log(JSON.stringify({workbook:path.join(dir,'weighted_model_selection.xlsx'),sheets:3,contribution_rows:rows.length}));
