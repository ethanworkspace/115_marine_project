"""Evaluate immutable Phase 15.3 outputs with a frozen, local RAGAS judge."""
from __future__ import annotations

import argparse
import asyncio
import importlib.metadata
import json
import math
import os
import platform
import subprocess
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from .core import (CONDITIONS, ITERATIONS, LOW_THRESHOLDS, METRICS, SEED, answered_only,
                   error_labels, pair_inputs, paired_comparison, repeatability,
                   retrieval_split, select_repeat_subset, summarize)
from .runtime import (ADAPTER_VERSION, EMBED_DIGEST, EMBED_MODEL, ENDPOINT, JUDGE_DIGEST,
                      JUDGE_MODEL, OPTIONS, append_jsonl, local_inventory, make_adapters,
                      make_metrics, sha_text)
from ..generation.frozen import read_jsonl, sha256_file, validate_frozen_inputs

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / 'reports/evaluation/ragas'
PHASE = OUT / 'phase16'
GENERATION = ROOT / 'reports/evaluation/generation'
FOLDERS = {'oracle': 'G0_grounded_oracle_generation_v2_2', 'e4_top5': 'G1_grounded_e4_top5_generation_v2_2'}
INPUT_SHA = 'dbf7ad89cda9b6e4666d6e7adc54d009a59a849da8d7f0075034f684ba2c77c1'


def write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + '\n', encoding='utf-8')
    temp.replace(path)


def load_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def load_rows() -> tuple[list[dict], dict]:
    frozen = validate_frozen_inputs(ROOT)
    path = ROOT / 'data/evaluation/generation/ragas_input_v2_2.jsonl'
    if sha256_file(path) != INPUT_SHA:
        raise ValueError('Frozen RAGAS export checksum changed')
    exported = read_jsonl(path)
    paired = pair_inputs(exported)
    if len(exported) != 338:
        raise ValueError('Expected 338 frozen evaluation rows')
    questions = {q['question_id']: q for q in frozen['questions']}
    if set(paired) != set(questions):
        raise ValueError('Question IDs differ from frozen Grounded Silver v1')
    rows = []
    hashes = dict(frozen['hashes'], ragas_input_v2_2_sha256=INPUT_SHA)
    for condition in CONDITIONS:
        folder = GENERATION / FOLDERS[condition]
        manifest = load_json(folder / 'experiment_manifest.json')
        if manifest['status'] != 'completed' or manifest['input_hashes'] != frozen['hashes']:
            raise ValueError('Frozen generation manifest is incomplete or changed')
        outputs = {r['question_id']: r for r in read_jsonl(folder / 'per_question.jsonl')}
        contexts = {r['question_id']: r['contexts'] for r in read_jsonl(folder / 'context_manifest.jsonl')}
        hashes[condition + '_outputs_sha256'] = sha256_file(folder / 'per_question.jsonl')
        hashes[condition + '_contexts_sha256'] = sha256_file(folder / 'context_manifest.jsonl')
        hashes[condition + '_manifest_sha256'] = sha256_file(folder / 'experiment_manifest.json')
        for qid in sorted(questions):
            export, output, q = paired[qid][condition], outputs[qid], questions[qid]
            texts = [frozen['corpus_by_id'][c['chunk_id']]['text'] for c in contexts[qid]]
            for context, text in zip(contexts[qid], texts):
                if sha_text(text) != context['content_checksum']:
                    raise ValueError('Frozen context snapshot checksum differs')
            if [c['chunk_id'] for c in contexts[qid]] != output['context_chunk_ids']:
                raise ValueError('Frozen context order differs from per-question output')
            if texts != export['contexts']:
                raise ValueError(f'Context texts/order differ from frozen generation: {condition}/{qid}')
            if output['answer'] != export['answer'] or q['question'] != export['question'] or q['reference_answer'] != export['reference_answer']:
                raise ValueError('Frozen answer/question/reference differs from export')
            if output['status'] not in {'answered', 'insufficient_evidence'} or not output['schema_valid']:
                raise ValueError('Phase 15.3 output not ready for Phase 16')
            rows.append({**export, 'status': output['status'], 'query_style': q['query_style'],
                         'species': q.get('species') or 'unknown', 'category': q['category'],
                         'difficulty': q['difficulty'],
                         'required_evidence_complete_in_top5': output['required_evidence_in_context'],
                         'citation_failure': output['strict_citation_count'] != output['citation_count'] or output['missing_citation'],
                         'deterministic_generation': output, 'metrics': {}})
    return rows, hashes


