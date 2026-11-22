import fs from "node:fs/promises";
import path from "node:path";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const dir = path.resolve("reports/evaluation/fish_test_phase_u_20261018_171024");
const items = [
  ["source_inventory_six_species.xlsx", "Summary", "source_inventory_summary_preview.png"],
  ["source_admission_approval_matrix.xlsx", "Summary", "source_approval_summary_preview.png"],
  ["fish_test_evaluation_v3_final.xlsx", "Gate_Status", "evaluation_gate_preview.png"],
];
for (const [file, sheetName, png] of items) {
  const wb = await SpreadsheetFile.importXlsx(await FileBlob.load(path.join(dir, file)));
  const preview = await wb.render({ sheetName, autoCrop: "all", scale: 1.5, format: "png" });
  await fs.writeFile(path.join(dir, png), new Uint8Array(await preview.arrayBuffer()));
}
console.log("Rendered three summary previews from the reopened workbooks.");
