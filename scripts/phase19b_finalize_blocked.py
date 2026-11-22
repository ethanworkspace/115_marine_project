"""Preserve a blocked gate, run tests and audit compatibility; no inference calls."""
import importlib.metadata
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.evaluation.generation.frozen import sha256_file
from src.evaluation.edge.core19b import MODELS, CONDITIONS, split_readiness, utc_now
from src.evaluation.edge.telemetry19b import windows_process_tree

OUT = ROOT / 'reports/evaluation/edge/phase19B'


def write(name, data):
    path = OUT / name
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2);stream.write('\n')


def main():
    probe = json.loads((OUT/'runtime_preflight.json').read_text(encoding='utf-8'))
    if probe['phase19B_status'] != 'blocked_reranker_runtime':
        raise SystemExit('Blocked finalizer must not be used for a passed runtime')
    readiness = split_readiness({m:'benchmark_incomplete' for m in MODELS})
    write('phase20_readiness.json', {**readiness, 'phase19B_status':'blocked_reranker_runtime',
        'technical_feasibility_established':False, 'independent_judge_ready':False,
        'human_reviewed_outputs':0,'human_reviewed_claims':0,'qwen_quality_status':'evaluation_unresolved'})
    observed_steps = {'torch_import':'failed','CUDA_availability':'not_reached','model_load':'not_reached',
                      'single_pair_inference':'not_reached','ten_query_inference':'not_reached'}
    # Read installed distribution metadata without trying another torch import or changing packages.
    code = "import json,importlib.metadata as m; print(json.dumps({k:m.version(k) for k in ['torch','transformers','safetensors','tokenizers','huggingface-hub']}))"
    runtime = subprocess.run([str(ROOT/'.venv-reranker/Scripts/python.exe'),'-B','-c',code],cwd=ROOT,
                             capture_output=True,text=True,encoding='utf-8',errors='replace')
    write('runtime_distribution_metadata.json', dict(return_code=runtime.returncode,
        packages=json.loads(runtime.stdout) if runtime.returncode==0 else None,
        error=runtime.stderr or None, source='Installed metadata only, not runtime import success'))
    baseline = {'timestamp':utc_now(),'measurement_phase':'post_failed_preflight; not formal performance measurement',
                'process_tree':windows_process_tree(),'ollama_ps':None,'sensors':None}
    errors=[]
    try:
        with urlopen('http://127.0.0.1:11434/api/ps',timeout=10) as response:
            baseline['ollama_ps']=json.load(response)
    except Exception as exc:errors.append(str(exc))
    try:
        from src.evaluation.edge.hardware19a import Sensors
        sensor=Sensors()
        sensor.sample();time.sleep(1)
        baseline['sensors']=sensor.sample()
        # Preserve full WDDM instance arrays so model-runner counters are not filtered out.
        baseline['GPU_memory_counter_instances']=sensor.pdh.sample() if sensor.pdh else None
        errors.extend(sensor.errors);sensor.close()
    except Exception as exc:errors.append(str(exc))
    baseline['measurement_errors']=errors
    baseline['reranker_process_state']={'resident':False,'reason':'Isolated preflight process exited after torch import failure'}
    write('environment_baseline.json',baseline)
    write('retrieval_reproducibility.json', dict(status='not_run',reason='blocked_reranker_runtime',
        retrieval_reproducibility_pass=False,questions_expected=60,questions_checked=0,
        matched=None,mismatches=None,not_a_reproducibility_failure=True,
        intermediate_rankings_comparison=None))
    write('retrieval_drift.json',dict(status='not_measured',requests_executed=0,retrieval_drift_count=None))
    base=dict(status='not_run',reason='blocked_reranker_runtime',formal_queries_planned=540,formal_queries_executed=0)
    write('stage_latency.json',{**base,'units':'milliseconds','stages':{s:None for s in
        ('bm25','dense_query_embedding','dense_search','rrf','reranker','context_assembly','retrieval_to_context',
         'generator_load_or_reload','generator_ttft_any','generator_ttft_final','generation_completion')},
        'conditions':{c:None for c in CONDITIONS}})
    write('end_to_end_latency.json',{**base,'e2e_ttft_final_ms':None,'e2e_total_latency_ms':None,
        'retry_inclusive_latency_ms':None,'generator_component_ms':None,'Phase19A_overhead_comparison':None})
    write('memory.json',{**base,'system_RAM_peak':None,'benchmark_runner_peak':None,'ollama_server_peak':None,
        'ollama_model_runner_peak':None,'reranker_python_peak':None,
        'process_tree_collector':'src.evaluation.edge.telemetry19b.windows_process_tree includes llama-server.exe',
        'baseline_available':True,'benchmark_peak_measured':False})
    write('gpu_memory.json',{**base,'device_dedicated_peak':None,'device_shared_peak':None,'per_process_GPU_peak':None,
        'shared_memory_is_dedicated_VRAM':False,'memory_semantics':'Shared memory is system-RAM-backed; separate device/process scopes'})
    write('ifr.json',{**base,'retrieval_IFR':None,'generation_IFR':None,'fullrag_IFR':None,
        'formal_failed_requests':None,'preflight_runtime_failure_count':1,
        'note':'No formal queries executed: IFR undefined, not 0%; preflight failure excluded from formal IFR'})
    write('context_length_analysis.json',{**base,'short_questions':20,'medium_questions':21,'long_questions':19,
        'per_condition_metrics':None})
    write('run_stability.json',{**base,'completed_warm_runs':0,'retrieval_CV':None,'e2e_TTFT_CV':None,'e2e_latency_CV':None})
    write('sustained_load.json',{**base,'gate_passed':False,'duration_planned_per_model_seconds':1800,
        'Gemma_executed':False,'Qwen_executed':False,'reason':'Formal warm runs not started'})
    write('behavior_preservation.json',{**base,'schema_validity':None,'citation_validity':None,
        'required_citation_recall':None,'status_agreement':None,'citation_set_agreement':None,'answer_similarity':None})
    write('fullrag_deployment_matrix.json',{'models':[
        dict(model='gemma2:9b',quality_status='conditional_candidate',hardware_status='benchmark_incomplete',
             runtime_gate='blocked_reranker_runtime',technical_feasibility_established=False),
        dict(model='qwen2.5-coder:7b',quality_status='evaluation_unresolved',hardware_status='benchmark_incomplete',
             runtime_gate='blocked_reranker_runtime',technical_feasibility_established=False)],
        'no_quality_winner':True,'no_composite_score':True})
    write('environment_limitations.json',dict(phase19B_status='blocked_reranker_runtime',
        observed_error=probe['error'],observed_winerror=probe.get('winerror'),error_library='torch/lib/shm.dll or a dependency',
        exact_policy_component='unknown; WinError states application control policy blocked the file',
        runtime_step_status=observed_steps,CUDA_availability_measured=False,
        no_CPU_fallback=True,no_model_substitution=True,no_runtime_reinstallation=True,
        no_Windows_policy_change=True,no_security_software_change=True,
        no_Retrieval_or_Generator_inference=True,no_RAGAS=True,
        existing_E4_metric_invalidated=False))
    for name in ('model_residency.jsonl','cold_pipeline.jsonl','retrieval_only_runs.jsonl',
                 'fullrag_gemma_runs.jsonl','fullrag_qwen_runs.jsonl'):
        (OUT/name).open('x',encoding='utf-8').close()
    run = subprocess.run([str(ROOT/'.venv/Scripts/python.exe'),'-B','-m','unittest','discover','-s','tests','-v'],
        cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,encoding='utf-8',errors='replace',
        env={**os.environ,'PYTHONIOENCODING':'utf-8','PYTHONDONTWRITEBYTECODE':'1'})
    (OUT/'unittest_final.log').write_text(run.stdout,encoding='utf-8')
    n=re.search(r'Ran (\d+) tests?',run.stdout);skips=re.search(r'skipped=(\d+)',run.stdout)
    tests=dict(return_code=run.returncode,tests=int(n[1]) if n else None,skipped=int(skips[1]) if skips else 0)
    write('tests.json',tests)
    before=json.loads((OUT/'protected_before.json').read_text(encoding='utf-8'));changed=[]
    for name,old in before.items():
        p=ROOT/name
        if not p.is_file():changed.append(name);continue
        s=p.stat();new=dict(sha256=sha256_file(p),size=s.st_size,mtime_ns=s.st_mtime_ns)
        if new!=old:changed.append(name)
    db=ROOT/'rag_store.sqlite3';s=db.stat()
    db_after=dict(sha256=sha256_file(db),size=s.st_size,mtime_ns=s.st_mtime_ns)
    http=None;health_error=None
    try:
        with urlopen('http://127.0.0.1:8767/_stcore/health',timeout=10) as response:http=response.status
    except Exception as exc:health_error=str(exc)
    compatibility=dict(protected_count=len(before),changed=changed,unchanged=not changed,
        sqlite_before=before['rag_store.sqlite3'],sqlite_after=db_after,
        SQLite_identical=before['rag_store.sqlite3']==db_after,
        production_Streamlit_HTTP=http,health_error=health_error,
        production_code_modified=False,production_prompt_modified=False,
        prior_environment_modified=False,no_model_download=True,no_RAGAS=True,
        phase19A_artifacts_unchanged=not any(n.startswith('reports/evaluation/edge/phase19A/') for n in changed))
    write('compatibility.json',compatibility)
    write('execution_status.json',dict(phase19B_status='blocked_reranker_runtime',runtime_ready=False,
        E4_reproduction_executed=False,formal_queries_executed=0,pairs_scored=probe['pairs_scored'],
        cold_runs_executed=0,warm_runs_executed=0,sustained_runs_executed=0,
        tests=tests,compatibility_passed=not changed and compatibility['SQLite_identical'] and http==200,
        **readiness))
    md=f'''# Phase 19B — Full Edge RAG preflight 停止報告

## 狀態

`phase19B_status = blocked_reranker_runtime`。沒有執行正式 benchmark，也沒有形成 full-RAG technical feasibility 結論。

Target：marine-edge-workstation-01；i5-14400F、32 GiB、RTX 4060 8 GB dedicated VRAM；Windows 11 build 26300、Ollama 0.35.0。
Scope：evaluation-only full RAG；acceptance thresholds 未預先定義。AI-generated Corpus-Grounded Silver Benchmark，沒有 human-validated quality winner。

## Frozen input gate

Corpus v2、Grounded Silver v1、E1-E4 manifests、BGE-M3 1024維 index/vectors、reranker model/config/tokenizer checksums 通過。
凍結60 questions、300 E4 Top-5 contexts、question order、context checksums與 generation_v2／schema／Protocol v2.2維持一致。
Gemma／Qwen artifact digests與 Phase19A一致；BGE-M3 model digest與 E2一致。没有下載或修改模型。

## Reranker preflight

Existing executable：`.venv-reranker/Scripts/python.exe`；Python {probe['Python']}。
失敗位置：`torch import`；WinError {probe.get('winerror')}。
原始錯誤：{probe['error']}

錯誤指出Windows application control policy封鎖`torch/lib/shm.dll`或相依DLL；本輪沒有證據判定具體 policy component，也不能聲稱錯誤是`c10_cuda.dll`。
CUDA availability、model load、single pair、10-query inference皆未到達；不是已測得CUDA硬體不可用。
scored pairs=0；没有CPU fallback、模型替換、重新安裝、Windows policy或安全軟體變更。

## 未執行項目

- E4 60/60 Top-5 reproduction：未執行；`retrieval_reproducibility_pass=false`表示未通過執行gate，不是rank mismatch。
- R0/F1/F2正式queries：0/540；pipeline-cold、三輪warm、兩個sustained tests：皆未執行。
- BM25、Dense embedding/search、RRF、reranker、context assembly、Generation component、E2E TTFT/latency：null。
- 正式RAM/VRAM/shared-memory peaks、IFR、retrieval drift、Short/Medium/Long、三輪穩定性、behavior preservation：未量測。IFR不能報為0%。
- Residency/reload/eviction/CPU fallback/spill：沒有formal-request觀測，不能推論。只保存post-preflight baseline與process-tree telemetry。

## Status 與 readiness

| Model | Full-RAG hardware status | Frozen quality status |
| --- | --- | --- |
| Gemma 9B | benchmark_incomplete | conditional_candidate |
| Qwen Coder 7B | benchmark_incomplete | evaluation_unresolved |

`phase20_research_integration_ready=false`；`final_model_selection_ready=false`。
尚缺full-RAG technical feasibility；Independent Judge與human claim-citation review亦未完成。不能以Phase19A generator-only metrics代填本輪full-RAG結果。

## Tests／compatibility

Tests：{tests['tests']}，skipped={tests['skipped']}，return_code={tests['return_code']}。完整輸出保存在`unittest_final.log`。
Protected files：{len(before)}；changed={len(changed)}。Production Streamlit HTTP={http}。
SQLite size={db_after['size']}，mtime_ns={db_after['mtime_ns']}，SHA-256=`{db_after['sha256']}`；與執行前一致={compatibility['SQLite_identical']}。
Corpus/Silver/E1-E4/Phase15-19A與production code/prompt/DB保持不變。新增內容僅evaluation gates、process-tree collector、tests、reports與protocol文件。

## 下一步

先由系統管理者確認既有PyTorch DLL受到哪個Windows application control policy阻擋；保持模型、實驗config與安全policy完整。
Runtime問題解決後，在新的execution revision重新確認protected checksums，再通過CUDA、single-pair、10-query以及60/60 E4 reproduction gates；全部通過才執行540 formal queries與sustained tests。
沒有開始Phase20、production migration、RAGAS、Retrieval/Prompt/Reranker/Quantization tuning。
'''
    (OUT/'phase19B_summary.md').write_text(md,encoding='utf-8')
    write('implementation_checksums.json',{p.relative_to(ROOT).as_posix():sha256_file(p) for p in
        [*(ROOT/'src/evaluation/edge').glob('*19b.py'),*(ROOT/'scripts').glob('phase19b*.py')]})
    print(json.dumps({'status':'blocked_reranker_runtime','tests':tests,'compatibility':compatibility,'readiness':readiness},ensure_ascii=False),flush=True)
    if run.returncode or changed or http!=200:raise SystemExit(1)


if __name__=='__main__':main()