def prepare():
    os.environ['RAGAS_DO_NOT_TRACK'] = 'true'
    os.environ['LANGCHAIN_TRACING_V2'] = 'false'
    rows, hashes = load_rows()
    manifest = {'experiment_id': 'phase16_frozen_generation_ragas_v1',
                'timestamp_utc': datetime.now(timezone.utc).isoformat(), 'status': 'prepared',
                'benchmark_type': 'silver', 'generation_source': 'corpus_grounded_ai',
                'silver_reference': True, 'input_hashes': hashes,
                'question_count': 169, 'row_count': 338, 'conditions': list(CONDITIONS),
                'metrics': {'faithfulness': 'ragas.metrics.Faithfulness',
                            'answer_relevancy': 'ragas.metrics.AnswerRelevancy strictness=3',
                            'silver_reference_correctness': 'ragas.metrics.AnswerCorrectness weights=[0.75,0.25] beta=1.0'},
                'primary_cohort': 'answered_only', 'paired_comparison': 'both answered and both valid, matched on question_id',
                'bootstrap': {'iterations': ITERATIONS, 'seed': SEED, 'unit': 'question', 'confidence': .95},
                'low_score_thresholds': LOW_THRESHOLDS,
                'context_metrics': {'status': 'not_run', 'reason': 'Use deterministic required-evidence availability as primary retrieval evidence'},
                'citation_support_limitation': 'Provenance validity and required-evidence citation recall do not prove every generated claim is supported by its individual citation. RAGAS Faithfulness evaluates all provided contexts, not claim-to-citation alignment.',
                'unchanged_generation': True, 'answer_regeneration': False,
                'judge_adapter_version': ADAPTER_VERSION,
                'ragas_version': importlib.metadata.version('ragas'),
                'runtime_python': sys.version, 'os': platform.platform(),
                'git_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
                'repeatability_subset': [{'question_id': r['question_id'], 'condition': r['condition']} for r in select_repeat_subset(rows)],
                'research_note': 'AI-generated Silver Benchmark, Silver reference, judge-based metric; no human expert correctness claims'}
    manifest['judge_selection'] = {'model': JUDGE_MODEL, 'digest': JUDGE_DIGEST,
        'authorization': 'User explicitly approved existing Qwen after DeepSeek budget exhaustion',
        'diagnostics': 'reports/evaluation/ragas/runtime_diagnostics/deepseek_r1_8b',
        'mixed_judge_scores': False}
    path = PHASE / 'experiment_manifest.json'
    if path.exists():
        old = load_json(path)
        for key in ('input_hashes', 'metrics', 'bootstrap', 'low_score_thresholds', 'repeatability_subset', 'ragas_version', 'judge_selection'):
            if old[key] != manifest[key]:
                raise ValueError('Cannot resume experiment with changed ' + key)
    else:
        write_json(path, manifest)
    packages = {d.metadata['Name']: d.version for d in importlib.metadata.distributions()}
    write_json(OUT / 'runtime_versions.json', {'python': sys.version, 'packages': packages,
               'adapter': ADAPTER_VERSION, 'compatibility_pin': 'langchain-community==0.4.1; 0.4.2 removed legacy VertexAI imports required by ragas 0.4.3',
               'cloud_clients_used': False, 'frameworks': 'Only RAGAS required transitive dependencies installed; no retrieval or RAG framework used by evaluation'})
    freeze = subprocess.check_output([sys.executable, '-m', 'pip', 'freeze'], text=True)
    (OUT / 'requirements.lock.txt').write_text(freeze, encoding='utf-8')
    write_json(PHASE / 'input_validation.json', {'status': 'valid', 'row_count': len(rows), 'paired_question_count': 169,
               'by_condition': {c: dict(Counter(r['status'] for r in rows if r['condition'] == c)) for c in CONDITIONS},
               'reference_answers_equal': True, 'contexts_match_frozen_outputs': True,
               'g1_incomplete_required_evidence_count': sum(r['condition'] == 'e4_top5' and not r['required_evidence_complete_in_top5'] for r in rows),
               'hashes': hashes})
    print('Frozen inputs validated: 169 paired questions / 338 rows', flush=True)


