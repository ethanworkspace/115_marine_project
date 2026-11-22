from pathlib import Path
import sys,json,collections
W=Path(__file__).resolve().parent;sys.path.insert(0,str(W))
from frozen_runner import jl,write
m=json.loads((W/'evaluation_metrics_11.json').read_text(encoding='utf-8'));f=json.loads((W/'frozen_evaluation_manifest.json').read_text(encoding='utf-8'));gs=jl(W/'generator_final_results_720.jsonl');ps=jl(W/'per_question_metrics.jsonl');refs=jl(W/'verified_reference_answers_v3.jsonl');av=jl(W/'corpus_evidence_availability_180.jsonl');p5=jl(W/'context_precision_detailed.jsonl');ab=json.loads((W/'abstention_analysis.json').read_text(encoding='utf-8'));group=json.loads((W/'source_group_evaluation.json').read_text(encoding='utf-8'));breakdown=json.loads((W/'species_category_comparison.json').read_text(encoding='utf-8'));dd=json.loads((W/'duplicate_sensitivity.json').read_text(encoding='utf-8'))
short=lambda v,n=320:str(v or '')[:n]+('… [完整內容見JSONL]' if len(str(v or ''))>n else '')
def rows_for(dim):
 out=[]
 for value,layers in breakdown[dim].items():
  for layer,models in layers.items():
   for mid,metrics in models.items():
    for metric,s in metrics.items():out.append([value,layer,mid,metric,s['mean'],s['n'],s['min'],s['max']])
 return out
metrics=[]
for layer,models in m['all_available_samples'].items():
 for mid,vals in models.items():
  for metric,s in vals.items():
   if metric.endswith('_counts'):continue
   paired=m['four_model_paired_samples'][layer][metric]
   metrics.append([layer,mid,metric,s['mean'],s['n'],s['median'],s['min'],s['max'],paired['models'][mid]['mean'],paired['common_question_n']])
raw=[]
for i,g in enumerate(gs,1):
 raw.append([g['question_id'],g['model_id'],g['species'],g['category'],g['context_count'],g['answer_origin'],g['api_completed'],g['raw_model_structure_valid'],(g.get('parsed_model_response') or {}).get('abstained'),g['raw_citation_validation']['status'],short(g['raw_model_response']),short(g['final_response'].get('answer')),g['final_response'].get('reason'),g['context_digest'],g['model_digest'],i,g['stream_trace_file'],g['prompt_file']])
per=[]
for p in ps:per.append([p['question_id'],p['model_id'],p['answer_layer'],p['species'],p['category'],p['answer_origin'],p['faithfulness'],p['judge_answer_relevance'],p['bge_m3_cosine'],p['structured_ifr'],p['ttft_seconds'],p['tps'],p['peak_system_ram_gib'],p['peak_dedicated_vram_gib'],p['logical_accuracy'],p['arithmetic_accuracy'],p['quality_missing_reason'],p['logical_reason'],p['arithmetic_reason'],p['canonical_result_line'],p.get('bge_missing_reason'),p.get('response_content_status')])
accuracy=[]
for typ,filename in [('Logical','logical_accuracy_detailed.jsonl'),('Arithmetic','arithmetic_accuracy_detailed.jsonl')]:
 for a in jl(W/filename):accuracy.append([a['question_id'],a['model_id'],a['answer_layer'],typ,a['verdict'],a.get('reason'),a['answer_origin'],' | '.join(a['source_group_ids']),a['rubric_sha256'],a.get('parsed_numeric_value'),a.get('decimal_reference_result'),a.get('unit_valid')])
attempts=[]
for i,a in enumerate(jl(W/'generator_raw_attempts_720.jsonl'),1):attempts.append([a['question_id'],a['model_id'],a['attempt'],a['api_completed'],a['error'],a['wall_seconds'],a['ttft_visible_content_seconds'],a['first_thinking_seconds'],a['tps'],a['engine_metrics'].get('eval_count'),a['engine_metrics'].get('eval_duration'),a['engine_metrics'].get('done_reason'),a['hardware']['sample_count'],a['raw_model_structure_valid'],a['attempt_id'],a['stream_trace_file']])
questions=[]
rm={r['question_id']:r for r in refs};ct={r['question_id']:r for r in jl(W/'frozen_corpus_and_contexts_180.jsonl')}
for a in av:
 r=rm[a['question_id']];questions.append([a['question_id'],a['species'],a['category'],a['original_question'],a['gap_classification'],len(ct[a['question_id']]['top5']),bool(r.get('logical_rubric')),bool(r.get('expected_calculation')),short(r.get('reference_answer'),600),' | '.join(a['original_record_group_keys']),r.get('rubric_sha256'),'AUTO_SOURCE_VERIFIED; NOT_HUMAN_GOLD' if r.get('logical_rubric') or r.get('expected_calculation') else r.get('eligibility')])
