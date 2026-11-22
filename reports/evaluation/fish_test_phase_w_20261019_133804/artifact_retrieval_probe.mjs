import fs from 'node:fs/promises';
import { Workbook, SpreadsheetFile } from '@oai/artifact-tool';
const rs=(await fs.readFile('retrieval_results_v3_updated.jsonl','utf8')).trim().split(/\r?\n/).map(x=>JSON.parse(x));
const rows=[['question_id','rank','chunk_id','source_id','content']];
for(const r of rs) for(const c of r.reranked_top5||[]) rows.push([r.question_id,c.rank,c.chunk_id,c.source_id,c.content]);
const w=Workbook.create();const s=w.worksheets.add('Ctx');s.getRange(`A1:E${rows.length}`).values=rows;
console.log('rows ready',rows.length);await SpreadsheetFile.exportXlsx(w);console.log('retrieval export ok');
