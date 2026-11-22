"""Separate Silver quality, reliability and performance; no composite score."""
from __future__ import annotations

from collections import Counter, defaultdict
from itertools import combinations

from .core import CONDITIONS, METRICS, ITERATIONS, SEED, pair_compare, scalar, stats, pareto, total_latency_or_none
from .runner import OUT, ROOT, MODELS, model_dir, load_json, all_rows, write_jsonl
from ..generation.frozen import read_jsonl, sha256_file
from ..generation.runner_v2 import _summary
from ..generation.retry_v21 import first_pass_metrics, validate_attempt_records
from ..ragas_eval.core import summarize, valid_score, bootstrap, repeatability, error_labels
from ..ragas_eval.runner import write_json


def condition_summary(rows):
    judged = summarize(rows, ci=False)
    for metric in METRICS:
        values = [scalar(r, metric) for r in rows if scalar(r, metric) is not None]
        judged['metrics'][metric]['bootstrap'] = bootstrap(values, iterations=ITERATIONS, seed=SEED)
        judged['metrics'][metric]['n_non_answered_excluded'] = sum(r['status'] != 'answered' for r in rows)
        judged['metrics'][metric]['n_abstained_excluded'] = sum(r['status'] == 'insufficient_evidence' for r in rows)
        judged['metrics'][metric]['n_generation_error_excluded'] = sum(r['status'] == 'generation_error' for r in rows)
    d = [r['deterministic_generation'] for r in rows]
    deterministic = _summary(d, [{'raw_output': 'captured'} for _ in rows]) if rows else None
    if deterministic is not None:
        calculations = [r for r in rows if r['deterministic_generation'].get('calculation_numeric_evaluation')]
        deterministic['calculation_output_admissibility'] = {
            'n_calculation_questions': len(calculations),
            'n_answered_valid_outputs': sum(r['status'] == 'answered' and r['deterministic_generation']['schema_valid'] for r in calculations),
            'n_exact_numeric_and_valid_output': sum(r['status'] == 'answered' and r['deterministic_generation']['schema_valid'] and r['deterministic_generation']['calculation_numeric_evaluation'].get('exact_numeric_match') is True for r in calculations),
            'numerically_matching_but_unusable_output': sum(r['status'] != 'answered' and r['deterministic_generation']['calculation_numeric_evaluation'].get('exact_numeric_match') is True for r in calculations),
            'interpretation': 'Original numeric evaluator is unchanged; invalid or abstaining outputs are not system-level calculation successes. Three-question descriptive sample.'}
    return {'judge_metrics': judged, 'deterministic_metrics': deterministic,
            'primary_judge_eligible': not any(r.get('judge_conflict') for r in rows),
            'small_sample_descriptive': len(rows) < 20,
            'raw_capture_scope': 'Final outputs; all-attempt capture failures are separately retained in reliability and execution diagnostics',
            'citation_support_limitation': 'Context-ID provenance validity does not establish claim-to-citation support; Faithfulness judges all supplied contexts.'}


def reliability(name, condition, rows):
    if name == MODELS[0]:
        label = 'G0_grounded_oracle_generation_v2_2' if condition == 'oracle' else 'G1_grounded_e4_top5_generation_v2_2'
        folder = ROOT / 'reports/evaluation/generation' / label
        attempts = read_jsonl(folder / 'attempts.jsonl')
        # Legacy file names are intentionally resolved without altering any frozen file.
    else:
        attempts = [a for a in read_jsonl(model_dir(name) / 'attempts.jsonl') if a['condition'] == condition]
    validate_attempt_records(attempts, question_ids=[r['question_id'] for r in rows])
    retries = [a for a in attempts if a['attempt_number'] == 2]
    final = [r['deterministic_generation'] for r in rows]
    audits = [(a.get('captured_runtime') or {}).get('context_window_budget') or a.get('context_window_budget') or {} for a in attempts]
    return {**first_pass_metrics(attempts, question_count=len(rows)),
            'final_schema_valid_rate': sum(r['schema_valid'] for r in final) / len(final),
            'final_json_parse_rate': sum(r['json_parse_valid'] for r in final) / len(final),
            'final_citation_parse_rate': sum(r['citation_parse_valid'] for r in final) / len(final),
            'retry_count': len(retries), 'retry_success': sum(a['attempt_valid'] for a in retries),
            'retry_failure': sum(not a['attempt_valid'] for a in retries),
            'raw_output_preservation_rate': sum(a['raw_output_preserved'] for a in attempts) / len(attempts),
            'attempt_count': len(attempts), 'generation_errors': sum(r['status'] == 'generation_error' for r in final),
            'raw_capture_failure_count': sum(not a['raw_output_preserved'] for a in attempts),
            'native_schema_unknown_due_to_capture_loss': sum(bool(a.get('capture_failure')) for a in attempts),
            'completion_truncation_attempts': sum(a.get('finish_reason') == 'length' for a in attempts),
            'completion_truncation_final': sum(r.get('done_reason') == 'length' for r in final),
            'input_truncation_attempts': sum(a.get('input_truncated') is True for a in audits),
            'input_truncation_unknown_attempts': sum(a.get('input_truncated') is None for a in audits),
            'context_margins': stats([a.get('remaining_context_margin') for a in audits]),
            'unknown_context_id': sum(r.get('citation_error_taxonomy', {}).get('unknown_context_id', 0) for r in final),
            'status_counts': dict(Counter(r['status'] for r in final)),
            'schema_failures_remain_failures': True}