abrows=[]
for mid,a in ab.items():
 for label,val in [('API completed',a['api_completed']),('API failed',a['api_failed']),('Raw model declared abstentions',a['raw_model_declared_abstentions']),('Raw citation failures',a['raw_citation_failed']),('Qualified50 model direct answers',a['qualified50_model_direct_answer_n']),('Qualified50 system answers',a['qualified50_system_answer_n']),('Unnecessary refusal candidates',len(a['qualified50_unnecessary_abstention_candidates'])),('Raw answers with insufficient evidence',len(a['raw_answers_with_insufficient_evidence'])),('Final citation pass',a['final_citation_pass_n'])]:abrows.append([mid,label,val,180 if 'Qualified50' not in label else 50])
 for origin,n in a['answer_origins'].items():abrows.append([mid,origin,n,180])
grows=[]
for name,g in group['groups'].items():
 for layer,models in g['metrics'].items():
  for mid,ms in models.items():
   for metric,s in ms.items():grows.append([name,g['question_n'],layer,mid,metric,s['mean'],s['n'],' | '.join(g['question_ids'])])
paired=[]
for layer,ms in m['four_model_paired_samples'].items():
 for metric,p in ms.items():
  for mid,s in p['models'].items():paired.append([layer,metric,mid,p['common_question_n'],s['mean'],s['median'],s['min'],s['max'],' | '.join(p['question_ids'])])
dedup=[]
for layer,ms in dd['descriptive_metrics'].items():
 for mid,vs in ms.items():
  for metric,s in vs.items():dedup.append([layer,mid,metric,175,s['mean'],s['n'],m['all_available_samples'][layer][mid][metric]['mean']])
errors=[[g['question_id'],g['model_id'],g['error'],g.get('validation_error'),g['raw_model_structure_valid'],g['answer_origin'],g['final_response'].get('reason'),g['attempt_id']] for g in gs if g['error'] or g.get('validation_error')]
for c in jl(W/'response_content_audit_1440.jsonl'):
 if c['answer_layer']=='model' and c['content_status'] in {'QUESTION_ECHO_NO_ANSWER','INCOMPLETE_ANTECEDENT_NO_ANSWER'}:
  g=next(g for g in gs if g['question_id']==c['question_id'] and g['model_id']==c['model_id']);errors.append([g['question_id'],g['model_id'],None,'RESPONSE_CONTENT: '+c['reason'],g['raw_model_structure_valid'],g['answer_origin'],'原始生成保留；無可辨識答案的準確率N/A',g['attempt_id']])
