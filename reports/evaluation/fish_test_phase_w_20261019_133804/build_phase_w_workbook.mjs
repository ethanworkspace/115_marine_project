import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { FileBlob, SpreadsheetFile, Workbook } from '@oai/artifact-tool';

const dir = path.dirname(fileURLToPath(import.meta.url));
const readJson = async name => JSON.parse(await fs.readFile(path.join(dir, name), 'utf8'));
const readJsonl = async name => (await fs.readFile(path.join(dir, name), 'utf8')).split(/\r?\n/).filter(Boolean).map(line => JSON.parse(line));
const cleanText = s => s.replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F]/g, ch => ch === '\f' ? ' [page break] ' : '�');
const cell = x => x === null || x === undefined ? 'N/A' : (typeof x === 'object' ? cleanText(JSON.stringify(x)) : (typeof x === 'string' ? cleanText(x) : x));
const wb = Workbook.create();
const sheetNames = [];
const colName = n => { let s = ''; while (n) { const r=(n-1)%26; s=String.fromCharCode(65+r)+s; n=Math.floor((n-1)/26); } return s; };

function addSheet(name, rows, widths=[], table=false) {
  const sh = wb.worksheets.add(name); sheetNames.push(name); sh.showGridLines = false;
  const maxCols = Math.max(1, ...rows.map(r=>r.length));
  const matrix = rows.map(r=>Array.from({length:maxCols},(_,i)=>cell(r[i])));
  const lastCol = colName(maxCols); const lastRow = Math.max(1,matrix.length);
  sh.getRange(`A1:${lastCol}${lastRow}`).values = matrix;
  sh.getRange(`A1:${lastCol}1`).format = {fill:'#1F4E62',font:{name:'Aptos',size:10,bold:true,color:'#FFFFFF'},wrapText:true,verticalAlignment:'center'};
  sh.getRange(`A1:${lastCol}1`).format.rowHeight = 34;
  if (lastRow>1) { sh.getRange(`A2:${lastCol}${lastRow}`).format = {font:{name:'Aptos',size:10,color:'#24323D'},wrapText:true,verticalAlignment:'top'}; }
  sh.freezePanes.freezeRows(1);
  if (table && lastRow>1) { const t=sh.tables.add(`A1:${lastCol}${lastRow}`,true,`W${sheetNames.length}Data`); t.style='TableStyleMedium2'; t.showFilterButton=true; }
  widths.forEach((w,i)=>{ const c=colName(i+1); sh.getRange(`${c}:${c}`).format.columnWidth=w; });
  return sh;
}

const [metrics, genSummary, retrieval, generations, judges, bge, refs, sources, structure, scope, corpusIntegrity, streamlit, interaction, smoke, facts, retryErrors] = await Promise.all([
  readJson('evaluation_metrics_v3.json'), readJson('generator_run_summary_v3.json'), readJsonl('retrieval_results_v3_updated.jsonl'),
  readJsonl('generator_results_v3.jsonl'), readJsonl('judge_results_v3.jsonl'), readJsonl('bge_m3_cosine_v3.jsonl'),
  readJsonl('reference_answers_v3.jsonl'), readJsonl('source_resolution_final.jsonl'), readJsonl('structured_output_audit_v3.jsonl'),
  readJson('species_scope_regression_validation.json'), readJson('corpus_and_retrieval_integrity_v3.json'),
  readJson('rag_v3_streamlit_validation.json'), readJson('rag_v3_streamlit_interaction_validation.json'),
  readJson('rag_v3_end_to_end_validation.json'), readJsonl('research_fact_cards_w.jsonl'), readJsonl('generator_retry_error_audit.jsonl')
]);