def latency(name, condition, rows):
    if name == MODELS[0]:
        d = [r['deterministic_generation'] for r in rows]
        memory = {'peak_ram_bytes': None, 'peak_vram_bytes': None, 'reason': 'Frozen baseline did not measure these peaks'}
        prefix = 'G0' if condition == 'oracle' else 'G1'
        label = f'{prefix}_grounded_{"oracle" if prefix == "G0" else "e4_top5"}_generation_v2_2'
        allocations = load_json(ROOT / 'reports/evaluation/generation' / label / 'experiment_manifest.json')['generator']['device_information']
        attempts = d
    else:
        attempts = [a['captured_runtime'] for a in read_jsonl(model_dir(name) / 'attempts.jsonl') if a['condition'] == condition]
        d = [r['deterministic_generation'] for r in rows]
        memory = load_json(model_dir(name) / 'memory.json')
        allocations = load_json(model_dir(name) / 'runtime_allocations.json')
        supplemental_path = OUT / 'supplemental_memory_samples.jsonl'
        if supplemental_path.exists():
            samples = [s for s in read_jsonl(supplemental_path) if any(m.get('name') == name for m in s.get('allocation', {}).get('models', [])) and not s.get('error')]
            memory.update(peak_ram_bytes=max((s['working_set_bytes'] for s in samples), default=None),
                          peak_device_vram_used_mib=max((s['device_vram_used_mib'] for s in samples), default=None),
                          sample_scope='Ollama plus llama-server working-set sum; device-wide VRAM; supplemental sampler',
                          sample_count=len(samples), early_sampling_gap=name == MODELS[1],
                          peak_is_sampled_lower_bound=True)
    if name == MODELS[0]:
        protocol_latencies = [total_latency_or_none([a.get('latency_seconds') for a in attempts if a.get('question_id') == r['question_id']]) for r in rows]
    else:
        records = read_jsonl(model_dir(name) / 'attempts.jsonl')
        protocol_latencies = [total_latency_or_none([a.get('generation_latency_seconds') for a in records if a['condition'] == condition and a['question_id'] == r['question_id']]) for r in rows]
    return {'final_attempt': {k: stats([r.get(k) for r in d]) for k in ('ttft_seconds', 'latency_seconds', 'tokens_per_second', 'prompt_tokens', 'completion_tokens')},
            'all_attempts': {k: stats([r.get(k) for r in attempts]) for k in ('ttft_seconds', 'latency_seconds', 'tokens_per_second', 'prompt_tokens', 'completion_tokens')},
            'question_protocol_latency': stats(protocol_latencies),
            'question_protocol_latency_missing_count': sum(v is None for v in protocol_latencies),
            'model_load_seconds': stats([r['load_duration_ns'] / 1e9 if r.get('load_duration_ns') is not None else None for r in attempts]),
            'first_observed_load_seconds': next((r['load_duration_ns'] / 1e9 for r in attempts if r.get('load_duration_ns') is not None), None),
            'memory': {k: v for k, v in memory.items() if k != 'samples'}, 'runtime_allocations': allocations,
            'memory_condition_scope': 'Shared model-session peak over G0/G1; not a separate per-condition peak',
            'ttft_missing_final_count': sum(r.get('ttft_seconds') is None for r in d),
            'tps_definition': 'Ollama eval_count / eval_duration; includes native thinking tokens when the model emits them. Final-answer-only token counts are not exposed.',
            'ttft_definition': 'first final-answer content token; model thinking, if present, delays this; first stream token separately preserved in raw attempts',
            'comparison_limitation': 'Same hardware; Gemma uses historical frozen timing. CPU/GPU allocation and warm-cache state can differ; latency is descriptive, not a controlled edge-device winner.'}


