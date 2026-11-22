import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {Workbook,SpreadsheetFile,FileBlob} from '@oai/artifact-tool';
const W=path.dirname(fileURLToPath(import.meta.url));
const d=JSON.parse(await fs.readFile(path.join(W,'workbook_data.json'),'utf8'));
const wb=Workbook.create();
const names=['Dashboard','Model_Stats','Model_vs_System','Paired_Comparison','Species_Comparison','Category_Comparison','Source_Groups','Group_Uncertainty','Duplicate_Sensitivity','Context_Precision','Accuracy','Per_Question','Original_Results','Attempts','Questions','Settings','Errors','Limitations'];
const sheets=Object.fromEntries(names.map(n=>[n,wb.worksheets.add(n)]));
function col(n){let s='';for(n++;n;n=Math.floor((n-1)/26))s=String.fromCharCode(65+(n-1)%26)+s;return s;}
function table(name,title,headers,rows,widths,height=30){
 const sh=sheets[name];sh.showGridLines=false;sh.getRange('A2').values=[[title]];sh.getRange('A2').format.font={name:'Arial',size:14,bold:true,color:'#19364D'};
 const last=Math.max(4,rows.length+3),end=col(headers.length-1);sh.getRange(`A3:${end}${last}`).values=[headers,...(rows.length?rows:[headers.map(()=>null)])];
 sh.getRange(`A3:${end}${last}`).format.font={name:'Arial',size:10,color:'#263238'};sh.getRange(`A3:${end}3`).format={fill:'#294B68',font:{name:'Arial',size:10,bold:true,color:'#FFFFFF'},wrapText:true,rowHeight:44,horizontalAlignment:'center',verticalAlignment:'center'};
 sh.getRange(`A4:${end}${last}`).format.wrapText=true;sh.getRange(`A4:${end}${last}`).format.rowHeight=height;sh.getRange(`A4:${end}${last}`).format.verticalAlignment='top';
 widths.forEach((v,i)=>sh.getRange(`${col(i)}3:${col(i)}${last}`).format.columnWidth=v);
 sh.tables.add(`A3:${end}${last}`,true,name.replaceAll('_','')+'Data');sh.freezePanes.freezeRows(3);return sh;
}
table('Model_Stats','11項指標的模型與系統分層統計',['回答層','模型','指標','平均值','有效N','中位數','最小值','最大值','配對平均','四模型共同N'],d.metrics,[14,10,32,15,12,15,15,15,15,17]);
sheets.Model_Stats.getRange(`D4:J${d.metrics.length+3}`).setNumberFormat('0.0000');sheets.Model_Stats.getRange(`E4:E${d.metrics.length+3}`).setNumberFormat('0');sheets.Model_Stats.getRange(`J4:J${d.metrics.length+3}`).setNumberFormat('0');
table('Model_vs_System','模型宣告、系統安全閘與確定性摘取',['模型','結果／行為','數量','分組題數'],d.abstention,[10,57,15,15]);
table('Paired_Comparison','同題四模型均具有效值的配對比較',['回答層','指標','模型','共同N','平均','中位數','最小','最大','題目ID'],d.paired,[14,32,10,13,15,15,15,15,90],36);
table('Species_Comparison','六魚種的分層描述統計',['魚種','回答層','模型','指標','平均','有效N','最小','最大'],d.species,[14,14,10,31,15,12,15,15]);
table('Category_Comparison','原始題型的分層描述統計',['題型','回答層','模型','指標','平均','有效N','最小','最大'],d.category,[25,14,10,31,15,12,15,15]);
table('Source_Groups','50題的原始來源群組依賴',['來源群組','群組題數','回答層','模型','指標','平均','有效N','題目ID'],d.groups,[80,14,14,10,30,15,12,90],40);
table('Group_Uncertainty','來源依賴連通群組的不確定性補充',['回答層','指標','模型','配對題數','來源連通群組N','等群組平均','探索區間下界','探索區間上界','限制'],d.group_uncertainty,[14,29,10,15,21,19,20,20,68],42);
table('Duplicate_Sensitivity','175題幹敏感度（主分析保留180筆魚種情境）',['回答層','模型','指標','題幹總數','去重平均','去重有效N','180筆平均'],d.duplicates,[14,10,31,15,17,17,17]);
table('Context_Precision','共用檢索P@5的有限診斷樣本',['Question ID','魚種','題型','Context N','可靠標記N','P@5','下界','上界','狀態','不可評估原因'],d.p5,[25,12,24,14,17,14,14,14,37,68],45);
sheets.Context_Precision.getRange('F4:H183').setNumberFormat('0.0%');
table('Accuracy','來源核驗條件下的Logical與Arithmetic判定',['Question ID','模型','回答層','準確率類型','判定','理由','Answer Origin','原始來源群組','Rubric SHA','模型數值','Decimal標準值','單位有效'],d.accuracy,[25,10,14,20,20,90,43,90,70,18,18,15],70);
table('Per_Question','原始模型與系統答案的逐題指標',['Question ID','模型','回答層','魚種','題型','Answer Origin','Faithfulness','Judge Relevance','BGE Cosine','原始JSON IFR','TTFT 秒','TPS','RAM峰值 GiB','VRAM峰值 GiB','Logical','Arithmetic','品質缺失原因','Logical缺失原因','Arithmetic缺失原因','原始JSONL列','BGE缺失原因','回答內容狀態'],d.per_question,[25,10,14,12,24,43,17,18,15,17,14,14,18,18,15,15,62,70,70,18,65,45],42);
sheets.Per_Question.getRange('G4:P1443').setNumberFormat('0.0000');sheets.Per_Question.getRange('J4:J1443').setNumberFormat('0');
table('Original_Results','720筆原始生成與系統回答索引',['Question ID','模型','魚種','題型','Context N','Answer Origin','API完成','原始JSON有效','原始宣告拒答','原始Citation','原始回答摘錄','最終答案摘錄','拒答／後處理原因','Context Digest','模型Digest','JSONL列','Stream Trace','完整Prompt'],d.raw,[25,10,12,24,14,43,13,17,17,20,85,85,65,70,70,13,100,100],85);
table('Attempts','所有Generator嘗試與引擎量測',['Question ID','模型','嘗試','API完成','API錯誤','Wall 秒','可見TTFT 秒','首Thinking 秒','TPS','eval_count','eval_duration ns','done_reason','硬體採樣N','原始JSON有效','Attempt ID','Stream Trace'],d.attempts,[25,10,12,14,65,16,18,18,15,16,23,20,17,18,65,100],42);
table('Questions','180題、凍結參考答案及證據資格',['Question ID','魚種','題型','原始問題','來源／檢索缺口','Context N','Logical資格','Arithmetic資格','凍結參考答案','原始來源群組','Rubric SHA','核驗層級'],d.questions,[25,12,24,74,43,14,18,20,85,95,70,58],80);
table('Settings','模型、Corpus、Prompt與追溯資料',['設定','固定值或追溯位置'],d.settings,[34,145],44);
table('Errors','保留全部失敗、驗證拒絕與內容診斷',['Question ID','模型','API錯誤','驗證／內容診斷','原始JSON有效','Answer Origin','最終原因','Attempt ID'],d.errors,[25,10,75,90,18,43,70,65],55);
table('Limitations','探索性研究限制',['項目','說明'],d.limitations,[27,135],58);
const s=sheets.Dashboard;s.showGridLines=false;s.tabColor='#19364D';s.getRange('A2').values=[['Corpus v3 四模型凍結回歸評測']];s.getRange('A2').format.font={name:'Arial',size:15,bold:true,color:'#19364D'};
s.getRange('A3').values=[['EXPLORATORY · AUTO_SOURCE_VERIFIED · NOT_HUMAN_GOLD']];s.getRange('A3').format.font={name:'Arial',size:10,color:'#8A4C12'};
s.getRange('A5:I5').values=[['原始模型指標','M1','N','M2','N','M3','N','M4','N']];
const keys=['faithfulness','judge_answer_relevance','bge_m3_cosine','structured_ifr','ttft_seconds','tps','peak_system_ram_gib','peak_dedicated_vram_gib','logical_accuracy','arithmetic_accuracy'];
const labels=['Faithfulness','Judge Relevance','BGE-M3 Cosine','Raw JSON IFR','TTFT（秒）','TPS','System RAM 每次峰值平均GiB','Dedicated VRAM 每次峰值平均GiB','Logical Accuracy','Arithmetic Accuracy'];
s.getRange('A6:A15').values=labels.map(x=>[x]);
for(let j=0;j<4;j++)for(let i=0;i<keys.length;i++){
 const idx=d.metrics.findIndex(r=>r[0]==='model'&&r[1]===`M${j+1}`&&r[2]===keys[i])+4;
 s.getRange(`${col(1+2*j)}${i+6}`).formulas=[[`=IF('Model_Stats'!E${idx}=0,"n.a.",'Model_Stats'!D${idx})`]];
 s.getRange(`${col(2+2*j)}${i+6}`).formulas=[[`='Model_Stats'!E${idx}`]];
}
s.getRange('B6:I15').setNumberFormat('0.000');for(const c of ['C','E','G','I'])s.getRange(`${c}6:${c}15`).setNumberFormat('0');
for(const r of [9,14,15])for(const c of ['B','D','F','H'])s.getRange(`${c}${r}`).setNumberFormat('0.0%');
s.getRange('A17:C17').values=[['共用檢索／實驗範圍','數值','有效N']];
s.getRange('A18:C24').values=[['完成Generator結果',null,720],['固定Context題數',174,180],['共用探索性P@5',null,null],['完整來源支持',50,180],['Logical資格',37,180],['Arithmetic資格',13,180],['Human Gold',0,180]];
s.getRange('J17:J24').values=[['限制與範圍'],['每模型180；失敗與重試完整保留'],['124題完整Top-5；6題無Context'],['12題60段診斷樣本，不外推180題'],['49題Top-5命中，1題漏失保留'],['實際可評估N見Accuracy'],['來源綁定應用算術；非FCR／SGR'],['AI核驗不能替代人工專家真值']];
s.getRange('B18').formulas=[["=COUNTA('Original_Results'!$A$4:$A$723)"]];
s.getRange('B20').formulas=[["=AVERAGE('Context_Precision'!$F$4:$F$183)"]];s.getRange('C20').formulas=[["=COUNT('Context_Precision'!$F$4:$F$183)"]];s.getRange('B20').setNumberFormat('0.0%');
s.getRange('A26:F26').values=[['回答來源數量','模型通過閘','確定性摘取','系統拒答','驗證失敗','合計']];
s.getRange('A27:A30').values=[['M1'],['M2'],['M3'],['M4']];
for(let i=0;i<4;i++)for(let j=0;j<4;j++)s.getRange(`${col(j+1)}${27+i}`).formulas=[[`=COUNTIFS('Original_Results'!$B$4:$B$723,$A${27+i},'Original_Results'!$F$4:$F$723,"${['MODEL_GENERATED','DETERMINISTIC_EVIDENCE_EXTRACTION','ABSTAINED','VALIDATION_FAILED'][j]}")`]];
for(let i=0;i<4;i++)s.getRange(`F${27+i}`).formulas=[[`=SUM(B${27+i}:E${27+i})`]];
s.getRange('A32').values=[['答案品質須連同回答率、有效N與配對結果閱讀；不建立加權總分或正式Winner。']];
s.getRange('A33').values=[['模型原始拒答／格式失敗與系統摘取分開計分；安全閘阻擋結果不冒充模型直接成功。']];
s.getRange('A5:I30').format.font={name:'Arial',size:10};s.getRange('A5:I30').format.rowHeight=27;
for(const r of [5,17,26])s.getRange(`A${r}:${r===5?'I':r===17?'C':'F'}${r}`).format={fill:'#294B68',font:{name:'Arial',size:10,bold:true,color:'#FFFFFF'},rowHeight:32};
s.getRange('A5:A33').format.columnWidth=39;s.getRange('B5:I33').format.columnWidth=13;s.getRange('J17:J24').format={font:{name:'Arial',size:10,color:'#635343'},columnWidth:65};s.getRange('A32:I33').format.font={name:'Arial',size:10,color:'#8A4C12'};
// Place chart below data, with separate source-linked views for behaviour and efficiency.
const chart=s.charts.add('bar',s.getRange('A26:E30'));chart.title='原始模型回答與系統回補數量';chart.titleTextStyle.typeface='Arial';chart.titleTextStyle.fontSize=12;chart.legend={position:'top',textStyle:{typeface:'Arial',fontSize:10}};chart.yAxis={numberFormatCode:'0',numberFormatSourceLinked:false,textStyle:{typeface:'Arial'}};chart.setPosition('A36','I52');
const colors=['#294B68','#B98645','#9BA7B2','#A45151'];chart.series.items.forEach((x,i)=>x.fill=colors[i]);
wb.recalculate();
// Verify the Dashboard source dependency without leaving altered scientific inputs.
const original=sheets.Original_Results.getRange('F4').values[0][0];const model=sheets.Original_Results.getRange('B4').values[0][0];const rr=27+Number(model.slice(1))-1;const before=s.getRange(`B${rr}`).values[0][0];
sheets.Original_Results.getRange('F4').values=[['MODEL_GENERATED']];wb.recalculate();const changed=s.getRange(`B${rr}`).values[0][0];if(changed!==before+(original==='MODEL_GENERATED'?0:1))throw new Error('Outcome count dependency failed');sheets.Original_Results.getRange('F4').values=[[original]];wb.recalculate();
if(s.getRange('B18').values[0][0]!==720||s.getRange('C20').values[0][0]!==12||Math.abs(s.getRange('B20').values[0][0]-.3)>1e-10)throw new Error('Dashboard reconciliation failed');
const inspect=await wb.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#NUM!|#NULL!|#SPILL!|#CALC!',options:{useRegex:true,maxResults:100},summary:'formula errors'});await fs.writeFile(path.join(W,'workbook_formula_errors.ndjson'),inspect.ndjson);
await fs.mkdir(path.join(W,'previews'),{recursive:true});
for(const n of names){const blob=await wb.render({sheetName:n,range:n==='Dashboard'?'A1:J33':'A1:F7',scale:1,format:'png'});await fs.writeFile(path.join(W,'previews',n+'.png'),new Uint8Array(await blob.arrayBuffer()));}
const chblob=await wb.render({sheetName:'Dashboard',range:'A35:I52',scale:1,format:'png'});await fs.writeFile(path.join(W,'previews','Dashboard_chart.png'),new Uint8Array(await chblob.arrayBuffer()));
const output=path.join(W,'fish_test_evaluation_v3.xlsx');await(await SpreadsheetFile.exportXlsx(wb)).save(output);
const reopened=await SpreadsheetFile.importXlsx(await FileBlob.load(output));const ri=await reopened.inspect({kind:'region',sheetId:'Dashboard',range:'A5:I24',maxChars:6500,tableMaxRows:20,tableMaxCols:9});await fs.writeFile(path.join(W,'workbook_reopened_inspection.ndjson'),ri.ndjson);
await fs.writeFile(path.join(W,'workbook_validation_artifact.json'),JSON.stringify({output,sheet_names:names,sheet_count:names.length,reopened:true,formula_recalculation_and_restoration_verified:true,canonical_result_count:720,p5_n:12,p5_mean:.3,rendered_sheets:names.length,authoring_library:'@oai/artifact-tool'},null,2));
console.log(JSON.stringify({output,sheets:names.length,reopened:true}));
