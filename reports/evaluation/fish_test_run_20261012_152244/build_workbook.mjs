import fs from 'node:fs/promises';
import path from 'node:path';
import { FileBlob, SpreadsheetFile, Workbook } from '@oai/artifact-tool';

const runDir = path.resolve(process.argv[2]);
const xlsxPath = path.join(runDir, 'fish_test_evaluation_results.xlsx');
const readJson = async (name) => JSON.parse(await fs.readFile(path.join(runDir, name), 'utf8'));
const readJsonl = async (name) => {
  try {
    const text = await fs.readFile(path.join(runDir, name), 'utf8');
    return text.split(/\r?\n/).filter(Boolean).map((line) => JSON.parse(line));
  } catch { return []; }
};
const cleanXmlText = (value) => Array.from(value).filter((ch) => {
  const cp = ch.codePointAt(0);
  return cp === 0x09 || cp === 0x0A || cp === 0x0D || (cp >= 0x20 && cp <= 0xD7FF) || (cp >= 0xE000 && cp <= 0xFFFD) || (cp >= 0x10000 && cp <= 0x10FFFF);
}).join('');
const asCell = (v) => {
  if (v === undefined || v === null) return null;
  if (typeof v === 'number' || typeof v === 'boolean') return v;
  const s = cleanXmlText(typeof v === 'object' ? JSON.stringify(v) : String(v));
  return s.startsWith('=') ? `'${s}` : s;
};
const rowsToCells = (headers, rows, map) => [headers, ...rows.map((row) => headers.map((h) => asCell(map(row, h))))];
const mean = (values) => values.length ? values.reduce((a, b) => a + b, 0) / values.length : null;
const pct = (a, b) => b ? a / b : null;

const questions = await readJsonl('fish_test_questions_normalized.jsonl');
const generations = await readJsonl('generation_outputs.jsonl');
const judges = await readJsonl('judge_results.jsonl');
const retrievals = await readJsonl('retrieval_trace.jsonl');
const metrics = await readJsonl('per_question_metrics.jsonl');
const modelAudit = await readJson('model_runtime_alignment.json').catch(() => ({}));
const comparison = await readJson('model_comparison_summary.json').catch(() => ({}));
const pilot = await readJson('pilot_results.json').catch(() => ({}));
const execution = await readJson('execution_manifest.json').catch(() => ({}));
const protectBefore = await readJson('protected_baseline_before.json').catch(() => ({}));
const protectAfter = await readJson('protected_baseline_after.json').catch(() => ({}));
const metricSpec = await readJson('fish_test_metric_spec.json').catch(() => ({}));
const runtime = await readJson('evaluation_environment_readiness.json').catch(() => ({}));

const questionById = new Map(questions.map((q) => [q.question_id, q]));
const judgeByKey = new Map(judges.map((j) => [`${j.question_id}|${j.model_id}`, j]));
const metricByKey = new Map(metrics.map((m) => [`${m.question_id}|${m.model_id}`, m]));
const generationByKey = new Map(generations.map((g) => [`${g.question_id}|${g.model_id}`, g]));
const retrievalById = new Map(retrievals.map((r) => [r.question_id, r]));
const models = modelAudit.models ?? [];
const modelById = new Map(models.map((m) => [m.model_id, m]));
const modelIds = ['M1', 'M2', 'M3', 'M4'];
const modelTag = (id) => modelById.get(id)?.tag ?? generations.find((g) => g.model_id === id)?.model_tag ?? id;
const sourceWorkbookUnique = [...new Set(questions.map((q) => q.source_workbook).filter(Boolean))];
const metricKeys = ['faithfulness', 'answer_relevance', 'ttft_seconds', 'tps', 'system_ram_peak_bytes_sampled', 'dedicated_vram_peak_bytes_sampled', 'shared_gpu_memory_peak_counter_bytes_sampled'];
const summarize = (modelId, key) => {
  const values = metrics.filter((r) => r.model_id === modelId && Number.isFinite(r[key])).map((r) => r[key]);
  return { n: values.length, mean: mean(values), min: values.length ? Math.min(...values) : null, max: values.length ? Math.max(...values) : null };
};
const generationCount = generations.length;
const validJsonCount = generations.filter((g) => g.schema_valid === true).length;
const judgeScored = judges.filter((j) => j.status === 'scored');
const categories = [...new Set(questions.map((q) => q.inferred_category ?? '未分類'))].sort();
const species = [...new Set(questions.map((q) => q.species_chinese ?? '未分類'))].sort();

