import { FileBlob, SpreadsheetFile } from '@oai/artifact-tool';
const p = 'fish_test_evaluation_results.xlsx';
const wb = await SpreadsheetFile.importXlsx(await FileBlob.load(p));
const ws = wb.worksheets.getItem('Dashboard');
console.log(JSON.stringify({values:ws.getRange('B5:B7').values,formulas:ws.getRange('B5:B7').formulas}));
