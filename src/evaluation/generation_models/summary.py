"""Render saved Phase 17 statistics without rescoring or editing outputs."""
import json


def render_detailed_summary(out):
    def load(name):
        return json.loads((out / name).read_text(encoding='utf-8'))
    def number(value):
        return f'{value:.4f}' if isinstance(value, (int, float)) else 'NA'
    def percent(value):
        return f'{value:.2%}' if isinstance(value, (int, float)) else 'NA'
    lines = (out / 'comparison_summary.md').read_text(encoding='utf-8').splitlines()
    def table(headers, rows):
        lines.extend(['', '| ' + ' | '.join(headers) + ' |', '| ' + ' | '.join('---' for _ in headers) + ' |'])
        lines.extend('| ' + ' | '.join(str(v) for v in row) + ' |' for row in rows)
    def heading(text):
        lines.extend(['', '## ' + text, ''])
    def metric_cells(s):
        if not s.get('primary_judge_eligible', True):
            return ['excluded: self-judge'] * 3
        return [number(s['judge_metrics']['metrics'][m]['mean']) for m in ('faithfulness', 'answer_relevancy', 'silver_reference_correctness')]
    overall, reliability, timing = (load(n) for n in ('overall_comparison.json', 'reliability.json', 'latency.json'))
    manifest = load('generator_comparison_manifest.json')
    metadata = []
    for m in manifest['generators']:
        info = m.get('model_show', {}).get('model_info', {})
        key = str(info.get('general.architecture')) + '.context_length'
        metadata.append({'model': m['name'], 'native_context_length': info.get(key),
                         'metadata_key': key, 'configured_context_length': m['configured_context_length'],
                         'provenance': 'Frozen local Ollama model_show.model_info; no pre-execution manifest changes'})
    (out / 'model_context_metadata.json').write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    heading('Model artifacts and common protocol')
    table(['Model/tag', 'Parameters', 'Quantization', 'Native/context used', 'Digest', 'Judge conflict'],
          [[m['name'], m.get('parameter_size'), m.get('quantization'),
            f"{metadata[i]['native_context_length']} / {m['configured_context_length']}", m['digest'], m['judge_conflict']]
           for i, m in enumerate(manifest['generators'])])
    lines.extend(['', 'Ollama 0.35.0; generation_v2; output schema v2; protocol v2.2; temperature=0; top_p=1; seed=15015; max output=1024; maximum attempts=2. No model downloads or per-model prompt/parser customization.', '',
                  'Judge: qwen2.5-coder:7b, frozen Phase 16 digest/settings; RAGAS 0.4.3; BGE-M3 evaluation embeddings. Qwen generator judge metrics are excluded; exploratory self-judge was not run.'])
    heading('Reliability: first pass and final')
    rows = []
    for name, conditions in reliability.items():
        for condition, r in conditions.items():
            rows.append([name, condition, percent(r['first_pass_schema_valid_rate']), percent(r['final_schema_valid_rate']),
                         f"{r['retry_count']} / {r['retry_success']} / {r['retry_failure']}",
                         r['completion_truncation_attempts'], r['input_truncation_attempts'], r['input_truncation_unknown_attempts'],
                         percent(r['raw_output_preservation_rate']), r['raw_capture_failure_count']])
    table(['Model', 'Condition', 'First schema', 'Final schema', 'Retry trigger/success/fail', 'Length attempts', 'Input truncated', 'Input unknown', 'All-attempt raw', 'Capture gaps'], rows)
    lines.extend(['', 'One DeepSeek 8B first attempt lost its stream during byte serialization. Native schema, duration and token counts for that attempt remain unknown. Its single permitted retry was preserved. All final outputs are preserved; the all-attempt raw-capture requirement is not completely met. Unknown durations are excluded, never replaced with zero.'])
    heading('Deterministic citation, abstention and numeric results')
    rows = []
    for name, conditions in overall.items():
        for condition, s in conditions.items():
            d = s.get('deterministic_metrics')
            if not d:
                continue
            recalls = d['required_evidence_citation_recall']
            numeric = d.get('calculation_output_admissibility', {})
            rows.append([name, condition, d['answered_count'], d['insufficient_evidence_count'], d['generation_error_count'],
                         percent(d['strict_citation_validity_rate']), percent(d['recoverable_citation_validity_rate']),
                         *[percent(recalls[k]['strict_recall']) for k in ('all_questions', 'evidence_present', 'evidence_present_and_answered')],
                         number(d['silver_reference_similarity']['f1_mean']),
                         f"{numeric.get('n_exact_numeric_and_valid_output')} / {numeric.get('n_calculation_questions')}"])
    table(['Model', 'Condition', 'Answered', 'Abstained', 'Error', 'Strict cite', 'Recoverable cite', 'Recall A', 'Recall B', 'Recall C', 'Silver F1', 'Usable exact calc'], rows)
    lines.extend(['', 'A=all questions; B=required evidence present; C=present and answered. These are required-chunk micro recalls; paired citation bootstrap uses per-question macro recall over all 169 questions. Calculation n=3, descriptive.'])
    heading('Judge score validity counts')
    table(['Model', 'Condition', 'Metric', 'Mean', 'n answered', 'n valid', 'n failed', 'n skipped'],
          [[name, c, m, number(v['mean']), v['n_total'], v['n_valid'], v['n_failed'], v['n_skipped']]
           for name, conditions in overall.items() for c, s in conditions.items()
           for m, v in s.get('judge_metrics', {}).get('metrics', {}).items()])
    paired = load('paired_bootstrap.json')
    for title, comparisons in [('Within model: G1 minus G0', paired['within_model_G1_minus_G0']),
                               ('Cross model: E4 condition', paired['cross_model']['e4_top5']),
                               ('Cross model: Oracle condition', paired['cross_model']['oracle'])]:
        heading(title + ' — paired 95% CI')
        rows = []
        for label, values in comparisons.items():
            for metric, r in values.items():
                ci = r['ci95']
                rows.append([label, metric, r['n'], number(r['mean']),
                             f'[{number(ci[0])}, {number(ci[1])}]',
                             r.get('status', 'separated on this sample' if r.get('clearly_separated_on_silver_sample') else 'not clearly separated')])
        table(['Comparison/direction', 'Metric', 'Valid pairs', 'Difference', '95% CI', 'Interpretation'], rows)
    for field in ('query_style', 'species', 'category'):
        data = load('by_' + field + '.json')
        heading('Subgroups: ' + field)
        rows = []
        for name in overall:
            for condition, groups in data[name].items():
                for label, s in groups.items():
                    d = s['deterministic_metrics']
                    rows.append([label, name, condition, s['judge_metrics']['n_questions'], d['answered_count'],
                                 *metric_cells(s), percent(d['required_evidence_citation_recall']['evidence_present_and_answered']['strict_recall'])])
        table(['Group', 'Model', 'Condition', 'n questions', 'Answered', 'Faithfulness', 'Relevancy', 'Silver reference', 'Citation recall C'], rows)
    lines.extend(['', 'Milkfish has zero questions and no metrics. Small species/category groups and calculation n=3 are descriptive.'])
    heading('Retrieval hit and miss diagnostics')
    hit, miss = load('retrieval_hit_comparison.json'), load('retrieval_miss_behavior.json')
    rows = []
    for name in overall:
        s = hit[name]
        rows.append([name, 'complete evidence + answered', s['judge_metrics']['n_questions'], *metric_cells(s), s['judge_metrics']['status_counts']])
        s = miss[name]['summary']
        rows.append([name, 'same 11 incomplete-evidence questions', s['judge_metrics']['n_questions'], *metric_cells(s), s['judge_metrics']['status_counts']])
    table(['Model', 'Subset', 'n', 'Faithfulness', 'Relevancy', 'Silver reference', 'Status counts'], rows)
    heading('Performance and measured memory')
    rows = []
    for name, conditions in timing.items():
        for condition, t in conditions.items():
            f, mem = t['final_attempt'], t['memory']
            rows.append([name, condition, number(t['first_observed_load_seconds']),
                         number(f['ttft_seconds']['mean']), number(f['ttft_seconds']['p95']),
                         number(f['tokens_per_second']['mean']), number(t['question_protocol_latency']['mean']),
                         number(t['question_protocol_latency']['p95']), t['question_protocol_latency_missing_count'],
                         number(mem.get('peak_ram_bytes') / 2**30 if mem.get('peak_ram_bytes') is not None else None),
                         mem.get('peak_device_vram_used_mib', 'NA'), mem.get('peak_vram_bytes')])
    table(['Model', 'Condition', 'First load s', 'TTFT mean s', 'TTFT p95 s', 'TPS mean', 'Protocol mean s', 'Protocol p95 s', 'Duration unknown', 'Observed RAM GiB', 'Device VRAM MiB', 'Process peak VRAM'], rows)
    lines.extend(['', 'RAM is sampled Ollama + llama-server working-set sum, not unique physical RAM. Device VRAM is the whole GPU, not model-process peak. Peaks cover the shared model session, not separate condition peaks; DeepSeek 8B has an early sampling gap. Baseline peaks were not measured. TTFT is first final-answer content; TPS includes native thinking tokens when emitted. Historical Gemma timing, offload and cache differences prevent a controlled edge-latency winner claim. See latency.json for medians, token counts and allocations.'])
    heading('Judge repeatability: 30 new outputs, two fresh runs')
    repeat = load('judge_repeatability.json')
    table(['Metric', 'Valid pairs', 'Exact agreement', 'MAD', 'Correlation'],
          [[m, r['n_valid_pairs'], percent(r['exact_agreement']), number(r['mean_absolute_difference']), number(r['pearson_correlation'])]
           for m, r in repeat.items() if isinstance(r, dict) and 'n_valid_pairs' in r])
    lines.extend(['', 'Additional saved-score diagnostics: primary versus each repeat run. No extra Judge calls and no replacement of primary scores.'])
    table(['Comparison', 'Metric', 'Valid pairs', 'Exact agreement', 'MAD', 'Correlation'],
          [[label, m, r['n_valid_pairs'], percent(r['exact_agreement']), number(r['mean_absolute_difference']), number(r['pearson_correlation'])]
           for label in ('primary_vs_repeat1', 'primary_vs_repeat2') for m, r in repeat[label].items()])
    heading('Pareto and error analysis')
    frontier = load('pareto_analysis.json')
    lines.extend([f"Common valid quality cohort: {frontier['common_valid_quality_n']} questions.", '',
                  'Descriptive non-dominated models: ' + ', '.join(frontier['non_dominated']) + '.', '',
                  'No weighted composite, confidence-based dominance or automatic final model selection. Qwen is excluded from the primary quality frontier.'])
    errors = load('error_summary.json')
    table(['Model', 'Diagnostic', 'Count over both conditions'],
          [[name, label, count] for name, counts in errors.items() for label, count in sorted(counts.items())])
    heading('Tests, environment and protected artifacts')
    if (out / 'execution_interruption.json').exists():
        lines.extend(['The tool runtime reset interrupted the evaluator process. Evaluation resumed from immutable metric checkpoints; completed scores and generated answers were not rerun. The last saved raw record matched a completed metric, but the interrupted in-flight state is unknown. See execution_interruption.json; process-local call IDs must be read with full trace identity.', ''])
    lines.extend(['Final results are in test_summary.json and compatibility.json after the final audit. Existing environments and protected Corpus/Silver/E1-E4/Phase15-16 outputs are verified by size/mtime/SHA-256; production HTTP is recorded in production_smoke.json.', '',
                  'Historical Windows WinError 4551 / c10_cuda.dll blocking is retained. Initial and final import-only torch smoke outcomes are in environment_limitations.json; no reranker model scoring or E4 regeneration was performed.', '',
                  'Phase 17 stops here. Final edge selection still requires target-device validation, resolving the self-judge conflict with an independent evaluator, and independent checks of the Gemma-generated Silver references. No prompt/retrieval tuning or production migration was performed.'])
    (out / 'comparison_summary.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