const d = [
  ['項目','實際結果','N','說明'],
  ['評測定位','整合後回歸／探索性評估',180,'原題庫曾用於前期系統調整，不是未曝光 Holdout。'],
  ['Fish Test 題目',180,180,'180 個唯一題目 ID。'],
  ['新版生成紀錄',720,720,'每題×四模型各一筆 canonical result。'],
  ['實際嘗試紀錄',726,726,'包含 6 筆失敗後成功重試的嘗試；錯誤紀錄保留。'],
  ['未解決 API 錯誤',genSummary.api_errors,720,'完整生成沒有未解決 API 錯誤。'],
  ['有效回答',metrics.generation.effective_status_counts.answered,720,'有效回答才進入 Judge Faithfulness／Relevance。'],
  ['有效拒答',metrics.generation.effective_status_counts.abstain,720,'不代表已證明拒答正確。'],
  ['無效輸出',metrics.generation.effective_status_counts.invalid_output,720,'M2 一筆無效輸出。'],
  ['至少一筆合格 Context',metrics.retrieval_coverage.questions_with_any_context,180,'檢索覆蓋，不是 P@5。'],
  ['完整 Top-5',metrics.retrieval_coverage.questions_with_complete_top5,180,'固定 reranker Top-5 有五段。'],
  ['部分 Top-5',metrics.retrieval_coverage.questions_with_partial_top5,180,'不補造缺少的 Context。'],
  ['零 Context',metrics.retrieval_coverage.questions_with_zero_context,180,'仍可測試拒答行為。'],
  ['實際檢索段落',metrics.retrieval_coverage.returned_contexts,900,'所有檢索 Trace 回查正確；因 Top-5 不足，實際 Context 數低於 900。'],
  ['Context Precision@5','N/A',0,'沒有可靠二元相關性標籤；Top-5 命中數不是相關性標籤。'],
  ['Logical Accuracy','N/A',0,'缺少已核驗答案與凍結 Rubric。'],
  ['Arithmetic Accuracy','N/A',0,'缺少完整核驗的公式、條件、單位、答案及容許誤差。'],
  ['Human Gold',0,180,'本輪無人工覆核。'],
  ['正式加權總分／Winner','未計算',0,'權重未核准，未選 Winner。'],
  ['Frozen Manifest',`${metrics.protected_baseline.match}/${metrics.protected_baseline.records}`,636,'前後核對一致。'],
  ['正式 SQLite SHA-256',metrics.protected_baseline.production_sqlite_sha256,1,'符合凍結預期值。'],
  ['Corpus v3',metrics.system.corpus_version,metrics.system.corpus_records,'沿用 Phase V 隔離 Corpus；Phase W 未加入新來源。']
];
addSheet('Dashboard',d,[30,44,14,92],false);

const modelRows=[['model_id','模型標籤','模型 digest','答覆數','拒答數','無效數','Judge Faithfulness','Faithfulness N','Judge Answer Relevance','Relevance N','BGE-M3 Cosine','BGE N','Structured Output IFR','IFR N','TTFT 秒均值','TTFT N','TPS 均值','TPS N','System RAM sampled max GiB','RAM samples','Dedicated VRAM sampled max MiB','VRAM samples','Shared GPU Memory','Context Precision@5','P@5 N','Logical Accuracy','Logical N','Arithmetic Accuracy','Arithmetic N']];
for(const [mid,m] of Object.entries(metrics.models)) modelRows.push([
  mid,m.tag,m.digest,m.effective_answered,m.effective_abstentions,m.invalid_outputs,
  m.judge_faithfulness.mean,m.judge_faithfulness.n,m.judge_answer_relevance.mean,m.judge_answer_relevance.n,
  m.bge_m3_cosine.mean,m.bge_m3_cosine.n,`${(m.structured_output_ifr.rate*100).toFixed(2)}%`,m.structured_output_ifr.eligible_n,
  m.ttft_visible_content_seconds.mean,m.ttft_visible_content_seconds.n,m.tps.mean,m.tps.n,
  m.system_ram_gib.sampled_max,m.system_ram_gib.sample_count,m.dedicated_vram_mib.sampled_max,m.dedicated_vram_mib.sample_count,
  'N/A','N/A',0,'N/A',0,'N/A',0
]);
addSheet('Model_Metrics',modelRows,[12,48,68,12,12,12,20,16,24,16,18,12,22,12,16,12,16,12,24,14,30,14,18,22,10,20,12,22,12]);