const tabNames = ['Dashboard','Questions','Model_Settings','Per_Question','Retrieval','Faithfulness','Answer_Relevance','Accuracy','Instruction_Following','Efficiency','Species_Comparison','Category_Comparison','Model_Comparison','Errors','Limitations','Provenance'];
let workbook;
try {
  await fs.access(xlsxPath);
  workbook = await SpreadsheetFile.importXlsx(await FileBlob.load(xlsxPath));
  for (const name of tabNames) {
    const sheet = workbook.worksheets.getItem(name);
    if (sheet) {
      sheet.deleteAllDrawings();
      const used = sheet.getUsedRange();
      if (used) used.clear({ applyTo: 'all' });
    } else workbook.worksheets.add(name);
  }
} catch {
  workbook = Workbook.create();
  for (const name of tabNames) workbook.worksheets.add(name);
}

const writeSheet = (name, matrix, widths = {}) => {
  const sheet = workbook.worksheets.getItem(name);
  sheet.showGridLines = false;
  const rowCount = matrix.length;
  const colCount = Math.max(1, ...matrix.map((r) => r.length));
  const fixed = matrix.map((r) => Array.from({ length: colCount }, (_, i) => asCell(r[i] ?? null)));
  sheet.getRangeByIndexes(0, 0, rowCount, colCount).values = fixed;
  const used = sheet.getUsedRange();
  used.format.wrapText = true;
  used.format.verticalAlignment = 'center';
  if (rowCount > 0) {
    const header = sheet.getRangeByIndexes(0, 0, 1, colCount);
    header.format.fill = '#17365D';
    header.format.font = { bold: true, color: '#FFFFFF', size: 10 };
    header.format.rowHeight = 30;
    header.format.wrapText = true;
    sheet.freezePanes.freezeRows(1);
  }
  if (rowCount > 1) used.format.borders = { insideHorizontal: { style: 'thin', color: '#E2E8F0' } };
  try { used.format.autofitColumns(); } catch {}
  for (const [col, width] of Object.entries(widths)) sheet.getRange(`${col}:${col}`).format.columnWidth = width;
  if (rowCount > 1) sheet.getRangeByIndexes(1, 0, rowCount - 1, colCount).format.verticalAlignment = 'top';
  return sheet;
};

// Questions: preserve each normalized entry's source workbook, sheet, and original row.
const questionHeaders = ['question_id','species','species_label_in_test_data','topic','inferred_category','question_format','question_text','options','candidate_reference_answer_unverified','candidate_correct_option_unverified','candidate_scoring_points_unverified','candidate_source_urls','candidate_source_ids','source_workbook','source_worksheet','question_bank_excel_row','original_question_id','duplicate_group_id','near_duplicate_group_id','knowledge_group_ids','formal_scoring_suitability','answer_verification_status','human_gold_reviewed','source_page_or_exact_span'];
writeSheet('Questions', rowsToCells(questionHeaders, questions, (q, h) => ({
  question_id:q.question_id, species:q.species_chinese, species_label_in_test_data:q.species_label_in_test_data, topic:q.topic,
  inferred_category:q.inferred_category, question_format:q.question_format, question_text:q.question_text,
  options:q.options, candidate_reference_answer_unverified:q.candidate_reference_answer,
  candidate_correct_option_unverified:q.candidate_correct_option, candidate_scoring_points_unverified:q.candidate_scoring_key_points,
  candidate_source_urls:q.candidate_source_urls, candidate_source_ids:q.source_ids, source_workbook:q.source_workbook,
  source_worksheet:q.source_worksheet ?? q.source_sheet ?? q.source_worksheet_name, question_bank_excel_row:q.question_bank_excel_row,
  original_question_id:q.original_question_id, duplicate_group_id:q.duplicate_group_id,
  near_duplicate_group_id:q.near_duplicate_group_id, knowledge_group_ids:q.knowledge_group_ids ?? q.fact_ids,
  formal_scoring_suitability:q.formal_scoring_suitability, answer_verification_status:q.answer_verification_status,
  human_gold_reviewed:q.human_gold_reviewed, source_page_or_exact_span:q.source_page_or_exact_span
}[h])), {A:22,G:58,I:50,K:40,L:55,N:42,O:28});

