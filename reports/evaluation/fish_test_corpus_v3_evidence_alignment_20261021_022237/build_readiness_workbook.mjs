import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {Workbook,SpreadsheetFile,FileBlob} from '@oai/artifact-tool';
const W=path.dirname(fileURLToPath(import.meta.url));
const d=JSON.parse(await fs.readFile(path.join(W,'workbook_data.json'),'utf8'));
const wb=Workbook.create();
const names=['Overview','Questions','References','Context_Labels','P5','Metric_Readiness','Tests','Sources','Limitations'];
const sheets=Object.fromEntries(names.map(n=>[n,wb.worksheets.add(n)]));
const str=x=>x===undefined?null:x;
function col(n){let s='';for(n++;n;n=Math.floor((n-1)/26))s=String.fromCharCode(65+(n-1)%26)+s;return s;}
function table(n,title,headers,rows,widths,height=35){
 const s=sheets[n];s.showGridLines=false;s.getRange('A2').values=[[title]];s.getRange('A2').format.font={name:'Arial',size:14,bold:true,color:'#183153'};
 const end=col(headers.length-1),last=rows.length+3;
 s.getRange(`A3:${end}${last}`).values=[headers,...rows.map(r=>r.map(str))];
 s.getRange(`A3:${end}${last}`).format.font={name:'Arial',size:10,color:'#263238'};
 s.getRange(`A3:${end}3`).format={fill:'#24476B',font:{name:'Arial',size:10,bold:true,color:'#FFFFFF'},wrapText:true,rowHeight:34,horizontalAlignment:'center',verticalAlignment:'center'};
 s.getRange(`A4:${end}${last}`).format.wrapText=true;s.getRange(`A4:${end}${last}`).format.rowHeight=height;s.getRange(`A4:${end}${last}`).format.verticalAlignment='top';
 widths.forEach((v,i)=>{s.getRange(`${col(i)}3:${col(i)}${last}`).format.columnWidth=v;});
 s.tables.add(`A3:${end}${last}`,true,n.replace(/_/g,'')+'Data');s.freezePanes.freezeRows(3);return s;
}
table('Questions','180題來源與檢索缺口',['Question ID','魚種','原始類別','原始問題','Corpus證據狀態','缺口分類','Context數','資格狀態','核驗理由'],d.questions,[25,12,20,48,33,40,12,38,76],60);
table('References','來源核驗參考答案與判準',['Question ID','魚種','類別','參考答案（無則空白）','核驗層級','原始Record IDs','Logical適用1/0','Arithmetic適用1/0','人工核驗狀態'],d.references.map(r=>r.map((x,i)=>(i===6||i===7)?Number(x):x)),[25,12,20,65,38,60,18,20,45],90);
table('Context_Labels','檢索段落內容支持診斷',['Question ID','Rank','Chunk ID','Source ID','Record ID','內容標記','相關性0/1','二元標記可用','判定理由','來源定位'],d.contexts,[25,9,60,35,39,27,13,16,82,75],65);
table('P5','共用檢索P@5與缺失狀態',['Question ID','魚種','Context數','已核實二元數','探索性P@5','下界','上界','狀態'],d.p5,[25,12,15,19,20,15,15,58],44);
sheets.P5.getRange('E4:G183').setNumberFormat('0.0%');
table('Metric_Readiness','11項指標的下一輪條件',['Metric','狀態','可用題數上限','計分／量測條件'],d.readiness.metrics.map(r=>[r.metric,r.status,r.eligible_question_n,r.condition]),[29,50,20,108],70);
table('Tests','真實測試與隔離驗證',['測試','N','結果','方法與限制'],d.tests,[32,12,22,100],50);
table('Sources','來源版本、權利與使用範圍',['Source ID','Dataset ID','發布者','原件SHA-256','Owner Decision','使用依據範圍','來源版本','允許處理範圍','原始檔案'],d.sources,[36,28,25,70,55,65,65,90,115],130);
table('Limitations','研究限制',['項目','說明'],d.limitations,[25,118],62);
const ov=sheets.Overview;ov.showGridLines=false;ov.tabColor='#183153';ov.getRange('A2').values=[['Corpus v3 證據與評測就緒狀態']];ov.getRange('A2').format.font={name:'Arial',size:15,bold:true,color:'#183153'};
const metrics=[
 ['原始題目',"=COUNTA(Questions!$A$4:$A$183)",'180題保持原始問題與ID'],
 ['完整來源支持',"=COUNTIFS(Questions!$E$4:$E$183,\"FULL_SUPPORT\")",'AUTO_SOURCE_CHECKED，非Human Gold'],
 ['完整支持且檢索命中',"=COUNTIFS(Questions!$F$4:$F$183,\"SOURCE_SUPPORTED_RETRIEVED\")",'來源資格與檢索命中分開'],
 ['完整支持但檢索漏失',"=COUNTIFS(Questions!$F$4:$F$183,\"SOURCE_SUPPORTED_NOT_RETRIEVED\")",'FT-grouper-Q16缺隔離支持段'],
 ['部分支持',"=COUNTIFS(Questions!$E$4:$E$183,\"PARTIAL_SUPPORT\")",'不進入完整答案正確率分母'],
 ['適用範圍待核實',"=COUNTIFS(Questions!$E$4:$E$183,\"SOURCE_SCOPE_UNVERIFIED\")",'主要為日本鰻與鱸鰻差異'],
 ['本版未找到完整答案',"=COUNTIFS(Questions!$E$4:$E$183,\"SOURCE_NOT_FOUND_IN_CORPUS\")",'限定搜尋結果，非不存在證明'],
 ['問題條件不足',"=COUNTIFS(Questions!$E$4:$E$183,\"QUESTION_CONDITIONS_MISSING\")",'不得由症狀猜劑量或必死時間'],
 ['至少一段Context',"=COUNTIFS(Questions!$G$4:$G$183,\">0\")",'不強制補滿五段'],
 ['完整Top-5',"=COUNTIFS(Questions!$G$4:$G$183,5)",'Coverage不等於P@5'],
 ['探索性P@5有效題數',"=COUNT(P5!$E$4:$E$183)",'刻意選取12題、60段內容核驗'],
 ['探索性P@5平均',"=AVERAGE(P5!$E$4:$E$183)",'只代表此診斷子集'],
 ['Logical判準題數',"=COUNTIFS(References!$G$4:$G$183,1)",'分數待下一輪生成，非Human Gold'],
 ['來源支持應用算術',"=COUNTIFS(References!$H$4:$H$183,1)",'不含未核實FCR／SGR／bFCR'],
 ['Human Gold',"=COUNTIFS(References!$I$4:$I$183,\"HUMAN_GOLD\")",'尚無獨立人工核驗']
];
ov.getRange('A4:C4').values=[['指標','N或數值','範圍與限制']];ov.getRange('A4:C4').format={fill:'#24476B',font:{bold:true,color:'#FFFFFF',name:'Arial',size:10}};
ov.getRange('A5:C19').values=metrics.map(x=>[x[0],null,x[2]]);ov.getRange('B5:B19').formulas=metrics.map(x=>[x[1]]);
ov.getRange('A5:C19').format.font={name:'Arial',size:10};ov.getRange('A5:C19').format.rowHeight=28;ov.getRange('B5:B19').setNumberFormat('#,##0');ov.getRange('B16').setNumberFormat('0.0%');
ov.getRange('A4:A35').format.columnWidth=31;ov.getRange('B4:B35').format.columnWidth=15;ov.getRange('C4:C35').format.columnWidth=43;ov.getRange('D4:D35').format.columnWidth=17;
ov.getRange('A22:F22').values=[['魚種','完整支持','部分支持','Logical N','Arithmetic N','P@5 N']];
ov.getRange('A22:F22').format={fill:'#24476B',font:{bold:true,color:'#FFFFFF',name:'Arial',size:10},rowHeight:28};
const species=Object.entries(d.summary.species);
ov.getRange('A23:F28').values=species.map(([s,v])=>[s,v.full_source_support,v.partial_source_support,v.logical_eligible,v.arithmetic_eligible,v.p5_evaluable]);
ov.getRange('A23:F28').format.font={name:'Arial',size:10};ov.getRange('A23:F28').format.rowHeight=27;ov.getRange('E4:K28').format.columnWidth=14;
ov.getRange('A31').values=[['技術：來源受限研究流程可運作。M3回補與模型直接成功分開。']];
ov.getRange('A33').values=[['720次：可安排系統效能／拒答測試。專業準確率僅限已核驗子集。']];
ov.getRange('A35').values=[['本輪未執行720次，不建立加權總分，不選Winner。']];
ov.getRange('A31:K35').format.font={name:'Arial',size:10,color:'#7A4B10'};
const ch=ov.charts.add('bar',ov.getRange('A22:B28'));ch.title='六魚種完整來源支持題數';ch.hasLegend=false;ch.titleTextStyle.typeface='Arial';ch.setPosition('E4','L19');
// Exercise a representative dependency, then restore the original data exactly.
const saved=sheets.Questions.getRange('E4').values[0][0];
sheets.Questions.getRange('E4').values=[['FULL_SUPPORT']];wb.recalculate();
if(ov.getRange('B6').values[0][0]!==51)throw new Error('COUNTIFS dependency did not update');
sheets.Questions.getRange('E4').values=[[saved]];wb.recalculate();
const values=ov.getRange('B5:B19').values.map(r=>r[0]);
const expected=[180,50,49,1,17,17,84,12,174,124,12,.3,37,13,0];
if(values.some((x,i)=>typeof x!=='number'||Math.abs(x-expected[i])>1e-10))throw new Error('Summary formula mismatch '+JSON.stringify(values));
const errors=await wb.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#NUM!|#NULL!|#SPILL!|#CALC!',options:{useRegex:true,maxResults:100},summary:'formula errors'});
await fs.writeFile(path.join(W,'workbook_formula_inspection.ndjson'),errors.ndjson);
await fs.mkdir(path.join(W,'workbook_previews'),{recursive:true});
for(const n of names){const blob=await wb.render({sheetName:n,range:n==='Overview'?'A1:L35':'A1:F7',scale:1,format:'png'});await fs.writeFile(path.join(W,'workbook_previews',n+'.png'),new Uint8Array(await blob.arrayBuffer()));}
const out=path.join(W,'evaluation_readiness_final.xlsx');await(await SpreadsheetFile.exportXlsx(wb)).save(out);
const reopened=await SpreadsheetFile.importXlsx(await FileBlob.load(out));
const check=await reopened.inspect({kind:'region',sheetId:'Overview',range:'A4:C19',maxChars:5500,tableMaxRows:18,tableMaxCols:3});await fs.writeFile(path.join(W,'workbook_reopened_inspection.ndjson'),check.ndjson);
await fs.writeFile(path.join(W,'workbook_artifact_validation.json'),JSON.stringify({exported:out,sheets:names,summary_formula_values:values,expected,formula_values_match:true,input_change_recalculation_verified_and_restored:true,reopened:true,rendered_sheets:names.length,authoring_library:'@oai/artifact-tool'},null,2));
console.log(JSON.stringify({exported:out,sheets:names.length,summary:values}));