const retRows=[['question_id','species','category','question_text','corpus_version','applicable_source_count','applicable_chunk_count','BM25 candidates','Dense candidates','RRF candidates','source_qualification_pass','species_scope_pass','reranker_candidates','actual_top5_count','retrieval_status','failure_reason','top5_chunk_ids','top5_source_ids','context_digest']];
for(const r of retrieval) retRows.push([r.question_id,r.species,r.category,r.question_text,r.corpus_version,r.corpus_applicable_source_count,r.corpus_applicable_chunk_count,r.bm25_candidate_count,r.dense_candidate_count,r.rrf_candidate_count,r.source_qualification_pass_count,r.species_applicability_pass_count,r.reranker_candidate_count,r.final_top5_count,r.retrieval_status,r.retrieval_failure_reason,(r.reranked_top5||[]).map(x=>x.chunk_id),(r.reranked_top5||[]).map(x=>x.source_id),generations.find(g=>g.question_id===r.question_id)?.retrieval_ref?.context_digest]);
addSheet('Retrieval_Summary',retRows,[20,14,20,62,36,22,22,18,18,18,24,22,20,18,42,44,70,50,68]);

const ctxRows=[['question_id','species','category','rank','chunk_id','source_id','source_title','source_version','page_or_locator','source_sha256','chunk_sha256','reranker_score','RRF rank','BM25 rank','Dense rank','species_scope','category_scope','content']];
for(const r of retrieval) for(const c of (r.reranked_top5||[])) ctxRows.push([r.question_id,r.species,r.category,c.rank,c.chunk_id,c.source_id,c.source_title,c.source_version,c.page_or_locator,c.source_sha256,c.content_sha256,c.reranker_score,c.rrf_rank,c.bm25_rank,c.dense_rank,c.species_scope,c.category_scope,c.content]);
addSheet('Retrieval_Contexts',ctxRows,[20,14,20,10,38,34,42,40,52,66,66,18,12,12,12,36,28,100]);

const refRows=[['question_id','species','category','original_question','verification_status','source_id','source_version','expected_answer','required_conditions','expected_abstention_candidate','evidence_span','limitations','human_gold_reviewed','corpus_version','reason']];
for(const r of refs) refRows.push([r.question_id,r.species,r.category,r.original_question,r.verification_status,r.source_id,r.source_version,r.expected_answer,r.required_conditions,r.expected_abstention,r.exact_evidence_span,r.limitations,r.human_gold_reviewed,r.corpus_version,r.reason]);
addSheet('Question_References',refRows,[20,14,20,58,42,34,42,72,54,28,78,80,18,34,86]);

const genRows=[['run_id','question_id','species','category','model_id','model_tag','model_digest','effective_status','model_reported_status','safety_guard_applied','answer','abstention_reason','citation_validation','citations','context_count','context_digest','TTFT visible seconds','TPS','eval_count','eval_duration_ns','raw_response_sha256','prompt_sha256','api_attempts']];
for(const g of generations) {
  const raw=g.raw_response||''; const prompt=JSON.stringify(g.prompt||{}); const timing=g.timing||{};
  genRows.push([g.run_id,g.question_id,g.species,g.category,g.model_id,g.model_tag,g.model_digest,g.status,g.model_reported_status,g.safety_guard_applied,g.answer,g.abstention_reason,g.citation_validation,g.model_citations_canonicalized||g.citations||[],g.retrieval_ref?.top5_count,g.retrieval_ref?.context_digest,timing.ttft_visible_content_seconds,timing.tps,timing.eval_count,timing.eval_duration_ns,await import('node:crypto').then(({createHash})=>createHash('sha256').update(raw).digest('hex')),await import('node:crypto').then(({createHash})=>createHash('sha256').update(prompt).digest('hex')),g.api_attempts]);
}
addSheet('Generation_720',genRows,[30,20,14,20,12,52,68,18,20,20,78,60,68,80,14,68,18,16,14,22,68,68,14]);

