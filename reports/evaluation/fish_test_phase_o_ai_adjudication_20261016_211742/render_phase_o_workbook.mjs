import fs from 'node:fs/promises';
import { FileBlob, SpreadsheetFile } from '@oai/artifact-tool';

const dir = 'C:/my project/115_marine_project/reports/evaluation/fish_test_phase_o_ai_adjudication_20261016_211742';
const file = await FileBlob.load(`${dir}/fish_test_evaluation_results_ai_v5.xlsx`);
const wb = await SpreadsheetFile.importXlsx(file);
const names = ['Dashboard','AI_Adjudication','Context_900','P5_180','Profiles_180','Support_Checks','Judge_Calls','Reference_Verification','Accuracy_Status','Limitations_Provenance'];
const results = [];
for (const name of names) {
  const sheet = wb.worksheets.getItem(name);
  const preview = await wb.render({sheetName:name, range:name==='Dashboard'?'A1:C16':'A1:H9', scale:1, format:'png'});
  const out = `${dir}/preview_${name}.png`;
  await fs.writeFile(out,new Uint8Array(await preview.arrayBuffer()));
  const used = sheet.getUsedRange();
  results.push({sheet:name,preview:out,rowCount:used?.rowCount??0,columnCount:used?.columnCount??0});
}
await fs.writeFile(`${dir}/workbook_sheet_previews.json`,JSON.stringify(results,null,2)+'\n','utf8');
console.log(JSON.stringify(results));
