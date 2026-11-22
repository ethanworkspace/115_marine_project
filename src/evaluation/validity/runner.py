"""Prepare immutable samples, score blind citation pairs, render Phase 18 reports."""
from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import requests

from .core import (MODELS, SAMPLE_RULE, BIAS, answer_id, identity, digest, independent_candidates,
    stratified_outputs, extract_claims, verify_claim, blind_record, claim_verdict, edge_subset)
from ..generation.frozen import read_jsonl, sha256_file
from ..ragas_eval.runner import write_json
from ..ragas_eval.runtime import ENDPOINT, JUDGE_MODEL, JUDGE_DIGEST, OPTIONS, append_jsonl
from .runtime import AUDIT_PROMPT, audit_claim

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / 'reports/evaluation/validity/phase18'
PRIOR = ROOT / 'reports/evaluation/generation_models/phase17'


def write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(''.join(json.dumps(r, ensure_ascii=False, sort_keys=True, allow_nan=False)+'\n' for r in rows), encoding='utf-8')


def load_inputs():
    return read_jsonl(PRIOR / 'per_question_metrics.jsonl')


def check_inputs():
    manifest = json.loads((OUT / 'experiment_manifest.json').read_text(encoding='utf-8'))
    for name, expected in manifest['input_sha256'].items():
        if sha256_file(ROOT / name) != expected:
            raise ValueError('Frozen input changed: '+name)
    for name, expected in manifest['sample_sha256'].items():
        if sha256_file(OUT / name) != expected:
            raise ValueError('Predeclared sample changed: '+name)
    tags = requests.get(ENDPOINT+'/api/tags', timeout=20).json()['models']
    if next((m['digest'] for m in tags if m['name']==JUDGE_MODEL), None) != JUDGE_DIGEST:
        raise ValueError('Fixed AI audit judge artifact changed')
    protocol_path=OUT/'audit_execution_protocol_v2.json'
    if protocol_path.exists():
        protocol=json.loads(protocol_path.read_text(encoding='utf-8'))
        from .runtime import AUDIT_OUTPUT_CONTRACT_V2
        if protocol['prompt_sha256']!=digest(AUDIT_PROMPT+'\n'+AUDIT_OUTPUT_CONTRACT_V2):
            raise ValueError('Blind audit protocol v2 changed')
        for n,h in protocol['sample_sha256'].items():
            if sha256_file(OUT/n)!=h:raise ValueError('Derived audit claim snapshot changed: '+n)
    return manifest


