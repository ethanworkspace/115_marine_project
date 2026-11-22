import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";
const path="reports/evaluation/fish_test_phase_n_20261016_205314/human_context_pilot_12_questions.xlsx";
const wb=await SpreadsheetFile.importXlsx(await FileBlob.load(path));
const contexts=wb.worksheets.getItem("Context Labels");
const summary=wb.worksheets.getItem("Summary");
const labels=contexts.getRange("O5:O64").values.flat();
if(labels.length!==60 || labels.some(v=>v!==null && v!=="")) throw new Error("Human annotation cells are not blank");
for(let r=5;r<=16;r++){
 const row=summary.getRange("D"+r+":G"+r).values[0];
 if(row[0]!==0 || row[1]!==5 || row[2]!==null || row[3]!=="PENDING_HUMAN_REVIEW")
   throw new Error("Unexpected initial P@5 status in row "+r+": "+JSON.stringify(row));
}
const names=(await wb.inspect({kind:"sheet",include:"id,name"})).ndjson;
if(!names.includes("Context Labels") || !names.includes("Summary")) throw new Error("Missing required worksheet");
console.log(JSON.stringify({passed:true,question_rows:12,context_rows:60,blank_human_labels:60,exact_p5_n:0,reason:"pending human review"}));