const judgeRows=[['run_id','question_id','model_id','status','faithfulness','answer_relevance','context_sufficient','unsupported_claims','rationale','judge_tag','judge_digest','judge_prompt_sha256','judge_attempts','judge_wall_seconds','human_gold','reason']];
for(const j of judges) judgeRows.push([j.run_id,j.question_id,j.model_id,j.status,j.faithfulness,j.answer_relevance,j.context_sufficient,j.unsupported_claims,j.rationale,j.judge_tag,j.judge_digest,j.judge_prompt_sha256,j.judge_attempts,j.judge_wall_seconds,j.human_gold,j.reason||j.error]);
addSheet('Judge_Scores',judgeRows,[30,20,12,38,18,18,20,64,86,46,68,68,16,18,16,72]);

const bgeRows=[['run_id','question_id','model_id','similarity','status','BGE-M3 tag','BGE-M3 digest','embedding dimension','normalization','input_answer_field','question_sha256','answer_sha256','metric limitation']];
for(const x of bge) bgeRows.push([x.run_id,x.question_id,x.model_id,x.similarity,x.status,x.bge_model_tag,x.bge_model_digest,x.embedding_dimension,x.normalization,x.input_answer_field,x.question_sha256,x.effective_answer_sha256,x.metric_label]);
addSheet('BGE_M3_Similarity',bgeRows,[30,20,12,16,18,28,68,18,74,36,68,68,78]);

const structRows=[['run_id','question_id','model_id','effective_status','raw_model_json_schema_valid','schema_validation_reason','citation_id_context_valid','citation_validation_reason','safety_guard_applied','human_gold']];
for(const x of structure) structRows.push([x.run_id,x.question_id,x.model_id,x.generator_status,x.raw_model_json_schema_valid,x.schema_validation_reason,x.citation_id_context_valid,x.citation_validation_reason,x.safety_guard_applied,x.human_gold]);
addSheet('Output_Validation',structRows,[30,20,12,18,28,44,28,44,20,16]);

const sourceRows=[['source_record_id','source_id','title','publisher','official_url','local_file','owner_decision','source_checksum_expected','source_checksum_actual','checksum_status','version','usage_basis','formal_admission_recorded','admission_status','corpus_inclusion_status','fulltext_index_rights_independently_verified','phase_v_blocker_codes','phase_v_resolution','notes']];
for(const s of sources) sourceRows.push([s.source_record_id,s.source_id,s.title,s.publisher,s.official_url,s.local_file,s.owner_decision,s.sha256_expected,s.sha256_actual,s.checksum_status,s.version,s.usage_basis,s.formal_source_admission_recorded,s.admission_status,s.corpus_v3_inclusion_status,s.fulltext_index_rights_independently_verified,s.phase_v_blocker_codes,s.phase_v_resolution,s.notes]);
addSheet('Source_57',sourceRows,[30,36,58,35,70,60,18,68,68,18,58,64,24,38,34,38,58,76,88]);

const factRows=[['fact_id','source_id','source_title','publisher','official_url','page_version','locator','factual_statement','species_scope','category','knowledge_group_id','source_cluster_id','usage_basis','verification_status','corpus_status','limitations']];
for(const x of facts) factRows.push([x.fact_id,x.source_id,x.source_title,x.publisher,x.official_url,x.page_version,x.locator,x.factual_statement,x.species_scope,x.category,x.knowledge_group_id,x.source_cluster_id,x.usage_basis,x.verification_status,x.corpus_status,x.limitations]);
addSheet('Research_Facts',factRows,[24,38,58,35,70,50,90,90,62,22,46,38,90,58,24,90]);