const perHeaders = ['question_id','model_id','model_tag','species','category','topic','generation_status','schema_valid','citation_ids_valid','answer','raw_output','faithfulness','answer_relevance','context_sufficient','context_sha256','ttft_first_content_token_seconds','ttft_first_any_token_seconds','tokens_per_second','generated_token_count','wall_time_seconds','system_ram_peak_bytes_sampled','dedicated_vram_peak_bytes_sampled','shared_gpu_memory_peak_counter_bytes_sampled','context_precision_at_5','arithmetic_accuracy','logical_accuracy','gold_status','composite_score','judge_status','judge_rationale','unsupported_claims'];
const perRows = generations.map((g) => {
  const q = questionById.get(g.question_id) ?? {};
  const m = metricByKey.get(`${g.question_id}|${g.model_id}`) ?? {};
  const j = judgeByKey.get(`${g.question_id}|${g.model_id}`) ?? {};
  return [g.question_id,g.model_id,modelTag(g.model_id),q.species_chinese,q.inferred_category,q.topic,g.generation_status,g.schema_valid,g.citation_ids_valid,g.parsed_output?.answer,g.raw_output,m.faithfulness,m.answer_relevance,m.context_sufficient_by_judge,g.context_sha256,g.ttft_first_content_token_seconds,g.ttft_first_any_token_seconds,g.tokens_per_second,g.generated_token_count,g.wall_time_seconds,m.system_ram_peak_bytes_sampled,m.dedicated_vram_peak_bytes_sampled,m.shared_gpu_memory_peak_counter_bytes_sampled,null,null,null,m.gold_status,null,j.status,j.rationale,j.unsupported_claims];
});
writeSheet('Per_Question', [perHeaders, ...perRows], {A:22,C:46,D:18,E:24,J:48,K:65,AE:45});

const retrievalHeaders = ['question_id','query','retrieval_configuration','corpus_version','corpus_sha256','index_checksum','context_id','top5_rank','chunk_id','document_id','page','bm25_rank','dense_rank','reranker_score','context_text','context_text_sha256','aggregate_context_sha256','retrieval_elapsed_seconds','retrieval_hit_miss','expected_evidence_mapping_status','expected_evidence_hit_at_5','support_sufficiency_status','support_sufficiency_reason'];
const retrievalRows = [];
for (const r of retrievals) for (const c of (r.contexts ?? [])) retrievalRows.push([r.question_id,r.query,r.retrieval_config,r.corpus_version,r.corpus_sha256,r.index_checksum,c.context_id,c.top5_rank,c.chunk_id,c.document_id,c.page,c.bm25_rank,c.dense_rank,c.reranker_score,c.text,c.text_sha256,r.context_sha256,r.retrieval_elapsed_seconds,r.retrieval_hit_miss,r.expected_evidence_mapping,r.expected_evidence_hit_at_5,r.support_sufficiency,r.support_sufficiency_reason]);
writeSheet('Retrieval', [retrievalHeaders, ...retrievalRows], {A:22,B:56,C:48,I:40,J:42,O:80,P:68,Q:68,W:45});

const modelSettings = [['Setting','Value','Status / note']];
modelSettings.push(['Ollama version',modelAudit.runtime_version,modelAudit.runtime_version_matches_historical ? 'Matches recorded environment' : 'Version difference / see audit']);
for (const m of models) modelSettings.push([`${m.model_id} tag`,m.tag,`architecture=${m.architecture ?? 'unknown'}; identity=${m.identity_status ?? m.status ?? 'audited'}; digest=${m.digest}`]);
modelSettings.push(['M3 incorrect historical alias','deepseek-r1:8b','Excluded; metadata architecture is Qwen3, not Llama']);
modelSettings.push(['Independent Judge',modelAudit.judge?.tag ?? modelAudit.judge_tag ?? 'mistral-nemo:12b-instruct-2407-q4_K_M',`digest=${modelAudit.judge?.digest ?? 'see model_runtime_alignment.json'}; independent from candidates`]);
modelSettings.push(['Embedding',modelAudit.embedding?.tag ?? 'bge-m3:latest',`digest=${modelAudit.embedding?.digest ?? 'see model_runtime_alignment.json'}`]);
modelSettings.push(['Retrieval','BM25 + BGE-M3 Dense + RRF k=60 + BGE Reranker + Top-5','Same freshly retrieved contexts fixed across all four generators']);
modelSettings.push(['Reranker','BAAI/bge-reranker-v2-m3','Dedicated reranker environment; no Production setting changed']);
modelSettings.push(['Generation options','temperature=0; top_p=1; seed=15015; num_predict=1024; num_ctx=8192','Same request options and JSON schema for all models']);
modelSettings.push(['Prompt leakage control','Question + retrieved Top-5 only','Candidate answers and scoring rubrics excluded from generator prompts']);
modelSettings.push(['Judge leakage control','Question + Context + model answer only','Candidate answers and scoring rubrics excluded from Judge prompts']);
modelSettings.push(['Metric weights',metricSpec.historical_weights ?? metricSpec.weights ?? 'See fish_test_metric_spec.json','Exploratory only; TTFT/TPS/Memory normalization and final weighting not frozen']);
writeSheet('Model_Settings', modelSettings, {A:32,B:60,C:100});

