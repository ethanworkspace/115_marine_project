import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {Workbook,SpreadsheetFile,FileBlob} from '@oai/artifact-tool';
const W=path.dirname(fileURLToPath(import.meta.url));
const d=JSON.parse(await fs.readFile(path.join(W,'final_workbook_data.json'),'utf8'));
const wb=Workbook.create();
const names=['Summary','Metric_Audit','Paired_Summary','Paired_Questions','Paired_Reasons','Species','Source_Dependency','Judge_Populations','Judge_Cross_Tab','Exceptions','Methods'];
const ss=Object.fromEntries(names.map(n=>[n,wb.worksheets.add(n)]));
function col(n){let s='';for(n++;n;n=Math.floor((n-1)/26))s=String.fromCharCode(65+(n-1)%26)+s;return s;}
function tab(n,title,headers,rows,widths,height=32){const s=ss[n],end=col(headers.length-1),last=rows.length+3;s.showGridLines=false;s.getRange('A1').values=[[title]];s.getRange('A1').format.font={name:'Arial',size:15,color:'#17364D',bold:true};s.getRange(`A3:${end}${last}`).values=[headers,...rows];s.getRange(`A3:${end}${last}`).format.font={name:'Arial',size:10,color:'#243B47'};s.getRange(`A3:${end}3`).format={fill:'#294B68',font:{name:'Arial',size:10,bold:true,color:'#FFFFFF'},rowHeight:45,wrapText:true,verticalAlignment:'center'};s.getRange(`A4:${end}${last}`).format={rowHeight:height,wrapText:true,verticalAlignment:'top'};widths.forEach((w,i)=>s.getRange(`${col(i)}3:${col(i)}${last}`).format.columnWidth=w);s.tables.add(`A3:${end}${last}`,true,n.replaceAll('_','')+'Table');s.freezePanes.freezeRows(3);return s;}
tab('Metric_Audit','原始模型與系統層指標重算',['回答層','模型','指標','平均','有效N','中位數','標準差','最小','最大','配對N','配對平均'],d.metrics,[14,10,31,15,12,15,15,15,15,13,16]);
ss.Metric_Audit.getRange('D4:K83').setNumberFormat('0.0000');for(const c of ['E','J'])ss.Metric_Audit.getRange(`${c}4:${c}83`).setNumberFormat('0');
tab('Paired_Questions','34個共同題目的原始模型判定 1正確 0錯誤',['指標','Question ID','魚種','原始問題','M1','M2','M3','M4','來源群組'],d.paired_questions,[20,25,13,80,10,10,10,10,100],60);
tab('Paired_Reasons','逐題原始回答 判定理由及凍結參考答案',['指標','Question ID','魚種','模型','判定','原始判定理由','原始模型answer','凍結參考答案','Rubric SHA','Source groups','解析數值','標準數值'],d.paired_reasons,[20,25,13,10,18,100,100,85,70,100,18,18],90);
tab('Paired_Summary','共同題目與原各自有效分母並列',['指標','模型','共同N','共同正確','共同錯誤','共同準確率','各自正確','各自有效N','各自準確率','各自N/A'],d.paired_summary,[20,10,14,16,16,18,16,18,18,16]);
for(let i=0;i<d.paired_summary.length;i++){let row=i+4;let mi=Number(d.paired_summary[i][1].slice(1));let c=col(3+mi);ss.Paired_Summary.getRange(`C${row}`).formulas=[[`=COUNTIF('Paired_Questions'!$A$4:$A$37,A${row})`]];ss.Paired_Summary.getRange(`D${row}`).formulas=[[`=SUMIF('Paired_Questions'!$A$4:$A$37,A${row},'Paired_Questions'!$${c}$4:$${c}$37)`]];ss.Paired_Summary.getRange(`E${row}`).formulas=[[`=C${row}-D${row}`]];ss.Paired_Summary.getRange(`F${row}`).formulas=[[`=IF(C${row}=0,"n.a.",D${row}/C${row})`]];}
ss.Paired_Summary.getRange('F4:F11').setNumberFormat('0.00%');ss.Paired_Summary.getRange('I4:I11').setNumberFormat('0.00%');
tab('Species','六魚種共同樣本及All Available結果',['分析／指標','魚種','模型','有效N','正確','錯誤','準確率或平均'],d.species,[38,14,10,14,14,14,23]);ss.Species.getRange(`G4:G${d.species.length+3}`).setNumberFormat('0.0000');
tab('Source_Dependency','來源群組及原件層級組成敏感度 非因果效果',['群組別名','來源層級','完整來源群組','群組題數','占50題比例','指標','回答層','模型','組內正確','組內N','組內準確率','排除後N','排除後準確率','整體準確率','整體減排除後'],d.groups,[15,22,85,14,18,20,14,10,15,13,19,15,21,19,23],42);for(const c of ['E','K','M','N','O'])ss.Source_Dependency.getRange(`${c}4:${c}${d.groups.length+3}`).setNumberFormat('0.00%');
tab('Judge_Populations','原始Judge樣本與系統安全閘的不同母體',['模型','原答Judge N','原答引用通過¹','模型通過閘','確定性摘取','系統拒答','驗證失敗','原始宣告拒答','系統Judge N','系統無實質答案'],d.flow,[10,20,23,20,20,20,20,23,20,25]);
tab('Judge_Cross_Tab','Judge有效原答依系統最終origin交叉統計',['模型','系統最終Origin','Judge有效原答N','其中原答引用失敗','其中非充分證據'],d.cross,[10,50,25,27,27]);
tab('Exceptions','M2一筆及M3四筆缺陷的原始及勘誤後狀態',['模型','Question ID','回答層','原始問題','原始模型JSON摘錄','系統最終JSON摘錄','內容狀態','原BGE','更正BGE','原Logical','更正Logical','原Arithmetic','更正Arithmetic'],d.special,[10,25,14,75,100,100,48,15,15,20,20,20,20],110);
tab('Methods','11指標公式與統計重現位置',['項目','定義或追溯位置'],d.methods,[35,150],65);
const s=ss.Summary;s.showGridLines=false;s.getRange('A1').values=[['Corpus v3 最終統計核對']];s.getRange('A1').format.font={name:'Arial',size:17,bold:true,color:'#17364D'};s.getRange('A2').values=[['來源核驗型探索性評估 Human Gold 0 無正式總分或Winner']];
s.getRange('A4:D9').values=[['核對項目','結果','有效N','說明'],['生成最終結果',720,720,'四模型各180 同題Context與Prompt一致'],['Logical共同題目',27,37,'原始各模型有效N另列'],['Arithmetic共同題目',7,13,'來源綁定應用算術 非FCR SGR bFCR'],['探索性共用P@5',0.3,12,'只限12題60段 不外推180題'],['來源依賴',10,3,'10組紀錄或頁 共享3份原件']];s.getRange('B8').setNumberFormat('0.00%');
s.getRange('A12:G18').values=[['魚種','題數','完整來源支持','Logical資格','Arithmetic資格','有Context','完整Top5'],...d.coverage];
s.getRange('A21:E21').values=[['配對準確率','M1','M2','M3','M4']];s.getRange('A22:A23').values=[['Logical N27'],['Arithmetic N7']];
for(let m=0;m<4;m++){s.getRange(`${col(m+1)}22`).formulas=[[`='Paired_Summary'!F${m+4}`]];s.getRange(`${col(m+1)}23`).formulas=[[`='Paired_Summary'!F${m+8}`]];}
s.getRange('B22:E23').setNumberFormat('0.00%');
s.getRange('A25').values=[['引用¹僅限原答Judge有效者；通過引用不等於通過證據充分性或專業正確。']];s.getRange('A26').values=[['模型生成與系統摘取分開；原始分數與五筆缺陷均保留，不以N/A補0。']];
s.getRange('A4:G26').format.font={name:'Arial',size:10,color:'#243B47'};s.getRange('A4:G26').format.rowHeight=29;s.getRange('A4:A26').format.columnWidth=28;s.getRange('B4:C26').format.columnWidth=17;s.getRange('D4:D26').format.columnWidth=62;s.getRange('E4:G26').format.columnWidth=20;for(const r of [4,12,21])s.getRange(`A${r}:${r===4?'D':r===12?'G':'E'}${r}`).format={fill:'#294B68',font:{name:'Arial',size:10,color:'#FFFFFF',bold:true},rowHeight:38,wrapText:true};
const ch=s.charts.add('bar',s.getRange('A21:E23'));ch.title='相同Question ID配對描述性結果';ch.legend={position:'top'};ch.yAxis={numberFormatCode:'0%',numberFormatSourceLinked:false};ch.setPosition('A29','G45');
for(const sheet of Object.values(ss))sheet.getRange('A1').format.rowHeight=36;
wb.recalculate();
if(ss.Paired_Summary.getRange('C4').values[0][0]!==27||ss.Paired_Summary.getRange('D4').values[0][0]!==21||ss.Paired_Summary.getRange('C8').values[0][0]!==7)throw Error('Paired formula reconciliation failed');
const orig=ss.Paired_Questions.getRange('E4').values[0][0];const old=ss.Paired_Summary.getRange('D4').values[0][0];ss.Paired_Questions.getRange('E4').values=[[1-orig]];wb.recalculate();if(ss.Paired_Summary.getRange('D4').values[0][0]!==old+(1-2*orig))throw Error('Source dependency did not recalculate');ss.Paired_Questions.getRange('E4').values=[[orig]];wb.recalculate();
const errors=await wb.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#NUM!|#NULL!|#SPILL!|#CALC!',options:{useRegex:true,maxResults:60}});await fs.writeFile(path.join(W,'final_workbook_formula_scan.ndjson'),errors.ndjson);
await fs.mkdir(path.join(W,'xlsx_previews'),{recursive:true});for(const n of names){const b=await wb.render({sheetName:n,range:n==='Summary'?'A1:G26':'A1:F7',scale:1,format:'png'});await fs.writeFile(path.join(W,'xlsx_previews',n+'.png'),new Uint8Array(await b.arrayBuffer()));}
const cb=await wb.render({sheetName:'Summary',range:'A28:G45',scale:1,format:'png'});await fs.writeFile(path.join(W,'xlsx_previews','paired_chart.png'),new Uint8Array(await cb.arrayBuffer()));
const out=path.join(W,'final_statistical_verification.xlsx');await(await SpreadsheetFile.exportXlsx(wb)).save(out);const reopened=await SpreadsheetFile.importXlsx(await FileBlob.load(out));const ri=await reopened.inspect({kind:'region',sheetId:'Paired_Summary',range:'A3:J11',maxChars:5000,tableMaxRows:9,tableMaxCols:10});await fs.writeFile(path.join(W,'final_workbook_reopen.ndjson'),ri.ndjson);await fs.writeFile(path.join(W,'final_workbook_validation.json'),JSON.stringify({sheets:names,formula_recalculation_verified:true,temporary_input_restored:true,reopened:true,source_tables:'final_workbook_data.json'},null,2));console.log(JSON.stringify({output:out,sheets:names.length}));