def score_row(row, judge, metrics, stage='primary', checkpoints: Path | None = None):
    from ragas.dataset_schema import SingleTurnSample
    sample = SingleTurnSample(user_input=row['question'], response=row['answer'],
                              retrieved_contexts=row['contexts'], reference=row['reference_answer'])
    result = {k: v for k, v in row.items() if k not in {'contexts', 'deterministic_generation', 'metrics'}}
    result['metrics'] = {}
    completed_metrics = {}
    if checkpoints is not None and checkpoints.exists():
        for saved in read_jsonl(checkpoints):
            if (saved['question_id'], saved['condition'], saved['stage']) == (row['question_id'], row['condition'], stage):
                if saved['metric'] in completed_metrics:
                    raise ValueError('Duplicate immutable metric checkpoint')
                completed_metrics[saved['metric']] = saved['result']
    for name, metric in metrics.items():
        if name in completed_metrics:
            result['metrics'][name] = completed_metrics[name]
            continue
        if row['status'] != 'answered':
            result['metrics'][name] = {'status': 'not_applicable', 'score': None, 'reason': 'insufficient_evidence excluded from answered-only judge metrics'}
            continue
        judge.identity = {'question_id': row['question_id'], 'condition': row['condition'], 'metric': name, 'stage': stage}
        start = time.perf_counter()
        calls_before = judge.call_count
        retries_before, attempts_before = judge.retry_count, judge.attempt_count
        try:
            value = float(asyncio.run(metric.single_turn_ascore(sample, timeout=7200)))
            if not math.isfinite(value):
                raise ValueError('non_finite_ragas_score')
            record = {'status': 'valid', 'score': value, 'parse_status': 'valid', 'failure_reason': None}
        except Exception as exc:
            record = {'status': 'failed', 'score': None, 'parse_status': 'failed', 'failure_reason': type(exc).__name__ + ': ' + str(exc)}
        record.update(latency_seconds=time.perf_counter() - start, judge_call_count=judge.call_count - calls_before,
                      retry_count=judge.retry_count - retries_before, attempt_count=judge.attempt_count - attempts_before,
                      raw_output_reference={'file': 'raw_evaluator_outputs.jsonl' if stage != 'preflight' else 'preflight_evaluator_outputs.jsonl',
                                            'stage': stage, 'condition': row['condition'], 'question_id': row['question_id'], 'metric': name})
        result['metrics'][name] = record
        if checkpoints is not None:
            append_jsonl(checkpoints, {'question_id': row['question_id'], 'condition': row['condition'],
                                      'stage': stage, 'metric': name, 'result': record})
        print(f"{stage} {row['condition']} {row['question_id']} {name}: {record['status']} {record['score']}", flush=True)
    return result


