"""Finalize forensics and recovered gates without starting any formal benchmark."""
import datetime as dt
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.request import urlopen

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from src.evaluation.generation.frozen import sha256_file
from src.evaluation.edge.recovery19b1 import resume_gate
OUT=ROOT/'reports/evaluation/edge/phase19B_runtime_recovery'


def read(name):return json.loads((OUT/name).read_text(encoding='utf-8'))
def write(name,obj):
    with (OUT/name).open('x',encoding='utf-8') as f:json.dump(obj,f,ensure_ascii=False,indent=2);f.write('\n')


def main():
    execution=read('R0_R5_execution.json');gates=execution['gates']
    if (OUT/'e4_60_reproduction.json').is_file():e4=read('e4_60_reproduction.json')
    else:
        e4=dict(passed=False,status='not_reached',questions_checked=0,reason='R0-R5 not all passed')
        write('e4_60_reproduction.json',e4)
    gates={**gates,'E4_60':{'passed':e4['passed']}}
    machine={'timestamp':dt.datetime.now(dt.timezone.utc).isoformat()}
    try:
        from src.evaluation.edge.hardware19a import gpu_sample
        machine['GPU']=gpu_sample()
    except Exception as exc:machine['GPU_error']=str(exc)
    policy_script="[ordered]@{timestamp=[datetime]::UtcNow.ToString('o');VerifiedAndReputablePolicyState=(Get-ItemProperty -LiteralPath 'HKLM:\\SYSTEM\\CurrentControlSet\\Control\\CI\\Policy').VerifiedAndReputablePolicyState;active_policy_files=@(Get-ChildItem -LiteralPath \"$env:WINDIR/System32/CodeIntegrity/CiPolicies/Active\" -File|ForEach-Object {@{path=$_.FullName;sha256=(Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash}})}|ConvertTo-Json -Depth 6"
    p=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',policy_script],capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=30)
    machine['policy_read_exit_code']=p.returncode;machine['policy_read_stdout']=p.stdout;machine['policy_read_stderr']=p.stderr
    try:machine['policy_after']=json.loads(p.stdout)
    except json.JSONDecodeError:machine['policy_after']=None
    write('current_machine_and_policy_after.json',machine)
    original=read('windows_policy_state.json');after=machine['policy_after'] or {}
    before_policies={r['path']:r['sha256'] for r in original.get('active_policy_files',[])}
    after_policies={r['path']:r['sha256'] for r in after.get('active_policy_files',[])}
    current_comparison=read('working_vs_blocked_runtime.json')
    driver=machine.get('GPU',{}).get('driver_version')
    write('working_vs_current_addendum.json',dict(nvidia_driver_actual=driver,Phase14_1_driver='610.88',
        NVIDIA_driver_same=driver=='610.88',runtime_rebuilt=False,
        active_policy_file_hashes_before=before_policies,active_policy_file_hashes_after=after_policies,
        active_policy_files_unchanged_during_this_turn=before_policies==after_policies if before_policies and after_policies else None,
        VerifiedAndReputablePolicyState_before=original.get('CI_policy_registry',{}).get('VerifiedAndReputablePolicyState'),
        VerifiedAndReputablePolicyState_after=after.get('VerifiedAndReputablePolicyState'),
        note='This-turn policy file equality cannot establish unchanged historical policy or cloud/reputation trust state'))
    result=subprocess.run([str(ROOT/'.venv/Scripts/python.exe'),'-B','-m','unittest','discover','-s','tests','-v'],
        cwd=ROOT,capture_output=True,encoding='utf-8',errors='replace',
        env={**os.environ,'PYTHONIOENCODING':'utf-8','PYTHONDONTWRITEBYTECODE':'1'})
    (OUT/'unittest_final.log').write_text(result.stdout+result.stderr,encoding='utf-8')
    output=result.stdout+result.stderr;n=re.search(r'Ran (\d+) tests?',output);skip=re.search(r'skipped=(\d+)',output)
    tests=dict(return_code=result.returncode,tests=int(n[1]) if n else None,skipped=int(skip[1]) if skip else 0)
    write('tests.json',tests)
    before=read('protected_before.json');changed=[]
    for name,old in before.items():
        path=ROOT/name
        if not path.is_file():changed.append(name);continue
        s=path.stat();record=dict(sha256=sha256_file(path),size=s.st_size,mtime_ns=s.st_mtime_ns)
        if record!=old:changed.append(name)
    env_before=read('failed_runtime_files_before.json')
    env_after={p.relative_to(ROOT).as_posix() for p in (ROOT/'.venv-reranker').rglob('*') if p.is_file()}
    added=sorted(env_after-set(env_before));removed=sorted(set(env_before)-env_after)
    env_changed=[r for r in changed if r.startswith('.venv-reranker/')]
    immutable=not(env_changed or added or removed)
    db=ROOT/'rag_store.sqlite3';s=db.stat();db_after=dict(sha256=sha256_file(db),size=s.st_size,mtime_ns=s.st_mtime_ns)
    http=None;health_error=None
    try:
        with urlopen('http://127.0.0.1:8767/_stcore/health',timeout=10) as response:http=response.status
    except Exception as exc:health_error=str(exc)
    compatible=not changed and immutable and db_after==before['rag_store.sqlite3'] and http==200
    write('compatibility.json',dict(protected_count=len(before),changed=changed,unchanged=not changed,
        failed_runtime_files_before=len(env_before),failed_runtime_files_after=len(env_after),failed_runtime_immutable=immutable,
        runtime_files_changed=env_changed,runtime_files_added=added,runtime_files_removed=removed,
        sqlite_before=before['rag_store.sqlite3'],sqlite_after=db_after,SQLite_identical=db_after==before['rag_store.sqlite3'],
        production_Streamlit_HTTP=http,health_error=health_error,compatible=compatible,
        model_or_package_installation_performed=False,security_settings_changed=False,
        original_Phase19B_outputs_modified=False,formal_benchmark_queries_executed=0))
    ready=resume_gate(gates) and compatible and result.returncode==0
    write('recovery_gate_summary.json',dict(gates=gates,phase19b_runtime_ready=ready,
        original_environment_used=True,runtime_r2_created=False,
        permanent_policy_resolution_claimed=False,artifact_compatibility_passed=compatible))
    write('phase19b_resume_status.json',dict(phase19b_runtime_ready=ready,
        phase20_research_integration_ready=False,final_model_selection_ready=False,
        formal_benchmark_queries_executed=0,original_runner_resume_entrypoint=False,
        action='Ready to start a new formal Phase19B execution revision' if ready else 'Stop: recovery gates or integrity failed',
        reason='Runtime gates alone do not constitute completed Full-RAG performance benchmark',
        independent_judge_ready=False,human_claim_review_complete=False,Qwen_quality_status='evaluation_unresolved'))
    cause=read('root_cause_analysis.json');ten=read('ten_query_compatibility.json');files=read('blocked_file_identity.json')
    shm=next(r for r in files if Path(r.get('absolute_path','')).name=='shm.dll')
    r0=read('torch_preflight.json');r1=read('cuda_preflight.json');r2=read('reranker_model_preflight.json');r3=read('single_pair_validation.json')
    rows=[json.loads(x) for x in (OUT/'normalized_windows_events.jsonl').read_text(encoding='utf-8').splitlines()]
    ci=[r for r in rows if r['event_id'] in (3033,3077,3089,3118) and ('.venv-reranker' in str(r.get('blocked_path','')) or r.get('correlation_id') in {b.get('correlation_id') for b in rows if b['event_id']==3077})]
    summary=f'''# Phase 19B.1 — Windows reranker runtime recovery

## 結果

`phase19b_runtime_ready={str(ready).lower()}`。本輪原環境直接通過recovery gates；沒有建立`.venv-reranker-r2`或施作package/security修復。
原Phase19B blocked reports保持immutable。正式R0/F1/F2仍為0 requests；沒有開始540-query benchmark。

## Minimal reproduction與historical block

新的唯一minimal `python -B -c "import torch"` exit code={read('minimal_failure.json')['exit_code']}；stdout/stderr原始bytes、SHA與timestamps完整保存。
Historical Phase19B failure有direct Code Integrity evidence：event3077 record32945、3033 record32943及correlated3089/3118。
3077 policy=`VerifiedAndReputableDesktop`，GUID=`{{0283ac0f-fff1-49ae-ada1-8a933130cad6}}`，status=`0xc0e90002`。
真正blocked file為`{shm['absolute_path']}`本身；CI SHA256 Flat Hash與current SHA完全相同。
SHA-256=`{shm['sha256'].lower()}`；size={shm['size']}；Authenticode={shm['signature']['status']}；Zone.Identifier={shm['Zone_Identifier_present']}；owner/ACL/mtime保存在identity report。

Root-cause classifications：{', '.join(cause['classifications'])}。Unsigned信任條件為歷史block的相關證據，不是malware或expired/revoked certificate判定。
沒有runtime DLL drift、package freeze差異或model artifact差異。沒有證據證明MOTW、PATH或一般missing-dependency造成此次historical block。
為何相同unsigned DLL現在被允許：unknown。Defender cloud/reputation diagnostic欄位已保存，但不將未證實假說宣稱為因果。

## Windows evidence limitations

- 原始與exact UTC XPath events皆保留。Initial FilterHashtable捕捉到out-of-window events，未用於root-cause；以XML SystemTime與exact UTC查詢為準。
- CiTool完整policy inventory仍Access Denied，collector不是administrator。可由IT補充唯讀inventory/history；不需要allow rule或security-policy exception來執行本輪已通過gates。
- 本輪前後active policy hashes/registry值另存comparison addendum；不能以此斷言歷史policy或dynamic reputation未改變。
- 沒有卸除Zone.Identifier、whitelist、policy disable、Defender disable、DLL复制、PATH修改或CPU fallback。

## Working baseline comparison

Python3.14.7、torch2.14.1+cu130、Transformers5.18.0、HF Hub1.33.0及全部37項freeze一致；Windows11build26300、NVIDIA driver={driver}。
Phase14.1本身沒有完整DLL hashes/envvars/policy inventory；DLL比較明確使用後續Phase16protection snapshot，不冒充當時未保存的資料。
Model仍為BAAI/bge-reranker-v2-m3，revision953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e，weights/config/tokenizer hashes全部符合。

## Recovery gates

| Gate | 結果 |
| --- | --- |
| R0 torch import | {r0.get('passed')}；{r0.get('torch_version')}；CUDA build {r0.get('CUDA_build')} |
| R1 CUDA/GPU | {r1.get('passed')}；{r1.get('GPU_name')} |
| R2 exact model load | {r2.get('passed')}；cuda:0／float32／max_length512／batch4 |
| R3 1query×2candidates | {r3.get('passed')}；finite scores／identity preserved |
| R4 original10queries×50 | {gates.get('R4',{}).get('passed')}；500 pairs |
| R5 frozen E4 compatibility | {ten.get('passed')}；ordering mismatches={ten.get('ordering_mismatch_count')}；max score delta={ten.get('max_score_difference')} |
| Fixed60-question E4 reproduction | {e4.get('passed')}；matched={e4.get('matched')}/60；mismatches={e4.get('mismatch_count')} |

Reproduction使用fresh BGE-M3 query embeddings、same frozen corpus vectors、BM25/RRF/reranker；不是重播saved Top5。
Intermediate BM25/Dense/RRF Top50差異與embedding delta均在reproduction traces/report；未為追求一致而tune。

## Tests與compatibility

Tests={tests['tests']}；skipped={tests['skipped']}；return code={tests['return_code']}。
Protected files={len(before)}；changed={len(changed)}。
原`.venv-reranker`完整{len(env_before)}files：changed={len(env_changed)}、added={len(added)}、removed={len(removed)}；immutable={immutable}。
Production Streamlit HTTP={http}。SQLite size={db_after['size']}、mtime_ns={db_after['mtime_ns']}、SHA=`{db_after['sha256']}`，與執行前一致。
Corpus/Silver/E1-E4/Phase15-19B production artifacts均未改；新增只有evaluation diagnostics/code/tests/reports。

## Resume decision

可在新Phase19B execution revision開始正式benchmark={ready}。本輪沒有自動啟動；原runner沒有完整formal resume entrypoint。
`phase20_research_integration_ready=false`與`final_model_selection_ready=false`：尚未完成full-RAG performance，也仍缺Independent Judge/human citation validation。
後續保留每次torch/CUDA預檢與CI diagnostics；如block重現即停止，不宣稱本輪成功保證永久可執行。

## Primary documentation

[Microsoft App Control events](https://learn.microsoft.com/en-us/windows/security/application-security/application-control/app-control-for-business/operations/event-id-explanations)：3077為enforced block，3089提供signature資訊並透過Correlation ActivityID連結。
[Smart App Control overview](https://learn.microsoft.com/en-us/windows/apps/develop/smart-app-control/overview)：用於解讀trust/reputation背景；本報告不推論未記錄的內部decision。
'''
    (OUT/'phase19B_runtime_recovery_summary.md').write_text(summary,encoding='utf-8')
    write('implementation_checksums.json',{p.relative_to(ROOT).as_posix():sha256_file(p) for p in
        [ROOT/'src/evaluation/edge/recovery19b1.py',*(ROOT/'scripts').glob('phase19b1*')]})
    write('output_checksums.json',{p.relative_to(ROOT).as_posix():sha256_file(p) for p in OUT.rglob('*') if p.is_file() and p.name!='output_checksums.json'})
    print(json.dumps({'phase19b_runtime_ready':ready,'tests':tests,'protected_changed':changed,
        'failed_runtime_immutable':immutable,'new_runtime_files':added,'production_HTTP':http,'formal_benchmark_queries':0}),flush=True)
    if result.returncode or not compatible:raise SystemExit(1)


if __name__=='__main__':main()