const faithRows = generations.map((g) => { const j=judgeByKey.get(`${g.question_id}|${g.model_id}`)??{}; const q=questionById.get(g.question_id)??{}; return [g.question_id,g.model_id,modelTag(g.model_id),q.species_chinese,q.inferred_category,j.faithfulness,j.context_sufficient,j.rationale,j.unsupported_claims,j.status]; });
writeSheet('Faithfulness', [['question_id','model_id','model_tag','species','category','faithfulness_0_1_exploratory','context_sufficient','judge_rationale','unsupported_claims','judge_status'], ...faithRows], {A:22,C:46,H:70,I:55});
const relevanceRows = generations.map((g) => { const j=judgeByKey.get(`${g.question_id}|${g.model_id}`)??{}; const q=questionById.get(g.question_id)??{}; return [g.question_id,g.model_id,modelTag(g.model_id),q.species_chinese,q.inferred_category,j.answer_relevance,j.rationale,j.status]; });
writeSheet('Answer_Relevance', [['question_id','model_id','model_tag','species','category','answer_relevance_0_1_exploratory','judge_rationale','judge_status'], ...relevanceRows], {A:22,C:46,G:70});

const accuracyRows = questions.map((q) => [q.question_id,q.species_chinese,q.inferred_category,q.question_text,q.candidate_reference_answer,'candidate answer not independently verified; not Gold',null,'N/A — no independent answer validation for formal accuracy',q.calculation_record ? 'calculation candidate; formula/units/range/tolerance unverified' : 'not a verified deterministic calculation item',q.candidate_source_urls]);
writeSheet('Accuracy', [['question_id','species','category','question_text','candidate_reference_answer_unverified','candidate_answer_status','model_accuracy','accuracy_status','arithmetic_accuracy_status','source_url'], ...accuracyRows], {A:22,D:62,E:60,H:60,J:60});

const ifrRows = generations.map((g) => [g.question_id,g.model_id,modelTag(g.model_id),g.schema_valid,g.citation_ids_valid,g.generation_status,g.parse_error,g.parsed_output?.citations?.length ?? null,g.parsed_output?.uncertainty ?? null,'Structural JSON/schema compliance only; not general instruction-following quality']);
writeSheet('Instruction_Following', [['question_id','model_id','model_tag','schema_valid_structural_ifr','citation_ids_valid','generation_status','parse_error','citation_count','uncertainty','scope_note'], ...ifrRows], {A:22,C:46,G:52,I:55,J:66});

const efficiencyRows = generations.map((g) => { const mem=(g.attempts??[]).at(-1)?.memory??{}; return [g.question_id,g.model_id,modelTag(g.model_id),g.generated_token_count,g.ttft_first_content_token_seconds,g.ttft_first_any_token_seconds,g.tokens_per_second,g.wall_time_seconds,mem.system_ram_peak_bytes_sampled,mem.dedicated_vram_peak_bytes_sampled,mem.shared_gpu_memory_peak_counter_bytes_sampled,mem.system_ram_sample_count,mem.dedicated_vram_sample_count,mem.shared_gpu_sample_count,mem.shared_gpu_scope]; });
writeSheet('Efficiency', [['question_id','model_id','model_tag','generated_tokens','ttft_first_content_sec','ttft_first_any_sec','tps_ollama','wall_time_sec','system_ram_peak_bytes_sampled','dedicated_vram_peak_bytes_sampled','shared_gpu_peak_bytes_sampled','ram_sample_count','dedicated_vram_sample_count','shared_gpu_sample_count','measurement_scope'], ...efficiencyRows], {A:22,C:46,O:65});