def preflight():
    os.environ['RAGAS_DO_NOT_TRACK'] = 'true'
    os.environ['LANGCHAIN_TRACING_V2'] = 'false'
    inventory = local_inventory()
    inventory['status'] = 'checking'
    write_json(OUT / 'evaluator_preflight.json', inventory)
    judge, embeddings = make_adapters(PHASE / 'preflight_evaluator_outputs.jsonl')
    metrics = make_metrics(judge, embeddings)
    prompts = {}
    for name, metric in metrics.items():
        for key, prompt in metric.get_prompts().items():
            text = prompt.to_string()
            prompts[name + '/' + key] = {'instruction': prompt.instruction, 'examples': len(prompt.examples),
                                       'serialized_empty_input_sha256': sha_text(text), 'output_schema': prompt.output_model.model_json_schema()}
    smoke = {'question_id': 'local_judge_preflight', 'condition': 'oracle', 'status': 'answered',
             'question': '水溫是多少？', 'answer': '水溫為20℃。', 'reference_answer': '水溫為20℃。',
             'contexts': ['水溫為20℃。'], 'benchmark_type': 'silver'}
    result = score_row(smoke, judge, metrics, 'preflight')
    ready = all(result['metrics'][name]['status'] == 'valid' for name in METRICS)
    traces = read_jsonl(PHASE / 'preflight_evaluator_outputs.jsonl')
    inventory.update(status='ready' if ready else 'blocked_evaluator_runtime', smoke_result=result,
                     observed_reasoning_with_think_false=any(bool(r.get('thinking')) for r in traces))
    write_json(OUT / 'evaluator_preflight.json', inventory)
    manifest = {'judge_model': JUDGE_MODEL, 'model_tag': JUDGE_MODEL, 'model_digest': JUDGE_DIGEST,
                'runtime': 'Ollama', 'runtime_version': inventory['runtime_version'],
                'context_length': OPTIONS['num_ctx'], 'generation_parameters': OPTIONS,
                'temperature': 0, 'seed': SEED, 'max_output_tokens': OPTIONS['num_predict'],
                'structured_output_mode': 'Ollama /api/chat native JSON schema from the unmodified native RAGAS PydanticPrompt',
                'thinking_request': False, 'thinking_observed': inventory['observed_reasoning_with_think_false'],
                'adapter_version': ADAPTER_VERSION, 'maximum_attempts': 2,
                'retry': 'Exactly one same-payload fresh retry for technical transport/JSON/schema/completion failure; no repair and no score-based retry',
                'ragas_internal_retry': 'Disabled by adapter.generate; valid schema returned before native RAGAS parser; no parser repair call possible after adapter failure',
                'ragas_prompts': prompts, 'metric_prompt_modification': False,
                'embedding': inventory['embedding'], 'status': inventory['status']}
    manifest['selection_rule'] = inventory['selection_rule']
    manifest['judge_limitation'] = inventory['judge_limitation']
    write_json(PHASE / 'evaluator_manifest.json', manifest)
    print('Evaluator preflight: ' + inventory['status'], flush=True)
    if not ready:
        raise SystemExit(2)


