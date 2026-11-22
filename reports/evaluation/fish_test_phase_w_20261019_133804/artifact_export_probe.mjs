import { Workbook, SpreadsheetFile } from '@oai/artifact-tool';
const w=Workbook.create();
const s=w.worksheets.add('Probe');
s.getRange('A1:B2').values=[['metric','value'],['x',1]];
console.log('start export');
const b=await SpreadsheetFile.exportXlsx(w);
console.log('export ok',b.constructor.name);
