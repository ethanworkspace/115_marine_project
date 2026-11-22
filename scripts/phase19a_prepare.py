"""Freeze prior artifacts, attest the user-selected workstation, no model execution."""
import json
import platform
import sys
from pathlib import Path
import requests
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from src.evaluation.edge.hardware19a import gpu_sample,validate_identity,Sensors
from src.evaluation.edge.inputs import BUNDLE,load_bundle,validate_target_schema
from src.evaluation.edge.core import MODELS,OPTIONS,target_gate,schedule
from src.evaluation.edge.runtime import OllamaEdge
from src.evaluation.generation.frozen import sha256_file,validate_frozen_inputs

OUT=ROOT/'reports/evaluation/edge/phase19A'
def write(name,data):
    p=OUT/name;p.parent.mkdir(parents=True,exist_ok=True)
    text=json.dumps(data,ensure_ascii=False,indent=2)+'\n'
    if p.exists() and p.read_text(encoding='utf-8')!=text:raise RuntimeError('Refusing to overwrite '+str(p))
    p.write_text(text,encoding='utf-8')

def main():
    before_path=OUT/'protected_before.json'
    if not before_path.exists():
        prior=json.loads((ROOT/'reports/evaluation/edge/phase19/protected_before.json').read_text())
        for folder in ('reports/evaluation/edge/phase19','data/evaluation/edge/phase19_inputs_v1','src/evaluation/edge'):
            for p in (ROOT/folder).rglob('*'):
                if p.is_file() and '__pycache__' not in p.parts and not p.name.endswith('19a.py'):
                    s=p.stat();prior[p.relative_to(ROOT).as_posix()]=dict(sha256=sha256_file(p),size=s.st_size,mtime_ns=s.st_mtime_ns)
        write('protected_before.json',prior)
    before=json.loads(before_path.read_text())
    changed=[n for n,r in before.items() if not (ROOT/n).is_file() or sha256_file(ROOT/n)!=r['sha256']]
    if changed:raise RuntimeError('Earlier artifact mismatch: '+str(changed[:8]))
    capture=json.loads((OUT/'hardware_readonly_capture.json').read_text(encoding='utf-8-sig'))
    gpu=gpu_sample();version=requests.get('http://127.0.0.1:11434/api/version',timeout=10).json()['version']
    matched=validate_identity(capture,gpu,version)
    target=json.loads((ROOT/'configs/edge_target_device.yaml').read_text())
    write('previous_pending_target.json',target)
    target.update(target_device_confirmed=True,device_name='marine-edge-workstation-01',device_id='marine-edge-workstation-01',execution_node=platform.node())
    target['CPU'].update(name=capture['CPU']['Name'],cores=10,threads=16,base_clock_GHz=2.5)
    target['GPU'].update(available=True,name=gpu['name'],driver_version=capture['GPU']['DriverVersion'],
        driver_date=capture['GPU']['DriverDate'],device_index=0,nvidia_driver_version=gpu['driver_version'])
    target['NPU'].update(available=False,name=None,runtime=None,verification='User-designated none; i5-14400F has no specified NPU')
    target['RAM'].update(bytes=32*1024**3,memory_type='DDR4',speed_MT_s=3200,OS_usable_bytes=capture['computer']['TotalPhysicalMemory'])
    target['VRAM']['bytes']=gpu['dedicated_total_bytes'];target['unified_memory']['bytes']=None
    target['shared_GPU_memory']={'capacity_GiB_approx':15.9,'capacity_source':'user Windows display','measured_capacity_bytes':None,
        'scope':'system RAM-backed WDDM shared GPU memory, not dedicated VRAM or a unified pool'}
    target['OS'].update(name=capture['OS']['Caption'],version=capture['OS']['Version'],build=capture['OS']['BuildNumber'])
    target['runtime'].update(name='Ollama',version=version,endpoint='http://127.0.0.1:11434',log_path=str(Path.home()/'AppData/Local/Ollama/server.log'))
    disk=next(d for d in capture['storage'] if d['BusType']=='NVMe')
    target['storage'].update(device='NVMe SSD: '+disk['FriendlyName'],capacity_bytes=disk['Size'],free_bytes=None)
    target['power_measurement'].update(available=gpu['gpu_board_power_watts'] is not None,sensor='nvidia-smi' if gpu['gpu_board_power_watts'] is not None else None,
        scope='GPU_board' if gpu['gpu_board_power_watts'] is not None else None)
    target['thermal_measurement'].update(available=gpu['temperature_c'] is not None,sensor='nvidia-smi',scope='GPU_sensor')
    target['runtime_settings']['power_mode']=capture['power_plan'];target['_notes']='User-designated local edge inference workstation; not embedded/Jetson. Existing runtime defaults, no tuning.'
    if validate_target_schema(target):raise RuntimeError(validate_target_schema(target))
    gate=target_gate(target)
    if not gate['edge_execution_ready']:raise RuntimeError(gate)
    adapter=OllamaEdge(target)
    models={m:json.loads((ROOT/'reports/evaluation/edge/phase19/model_manifests'/(m.replace(':','_')+'.json')).read_text()) for m in MODELS}
    actual=adapter.preflight(models)
    rows,bundle=load_bundle();frozen=validate_frozen_inputs(ROOT)
    if bundle['parent_frozen_hashes']!=frozen['hashes']:raise RuntimeError('Frozen parent checksum mismatch')
    sensors=Sensors();sample=sensors.sample();sensors.close()
    # The explicitly requested target config is the only existing configuration updated.
    (ROOT/'configs/edge_target_device.yaml').write_text(json.dumps(target,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    write('target_device_manifest.json',{'target':target,'gate':gate,'identity_validation':matched})
    write('environment_baseline.json',{'hardware_capture':capture,'gpu_preflight':gpu,'sensor_preflight':sample,
        'sensor_errors':sensors.errors,'gpu_power_available':gpu['gpu_board_power_watts'] is not None,
        'GPU_power_semantics':'GPU board power only; N/A stays null','edge_execution_ready':True})
    for m in MODELS:write('model_manifests/'+m.replace(':','_')+'.json',{**models[m],'target_runtime_identity':actual[m],'availability_on_target':'available_exact_digest'})
    write('experiment_manifest.json',dict(experiment_id='phase19A_local_edge_generator_v1',status='inputs_frozen_execution_pending',
        target_device='marine-edge-workstation-01',edge_execution_ready=True,benchmark_scope='generator_only',
        acceptance_thresholds_defined=False,models=list(MODELS),quality_status_frozen=True,generation_options=OPTIONS,
        prompt_sha256=sha256_file(BUNDLE/'generation_v2.txt'),schema_sha256=sha256_file(BUNDLE/'generation_output_v2.schema.json'),
        protocol='v2.2',maximum_attempts=2,question_ids=bundle['question_ids'],input_bundle=bundle,
        question_count=60,context_count=300,model_order=schedule(),cold_repetitions=3,warm_repetitions=3,
        formal_requests_per_model=180,formal_requests_total=720,cold_definition='Ollama model-unloaded, GPU model allocation released; OS filesystem cache retained',
        thermal_start={'GPU_utilization_below_percent':5,'continuous_idle_seconds':60,'preferred_temperature_max_C':45,'maximum_wait_seconds':300},
        sustained={'models':['gemma2:9b','qwen2.5-coder:7b'],'seconds_per_model':1800,'interval_seconds':300,'question_order':'frozen 60 cyclic'},
        bootstrap={'iterations':10000,'seed':19019,'unit':'paired question medians of three warm runs'},
        native_reasoning_tokens_never_count_as_final_TTFT=True,no_retrieval_execution=True,no_RAGAS=True,
        runtime_timeout_seconds=900,telemetry_interval_seconds=2.0,human_validated_winner=False,
        git_commit=__import__('subprocess').check_output(['git','rev-parse','HEAD'],text=True).strip(),
        declared_before_benchmark=True))
    print(json.dumps({'edge_execution_ready':True,'questions':len(rows),'contexts':300,'exact_models':list(actual),'power_available':gpu['gpu_board_power_watts'] is not None}))

if __name__=='__main__':main()