const groupedRows = (groups) => {
  const result=[];
  for (const group of groups) for (const mid of modelIds) {
    const ids=new Set(questions.filter((q)=>group.key==='species'?q.species_chinese===group.value:q.inferred_category===group.value).map(q=>q.question_id));
    const subset=metrics.filter(m=>ids.has(m.question_id)&&m.model_id===mid);
    const f=subset.map(m=>m.faithfulness).filter(Number.isFinite), rel=subset.map(m=>m.answer_relevance).filter(Number.isFinite), tt=subset.map(m=>m.ttft_seconds).filter(Number.isFinite), tps=subset.map(m=>m.tps).filter(Number.isFinite);
    const gens=generations.filter(g=>ids.has(g.question_id)&&g.model_id===mid);
    result.push([group.value,mid,modelTag(mid),ids.size,mean(f),f.length,mean(rel),rel.length,pct(gens.filter(g=>g.schema_valid===true).length,gens.length),gens.length,mean(tt),tt.length,mean(tps),tps.length]);
  }
  return result;
};
const groupHeaders=['species','model_id','model_tag','pilot_questions_in_group','faithfulness_mean','faithfulness_n','answer_relevance_mean','answer_relevance_n','structural_ifr_rate','generation_n','ttft_content_mean_sec','ttft_n','tps_mean','tps_n'];
writeSheet('Species_Comparison', [groupHeaders, ...groupedRows(species.map(value=>({key:'species',value})))], {A:24,C:48});
const catHeaders=['inferred_category_heuristic','model_id','model_tag','pilot_questions_in_group','faithfulness_mean','faithfulness_n','answer_relevance_mean','answer_relevance_n','structural_ifr_rate','generation_n','ttft_content_mean_sec','ttft_n','tps_mean','tps_n'];
writeSheet('Category_Comparison', [catHeaders, ...groupedRows(categories.map(value=>({key:'category',value})))], {A:30,C:48});

const comparisonRows = modelIds.map((mid) => {
  const gens=generations.filter(g=>g.model_id===mid); const validJ=judges.filter(j=>j.model_id===mid&&j.status==='scored');
  const nttft=summarize(mid,'ttft_seconds'), ntps=summarize(mid,'tps'), nram=summarize(mid,'system_ram_peak_bytes_sampled'), nvram=summarize(mid,'dedicated_vram_peak_bytes_sampled'), nshared=summarize(mid,'shared_gpu_memory_peak_counter_bytes_sampled');
  return [mid,modelTag(mid),modelById.get(mid)?.digest??gens[0]?.model_digest??null,gens.filter(g=>g.generation_status==='success').length,gens.filter(g=>g.generation_status!=='success').length,validJ.length,mean(validJ.map(j=>j.faithfulness).filter(Number.isFinite)),validJ.filter(j=>Number.isFinite(j.faithfulness)).length,mean(validJ.map(j=>j.answer_relevance).filter(Number.isFinite)),validJ.filter(j=>Number.isFinite(j.answer_relevance)).length,pct(gens.filter(g=>g.schema_valid===true).length,gens.length),gens.filter(g=>g.schema_valid===true).length,nttft.mean,nttft.n,ntps.mean,ntps.n,nram.mean,nram.n,nvram.mean,nvram.n,nshared.mean,nshared.n,null,'No winner: weighting/normalization is not frozen; candidate answers are not Gold'];
});
writeSheet('Model_Comparison', [['model_id','model_tag','digest','successful_generations','failed_generations','judge_scored_n','faithfulness_mean','faithfulness_n','answer_relevance_mean','answer_relevance_n','structural_ifr_rate','ifr_valid_n','ttft_content_mean_sec','ttft_n','tps_mean','tps_n','system_ram_peak_mean_bytes','ram_n','dedicated_vram_peak_mean_bytes','vram_n','shared_gpu_peak_mean_bytes','shared_gpu_n','weighted_total','comparison_status'], ...comparisonRows], {A:18,B:50,C:68,X:80});