def prepare():
    if (OUT / 'experiment_manifest.json').exists():
        check_inputs()
        print('Existing immutable Phase 18 preparation validated', flush=True)
        return
    if not (OUT / 'protected_before.json').exists():
        raise ValueError('Run Phase 18 protected snapshot before preparation')
    # Verify Phase 17 output inventory as originally frozen.
    previous = json.loads((PRIOR / 'output_checksums.json').read_text(encoding='utf-8'))
    changed = [n for n,h in previous.items() if sha256_file(ROOT/n)!=h]
    if changed:
        raise ValueError('Phase 17 frozen outputs changed: '+str(changed))
    rows = load_inputs()
    if len(rows)!=1352 or len({identity(r) for r in rows})!=1352:
        raise ValueError('Expected four models, two conditions, 169 unique outputs')
    tags_response = requests.get(ENDPOINT+'/api/tags', timeout=20)
    tags_response.raise_for_status()
    models = tags_response.json()['models']
    version = requests.get(ENDPOINT+'/api/version', timeout=10).json()
    infos = []
    for m in models:
        show = requests.post(ENDPOINT+'/api/show', json={'model': m['name']}, timeout=30)
        show.raise_for_status()
        infos.append({**m, 'capabilities': show.json().get('capabilities', m.get('capabilities', [])),
                      'model_info': show.json().get('model_info', {})})
    gens = json.loads((PRIOR/'generator_comparison_manifest.json').read_text(encoding='utf-8'))['generators']
    checked = independent_candidates(infos, [m['digest'] for m in gens])
    eligible = [m for m in checked if m['independent_eligible']]
    cache_paths = [Path.home()/'.cache/huggingface/hub', ROOT/'data/evaluation/models']
    for name in ('HF_HOME', 'HUGGINGFACE_HUB_CACHE', 'TRANSFORMERS_CACHE'):
        if os.environ.get(name):
            cache_paths.append(Path(os.environ[name]))
    caches = [{'path':str(p), 'exists':p.exists(),
               'top_level_entries':sorted(x.name for x in p.iterdir()) if p.is_dir() else []} for p in cache_paths]
    if eligible:
        # Never silently start a newly discovered judge without a frozen manifest.
        raise ValueError('Independent completion model found; freeze explicit independent evaluator settings before scoring')
    preflight = {'independent_judge_ready':False, 'status':'unavailable_independent_artifact',
        'selected_judge':None, 'available_models':checked, 'runtime':version, 'local_cache_checks':caches,
        'searched_scope':'Ollama installed manifests and configured/common local HF caches; no download/cloud API',
        'reason':'All local completion artifacts are Generators; BGE-M3 is embedding-only',
        'claim_audit_continues':True, 'qwen_independent_metric_status':'not_available'}
    write_json(OUT/'independent_judge_preflight.json',preflight)
    judge_sample = stratified_outputs(rows)
    audit_sample = stratified_outputs(rows,audit=True)
    judge_records = [dict(answer_id=answer_id(r), question_id=r['question_id'], generator=r['generator'],
                         condition=r['condition'], query_style=r['query_style'], species=r.get('species'),
                         category=r['category'], primary_metrics=r['metrics'],
                         required_evidence_complete_in_top5=r['required_evidence_complete_in_top5']) for r in judge_sample]
    write_jsonl(OUT/'independent_judge_sample.jsonl',judge_records)
    records = []; blind=[]; claims=[]
    for r in audit_sample:
        extracted=extract_claims(r)
        if not all(verify_claim(c,r['answer']) for c in extracted):
            raise ValueError('Claim is not a verbatim answer span')
        private={'answer_id':answer_id(r),'question_id':r['question_id'],'generator':r['generator'],
                 'condition':r['condition'],'query_style':r['query_style'],'species':r.get('species'),
                 'category':r['category'],'required_evidence_complete_in_top5':r['required_evidence_complete_in_top5'],
                 'primary_metrics':r['metrics'],'answer_sha256':digest(r['answer']),
                 'claim_count':len(extracted),'extraction_review_reason':None if extracted else 'answer_only_heading_no_assertion',
                 'citation_count':r['deterministic_generation']['citation_count'],
                 'strict_citation_count':r['deterministic_generation']['strict_citation_count']}
        records.append(private); blind.append(blind_record(r,extracted));claims.extend(extracted)
    # Pseudonymous display order cannot reveal per-generator quota blocks.
    blind.sort(key=lambda r:digest('blind_display_v1'+r['answer_id']))
    write_jsonl(OUT/'claim_citation_sample.jsonl',records)
    write_jsonl(OUT/'blind_audit_records.jsonl',blind)
    write_jsonl(OUT/'claims.jsonl',claims)
    edge,cuts=edge_subset(rows)
    edge_rows=[{'question_id':r['question_id'],'question':r['question'],'query_style':r['query_style'],
        'species':r.get('species'),'category':r['category'],'difficulty':r['difficulty'],
        'context_characters':sum(len(t) for t in r['contexts']),
        'context_band':'short' if sum(len(t) for t in r['contexts'])<=cuts[0] else
                       ('medium' if sum(len(t) for t in r['contexts'])<=cuts[1] else 'long'),
        'context_provenance':r['context_provenance'],
        'context_sha256':digest(json.dumps(r['contexts'],ensure_ascii=False)),
        'required_evidence_complete_in_top5':r['required_evidence_complete_in_top5']} for r in edge]
    write_jsonl(OUT/'edge_benchmark_subset_v1.jsonl',edge_rows)
    inputs=['data/evaluation/corpus_v2.jsonl','data/evaluation/grounded/questions_v1.jsonl',
        'reports/evaluation/generation_models/phase17/per_question_metrics.jsonl',
        'reports/evaluation/generation_models/phase17/overall_comparison.json',
        'reports/evaluation/generation_models/phase17/reliability.json',
        'reports/evaluation/generation_models/phase17/latency.json',
        'reports/evaluation/generation_models/phase17/generator_comparison_manifest.json',
        'reports/evaluation/ragas/phase16/evaluator_manifest.json']
    samples=['independent_judge_sample.jsonl','claim_citation_sample.jsonl','blind_audit_records.jsonl',
             'claims.jsonl','edge_benchmark_subset_v1.jsonl']
    manifest={'experiment_id':'phase18_evaluation_validity_v1','timestamp':datetime.now(timezone.utc).isoformat(),
        'benchmark_type':'silver','reference_bias':BIAS,'independent_judge_ready':False,
        'sampling_rule':SAMPLE_RULE,'independent_judge_sample_count':len(judge_sample),
        'claim_audit_output_count':len(audit_sample),'claim_count':len(claims),
        'input_sha256':{n:sha256_file(ROOT/n) for n in inputs},
        'sample_sha256':{n:sha256_file(OUT/n) for n in samples},
        'audit_judge':{'model':JUDGE_MODEL,'digest':JUDGE_DIGEST,'runtime':version,
            'options':OPTIONS,'maximum_attempts':2,'independent':False,
            'generator_identity_blind':True,'prompt_sha256':digest(AUDIT_PROMPT),
            'qwen_generator_policy':'self-judge exploratory; excluded from primary entailment conclusion',
            'semantic_quote_policy':'missing/invalid exact quote retains model verdict but effective verdict cannot_determine; no semantic retry'},
        'claim_extraction':'verbatim sentence/clause candidates; atomicity requires human review; no LLM rewriting',
        'answer_level_citation_policy':'Audit each declared cited context for each claim; association is provisional, not proven claim-level binding',
        'edge_context_character_cuts':cuts,'edge_subset_count':len(edge_rows),
        'edge_benchmark_executed':False,'generators_reexecuted':False,
        'shortlist_gates':{'schema_low_priority_below':.95,'schema_strong_minimum':.99,
            'strong_requires_independent_judge_and_human_claim_review':True,'no_composite_score':True}}
    write_json(OUT/'experiment_manifest.json',manifest)
    write_json(OUT/'audit_judge_manifest.json',manifest['audit_judge'])
    write_json(OUT/'sample_distribution.json',{
        'judge':{'outputs':len(judge_sample),'by_model':dict(Counter(r['generator'] for r in judge_sample))},
        'audit':{'outputs':len(audit_sample),'by_model':dict(Counter(r['generator'] for r in audit_sample)),
            'by_style':dict(Counter(r['query_style'] for r in audit_sample)),
            'by_species':dict(Counter(r.get('species') or 'unknown' for r in audit_sample)),
            'by_category':dict(Counter(r['category'] for r in audit_sample)),
            'retrieval_miss':sum(not r['required_evidence_complete_in_top5'] for r in audit_sample)},
        'edge':{'questions':len(edge_rows),'by_style':dict(Counter(r['query_style'] for r in edge_rows)),
            'by_context_band':dict(Counter(r['context_band'] for r in edge_rows)),
            'by_species':dict(Counter(r.get('species') or 'unknown' for r in edge_rows)),
            'by_category':dict(Counter(r['category'] for r in edge_rows))}})
    print(json.dumps({'independent_judge_ready':False,'judge_sample':len(judge_sample),
        'audit_outputs':len(audit_sample),'claims':len(claims),'edge_subset':len(edge_rows)}),flush=True)