def run():
    os.environ['RAGAS_DO_NOT_TRACK'] = 'true'
    os.environ['LANGCHAIN_TRACING_V2'] = 'false'
    rows, hashes = load_rows()
    evaluator = load_json(PHASE / 'evaluator_manifest.json')
    manifest = load_json(PHASE / 'experiment_manifest.json')
    if evaluator['status'] != 'ready' or manifest['input_hashes'] != hashes:
        raise ValueError('Blocked evaluator or changed frozen inputs')
    local_inventory()
    manifest.update(status='running', started_at=manifest.get('started_at') or datetime.now(timezone.utc).isoformat(),
                    evaluator_manifest_sha256=sha256_file(PHASE / 'evaluator_manifest.json'))
    write_json(PHASE / 'experiment_manifest.json', manifest)
    judge, embeddings = make_adapters(PHASE / 'raw_evaluator_outputs.jsonl')
    metrics = make_metrics(judge, embeddings)
    path = PHASE / 'per_question_metrics.jsonl'
    done = {(r['question_id'], r['condition']) for r in read_jsonl(path)} if path.exists() else set()
    for i, row in enumerate(rows, 1):
        if (row['question_id'], row['condition']) in done:
            continue
        print(f'Primary evaluation row {i}/338', flush=True)
        append_jsonl(path, score_row(row, judge, metrics, checkpoints=PHASE / 'metric_checkpoints.jsonl'))
    subset = select_repeat_subset(rows)
    for round_number in (1, 2):
        path = PHASE / f'judge_repeat_run_{round_number}.jsonl'
        done = {(r['question_id'], r['condition']) for r in read_jsonl(path)} if path.exists() else set()
        for i, row in enumerate(subset, 1):
            if (row['question_id'], row['condition']) in done:
                continue
            print(f'Judge repeat {round_number}: {i}/30', flush=True)
            append_jsonl(path, score_row(row, judge, metrics, f'repeat_{round_number}', checkpoints=PHASE / 'metric_checkpoints.jsonl'))
    local_inventory()
    if load_rows()[1] != hashes:
        raise ValueError('Protected evaluation inputs changed while judging')
    manifest.update(status='completed', evaluator_manifest_sha256=sha256_file(PHASE / 'evaluator_manifest.json'),
                    output_count=338, completed_at=datetime.now(timezone.utc).isoformat())
    write_json(PHASE / 'experiment_manifest.json', manifest)
    report()


