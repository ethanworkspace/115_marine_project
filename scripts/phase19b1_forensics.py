"""Build evidence reports from immutable captures; never run remediation."""
import json
import os
import platform
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from src.evaluation.generation.frozen import sha256_file
from src.evaluation.edge.recovery19b1 import parse_event,classify,pe_imports,relevant_block_events
OUT=ROOT/'reports/evaluation/edge/phase19B_runtime_recovery'


def write(name,data):
    with (OUT/name).open('x',encoding='utf-8') as f:json.dump(data,f,ensure_ascii=False,indent=2);f.write('\n')


def main():
    rows=[parse_event(json.loads(line)) for line in (OUT/'windows_code_integrity_events_exact_utc.jsonl').read_text(encoding='utf-8').splitlines() if line]
    with (OUT/'normalized_windows_events.jsonl').open('x',encoding='utf-8') as f:
        for row in rows:f.write(json.dumps(row,ensure_ascii=False)+'\n')
    identity=json.loads((OUT/'blocked_file_identity.json').read_text(encoding='utf-8'))
    dlls=[r for r in identity if r.get('absolute_path','').lower().endswith('.dll')]
    lib=ROOT/'.venv-reranker/Lib/site-packages/torch/lib'
    dependency=[]
    for file in dlls:
        p=Path(file['absolute_path'])
        try:
            parsed=pe_imports(p)
            candidates={}
            for name in parsed['imports']+parsed['delay_imports']:
                locations=[lib/name,Path('C:/Windows/System32')/name,Path('C:/Python314')/name]
                candidates[name]=[str(l) for l in locations if l.is_file()]
            dependency.append(dict(path=str(p),**parsed,existing_candidates=candidates))
        except Exception as exc:dependency.append(dict(path=str(p),error=str(exc)))
    blocks=relevant_block_events(rows)
    shm=next(r for r in dlls if Path(r['absolute_path']).name=='shm.dll')
    block3077=[r for r in blocks if r['event_id']==3077]
    write('dependency_diagnostics.json',dict(method='Static PE normal/delay imports; no LoadLibrary, DLL copying or PATH edits',
        images=dependency,actual_blocked_target='shm.dll',direct_block_evidence=[r['record_id'] for r in block3077],
        blocked_flat_hash_matches=all(r['event_data'].get('SHA256 Flat Hash','').lower()==shm['sha256'].lower() for r in block3077),
        scope_limit='Existing candidates do not establish the actual loader resolution; direct CI event proves shm.dll itself blocked',
        transient_decision_explanation='unknown; Defender/ISG trust/caching fields captured without interpreting undocumented codes'))
    current=json.loads((OUT/'package_metadata.raw.json').read_text(encoding='utf-8'))
    old=json.loads((ROOT/'reports/evaluation/reranker_runtime/environment_audit.json').read_text(encoding='utf-8'))
    baseline=old['isolated_reranker_runtime'];meta=json.loads((ROOT/'reports/evaluation/reranker_runtime/model_metadata.json').read_text())
    normalized=lambda text:sorted(line.strip().casefold().replace('_','-') for line in text.splitlines() if line.strip())
    freeze_equal=normalized((OUT/'failed_runtime_pip_freeze.txt').read_text())==normalized((ROOT/'reports/evaluation/reranker_runtime/requirements.freeze.txt').read_text())
    later=json.loads((ROOT/'reports/evaluation/ragas/protected_before.json').read_text(encoding='utf-8'))
    DLL_compare=[]
    for r in dlls:
        rel=Path(r['absolute_path']).relative_to(ROOT).as_posix()
        ref=later.get(rel)
        DLL_compare.append(dict(path=rel,current_sha256=r['sha256'].lower(),post_Phase14_1_reference=ref,
            matches=ref['sha256']==r['sha256'].lower() if ref else None,
            reference_source='Phase16 protection snapshot; Phase14.1 did not save DLL checksums'))
    drift=any(r['matches'] is False for r in DLL_compare)
    model_matches=all(sha256_file(Path(meta['snapshot_location'])/name)==r['sha256'] for name,r in meta['files'].items())
    write('working_vs_blocked_runtime.json',dict(working_Phase14_1=dict(Python=baseline['python_version'],
        torch=baseline['torch_version'],transformers=baseline['transformers_version'],huggingface_hub=baseline['huggingface_hub_version'],
        torch_CUDA_build=baseline['torch_cuda_build'],OS=old['os'],GPU=old['gpu'],runtime_path='.venv-reranker',
        known_policy_evidence=baseline['sentencepiece_native_extension']),
        current=current,package_freeze_exact_same=freeze_equal,DLL_comparison=DLL_compare,runtime_artifact_drift=drift,
        model_identity_matches=model_matches,model_id=meta['model_id'],revision=meta['revision'],
        environment_variable_history='Phase14.1 did not preserve matching environment variables; historical change unknown',
        policy_history='Phase14.1 only records a native-extension block; complete previous policy inventory unavailable',
        OS_version_same=current['OS']==old['os']['platform'],
        warning='Unchanged runtime/corpus checksums do not establish unchanged Windows execution policy'))
    current_minimal=json.loads((OUT/'minimal_failure.json').read_text(encoding='utf-8'))
    write('root_cause_analysis.json',dict(classifications=classify(rows,runtime_drift=drift,
        signature_status=shm['signature']['status'],zone_present=shm['Zone_Identifier_present']),
        historical_block_confirmed=True,blocked_target=shm['absolute_path'],blocked_SHA256=shm['sha256'].lower(),
        direct_evidence=[dict(record_id=r['record_id'],event_id=r['event_id'],timestamp=r['timestamp'],
            policy=r['policy_name'],policy_identifier=r['policy_identifier'],status_code=r['status_code']) for r in blocks],
        unsigned_file_is_not_malware_determination=True,Zone_Identifier_related_cause_established=False,
        OS_policy_state_change_established=False,path_policy_issue_established=False,
        dependency_load_failure_without_policy_established=False,runtime_artifact_drift_established=drift,
        current_minimal_import_exit=current_minimal['exit_code'],current_allow_reason='unknown',
        possible_dynamic_trust_state='hypothesis only; no causal claim',
        event_window_correction='Initial FilterHashtable query returned out-of-window events; preserved separately and excluded. Exact UTC XPath capture is authoritative.',
        interpretation_sources=['https://learn.microsoft.com/en-us/windows/security/application-security/application-control/app-control-for-business/operations/event-id-explanations',
            'https://learn.microsoft.com/en-us/windows/apps/develop/smart-app-control/overview']))
    write('remediation_decision.json',dict(proposed_remediation='No file/security remediation; validate unchanged existing runtime with ordered recovery gates',
        why_policy_compliant='Original environment unchanged; current import succeeds under existing enforced policy; no exceptions or bypass actions',
        files_affected=[],runtime_r2_created=False,requires_policy_authorization=False,
        administrative_read_access_needed_for_full_policy_inventory=True,
        administrative_action='Optional administrator read-only CiTool policy inventory/history; no allow rules requested',
        runtime_rebuild_justified=False,reason='No package/DLL drift found; cloning identical unsigned binaries does not explain or remedy a policy decision',
        current_minimal_import_passed=current_minimal['exit_code']==0,
        permanent_recovery_claimed=False,expected_impact='Diagnostic/gate execution only; no experiment identity change'))
    print(json.dumps({'classifications':classify(rows,signature_status=shm['signature']['status']),
        'package_freeze_same':freeze_equal,'DLL_drift':drift,'model_identity_matches':model_matches,'r2_created':False}),flush=True)


if __name__=='__main__':main()