limits=[['設計','原180題多次參與開發；本次是單一凍結系統的探索性回歸，不是未曝光 Holdout。'],['Human Gold','0題。50題僅為AUTO_SOURCE_VERIFIED；Logical與Arithmetic由自動判準／獨立AI Judge輔助核驗。'],['來源依賴','50題來自10組原始JSON紀錄或PDF頁，不能當作50筆獨立觀測。'],['拒答與品質','只對實際可讀且非宣告拒答的答案計算品質；必須連同回答率、有效N與配對子集閱讀。'],['P@5','12題刻意抽樣、60段，均值0.30只代表該子集。303段UNVERIFIED保留；不得外推180題。'],['算術','13題來源綁定的比例／差值／區間計算，沒有核實FCR、SGR或bFCR協定。'],['記憶體','System-level sampled peak：每0.5秒採樣，含其他系統程序，不是模型程序專屬峰值；Shared GPU Memory為N/A。'],['TTFT','從HTTP請求開始至首個可見response串流事件；thinking首事件另存，不與可見TTFT混用。'],['TPS','Ollama eval_count ÷ (eval_duration / 1e9)，可能包含引擎計入的推理token，未稱為純可見字詞速度。'],['原始與系統','確定性摘取成功不計模型直接成功；Raw JSON Schema失敗不因回補而轉成IFR通過。'],['加權與Winner','未建立加權總分，未選正式Winner。'],['適用性','藥品許可不等於現行用藥建議，DGBAS限2020描述性Fact，無年度鰻魚統計維持Context-only。']]
limits=[(x if x[0]!='TTFT' else ['TTFT','串流呼叫包裝器啟動至首個實際可見JSON內容事件，包含取樣器初始化成本；thinking首事件另存。不是首個有意義答案字詞時間。']) for x in limits]
limits.append(['鱸魚範圍','鱸魚題組依原工作簿金目鱸情境評估；不外推全部鱸魚物種。'])
limits.append(['解析器更正','初算把部分題目複誦的輸入數值當成結果；保留v1原始衍生分數，BGE有效答案與Logical／Arithmetic的無答案個案改為N/A。生成、來源、公式及Rubric不變；Judge原始評分不改寫。'])
limits.append(['兩層效能','模型／系統兩層重用同一次Generator的TTFT、TPS、記憶體與原始JSON IFR，並非兩次獨立量測；未另量測最終系統答案出現延遲。'])
uncertainty=[]
for layer,ms in group['paired_component_bootstrap'].items():
 for metric,models in ms.items():
  for mid,s in models.items():
   ci=s['exploratory_component_bootstrap_95pct']
   uncertainty.append([layer,metric,mid,s['paired_question_n'],s['source_dependency_component_n'],s['equal_component_mean'],ci[0] if ci else None,ci[1] if ci else None,'探索性群組bootstrap，非專家真值或正式顯著性'])
settings=[['Run ID',W.name],['Corpus version',f['corpus']['corpus_version']],['Corpus SHA',f['corpus']['database_sha256']],['Prompt version',f['prompt_version']],['Frozen at',f['frozen_at']],['RRF k',f['retrieval']['rrf_k']],['Reranker',f['retrieval']['reranker']],['Generator options',json.dumps(f['generation_options'])],['Human Gold',0],['Source groups',10],['Paired dependency components',group['independent_components_n']],['Raw generation JSONL',str(W/'generator_final_results_720.jsonl')],['Raw attempt JSONL',str(W/'generator_raw_attempts_720.jsonl')],['Judge JSONL',str(W/'judge_quality_detailed.jsonl')],['Memory scope','system_level_sampled_peak'],['Scoring','NO_AGGREGATE_SCORE_OR_WINNER']]
settings.extend([['Active isolated database',str(W/'corpus/marine_hybrid_rag_corpus_v3.sqlite3')],['TTFT timer','Request-wrapper start includes sampler startup; first actual visible stream event; first thinking separate'],['Judge','mistral-nemo:12b-instruct-2407-q4_K_M'],['Judge digest','daf6737417121831e572a9c482e92a221ee0c33537f35f1f857c7b4f7191df55'],['Source manifest',str(W/'frozen_source_manifest.json')],['Frozen reference answers',str(W/'verified_reference_answers_v3.jsonl')],['Logical source scoring',str(W/'logical_accuracy_detailed.jsonl')],['Arithmetic source scoring',str(W/'arithmetic_accuracy_detailed.jsonl')]])
for mid,s in f['models'].items():settings.extend([[f'{mid} model',s['tag']],[f'{mid} digest',s['digest']],[f'{mid} quantization',s['details']['quantization_level']]])
write('workbook_data.json',{'metrics':metrics,'per_question':per,'raw':raw,'accuracy':accuracy,'attempts':attempts,'questions':questions,'p5':[[q['question_id'],q['species'],q['category'],q['top5_count'],q['reliably_binary_labeled_count'],q['p_at_5'],q.get('lower_bound'),q.get('upper_bound'),q['status'],q.get('reason')] for q in p5],'species':rows_for('species'),'category':rows_for('category'),'abstention':abrows,'groups':grows,'group_uncertainty':uncertainty,'paired':paired,'duplicates':dedup,'errors':errors,'limitations':limits,'settings':settings,'summary':m})
print('Workbook data prepared',len(gs),len(ps),flush=True)