const errorRows=[];
for(const g of generations){ if(g.generation_status!=='success'||g.parse_error||g.execution_error) errorRows.push(['generator',g.question_id,g.model_id,modelTag(g.model_id),g.generation_status,g.execution_error,g.parse_error,g.attempts?.at(-1)?.done_reason]); }
for(const j of judges){ if(j.status!=='scored') errorRows.push(['judge',j.question_id,j.model_id,j.judge_tag,j.status,j.execution_error,j.parse_error,j.reason]); }
for(const e of (pilot.errors??[])) errorRows.push([e.stage??'runtime',null,e.model_id??null,null,'error',e.error??null,e.traceback??null,null]);
writeSheet('Errors', [['stage','question_id','model_id','model_tag_or_judge','status','execution_error','parse_error_or_traceback','reason'], ...errorRows], {A:18,D:52,F:65,G:90,H:80});

const limitations=[
 ['Candidate Gold','Blocked','180 candidate/reference answers exist, but none has independent Gold approval; do not score answer accuracy.'],
 ['Faithfulness','Exploratory','Independent Judge Mistral NeMo evaluates answer claims against the fixed retrieved contexts; not human-reviewed.'],
 ['Answer Relevance','Exploratory','Independent Judge score from 0–1; report valid N per model.'],
 ['Context Precision@5','Not evaluable','No independently verified expected evidence-to-chunk mapping for these questions; N=0, not zero performance.'],
 ['Arithmetic Accuracy','Not evaluable','No verified formula, units, conditions, rounding, and tolerance set; N=0.'],
 ['Logical Accuracy','Not evaluable','No independent logical-accuracy rubric identified in Phase 16–20 files; N=0.'],
 ['Instruction Following Rate','Partial proxy','Measured only as structured JSON/schema compliance; do not call it broad instruction-following capability.'],
 ['TTFT / TPS','Measured','TTFT uses streamed first content token; TPS uses Ollama eval_count/eval_duration.'],
 ['RAM','Sampled system metric','Global system RAM high-water samples, not process-specific memory; sampled peaks are lower bounds.'],
 ['Dedicated VRAM','Sampled device metric','nvidia-smi sampled peak; transient peaks may be missed.'],
 ['Shared GPU Memory','Unavailable in Pilot','Windows performance counter capture produced no usable samples; report N/A, not 0.'],
 ['Weighted score / Winner','Not calculated','Metric weights and speed/memory normalization not confirmed/frozen; no composite ranking or Winner.'],
 ['Question dependence','Unresolved','Exact duplicates, near-duplicate pairs, and shared knowledge groups reduce independent sample count.'],
 ['Historical test split','Exploratory only','No independently frozen 120 Selection / 60 Holdout; do not represent this run as formal benchmark.'],
 ['Full suite pytest','Not claimed','Existing Windows tempfile WinError 5 remains separate; no full repository pytest pass is claimed.']
];
writeSheet('Limitations', [['item','status','detail'], ...limitations], {A:34,B:28,C:110});

const sourceFiles = [];
for (const w of sourceWorkbookUnique) sourceFiles.push(['fish_test_source_workbook',w,questions.find(q=>q.source_workbook===w)?.source_workbook_sha256??null,'read-only source; six original XLSX verified against Phase A']);
sourceFiles.push(['phase_a_normalized','reports/evaluation/fish_test_phase_a_20261012/fish_test_questions_normalized.jsonl',null,'Baseline source; see Phase A manifest']);
sourceFiles.push(['E4_manifest','reports/evaluation/experiments/E4_grounded_rrf_reranker_v1/experiment_manifest.json',null,'Historical E4 configuration used for this run; immutable']);
sourceFiles.push(['E4_corpus','data/evaluation/corpus_v2.jsonl',null,'Corpus v2; retrieval-eligible chunks only']);
sourceFiles.push(['Frozen protected manifest','reports/evaluation/final_model_selection/phase20/protected_inputs_before.json',null,`before=${protectBefore.verified_count??protectBefore.entry_count??'see protected_baseline_before.json'}; after=${protectAfter.verified_count??protectAfter.entry_count??'see protected_baseline_after.json'}`]);
sourceFiles.push(['SQLite','rag_store.sqlite3',protectAfter.sqlite_sha256??protectBefore.sqlite_sha256??'see baseline file','protected; expected d7d06d4d2a57d0a57d05bcb6131ffb24aefb226c6bd36349dbc5118d33b11087']);
for(const m of models) sourceFiles.push(['model',m.tag,m.digest,`model_id=${m.model_id}; architecture=${m.architecture??'unknown'}; status=${m.identity_status??m.status??'verified by metadata'}`]);
writeSheet('Provenance', [['artifact_type','path_or_tag','sha256_or_digest','notes'], ...sourceFiles], {A:32,B:94,C:82,D:95});