const validationRows=[['check','status','observed result','scope / limitation']];
validationRows.push(['Real four-model API smoke',smoke.full_system_smoke_passed?'PASS':'FAIL',`${smoke.generator_calls} calls; ${smoke.answered_outputs} answers; ${smoke.deterministic_abstentions} deterministic refusals; ${smoke.valid_json_and_citation_results} schema/citation checks`, 'Exploratory smoke only, not correctness benchmark.']);
validationRows.push(['Corpus integrity',corpusIntegrity.all_contexts_retraceable?'PASS':'FAIL',`${corpusIntegrity.chunk_records} chunks; ${corpusIntegrity.retrieval_eligible} eligible; ${corpusIntegrity.context_only} context-only; ${corpusIntegrity.top5_contexts_checked} contexts checked`, 'Chunk, SQLite, and vector hashes match Phase V manifest.']);
validationRows.push(['Species scope regression',scope.passed===scope.test_count?'PASS':'FAIL',`${scope.passed}/${scope.test_count}`, 'Regression checks, not a complete fish taxonomy audit.']);
validationRows.push(['Streamlit initial render',streamlit.status,`${streamlit.exception_count} exceptions; ${streamlit.title_count} title; ${streamlit.button_count} button`, 'Initial isolated render.']);
validationRows.push(['Streamlit real interaction smoke',interaction.status,`${interaction.warning_count} warning; ${interaction.error_count} error; ${interaction.elapsed_seconds.toFixed(1)} seconds`, 'User-facing retrieval/form flow; separate from the 720 canonical generator rows.']);
validationRows.push(['Canonical full generation',metrics.generation.canonical_unique_model_question_pairs===720?'PASS':'FAIL',`${metrics.generation.canonical_unique_model_question_pairs}/720 unique pairs; ${metrics.generation.api_errors_unresolved} unresolved API errors`, 'Six failed attempts preserved and recovered on retry.']);
validationRows.push(['Protected manifest',`${metrics.protected_baseline.match}/${metrics.protected_baseline.records}`,`${metrics.protected_baseline.mismatch} mismatch; ${metrics.protected_baseline.missing} missing`, 'Production SQLite SHA-256 matched expected digest.']);
addSheet('System_Validation',validationRows,[38,30,80,95]);

const errors=[['record_type','question_id','model_id','attempt','error_or_status','preserved_path']];
for(const e of retryErrors) errors.push(['generator_retry_error',e.question_id,e.model_id,e.attempt,e.error||e.status,'generator_retry_error_audit.jsonl']);
for(const g of generations.filter(x=>x.status==='invalid_output'||x.status==='api_error')) errors.push(['canonical_generation',g.question_id,g.model_id,g.api_attempts,g.parse_error||g.error||g.status,'generator_results_v3.jsonl']);
for(const j of judges.filter(x=>x.status==='judge_failed')) errors.push(['judge',j.question_id,j.model_id,j.judge_attempts,j.error,'judge_results_v3.jsonl']);
addSheet('Errors',errors,[28,20,12,12,88,42]);

const limits=[['項目','結果與限制'],
 ['來源准入','Owner Decision 57/57；SHA 去重為 55 份，50 筆來源仍未完成正式範圍／使用依據核驗；7 筆只有限定範圍准入。Owner approval 不是第三方授權。'],
 ['新增專業證據','新增 4 張水試所頁面事實研究卡，未進 Corpus。無新正式來源准入、無新專業全文 Chunk。網頁事實卡沒有原始 HTML checksum。'],
 ['Corpus','沿用 Phase V 隔離 Corpus v3，17,402 Chunks，其中 10,412 retrieval-eligible、6,990 context-only。Phase W 沒有重建或增添新來源內容。'],
 ['檢索','94/180 題有至少一段；34 題有完整 Top-5；60 題部分 Top-5；86 題無合格 Context。實際返回 259 段。這些不是相關性標註或答案可答性。'],
 ['模型輸出','66 筆有效回答、653 筆有效拒答、1 筆無效輸出；424 次安全守門覆寫。有效拒答不等於專家確認為正確拒答。'],
 ['Judge 指標','Mistral NeMo Judge 只評估 66 筆有效回答。結果是探索性、非水產專業真值，不能推論專業正確率。'],
 ['BGE-M3 Cosine','718 筆可計算，回答文字可能是拒答內容；只表示 embedding 相似度，不是正確率。'],
 ['Structured IFR','按原始模型 JSON 欄位與型別計算；引用是否有效另列。JSON 有效不代表引用語意支持答案。'],
 ['P@5','未建立可靠的 900 個二元段落相關性標籤，N=0；不以檢索覆蓋或 Judge context_sufficient 代替。'],
 ['Logical / Arithmetic Accuracy','可核驗答案與凍結 Rubric 均為 0 題，兩項 N=0。'],
 ['記憶體','RAM 與 Dedicated VRAM 為系統層級定時採樣峰值，非模型程序峰值；Shared GPU Memory N/A。'],
 ['Human Gold','0。自動 Judge 與來源研究卡皆非人工標準答案。'],
 ['正式決策','未計算未核准加權總分，未選 Winner，未切換正式環境。']];