def report():
    manifest, rows = all_rows()
    # Attach only materialized, immutable native metric checkpoints from this phase.
    full = []
    for model in manifest['generators']:
        name = model['name']
        if model['availability'] != 'available':
            continue
        if model['baseline_reuse']:
            full.extend(r for r in rows if r['generator'] == name)
        else:
            full.extend(read_jsonl(model_dir(name) / 'scored_outputs.jsonl'))
    keys = [(r['generator'], r['condition'], r['question_id']) for r in full]
    if len(keys) != len(set(keys)) or len(full) != 338 * sum(m['availability'] == 'available' for m in manifest['generators']):
        raise ValueError('Missing or duplicate model/condition/question outputs')
    from .core import assert_same_inputs
    reference = [r for r in full if r['generator'] == MODELS[0]]
    for m in manifest['generators']:
        if m['availability'] == 'available':
            assert_same_inputs(reference, [r for r in full if r['generator'] == m['name']])
    from .runner import context_records
    from ..generation.runner_v2 import format_v2_user_prompt
    from ..generation.protocol_v2 import sha256_text
    import json
    prompt = (ROOT / 'prompts/generation_v2.txt').read_text(encoding='utf-8').strip()
    schema = load_json(ROOT / 'schemas/generation_output_v2.schema.json')
    request_audit = {'validated': 0, 'capture_gap': 0, 'mismatches': []}
    for m in manifest['generators']:
        name = m['name']
        if m['baseline_reuse'] or m['availability'] != 'available':
            continue
        by_id = {(r['question_id'], r['condition']): r for r in full if r['generator'] == name}
        for a in read_jsonl(model_dir(name) / 'attempts.jsonl'):
            observed = a.get('captured_runtime', {}).get('request_sha256')
            if observed is None:
                request_audit['capture_gap'] += 1
                continue
            r = by_id[a['question_id'], a['condition']]
            body = {'model': name, 'stream': True, 'format': schema, 'keep_alive': '30m',
                'messages': [{'role': 'system', 'content': prompt}, {'role': 'user', 'content': format_v2_user_prompt(r, context_records(r))}],
                'options': manifest['generation_options']}
            expected = sha256_text(json.dumps(body, ensure_ascii=False, sort_keys=True))
            if observed != expected:
                request_audit['mismatches'].append([name, a['condition'], a['question_id'], a['attempt_number']])
            else:
                request_audit['validated'] += 1
    write_json(OUT / 'request_contract_audit.json', request_audit)
    if request_audit['mismatches']:
        raise ValueError('Frozen generation payload changed')
    write_json(OUT / 'fairness_validation.json', {'all_question_ids_equal': True, 'all_context_ids_equal': True,
        'all_context_order_equal': True, 'all_context_text_checksums_equal': True,
        'common_prompt_sha256': manifest['prompt_sha256'], 'common_schema_sha256': manifest['schema_sha256'],
        'common_generation_options': manifest['generation_options'], 'retrieval_reexecuted': False,
        'reference_answer_in_generation_prompt': False, 'judge_conflict_primary_exclusion': True,
        'historical_baseline_performance_measurement': True})
    questions = read_jsonl(ROOT / 'data/evaluation/grounded/questions_v1.jsonl')
    write_json(OUT / 'silver_reference_provenance.json', {
        'reference_generation_models': dict(Counter(str(q.get('generation_model')) for q in questions)),
        'benchmark_type': 'silver', 'human_verified': False,
        'limitation': 'All Silver questions/reference answers were generated by Gemma2 9B. Reference-style alignment can favor the frozen Gemma baseline; Silver-reference correctness alone cannot establish independent model superiority.'})
    groups = {(name, c): [r for r in full if r['generator'] == name and r['condition'] == c] for name in MODELS for c in CONDITIONS}
    overall, rel, timing = {}, {}, {}
    for name in MODELS:
        overall[name], rel[name], timing[name] = {}, {}, {}
        for c in CONDITIONS:
            if not groups[name, c]:
                overall[name][c] = {'status': 'blocked_runtime'}
                continue
            overall[name][c] = condition_summary(groups[name, c])
            rel[name][c] = reliability(name, c, groups[name, c])
            timing[name][c] = latency(name, c, groups[name, c])
    write_json(OUT / 'overall_comparison.json', overall)
    for c, filename in [('oracle', 'oracle_comparison.json'), ('e4_top5', 'e4_top5_comparison.json')]:
        write_json(OUT / filename, {name: overall[name][c] for name in MODELS})
    write_json(OUT / 'reliability.json', rel)
    write_json(OUT / 'latency.json', timing)
    for name in MODELS:
        for c in CONDITIONS:
            subset = groups[name, c]
            if not subset:
                continue
            prefix = 'G0' if c == 'oracle' else 'G1'
            from .runner import slug
            experiment = OUT / 'experiments' / f'{prefix}_{slug(name)}_{c}_v1'
            write_json(experiment / 'experiment_manifest.json', {'experiment_id': experiment.name,
                'generator': name, 'condition': c, 'question_count': len(subset),
                'frozen_baseline_reused': name == MODELS[0], 'generation_options': manifest['generation_options'],
                'input_hashes': manifest['input_hashes'], 'prompt_sha256': manifest['prompt_sha256'], 'schema_sha256': manifest['schema_sha256'],
                'judge_conflict': subset[0]['judge_conflict'], 'benchmark_type': 'silver', 'generation_protocol': 'v2.2'})
            write_json(experiment / 'overall.json', overall[name][c])
            write_jsonl(experiment / 'per_question.jsonl', subset)
            write_jsonl(experiment / 'context_manifest.jsonl', [{'question_id': r['question_id'], 'contexts': r['context_provenance']} for r in subset])
    paired = {'within_model_G1_minus_G0': {}, 'cross_model': {}, 'seed': SEED, 'iterations': ITERATIONS}
    for name in MODELS:
        if groups[name, 'oracle'] and groups[name, 'e4_top5']:
            paired['within_model_G1_minus_G0'][name] = pair_compare(groups[name, 'oracle'], groups[name, 'e4_top5'], primary_judge=not groups[name, 'oracle'][0]['judge_conflict'])
    for c in CONDITIONS:
        paired['cross_model'][c] = {}
        for a, b in combinations(MODELS, 2):
            if not groups[a, c] or not groups[b, c]:
                continue
            paired['cross_model'][c][b + '_minus_' + a] = pair_compare(groups[a, c], groups[b, c], primary_judge=not (groups[a, c][0]['judge_conflict'] or groups[b, c][0]['judge_conflict']))
    write_json(OUT / 'paired_bootstrap.json', paired)
    for field in ('query_style', 'species', 'category'):
        result = {}
        for name in MODELS:
            result[name] = {}
            for c in CONDITIONS:
                subset = groups[name, c]
                result[name][c] = {str(value or 'unknown'): condition_summary([r for r in subset if r.get(field) == value]) for value in sorted({r.get(field) for r in subset}, key=str)}
        if field == 'species':
            result['absent_species'] = {'虱目魚': {'n': 0, 'metrics': None}}
        if field == 'category':
            result['calculation_note'] = '3 questions; descriptive only'
        write_json(OUT / ('by_' + field + '.json'), result)
    hit, miss = {}, {}
    for name in MODELS:
        subset = groups[name, 'e4_top5']
        hit[name] = condition_summary([r for r in subset if r['required_evidence_complete_in_top5'] and r['status'] == 'answered'])
        absent = [r for r in subset if not r['required_evidence_complete_in_top5']]
        miss[name] = {'summary': condition_summary(absent), 'question_ids': [r['question_id'] for r in absent],
                      'per_question': [{'question_id': r['question_id'], 'status': r['status'], 'metrics': r['metrics'], 'citations': r['deterministic_generation']['citations'], 'silver_token_f1': scalar(r, 'silver_token_f1')} for r in absent],
                      'interpretation': 'Observational diagnostic; answered without required evidence is not automatically hallucination'}
    write_json(OUT / 'retrieval_hit_comparison.json', hit)
    write_json(OUT / 'retrieval_miss_behavior.json', miss)
    points = []
    for m in manifest['generators']:
        name = m['name']
        if not groups[name, 'e4_top5']:
            continue
        subset = groups[name, 'e4_top5']
        summary = overall[name]['e4_top5']
        points.append({'generator': name, 'judge_conflict': m['judge_conflict'], 'primary_eligible': not m['judge_conflict'],
                       'faithfulness': summary['judge_metrics']['metrics']['faithfulness']['mean'],
                       'silver_reference_correctness': summary['judge_metrics']['metrics']['silver_reference_correctness']['mean'],
                       'citation_recall': sum(scalar(r, 'citation_recall') for r in subset) / len(subset),
                       'ttft_mean': timing[name]['e4_top5']['final_attempt']['ttft_seconds']['mean'],
                       'tps_mean': timing[name]['e4_top5']['final_attempt']['tokens_per_second']['mean'],
                       'p95_latency': timing[name]['e4_top5']['question_protocol_latency']['p95'],
                       'schema_validity': rel[name]['e4_top5']['final_schema_valid_rate'],
                       'answered_count': sum(r['status'] == 'answered' for r in subset),
                       'judge_valid_count': summary['judge_metrics']['metrics']['faithfulness']['n_valid'],
                       'ram_bytes': timing[name]['e4_top5']['memory'].get('peak_ram_bytes'),
                       'vram_bytes': timing[name]['e4_top5']['memory'].get('peak_vram_bytes'),
                       'quantization': m['quantization'], 'context_length': m['configured_context_length']})
    write_json(OUT / 'quality_efficiency.json', {'points': points, 'composite_score': 'not_defined', 'note': 'Quality and efficiency displayed separately; selective answered-only cohorts and historical baseline timings limit direct ranking.'})
    primary_names = [p['generator'] for p in points if p['primary_eligible']]
    common_ids = set(r['question_id'] for r in reference if r['condition'] == 'e4_top5')
    for name in primary_names:
        common_ids &= {r['question_id'] for r in groups[name, 'e4_top5'] if r['status'] == 'answered'
                       and all(scalar(r, metric) is not None for metric in ('faithfulness', 'silver_reference_correctness'))}
    common_points = [dict(p) for p in points]
    for p in common_points:
        subset = [r for r in groups[p['generator'], 'e4_top5'] if r['question_id'] in common_ids]
        if p['primary_eligible']:
            for metric in ('faithfulness', 'silver_reference_correctness'):
                p[metric] = sum(scalar(r, metric) for r in subset) / len(subset) if subset else None
    frontier = pareto(common_points, manifest['pareto_axes'])
    frontier.update(common_valid_quality_question_ids=sorted(common_ids), common_valid_quality_n=len(common_ids),
                    n_quality_pairs_excluded=169-len(common_ids), points_on_common_quality_cohort=common_points,
                    citation_and_latency_cohort='all 169 E4 questions; system-level reliability retained',
                    caveat='Same-question complete-case quality means, descriptive point estimates only. Historical timing/cache and sampled memory limitations remain; no confidence-based dominance or automatic winner.')
    write_json(OUT / 'pareto_analysis.json', frontier)
    repeats = [read_jsonl(OUT / f'repeat{i}.jsonl') for i in (1, 2)]
    # Preserve original IDs in files; disambiguate generator identity only in repeatability keys.
    normalized = [[dict(r, question_id=r['generator'] + '/' + r['question_id']) for r in run] for run in repeats]
    repeat = repeatability(*normalized)
    repeat['requested_new_outputs'] = 30
    repeat['actual_new_outputs'] = len(repeats[0])
    repeat['meets_30_output_target'] = len(repeats[0]) >= 30
    selected_keys = {(r['generator'], r['condition'], r['question_id']) for r in repeats[0]}
    primary_selected = [dict(r, question_id=r['generator'] + '/' + r['question_id']) for r in full
                        if (r['generator'], r['condition'], r['question_id']) in selected_keys]
    repeat['primary_vs_repeat1'] = repeatability(primary_selected, normalized[0])
    repeat['primary_vs_repeat2'] = repeatability(primary_selected, normalized[1])
    repeat['primary_scores_replaced'] = False
    write_json(OUT / 'judge_repeatability.json', repeat)
    errors, failures = [], []
    for r in full:
        labels = error_labels(r)
        if r['status'] == 'generation_error':
            labels = [x for x in labels if x != 'false_abstention_candidate']
            labels.append('generation_schema_failure')
        if r['deterministic_generation'].get('done_reason') == 'length':
            labels.append('generation_truncation')
        labels = ['judge_failure' if x == 'judge_evaluation_failure' else x for x in labels]
        errors.append({'generator': r['generator'], 'condition': r['condition'], 'question_id': r['question_id'],
                       'labels': sorted(set(labels)), 'error_detected': bool(labels),
                       'judge_status': 'not_run_self_judge_conflict' if r.get('judge_conflict') else ('answered_only_not_applicable' if r['status'] != 'answered' else 'evaluated')})
        for metric, value in r['metrics'].items():
            if value.get('status') == 'failed':
                failures.append({'generator': r['generator'], 'condition': r['condition'], 'question_id': r['question_id'], 'metric': metric, **value})
    write_jsonl(OUT / 'error_attribution.jsonl', errors)
    write_jsonl(OUT / 'evaluation_failures.jsonl', failures)
    write_jsonl(OUT / 'per_question_metrics.jsonl', full)
    write_json(OUT / 'error_summary.json', {n: dict(Counter(x for r in errors if r['generator'] == n for x in r['labels'])) for n in MODELS})
    summary_lines = ['# Phase 17 Controlled Generation Model Comparison', '', 'AI-generated Corpus-Grounded Silver Benchmark; judge-based metrics and Silver reference, not human expert correctness.', '',
                     'Gemma uses immutable Phase 15.3 outputs and Phase 16 scores. New models use exactly the same 169 paired questions, frozen Oracle/E4 Top-5 contexts, prompt, schema and v2.2 options.', '',
                     'Qwen2.5-Coder is the identical artifact as the Primary Judge: all judge-based primary comparisons exclude it. Its deterministic metrics remain available.', '',
                     '| Generator | Condition | Answered | Schema | Faithfulness | Relevancy | Silver reference | Citation recall (all) |',
                     '|---|---|---:|---:|---:|---:|---:|---:|']
    for name in MODELS:
        for c in CONDITIONS:
            if not groups[name, c]:
                continue
            s = overall[name][c]
            values = [s['judge_metrics']['metrics'][m]['mean'] for m in METRICS]
            display = ['excluded (judge conflict)' if groups[name, c][0]['judge_conflict'] else ('NA' if v is None else f'{v:.4f}') for v in values]
            summary_lines.append(f"| {name} | {c} | {s['deterministic_metrics']['answered_count']} | {rel[name][c]['final_schema_valid_rate']:.2%} | {' | '.join(display)} | {s['deterministic_metrics']['required_evidence_citation_recall']['all_questions']['strict_recall']:.4f} |")
    summary_lines += ['', '## Interpretation', '',
        'Paired bootstrap uses 10,000 iterations, seed 17017, valid shared question IDs. A CI spanning zero is not clear superiority on this Silver sample. Scores conditional on answered outputs must be considered alongside full-cohort generation errors and abstention.', '',
        'Pareto flags are descriptive point estimates, not an automatic final edge-model choice. Historical baseline offload/cache state, sample gaps (milkfish=0; calculation=3), local code-specialized judge and self-judge conflict limit conclusions.', '',
        'All 169 Silver references were generated with Gemma2 9B. Potential same-model reference-style alignment is a limitation of reference-based cross-model comparison; it is not expert verification.', '',
        'Citation provenance and required-evidence recall do not independently verify each claim against the particular cited chunk. No production migration or tuning was performed.', '',
        'Windows Smart App Control / Code Integrity blocks a prior reranker CUDA DLL smoke path. Phase 17 uses frozen E4 Top-5; this environment limitation does not invalidate the frozen retrieval metrics.']
    (OUT / 'comparison_summary.md').write_text('\n'.join(summary_lines) + '\n', encoding='utf-8')
    capture_gaps = sum(rel[n][c]['raw_capture_failure_count'] for n in MODELS for c in CONDITIONS if c in rel[n])
    write_json(OUT / 'completion.json', {'status': 'completed_with_capture_warning' if capture_gaps else 'completed',
        'raw_capture_gap_count': capture_gaps, 'all_raw_capture_requirement_met': capture_gaps == 0,
        'generators': MODELS, 'rows': len(full), 'judge_failure_count': len(failures), 'next_phase_started': False, 'production_migration': False})
    from .summary import render_detailed_summary
    render_detailed_summary(OUT)
    print('Phase 17 reports materialized; no tuning or migration', flush=True)
