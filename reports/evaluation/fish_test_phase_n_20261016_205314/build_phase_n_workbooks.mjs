import fs from "node:fs/promises";
import { SpreadsheetFile, Workbook, FileBlob } from "@oai/artifact-tool";

const outDir = "reports/evaluation/fish_test_phase_n_20261016_205314";
const payload = JSON.parse(await fs.readFile(outDir + "/workbook_payload.json", "utf8"));
const navy = "#1F4E78", paleBlue = "#D9EAF7", paleYellow = "#FFF2CC", paleRed = "#FCE4D6", font = "Arial";

function setup(sheet,title,note) {
  sheet.showGridLines=false;
  sheet.getRange("A1").values=[[title]];
  sheet.getRange("A1").format={font:{name:font,size:15,bold:true,color:navy}};
  sheet.getRange("A2").values=[[note]];
  sheet.getRange("A2").format={font:{name:font,size:10,italic:true,color:"#404040"},wrapText:true};
}
function header(sheet,range) {
  sheet.getRange(range).format={fill:navy,font:{name:font,size:10,bold:true,color:"#FFFFFF"},horizontalAlignment:"center",verticalAlignment:"center",wrapText:true};
}
function body(sheet,range) {
  sheet.getRange(range).format.font={name:font,size:10,color:"#202020"};
  sheet.getRange(range).format.verticalAlignment="top";
  sheet.getRange(range).format.wrapText=true;
}
function widths(sheet,map) {
  for(const k of Object.keys(map)) sheet.getRange(k+":"+k).format.columnWidth=map[k];
}
function addTable(sheet,range,name) {
  const t=sheet.tables.add(range,true,name); t.style="TableStyleMedium2"; t.showFilterButton=true;
}
function colLetter(n) {
  let s=""; while(n>0){let r=(n-1)%26;s=String.fromCharCode(65+r)+s;n=Math.floor((n-1)/26);}return s;
}

// Workbook 1: the 63 purposive high-risk cases.
{
  const wb=Workbook.create();
  const inst=wb.worksheets.add("Instructions");
  setup(inst,"Phase N｜63 筆高風險案例人工覆核","AI 回顧警示僅供定位疑點；不得當成人工結論。");
  inst.getRange("A4:B10").values=[
    ["流程","逐列閱讀原題、必要答案元素與原始 Chunk，獨立判斷是否支持題目要求。"],
    ["標籤","1 = Relevant；0 = Irrelevant；U = 資訊不足或來源／適用性衝突；空白 = 尚未完成。"],
    ["判讀","先閱讀原文，再填人工判斷。歷史 AI 標籤與事後警示僅供追溯，不是正解。"],
    ["紀錄","填 Human Final Label、Human Support Reason、Reviewer、Review Date；標 1 必須指出支持的答案元素。"],
    ["限制","63 筆為刻意抽取的高風險案例，適用於失敗分析，不代表 900 段的整體錯誤率。"],
    ["不可改動","勿修改 Question ID、Chunk ID、Rank、原題、Chunk 文字、歷史 AI 標籤或警示。"],
    ["來源","Phase M 歷史開發／驗證試點與內容稽核；未改寫原始標籤。"]
  ];
  inst.getRange("A4:A10").format={fill:paleBlue,font:{name:font,bold:true,color:navy}};
  inst.getRange("A4:B10").format.wrapText=true;
  widths(inst,{"A":20,"B":110}); inst.getRange("A4:B10").format.rowHeight=44;

  const sh=wb.worksheets.add("Human Review");
  setup(sh,"Phase N｜人工覆核佇列（63 筆）","所有人工欄位皆留空；Human Status 初始為 Pending。歷史 AI 欄位僅供稽核追溯。");
  const hs=["Question ID","Species","Category","Original Question","Required Answer Elements","Rank","Chunk ID","Source Name","Source Version","Original Chunk Text","Exact Evidence Span","AI Initial Label","Content Audit Warning","Human Final Label","Human Support Reason","Reviewer","Review Date","Human Status"];
  sh.getRange("A4:R4").values=[hs];
  const rows=payload.review63.map(function(r){return hs.map(function(h){return r[h]===undefined||r[h]===null?"":r[h];});});
  sh.getRange("A5:R"+(4+rows.length)).values=rows;
  header(sh,"A4:R4"); body(sh,"A5:R"+(4+rows.length));
  addTable(sh,"A4:R"+(4+rows.length),"HighRiskReview63");
  sh.freezePanes.freezeRows(4); sh.freezePanes.freezeColumns(3);
  sh.getRange("N5:N"+(4+rows.length)).dataValidation={rule:{type:"list",values:["1","0","U"]}};
  sh.getRange("N5:N"+(4+rows.length)).format.fill=paleYellow;
  sh.getRange("O5:Q"+(4+rows.length)).format.fill=paleYellow;
  sh.getRange("R5:R"+(4+rows.length)).format.fill=paleRed;
  widths(sh,{"A":21,"B":12,"C":19,"D":48,"E":50,"F":9,"G":40,"H":35,"I":31,"J":82,"K":60,"L":20,"M":66,"N":18,"O":48,"P":20,"Q":16,"R":26});
  sh.getRange("A5:R"+(4+rows.length)).format.rowHeight=92;
  const reviewPreview=await wb.render({sheetName:"Human Review",range:"A1:R8",scale:1,format:"png"});
  await fs.writeFile(outDir+"/human_review_queue_preview.png",new Uint8Array(await reviewPreview.arrayBuffer()));
  wb.recalculate();
  const p=await wb.render({sheetName:"Instructions",range:"A1:B10",scale:1,format:"png"});
  await fs.writeFile(outDir+"/human_review_instructions_preview.png",new Uint8Array(await p.arrayBuffer()));
  const x=await SpreadsheetFile.exportXlsx(wb); await x.save(outDir+"/human_review_queue_63.xlsx");
}