def report():
    source_rows, _ = load_rows()
    path = PHASE / 'per_question_metrics.jsonl'
    judged = read_jsonl(path) if path.exists() else []
    by_key = {(r['question_id'], r['condition']): r for r in judged}
    if len(by_key) != len(judged):
        raise ValueError('Duplicate evaluated question/condition records')
    checkpoint_metrics = defaultdict(dict)
    checkpoints = PHASE / 'metric_checkpoints.jsonl'
    if checkpoints.exists():
        for saved in read_jsonl(checkpoints):
            if saved['stage'] == 'primary':
                checkpoint_metrics[(saved['question_id'], saved['condition'])][saved['metric']] = saved['result']
    rows = [{**r, 'metrics': {**checkpoint_metrics.get((r['question_id'], r['condition']), {}),
                            **by_key.get((r['question_id'], r['condition']), {}).get('metrics', {})}} for r in source_rows]
    for c in CONDITIONS:
        selected = [r for r in rows if r['condition'] == c]
        summary = summarize(selected)
        summary['existing_deterministic_metrics'] = load_json(GENERATION / FOLDERS[c] / 'overall.json')
        write_json(PHASE / (c + '.json'), summary)
    write_json(PHASE / 'overall.json', {'conditions': {c: summarize([r for r in rows if r['condition'] == c]) for c in CONDITIONS},
               'pooling_conditions_for_primary_mean': False, 'judged_row_count': len(judged),
               'e4_retrieval': load_json(ROOT / 'reports/evaluation/experiments/E4_grounded_rrf_reranker_v1/overall.json'),
               'existing_deterministic_generation': {c: load_json(GENERATION / FOLDERS[c] / 'overall.json') for c in CONDITIONS},
               'absent_species_question_counts': {'虱目魚': 0},
               'benchmark_type': 'silver', 'judge_based': True, 'composite_score': None})
    write_json(PHASE / 'paired_comparison.json', paired_comparison(rows))
    split = retrieval_split(rows)
    # Preserve deterministic citations, similarity and numeric results for each retrieval cohort.
    for label, cohort in (('hit', [r for r in rows if r['condition'] == 'e4_top5' and r['required_evidence_complete_in_top5']]),
                          ('miss', [r for r in rows if r['condition'] == 'e4_top5' and not r['required_evidence_complete_in_top5']]),
                          ('hit_and_answered', [r for r in rows if r['condition'] == 'e4_top5' and r['required_evidence_complete_in_top5'] and r['status'] == 'answered'])):
        records = [r['deterministic_generation'] for r in cohort]
        citations = sum(r['citation_count'] for r in records)
        split[label]['citation_validity'] = sum(r['strict_citation_count'] for r in records) / citations if citations else None
        den = sum(r['required_evidence_citation']['required_chunk_count_present_and_answered'] for r in records)
        num = sum(r['required_evidence_citation']['strict_cited_required_chunk_count_present_and_answered'] for r in records)
        split[label]['required_citation_recall_present_and_answered'] = num / den if den else None
        f1s = [r['silver_reference_similarity']['f1'] for r in records if r.get('silver_reference_similarity')]
        split[label]['silver_token_f1'] = sum(f1s) / len(f1s) if f1s else None
    write_json(PHASE / 'retrieval_hit_vs_miss.json', split)
    for key in ('query_style', 'species', 'category'):
        groups = {}
        for value in sorted({str(r.get(key) or 'unknown') for r in rows}):
            groups[value] = {c: summarize([r for r in rows if r['condition'] == c and str(r.get(key) or 'unknown') == value], ci=False) for c in CONDITIONS}
            groups[value]['descriptive_only'] = any(groups[value][c]['n_questions'] < 20 for c in CONDITIONS)
        write_json(PHASE / ('by_' + key + '.json'), groups)
    failures = []
    for r in rows:
        for name, value in r['metrics'].items():
            if value['status'] == 'failed':
                failures.append({'question_id': r['question_id'], 'condition': r['condition'], 'metric': name, **value})
    (PHASE / 'evaluation_failures.jsonl').write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in failures), encoding='utf-8')
    labels = [{'question_id': r['question_id'], 'condition': r['condition'], 'categories': error_labels(r),
               'interpretation': 'Judge-threshold and deterministic observational diagnostics; not clinical or authoritative correctness'} for r in rows]
    (PHASE / 'error_attribution.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in labels), encoding='utf-8')
    a, b = PHASE / 'judge_repeat_run_1.jsonl', PHASE / 'judge_repeat_run_2.jsonl'
    repeat = repeatability(read_jsonl(a), read_jsonl(b)) if a.exists() and b.exists() else {'status': 'not_completed'}
    write_json(PHASE / 'judge_repeatability.json', repeat)
    lines = ['# Phase 16 — AI-generated Silver Benchmark', '',
             f'Evaluation rows completed: {len(judged)}/338. Frozen Oracle and E4 Top-5 answers are the only inputs; no answer regeneration or retrieval/prompt/model tuning.', '',
             'Primary judge-based metrics use answered-only rows. Abstentions and failed judge evaluations remain explicitly counted. Silver reference correctness is not human expert correctness.', '',
             '| Condition | Questions | Answered | Faithfulness | Answer Relevancy | Silver reference correctness |',
             '|---|---:|---:|---:|---:|---:|']
    for c in CONDITIONS:
        s = summarize([r for r in rows if r['condition'] == c], ci=False)
        values = [s['metrics'][m]['mean'] for m in METRICS]
        lines.append('| ' + c + ' | ' + str(s['n_questions']) + ' | ' + str(s['status_counts'].get('answered', 0)) + ' | ' + ' | '.join('not evaluated' if v is None else f'{v:.4f}' for v in values) + ' |')
    lines += ['', 'Paired bootstrap differences use only question IDs with both answered and both valid scores (10,000 iterations, seed 16016).', '',
              'Required-evidence absence is an observational diagnostic, not proof of hallucination. Deterministic citation validity checks provenance; claim-to-citation factual support remains a limitation. Faithfulness judges claims against all provided context.', '',
              f'Evaluation failures: {len(failures)}. Full failures and raw judge attempt outputs are preserved.', '',
              'Small species/category groups, the three calculation questions, the 30-row repeatability sample, local judge competence, and evidence-generated question leakage limit conclusions. No pooled composite score or population-level correctness claim is made.']
    def fmt(value):
        return 'unavailable' if value is None else f'{value:.4f}'
    evaluator_path = PHASE / 'evaluator_manifest.json'
    if evaluator_path.exists():
        evaluator = load_json(evaluator_path)
        lines += ['', '## Frozen evaluator', '',
                  f"RAGAS {importlib.metadata.version('ragas')}; {evaluator['judge_model']}; {evaluator['runtime']} {evaluator['runtime_version']}.",
                  f"Digest: `{evaluator['model_digest']}`.",
                  evaluator.get('judge_limitation', ''), '',
                  'DeepSeek partial evaluations are retained as runtime diagnostics and do not enter these results. The user explicitly authorized Qwen after preflight.']
    lines += ['', '## Answered-only metric summaries', '',
              '| Condition | Metric | Valid / total | Failed | Mean | Median | SD | 95% CI |',
              '|---|---|---:|---:|---:|---:|---:|---|']
    for condition in CONDITIONS:
        summary = load_json(PHASE / (condition + '.json'))
        for name, value in summary['metrics'].items():
            ci = value['bootstrap']['ci95']
            lines.append(f"| {condition} | {name} | {value['n_valid']}/{value['n_total']} | {value['n_failed']} | {fmt(value['mean'])} | {fmt(value['median'])} | {fmt(value['std'])} | [{fmt(ci[0])}, {fmt(ci[1])}] |")
    lines += ['', '## Paired G1 minus G0', '', '| Metric | Valid pairs | Mean difference | 95% CI |', '|---|---:|---:|---|']
    for name, value in load_json(PHASE / 'paired_comparison.json').items():
        ci = value['ci95']
        lines.append(f"| {name} | {value['n']} | {fmt(value['mean'])} | [{fmt(ci[0])}, {fmt(ci[1])}] |")
    lines += ['', '## Judge repeatability', '', '| Metric | Valid pairs | Exact agreement | MAD | Correlation |', '|---|---:|---:|---:|---:|']
    for name in METRICS:
        if name in repeat:
            value = repeat[name]
            lines.append(f"| {name} | {value['n_valid_pairs']}/{value['n_total']} | {fmt(value['exact_agreement'])} | {fmt(value['mean_absolute_difference'])} | {fmt(value['pearson_correlation'])} |")
    for key in ('query_style', 'species', 'category'):
        lines += ['', '## By ' + key, '',
                  'Each metric cell is G0 / G1. Small groups are descriptive; absent species are not assigned invented metrics.', '',
                  '| Group | Questions per condition | Faithfulness | Relevancy | Silver reference correctness |', '|---|---:|---:|---:|---:|']
        for group, value in load_json(PHASE / ('by_' + key + '.json')).items():
            cells = [fmt(value['oracle']['metrics'][m]['mean']) + ' / ' + fmt(value['e4_top5']['metrics'][m]['mean']) for m in METRICS]
            lines.append('| ' + group + ' | ' + str(value['oracle']['n_questions']) + ' | ' + ' | '.join(cells) + ' |')
    lines += ['', '## Observational error attribution', '', '| Condition | Diagnostic | Questions |', '|---|---|---:|']
    for condition in CONDITIONS:
        counts = Counter(label for row in labels if row['condition'] == condition for label in row['categories'])
        lines += [f'| {condition} | {name} | {count} |' for name, count in sorted(counts.items())]
    lines += ['', 'The full deterministic retrieval, generation, citation, Silver token F1 and calculation results are retained in `overall.json`, `oracle.json`, `e4_top5.json`, and `retrieval_hit_vs_miss.json`. They are separate measures, not a composite score.']
    (PHASE / 'comparison_summary.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print('Phase 16 reports written', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('prepare', 'preflight', 'run', 'report'))
    getattr(sys.modules[__name__], parser.parse_args().action)()
