import fs from 'node:fs/promises';
import { Workbook, SpreadsheetFile } from '@oai/artifact-tool';
const rows=(await fs.readFile('generator_results_v3.jsonl','utf8')).trim().split(/\r?\n/).map(x=>JSON.parse(x));
const srows=[['question_id','model_id','status','answer','raw_response','prompt','timing','citations']];
for(const x of rows) srows.push([x.question_id,x.model_id,x.status,x.answer,x.raw_response,JSON.stringify(x.prompt||{}),JSON.stringify(x.timing||{}),JSON.stringify(x.citations||[])]);
const w=Workbook.create();const s=w.worksheets.add('Gen');s.getRange(`A1:H${srows.length}`).values=srows;
console.log('rows ready',srows.length);await SpreadsheetFile.exportXlsx(w);console.log('gen export ok');