const dashboardModelRows=modelIds.map(mid=>{
 const fa=summarize(mid,'faithfulness'), re=summarize(mid,'answer_relevance'), tt=summarize(mid,'ttft_seconds'), tp=summarize(mid,'tps');
 const gs=generations.filter(g=>g.model_id===mid);
 return [mid,fa.mean,fa.n,re.mean,re.n,pct(gs.filter(g=>g.schema_valid===true).length,gs.length),gs.filter(g=>g.schema_valid===true).length,gs.length,tt.mean,tt.n,tp.mean,tp.n];
});
const dash = [
 ['Marine Hybrid-RAG Fish Test — 四模型評測',''],
 ['Run ID',pilot.run_id??path.basename(runDir)],
 ['Phase',pilot.phase??execution.phase??'pilot'],
 ['Run status',pilot.status??execution.status??'in progress'],
 ['Unique question records',questions.length],
 ['Generator inference records',generationCount],
 ['Schema-valid answers',validJsonCount],
 ['Judge-scored answers',judgeScored.length],
 ['Historical RAG-ready baseline',25],
 ['Independently verified Human Gold',0],
 ['Weighted total / Winner','Not calculated — metric normalization and weighting not frozen'],
 ['Context Precision@5','N=0; no independent evidence-to-chunk gold mapping'],
 ['', ''],
 ['Model','Faithfulness mean','Faithfulness N','Answer Relevance mean','Answer Relevance N','Structural IFR','IFR valid N','Generation N','TTFT mean sec','TTFT N','TPS mean','TPS N'],
 ...dashboardModelRows
];
const dashboard=writeSheet('Dashboard',dash,{A:42,B:52,D:52});
dashboard.getRange('B5').formulas=[[`=COUNTA(Questions!A2:A${questions.length+1})`]];
dashboard.getRange('B6').formulas=[[`=COUNTA(Per_Question!A2:A${generationCount+1})`]];
dashboard.getRange('B7').formulas=[['=SUM(G15:G18)']];
dashboard.getRange('A14:L14').format.fill='#1F4E78';
dashboard.getRange('A14:L14').format.font={bold:true,color:'#FFFFFF'};
try {
 const chart=dashboard.charts.add('bar',[dashboard.getRange('A15:A18'),dashboard.getRange('B15:B18'),dashboard.getRange('D15:D18')]);
 chart.title='獨立 Judge 分項平均（探索性）';
 chart.setPosition('M14','U31');
} catch (e) { await fs.writeFile(path.join(runDir,'workbook_chart_note.txt'),`Dashboard chart omitted: ${e?.message??e}`,'utf8'); }

workbook.recalculate();
const output=await SpreadsheetFile.exportXlsx(workbook);
await output.save(xlsxPath);
const reopened=await SpreadsheetFile.importXlsx(await FileBlob.load(xlsxPath));
const overview=await reopened.inspect({kind:'workbook,sheet',maxChars:8000,tableMaxRows:3,tableMaxCols:5});
const formulaCheck=await reopened.inspect({kind:'formula',sheetId:'Dashboard',range:'A1:B12',maxChars:3000,options:{maxResults:20}});
await fs.writeFile(path.join(runDir,'workbook_reopen_validation.json'),JSON.stringify({path:xlsxPath,byte_size:(await fs.stat(xlsxPath)).size,sheet_names:tabNames,expected_question_rows:questions.length,expected_generation_rows:generationCount,formula_check:formulaCheck.ndjson??formulaCheck,workbook_overview:overview.ndjson??overview},null,2),'utf8');
try {
 const preview=await reopened.render({sheetName:'Dashboard',autoCrop:'all',scale:1,format:'png'});
 await fs.writeFile(path.join(runDir,'dashboard_preview.png'),new Uint8Array(await preview.arrayBuffer()));
} catch(e) { await fs.writeFile(path.join(runDir,'workbook_render_note.txt'),String(e?.stack??e),'utf8'); }
console.log(JSON.stringify({xlsxPath,bytes:(await fs.stat(xlsxPath)).size,sheets:tabNames.length,questions:questions.length,generations:generationCount,judgeScored:judgeScored.length,overview:(overview.ndjson??'').slice(0,1000)}));
