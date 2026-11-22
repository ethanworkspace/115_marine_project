"""Readable completion report from recorded metrics only; no model execution."""
from __future__ import annotations
import json
import re
from .core import MODELS
from .execution19a import OUT,write


def load(name):return json.loads((OUT/(name+'.json')).read_text(encoding='utf-8'))
def number(value):return 'N/A' if value is None else f'{value:.3f}'
def percent(value):return 'N/A' if value is None else f'{value*100:.2f}%'
def gib(value):return number(value/1024**3) if value is not None else 'N/A'
def table(header,rows):
    return ['| '+' | '.join(header)+' |','| '+' | '.join('---' for _ in header)+' |',
        *['| '+' | '.join(map(str,row))+' |' for row in rows],'']


def render_summary():
    target=load('target_device_manifest')['target'];validation=load('execution_validation')
    matrix=load('model_deployment_matrix');rel=load('reliability');cold=load('cold_start_summary')
    ttft=load('ttft');tps=load('throughput');lat=load('latency');context=load('context_length_analysis')
    stable=load('run_stability');sustained=load('sustained_load');behavior=load('behavior_preservation')
    paired=load('paired_performance');pareto=load('pareto_analysis');compat=load('compatibility');tests=load('tests')
    release=load('cold_gpu_release_audit');limits=load('environment_limitations')
    observations=load('runtime_placement_log_observations')['observations']
    placement={}
    for model in MODELS:
        lines=[r['raw_line'] for r in observations if r['model']==model]
        placement[model]=dict(GPU_layers=sorted({m.group(1)+'/'+m.group(2) for s in lines if (m:=re.search(r'offloaded (\d+)/(\d+) layers',s))}),
            CPU_threads=sorted({int(m.group(1)) for s in lines if (m:=re.search(r'n_threads\s*=\s*(\d+)',s))}),
            batch_size=sorted({int(m.group(1)) for s in lines if (m:=re.search(r'n_batch\s*=\s*(\d+)',s))}))
    write(OUT/'observed_runtime_defaults.json',dict(models=placement,
        source='Exact model-blob-bound runtime_placement_log_observations.json',manually_tuned=False,
        limitation='Native Ollama/model defaults selected different prompt batch sizes. This benchmarks recorded default-runtime behavior; no fixed-batch isolation claim.'))
    digest=dict(target_device=target['device_name'],edge_execution_ready=True,models={},
        warm_requests=720,cold_requests=12,validation=validation,tests=tests,compatibility=compat,
        cold_GPU_release_proxy_all_pass=release['all_device_proxies_pass'],pareto=pareto,
        paired_performance={pair:{metric:{k:v for k,v in values.items() if k!='question_ids'} for metric,values in metrics.items()}
            for pair,metrics in paired['comparison'].items()})
    lines=['# Phase 19A — Actual Local-Edge Generator Benchmark','',
        '已完成四模型 core benchmark。這是 generator-only Local Edge Inference Workstation 的描述性測量，不能視為 embedded／Jetson performance 或 full RAG latency。',
        'Human review 仍為 0；沒有 human-validated quality winner。未預先定義性能 acceptance thresholds。','',
        '## Target 與凍結輸入','',
        f"- Device：{target['device_name']}；Intel Core i5-14400F，10 cores／16 threads；32 GiB DDR4-3200；RTX 4060 8 GB dedicated VRAM。",
        f"- Windows 11 {target['OS']['version']}／build {target['OS']['build']}；Ollama 0.35.0；driver 32.0.16.1088（NVIDIA 610.88）。",
        '- NVMe XPG GAMMIX S50 CORE，1,000,204,886,016 bytes；NPU unavailable。',
        '- edge_execution_ready=true；deployment_mode=generator_only；acceptance_thresholds_defined=false。',
        '- 凍結 60 questions／300 E4 Top-5 contexts；Direct／Paraphrase／Contextual 各20；Short 20、Medium 21、Long 19。',
        '- generation_v2／原 JSON Schema／Protocol v2.2；temperature=0、top_p=1、seed=15015、max_output_tokens=1024、context_length=8192。',
        f"- 12 model-cold requests；720 formal warm requests（每模型3×60）。{validation['preserved_attempt_count']} attempts 全部保存，raw SHA mismatch={validation['raw_SHA_mismatches']}；contexts／question order mismatch=0。",'',
        '## Model artifact identity／placement','']
    for model in MODELS:
        m=load('model_manifests/'+model.replace(':','_'))
        lines.extend([f"### {model}",'',f"- Digest：`{m['digest']}`。",
            f"- {m['parameter_size']}／{m['quantization']}；artifact {m['artifact_size_bytes']} bytes；native context {m['native_context_length']}，experimental 8192。",
            f"- Runtime log GPU offload layers：{placement[model]['GPU_layers']}；CPU threads：{placement[model]['CPU_threads']}；batch size：{placement[model]['batch_size']}。",
            '- Ollama API allocation、GPU device usage、host RAM 記錄各自保留；不推測 CPU allocation bytes。',''])
        digest['models'][model]=dict(artifact=m,placement=placement[model],cold={k:cold[model][k] for k in ('model_load_seconds','ttft_any','ttft','latency')},
            warm_ttft=ttft[model],TPS=tps[model],latency=lat[model],reliability=rel[model],
            context_ratios=context[model]['long_short_ratios'],run_stability={k:v for k,v in stable[model].items() if k!='runs'},
            run_IFR=[r['IFR']['final_IFR'] for r in stable[model]['runs']],behavior=behavior[model]['behavior'])
    lines+=['原有 native defaults 的 prompt batch size 不同：Gemma／DeepSeek 8B=512；Qwen／DeepSeek 7B=1024；全部8 threads。沒有人工 tuning；本輪比較這些已記錄的 default-runtime behavior，不宣稱固定 batch 下的 isolation。','',
        '## Model-cold（3 repetitions／model）','',
        'Cold 為 Ollama model-unloaded，保留 OS filesystem cache，不是 OS cold boot。Parent-only PDH counter 不能代表 runner；另存 cold_gpu_release_audit.json，以 PS absence＋既有64 MiB background-memory proxy 核對，12筆全部支持卸載。','']
    lines+=table(['Model','Load mean／median s','TTFT-any median s','TTFT-final median s','Total median s'],
        [[m,number(cold[m]['model_load_seconds']['mean'])+' / '+number(cold[m]['model_load_seconds']['median']),number(cold[m]['ttft_any']['median']),number(cold[m]['ttft']['median']),number(cold[m]['latency']['median'])] for m in MODELS])
    lines+=['## Warm TTFT／TPS／latency','',
        '每模型180筆；TTFT 是 final attempt，retry-inclusive TTFT 另存。Latency 表採 retry-inclusive total。DeepSeek runtime TPS 包含 native reasoning，visible TPS 無法可靠分離，保留 null。Gemma／Qwen visible TPS 為 content-channel JSON output，非只計 answer 欄位。','']
    lines+=table(['Model','Any median s','Final mean／median／p95 s','Runtime TPS mean／median','Visible TPS median','Latency mean／median／p95／max s'],
        [[m,number(ttft[m]['any']['median']), ' / '.join(number(ttft[m]['final_answer'][k]) for k in ('mean','median','p95')),
          ' / '.join(number(tps[m]['runtime'][k]) for k in ('mean','median')),number(tps[m]['visible_answer']['median']),
          ' / '.join(number(lat[m]['latency'][k]) for k in ('mean','median','p95','max'))] for m in MODELS])
    lines+=['## Context length 與三輪穩定性','']
    lines+=table(['Model','Short／Medium／Long median final TTFT s','Short／Medium／Long median latency s','Long／Short TTFT ratio','Latency ratio','TPS ratio'],
        [[m,' / '.join(number(context[m][b]['ttft']['median']) for b in ('short','medium','long')),
          ' / '.join(number(context[m][b]['latency']['median']) for b in ('short','medium','long')),
          *[number(context[m]['long_short_ratios'][k]) for k in ('long_short_median_TTFT_ratio','long_short_median_latency_ratio','long_short_median_TPS_ratio')]] for m in MODELS])
    lines+=table(['Model','TTFT run-median CV','TPS CV','Latency CV','IFR round 1／2／3'],
        [[m,*[percent(stable[m][k]) for k in ('TTFT_run_median_CV','TPS_run_median_CV','latency_run_median_CV')],
          ' / '.join(percent(r['IFR']['final_IFR']) for r in stable[m]['runs'])] for m in MODELS])
    lines+=['## Memory／power／thermal','',
        '下表是 whole-system RAM／whole-GPU dedicated memory 與 RTX adapter shared memory 的2秒 sampled peak，包含背景工作；不是 model-process private footprint。Shared capacity 約15.9 GiB 是 RAM-backed capacity，不能加進 dedicated VRAM。',
        'Ollama parent working sets 已保存，但 llama-server.exe 未被 process filter 涵蓋，runner-specific RAM／VRAM peak 為 null。GPU board power、whole-system power、energy unavailable；沒有估算。Thermal throttling 無可靠直接證據，flag=null。','']
    lines+=table(['Model','System RAM peak GiB','Dedicated VRAM peak GiB','Shared GPU peak GiB','GPU temp peak °C'],
        [[r['model'],gib(r['RAM_sampled_peak_bytes']),gib(r['dedicated_VRAM_sampled_peak_bytes']),gib(r['shared_GPU_sampled_peak_bytes']),number(r['GPU_temperature_peak_C'])] for r in matrix])
    lines+=['## IFR／structured-output reliability','',
        'IFR=final failed formal requests／180；retry 成功不算 final failure。OOM／runtime crash／timeout／context capacity failure：本輪未觀察到。Parser／schema errors 不作 Retrieval failure。','']
    lines+=table(['Model','First-pass JSON／schema','Final schema／citation parse','Retry／success','Final IFR','Strict citation validity','Completion truncation'],
        [[m,percent(rel[m]['first_pass_JSON_valid_rate'])+' / '+percent(rel[m]['first_pass_schema_validity']),
          percent(rel[m]['final_schema_validity'])+' / '+percent(rel[m]['citation_parse_rate']),str(rel[m]['retry_trigger'])+' / '+str(rel[m]['retry_success']),
          percent(next(r['final_IFR'] for r in matrix if r['model']==m)),percent(rel[m]['strict_citation_validity']),rel[m]['completion_truncation']] for m in MODELS])
    lines+=['Input truncation（沿用既有 context budget audit）：'+ '；'.join(f"{m} confirmed={rel[m]['input_truncation']}、unknown={rel[m]['input_truncation_unknown']}" for m in MODELS)+'。Unknown context IDs 詳見 reliability.json。','',
        '## Sustained-load','',
        '只執行 Gemma／Qwen；DeepSeek 診斷候選依預先規則排除。Requests 按 start time 分區，hardware samples 按實際 timestamp 分區；最後一筆可在30分鐘後完成，不延長六個固定 sensor windows。','']
    for m in ('gemma2:9b','qwen2.5-coder:7b'):
        s=sustained[m];digest['models'][m]['sustained']={k:v for k,v in s.items() if k not in ('intervals','overall')}
        lines.extend([f"### {m}",'',
            f"- Requests {s['completion']['requests']}；duration {number(s['completion']['actual_seconds'])} s；IFR {percent(s['overall']['IFR']['final_IFR'])}。",
            f"- Temperature start／end／peak：{number(s['start_temperature_C'])} / {number(s['end_temperature_C'])} / {number(s['peak_temperature_C'])} °C。",
            f"- TPS last／first median ratio {number(s['TPS_last_first_ratio'])}；TTFT median drift {number(s['TTFT_median_drift_seconds'])} s；latency median drift {number(s['latency_median_drift_seconds'])} s。",
            f"- RAM median growth {gib(s['RAM_median_growth_bytes'])} GiB；VRAM median growth {gib(s['VRAM_median_growth_bytes'])} GiB。",
            '- 區段題目組成不同，不能將這些 drift 直接解讀為 thermal throttling 或 memory leak。',''])
    lines+=['## Phase 17 behavior preservation','']
    lines+=table(['Model','Status agreement','Schema agreement','Citation-set exact','Mean normalized answer similarity'],
        [[m,percent(behavior[m]['behavior']['status_agreement']),percent(behavior[m]['behavior']['schema_agreement']),percent(behavior[m]['behavior']['citation_set_exact']),number(behavior[m]['behavior']['normalized_answer_similarity']['mean'])] for m in MODELS])
    lines+=['不是 correctness／human validation。Silver token F1、required citation recall、calculation numeric results 保存在 behavior_preservation.json；Silver reference 由 Gemma 產生，可能存在 alignment bias。','',
        '## Paired performance bootstrap','',
        '每題先取三輪 median；10,000 iterations，seed 19019；下列 difference=second−first，單位秒。Latency 包含失敗與 retry；無法量到 final-content TTFT 的題目明確留在 missing 記錄，配對 TTFT 為57或60題。','']
    lines+=table(['Pair','Metric','n','Mean difference','95% CI'],
        [[pair,metric,v['n_paired'],number(v['mean_difference']),'['+', '.join(number(x) for x in v['CI95'])+']']
         for pair,metrics in digest['paired_performance'].items() for metric,v in metrics.items()])
    lines+=['## Hardware／quality deployment matrix','']
    lines+=table(['Model','Hardware status','Frozen quality status'],[[r['model'],r['hardware_status'],r['quality_status']] for r in matrix])
    lines.extend([f"Performance-axis Pareto non-dominated：{pareto['performance_only']['non_dominated']}。只描述已量測硬體軸；不代表品質勝者。Qwen judge conflict／quality unresolved 仍保留。",'',
        '## Protocol／measurement limitations','',
        f"- 共有 {len(validation['start_condition_protocol_deviations'])} 次起跑未達連續60秒 GPU利用率<5%（warm 5次、Gemma sustained 1次）；等待滿300秒後繼續，environment_start_protocol_complete=false。",
        '- Qwen warm round 3 起跑46°C；其餘已記錄溫度與等待過程，不更改 threshold。',
        '- Gemma warm round 1 在第38題後因 Windows report-file share lock 中斷，保留 resident model，約228.6秒後續跑；沒有重跑已完成題目。',
        '- Parent-process memory coverage 不完整，cold release 以另存的 device-memory proxy 補充；不用 parent counter 的0假稱 runner footprint。',
        '- Localized OS edition／power-plan文字有 decode replacement；原始 capture 保持不變，OS版本/build與power-plan GUID可用。',
        '- Windows policy可能阻擋reranker c10_cuda.dll；本階段未呼叫reranker，不影響既有 E4 metrics。','',
        '## Tests／compatibility／next stage','',
        f"- Unittest {tests['tests']}：{tests['tests']-tests['skipped']} passed，{tests['skipped']}既有optional runtime skipped；return_code={tests['return_code']}。",
        f"- {compat['protected_count']} protected files：changed={len(compat['changed'])}；Production Streamlit HTTP {compat['production_Streamlit_HTTP']}。",
        f"- rag_store.sqlite3：size={compat['sqlite_after']['size']}，mtime_ns={compat['sqlite_after']['mtime_ns']}，SHA-256=`{compat['sqlite_after']['sha256']}`；全部與執行前一致。",
        '- Corpus、Silver、E1-E4、Phase15-18.1 immutable；沒有RAGAS、Retrieval重跑、模型下載、Prompt／quantization tuning或production migration。',
        '- Phase19B值得規劃：優先Gemma／Qwen，先補足runner memory telemetry、控制背景負載與解決reranker Windows runtime限制，分開量Retrieval／reranking／Generation。尚未執行。',
        '- Phase20 ready=false：generator-only feasibility不足以證明full-RAG edge performance與最終品質選型。',''])
    (OUT/'phase19A_summary.md').write_text('\n'.join(lines),encoding='utf-8')
    write(OUT/'report_digest.json',digest)
    return digest