// Workbook 2: blinded 12-question / 60-context independent pilot.
{
  const wb=Workbook.create();
  const inst=wb.worksheets.add("Instructions");
  setup(inst,"Phase N｜獨立人工相關性試點","固定 12 題 × Top-5，共 60 段。此表不展示 AI 初始標籤、模型答案或模型分數。");
  inst.getRange("A4:B11").values=[
    ["標籤","1 = Relevant；0 = Irrelevant；U = 完整判讀後仍不確定；空白 = Pending。"],
    ["判定","只判斷該段是否支持題目的一項或多項必要答案元素；純主題相似不足以標 1。"],
    ["魚種","核對題目魚種與來源適用性。不同魚種的專屬數值／管理建議不可直接外推；一般法規依適用範圍判讀。"],
    ["標註","每個 Chunk 獨立標記並寫理由、Reviewer、日期；標 1 時指出原文支持的要素。"],
    ["計算","目前 Summary 保持 Pending。人工標籤完成並匯出後，使用附帶的核驗程式計算 P@5 與 AI 對照；不以空白充當 0。"],
    ["抽樣","seed 20261016；每魚種 2 題，六類別各 2 題；排除 Phase I–M 曾用於試點／規則調整的 20 個題目 ID。"],
    ["盲化","請勿查看獨立保存的 Phase G AI 對照標籤檔，直到人工標籤鎖定。"],
    ["限制","本試點僅檢查人工標註流程，不代表全部 180 題或 900 段的檢索品質。"]
  ];
  inst.getRange("A4:A11").format={fill:paleBlue,font:{name:font,bold:true,color:navy}};
  inst.getRange("A4:B11").format.wrapText=true;
  widths(inst,{"A":20,"B":110}); inst.getRange("A4:B11").format.rowHeight=42;

  const qsh=wb.worksheets.add("Questions");
  setup(qsh,"Frozen 12-question sample","題目清單已凍結；不含候選答案或 AI 標籤。");
  const qh=["Question ID","Species","Category","Original Question","Top-5 Contexts","Question SHA-256","Human Status"];
  qsh.getRange("A4:G4").values=[qh];
  const qrows=payload.pilot12.map(function(q){return [q.question_id,q.species,q.category,q.question_text,q.contexts.length,q.question_sha256,"PENDING_HUMAN_REVIEW"];});
  qsh.getRange("A5:G"+(4+qrows.length)).values=qrows;
  header(qsh,"A4:G4"); body(qsh,"A5:G"+(4+qrows.length)); addTable(qsh,"A4:G"+(4+qrows.length),"PilotQuestions12");
  qsh.freezePanes.freezeRows(4); qsh.freezePanes.freezeColumns(2);
  widths(qsh,{"A":23,"B":14,"C":22,"D":92,"E":18,"F":68,"G":28});
  qsh.getRange("D5:D"+(4+qrows.length)).format.rowHeight=48;

  const csh=wb.worksheets.add("Context Labels");
  setup(csh,"60 筆 Context 人工標註","逐列標記 1／0／U；文字、來源和頁碼來自凍結的 Evaluation Corpus v2 檢索 Trace。");
  const ch=["Question ID","Species","Category","Rank","Chunk ID","Source Name","Source Version","Chunk Version","Source ID","Document ID","Page","Source URL","Context Text","Context SHA-256","Human Label","Human Support Reason","Reviewer","Review Date","Human Status"];
  csh.getRange("A4:S4").values=[ch];
  const crows=[];
  for(const q of payload.pilot12) for(const c of q.contexts) crows.push([
    c.question_id,c.species,c.category,c.rank,c.chunk_id,c.source_name,c.source_version,c.chunk_version||"",
    c.source_id,c.document_id,c.page||"",c.source_url||"",c.context_text,c.context_sha256,"","","","","PENDING_HUMAN_REVIEW"
  ]);
  csh.getRange("A5:S"+(4+crows.length)).values=crows;
  header(csh,"A4:S4"); body(csh,"A5:S"+(4+crows.length)); addTable(csh,"A4:S"+(4+crows.length),"HumanPilotContexts60");
  csh.freezePanes.freezeRows(4); csh.freezePanes.freezeColumns(5);
  csh.getRange("O5:O64").dataValidation={rule:{type:"list",values:["1","0","U"]}};
  csh.getRange("O5:R64").format.fill=paleYellow;
  csh.getRange("S5:S64").format.fill=paleRed;
  widths(csh,{"A":22,"B":12,"C":20,"D":9,"E":40,"F":38,"G":34,"H":19,"I":28,"J":40,"K":10,"L":55,"M":95,"N":68,"O":16,"P":48,"Q":20,"R":16,"S":28});
  csh.getRange("A5:S64").format.rowHeight=120;
  csh.getRange("M5:M64").format.verticalAlignment="top";

  const sum=wb.worksheets.add("Summary");
  setup(sum,"人工試點標籤回收與 P@5","初始為 Pending；僅在五筆都為 1／0 時顯示精確 P@5。");
  const sh=["Question ID","Species","Category","Human Labels Received","Pending Contexts","Exact P@5","Status"];
  sum.getRange("A4:G4").values=[sh];
  sum.getRange("A5:C16").values=qrows.map(function(x){return x.slice(0,3);});
  sum.getRange("D5:G16").values=qrows.map(function(){return [0,5,null,"PENDING_HUMAN_REVIEW"];});
  header(sum,"A4:G4"); body(sum,"A5:G16");
  addTable(sum,"A4:G16","PilotP5Summary"); sum.freezePanes.freezeRows(4);
  widths(sum,{"A":23,"B":14,"C":22,"D":24,"E":20,"F":16,"G":30});
  sum.getRange("A20:B22").values=[
    ["Interpretation","12 selected questions; human labels not yet supplied."],
    ["Exact P@5 N",0],
    ["Mean P@5","N/A until at least one question has five binary labels."]
  ];
  sum.getRange("A20:A22").format={fill:paleBlue,font:{name:font,bold:true,color:navy}};
  sum.getRange("B20:B22").format.wrapText=true;
  wb.recalculate();

  for(const item of [
    ["Instructions","A1:B11","pilot_instructions_preview.png"],
    ["Questions","A1:G8","pilot_questions_preview.png"],
    ["Context Labels","A1:S9","pilot_context_labels_preview.png"],
    ["Summary","A1:H18","pilot_summary_preview.png"]
  ]){
    const blob=await wb.render({sheetName:item[0],range:item[1],scale:1,format:"png"});
    await fs.writeFile(outDir+"/"+item[2],new Uint8Array(await blob.arrayBuffer()));
  }
  const x=await SpreadsheetFile.exportXlsx(wb); await x.save(outDir+"/human_context_pilot_12_questions.xlsx");
}

// Reopen both exported files for export integrity checks.
for(const name of ["human_review_queue_63.xlsx","human_context_pilot_12_questions.xlsx"]){
  const file=await FileBlob.load(outDir+"/"+name);
  const reopened=await SpreadsheetFile.importXlsx(file);
  const info=await reopened.inspect({kind:"workbook,sheet,table",maxChars:5000,tableMaxRows:3,tableMaxCols:8});
  await fs.writeFile(outDir+"/"+name+".inspect.ndjson",info.ndjson||String(info));
}
console.log("created and reopened both Phase N workbooks");

