import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const base = path.dirname(fileURLToPath(import.meta.url));
const inputPath = path.join(base, "evaluation_readiness_v3.xlsx");
const workbook = await SpreadsheetFile.importXlsx(await FileBlob.load(inputPath));
const sheets = await workbook.inspect({ kind: "sheet", include: "id,name", maxChars: 6000 });
const tables = await workbook.inspect({ kind: "table", maxChars: 10000, tableMaxRows: 3, tableMaxCols: 6 });
const regions = {};
for (const [sheet, range] of [
  ["Dashboard", "A3:C8"],
  ["Question_Eligibility", "A1:H3"],
  ["Question_Eligibility", "A180:H181"],
  ["Retrieval_Coverage", "A180:M181"],
  ["Evidence_Diagnostics", "A1:K3"],
  ["Evidence_Diagnostics", "A790:K793"],
  ["Quality_Checks", "A1:C5"],
]) {
  regions[`${sheet}!${range}`] = await workbook.inspect({ kind: "region", sheetId: sheet, range, maxChars: 4000 });
}
const contentChecks = {};
for (const [sheetName, cells] of Object.entries({
  Dashboard: ["A3:C3", "A4:C4", "A20:C21"],
  Question_Eligibility: ["A1:H2", "A180:H181"],
  Retrieval_Coverage: ["A1:M2", "A180:M181"],
  Evidence_Diagnostics: ["A1:K2", "A792:K793"],
  Quality_Checks: ["A1:C2", "A20:C21"],
})) {
  const sheet = workbook.worksheets.getItem(sheetName);
  contentChecks[sheetName] = {
    usedRangeRows: sheet.getUsedRange().rowCount,
    samples: Object.fromEntries(cells.map(range => [range, sheet.getRange(range).values])),
  };
}
const result = { input: inputPath, reopened: true, sheet_inspection: sheets, table_inspection: tables, sampled_regions: regions, content_checks: contentChecks };
await fs.writeFile(path.join(base, "workbook_reopen_validation.json"), JSON.stringify(result, null, 2) + "\n", "utf8");
console.log(JSON.stringify({ reopened: true, inspection_file: path.join(base, "workbook_reopen_validation.json") }));