def audit():
    check_inputs()
    private={r['answer_id']:r for r in read_jsonl(OUT/'claim_citation_sample.jsonl')}
    records=read_jsonl(OUT/'blind_audit_records_v2.jsonl')
    checkpoint=OUT/'claim_citation_ai_audit.jsonl'
    done=read_jsonl(checkpoint) if checkpoint.exists() else []
    completed={r['claim_id'] for r in done}
    all_count=sum(len(r['claims']) for r in records)
    for record in records:
        contexts={c['context_id']:c for c in record['contexts']}
        for claim in record['claims']:
            if claim['claim_id'] in completed:
                continue
            ids=claim['audit_citation_set']; valid=[x for x in ids if x in contexts]
            result=audit_claim(record,claim,OUT/'raw_audit_judge_outputs.jsonl') if valid else {
                'evaluation_status':'not_called_no_valid_citation','judgments':[],'attempts':0,'retry_count':0}
            pairs=[]
            for j in result['judgments']:
                text=contexts[j['context_id']]['text']; quote=j['supporting_quote']
                # Evidence quotes are checked without correcting any raw judge output.
                quote_valid=bool(quote.strip()) and ''.join(quote.split()) in ''.join(text.split())
                supporting=j['verdict'] in ('entailed','partially_entailed')
                effective='cannot_determine' if supporting and not quote_valid else j['verdict']
                pairs.append({**j,'effective_verdict':effective,'supporting_quote_valid':quote_valid,
                    'provenance_valid':True, 'chunk_id':contexts[j['context_id']]['chunk_id'],
                    'document_id':contexts[j['context_id']]['document_id'],'page':contexts[j['context_id']]['page']})
            for cid in ids:
                if cid not in contexts:
                    pairs.append({'context_id':cid,'verdict':'cannot_determine','effective_verdict':'cannot_determine',
                                  'provenance_valid':False,'reason':'citation_not_in_supplied_context'})
            if result['evaluation_status']=='failed':
                pairs.extend({'context_id':cid,'verdict':'cannot_determine','effective_verdict':'cannot_determine',
                    'provenance_valid':True,'reason':'technical_judge_failure'} for cid in valid)
            output={**claim,'judge_result':result,'citation_pairs':pairs,'claim_verdict':claim_verdict(pairs),
                'review_source':'ai','human_verified':False,'independent_judge':False,
                'judge_conflict':private[record['answer_id']]['generator']==JUDGE_MODEL,
                'primary_entailment_eligible':private[record['answer_id']]['generator']!=JUDGE_MODEL,
                'generator_identity_provided_to_judge':False}
            append_jsonl(checkpoint,output); completed.add(claim['claim_id'])
            print(f'Blind claim audit {len(completed)}/{all_count}; {output["claim_verdict"]}',flush=True)
    check_inputs()


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['prepare','audit','report'])
    action=parser.parse_args().action
    if action=='report':
        from .report import render
        render()
    else:
        {'prepare':prepare,'audit':audit}[action]()
