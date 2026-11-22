import fs from "node:fs/promises";
import { SpreadsheetFile, Workbook, FileBlob } from "@oai/artifact-tool";
const report = "C:/my project/115_marine_project/reports/evaluation/final_model_selection/phase20_1E_exec_r3/step3k_exam_question_bank";
const out = report + "/aquaculture_exam_question_bank_180plus.xlsx";
const readJsonl = async (name) => (await fs.readFile(report + "/" + name, "utf8")).split(/\r?\n/).filter(Boolean).map((x) => JSON.parse(x));
const q = await readJsonl("exam_question_candidates.jsonl");
const src = await readJsonl("source_provenance_manifest.jsonl");
const groups = await readJsonl("knowledge_group_registry.jsonl");
const coverage = JSON.parse(await fs.readFile(report + "/question_coverage_matrix.json", "utf8"));
const validation = JSON.parse(await fs.readFile(report + "/question_validation_report.json", "utf8"));
const wb = Workbook.create();
const fontName = "Aptos";
function columnName(n) { let s=""; while(n>0){const r=(n-1)%26;s=String.fromCharCode(65+r)+s;n=Math.floor((n-1)/26);} return s; }
function addTableSheet(name, headers, rows, tableName, widths={}) {
 const sheet=wb.worksheets.add(name); sheet.showGridLines=false; sheet.tabColor="#1F4E78";
 const all=[headers,...rows], lastCol=columnName(headers.length), lastRow=Math.max(1,all.length);
 sheet.getRange("A1:"+lastCol+lastRow).values=all;
 const used=sheet.getRange("A1:"+lastCol+lastRow); used.format.font={name:fontName,size:10,color:"#243247"}; used.format.wrapText=true;
 sheet.getRange("A1:"+lastCol+"1").format={fill:"#164E63",font:{name:fontName,size:10,bold:true,color:"#FFFFFF"},wrapText:true};
 sheet.freezePanes.freezeRows(1);
 const table=sheet.tables.add("A1:"+lastCol+lastRow,true,tableName); table.style="TableStyleMedium2";
 for(const [col,width] of Object.entries(widths)) sheet.getRange(col+"1:"+col+lastRow).format.columnWidth=width;
 used.format.autofitRows();
 return sheet;
}
const readme=wb.worksheets.add("00_ReadMe"); readme.showGridLines=false; readme.tabColor="#B45309";
readme.getRange("A1:C1").merge(); readme.getRange("A1").values=[["Phase 20.1E Step 3K — Official Exam Topic Catalog"]];
readme.getRange("A1:C1").format={fill:"#123B52",font:{name:fontName,size:16,bold:true,color:"#FFFFFF"},wrapText:true};
const readmeRows=[
["Execution status","Incomplete — source acquisition blocked","Source-linked topic catalog only; not a validated 180+ question bank."],
["Official exam PDF links identified",validation.official_source_documents_identified,"MOEX direct PDF URLs surfaced from official pages."],
["Topic candidates surfaced",validation.indexed_topic_candidate_records,"Concise paraphrased metadata from indexed PDF text; exact prompts omitted."],
["In-scope topic candidates",validation.in_scope_topic_candidates,"Not yet verified answers or evidence."],
["Out-of-scope taxa",validation.out_of_scope_candidates,"Shrimp, shellfish, sea urchin, lobster retained with rejection reason."],
["Original files downloaded",validation.official_original_files_downloaded,"No local exam PDF bytes; existing proxy refused the connection."],
["Question text locally verified",validation.exact_question_text_locally_verified,"Browser PDF preview did not render; no local original available."],
["Answers validated",validation.official_answer_validated,"Essay rubric and answer evidence remain unverified."],
["RAG grounded ready",validation.rag_grounded_ready,"No controlled retrieval check against frozen eligible corpus."],
["Candidate target",validation.target_candidate_count,"Initial candidate collection target."],
["Validated question target",validation.final_question_target,"No validated questions counted toward this target."],
["Rights note","Metadata only","MOEX requests intact source attribution and states all rights reserved; full prompts and answers are not reproduced."],
["WDA Skill Test","No original dataset acquired","Reference material is not a substitute for the official test question/answer source."],
["Frozen baseline","No protected artifact changed","SQLite size/hash checked before and after; Production HTTP and pytest not tested here."]
];
readme.getRange("A3:C16").values=readmeRows;
readme.getRange("A3:C16").format={font:{name:fontName,size:11,color:"#243247"},wrapText:true};
readme.getRange("A3:A16").format={fill:"#E7F0F4",font:{name:fontName,size:11,bold:true,color:"#164E63"},wrapText:true};
readme.getRange("A1:A16").format.columnWidth=31; readme.getRange("B1:B16").format.columnWidth=42; readme.getRange("C1:C16").format.columnWidth=76;
readme.getRange("A1:C16").format.autofitRows(); readme.freezePanes.freezeRows(2);
const candHeaders=["Question ID","Year","ROC Year","Exam","Level","Exam Category","Subject","Q No.","Type","Brief Topic Summary","Species Scope","Species","Target Category","Prompt Text","Text Validated","Official Answer Status","Answer Validated","RAG Status","Rights Status","Official PDF URL","Local PDF","SHA-256","Review / Rejection Reason"];
const candRows=q.map(x=>[x.question_id,x.exam_year,x.exam_year_roc,x.examination_name,x.exam_level,x.exam_category,x.subject,x.original_question_number,x.question_type,x.brief_topic_summary,x.species_scope,(x.species||[]).join(", "),x.category,x.question_text,x.question_text_validated,x.official_answer_status,x.answer_validated,x.rag_grounded_ready?"rag_grounded_ready":x.retrieval_evidence_available,x.source_rights_status,x.source_url,x.source_pdf_path,x.source_sha256,x.rejection_or_review_reason]);
addTableSheet("01_Candidates",candHeaders,candRows,"ExamCandidates",{A:22,B:10,C:10,D:31,E:14,F:24,G:36,H:10,I:13,J:64,K:22,L:18,M:20,N:16,O:18,P:36,Q:18,R:23,S:30,T:68,U:20,V:18,W:62});
addTableSheet("02_Validated",["Question ID","Exam Year","Exam","Subject","Question No.","Expected Answer","Answer Evidence","Verification Method","Status","Notes"],[],"ValidatedQuestions",{A:22,B:12,C:30,D:36,E:13,F:45,G:58,H:28,I:22,J:55});
const coverageHeaders=["Species","Category","Target Questions","Species-Specific Candidates","Prompt Text Validated","Answer Validated","RAG Grounded Ready","Coverage Status"];
const coverageRows=coverage.matrix.map(x=>[x.species,x.category,x.target_question_count ?? "not allocated",x.species_specific_candidate_count,x.question_text_validated_count,x.answer_validated_count,x.rag_grounded_ready_count,x.coverage_status]);
const covSheet=addTableSheet("03_Coverage",coverageHeaders,coverageRows,"CoverageMatrix",{A:16,B:22,C:18,D:25,E:22,F:18,G:22,H:44});
const start=coverageRows.length+4;
covSheet.getRange("A"+start+":C"+start).values=[["General Aquaculture Candidates by Category","Candidate Count","Target Bank Questions"]];
covSheet.getRange("A"+start+":C"+start).format={fill:"#164E63",font:{name:fontName,size:10,bold:true,color:"#FFFFFF"},wrapText:true};
const targetByCat={"Fact":35,"Water Quality":35,"Disease":35,"Climate / Cold":20,"Medication / Law":20,"Calculation":35};
const genRows=coverage.general_aquaculture_category_counts.map(x=>[x.category,x.general_aquaculture_candidate_count,targetByCat[x.category]]);
covSheet.getRange("A"+(start+1)+":C"+(start+genRows.length)).values=genRows;
covSheet.tables.add("A"+start+":C"+(start+genRows.length),true,"GeneralCoverage");
covSheet.getRange("A"+start+":C"+(start+genRows.length)).format.autofitRows();
const sourceHeaders=["Source ID","Exam Year","Exam","Level","Exam Category","Subject","Publisher","Official Landing Page","Official PDF URL","PDF Downloaded","Local File","File Size","SHA-256","Page Count from Indexed Text","Locally Verified","Rights Status","Answer Key Status"];
const sourceRows=src.map(x=>[x.source_id,x.exam_year,x.examination_name,x.exam_level,x.exam_category,x.subject,x.official_publisher,x.landing_url,x.source_url,x.original_file_downloaded,x.local_original_path,x.source_file_size,x.source_sha256,x.pdf_page_count,x.page_verified_locally,x.source_rights_status,x.official_answer_link]);
addTableSheet("04_Sources",sourceHeaders,sourceRows,"OfficialSources",{A:32,B:12,C:38,D:18,E:25,F:42,G:38,H:64,I:68,J:18,K:18,L:14,M:68,N:24,O:20,P:32,Q:40});
const groupHeaders=["Knowledge Group ID","Question IDs","Source Cluster","Topic Summary","Independence Status","Duplicate Group","Formula ID","Group Note"];
const groupRows=groups.map(x=>[x.knowledge_group_id,x.question_ids.join(", "),x.source_cluster_id,x.topic_summary,x.independence_status,x.duplicate_group_id,x.formula_id_if_applicable,x.group_note]);
addTableSheet("05_Knowledge_Groups",groupHeaders,groupRows,"KnowledgeGroups",{A:42,B:30,C:36,D:68,E:26,F:22,G:22,H:70});
const dupHeaders=["Question ID","Source Cluster","Knowledge Group","Exact Duplicate Status","Duplicate Group","Scope Status","Reason"];
const dupRows=q.map(x=>[x.question_id,x.source_cluster_id,x.knowledge_group_id,"not_detected_full_text_audit_incomplete",x.duplicate_group_id,x.candidate_scope_status,x.rejection_or_review_reason]);
addTableSheet("06_Dedup_Review",dupHeaders,dupRows,"DedupReview",{A:22,B:36,C:44,D:42,E:20,F:30,G:70});
const ragHeaders=["Question ID","Topic Summary","Species Scope","Species","Category","Expected Answer","Answer Status","Corpus Retrieval Check","Retrieval Evidence Available","RAG Grounded Ready","Reason"];
const ragRows=q.map(x=>[x.question_id,x.brief_topic_summary,x.species_scope,(x.species||[]).join(", "),x.category,x.expected_answer,x.answer_status,"not_executed",x.retrieval_evidence_available,x.rag_grounded_ready,x.rejection_or_review_reason]);
addTableSheet("07_RAG_Status",ragHeaders,ragRows,"RagStatus",{A:22,B:68,C:23,D:18,E:22,F:24,G:24,H:24,I:28,J:22,K:70});
const expertHeaders=["Question ID","Exam Year","Subject","Question No.","Topic Summary","Review Needed","Expert / Rubric Need","High Risk","Current Status","Source URL"];
const expertRows=q.map(x=>[x.question_id,x.exam_year,x.subject,x.original_question_number,x.brief_topic_summary,"yes","Inspect original prompt; establish evidence-backed rubric and current applicability; confirm objective scoring.",x.category==="Medication / Law"?"yes":"no",x.candidate_scope_status==="rejected_out_of_scope"?"rejected_out_of_scope":"needs_expert_review",x.source_url]);
addTableSheet("08_Expert_Review",expertHeaders,expertRows,"ExpertReview",{A:22,B:12,C:42,D:13,E:64,F:17,G:72,H:15,I:28,J:70});
wb.recalculate();
await fs.mkdir(report+"/previews",{recursive:true});
const previewFiles=[];
for(const sheetName of ["00_ReadMe","01_Candidates","02_Validated","03_Coverage","04_Sources","05_Knowledge_Groups","06_Dedup_Review","07_RAG_Status","08_Expert_Review"]){
 const image=await wb.render({sheetName,autoCrop:"all",scale:1,format:"png"});
 const bytes=new Uint8Array(await image.arrayBuffer());
 const safe=sheetName.replace(/[^A-Za-z0-9_]/g,"_");
 const p=report+"/previews/"+safe+".png";
 await fs.writeFile(p,bytes); previewFiles.push(p);
}
const xlsx=await SpreadsheetFile.exportXlsx(wb); await xlsx.save(out);
const check=await SpreadsheetFile.importXlsx(await FileBlob.load(out));
const inspect=await check.inspect({kind:"sheet",include:"id,name",maxChars:6000});
console.log(JSON.stringify({output:out,previewFiles,sheetInspect:inspect.ndjson},null,2));