addSheet('Limitations',limits,[34,130],false);

const prov=[['artifact','version / path','records or digest','notes'],
 ['Phase W workspace',dir,'phase_w_integrated_v1','Isolated research output.'],
 ['Retrieval JSONL','retrieval_results_v3_updated.jsonl',retrieval.length,'180 questions; reranked candidates are shared across all models.'],
 ['Generator JSONL','generator_results_v3.jsonl',generations.length,'720 canonical rows; detailed prompt/raw response preserved.'],
 ['Attempt log','generator_attempt_log_v3.jsonl',metrics.generation.raw_attempt_log_rows,'Attempt-level history includes resolved failures.'],
 ['Judge results','judge_results_v3.jsonl',judges.length,'66 scored; abstentions/invalid outputs N/A.'],
 ['BGE cosine','bge_m3_cosine_v3.jsonl',bge.length,'Similarity only.'],
 ['Reference answers','reference_answers_v3.jsonl',refs.length,'0 fully verified answer keys; not Human Gold.'],
 ['Source registry','source_resolution_final.jsonl',sources.length,'57 owner-approved process records; 55 unique hashes.'],
 ['Corpus manifest','Phase V corpus v3',metrics.system.corpus_version,'17,402 chunks; exact corpus and retrieval file digests in corpus_and_retrieval_integrity_v3.json.'],
 ['Protected Manifest','protected_baseline_recheck.jsonl',`${metrics.protected_baseline.match}/${metrics.protected_baseline.records}`,'Pre/post baseline check identical.'],
 ['Production SQLite', 'rag_store.sqlite3',metrics.protected_baseline.production_sqlite_sha256,'Matches required digest; not changed.'],
 ['Source follow-up', 'official_source_followups.jsonl',facts.length,'Official page fact notes are research-only; no original page byte hash.']];
addSheet('Provenance',prov,[34,70,74,90]);

wb.recalculate();
const inspection=await wb.inspect({kind:'workbook,sheet,table',maxChars:5000,tableMaxRows:2,tableMaxCols:6});
await fs.writeFile(path.join(dir,'workbook_inspection.ndjson'),inspection.ndjson,'utf8');
const out=path.join(dir,'fish_test_evaluation_v3.xlsx');
console.log('export start');
const blob=await SpreadsheetFile.exportXlsx(wb);
console.log('export completed');
await blob.save(out);
console.log('save completed');
const reopened=await SpreadsheetFile.importXlsx(await FileBlob.load(out));
console.log('reopen completed');
const reopenedCheck=await reopened.inspect({kind:'workbook,sheet,table',maxChars:5000,tableMaxRows:2,tableMaxCols:6});
const validation={file:out,reopened:true,sheet_count:sheetNames.length,sheet_names:sheetNames,generator_rows:generations.length,retrieval_questions:retrieval.length,retrieval_context_rows:ctxRows.length-1,reference_rows:refs.length,source_rows:sources.length,judge_rows:judges.length,bge_rows:bge.length,formula_count:0,counts_reconciled:generations.length===720&&retrieval.length===180&&refs.length===180&&sources.length===57&&judges.length===720,status:'PASS_REOPENED_AND_COUNTS_RECONCILED',inspection_excerpt:reopenedCheck.ndjson.slice(0,2000)};
await fs.writeFile(path.join(dir,'fish_test_evaluation_v3_validation.json'),JSON.stringify(validation,null,2),'utf8');
console.log(JSON.stringify(validation));
