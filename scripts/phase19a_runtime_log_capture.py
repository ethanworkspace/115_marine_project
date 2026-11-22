"""Extract read-only Ollama placement/settings observations for this physical run."""
import datetime,json,re,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from src.evaluation.edge.execution19a import OUT,write
def main():
    target=json.loads((OUT/'target_device_manifest.json').read_text(encoding='utf-8'))['target']
    begin=json.loads((OUT/'execution_start.json').read_text(encoding='utf-8'))['timestamp']
    log=Path(target['runtime']['log_path']);models={}
    for p in (OUT/'model_manifests').glob('*.json'):
        m=json.loads(p.read_text(encoding='utf-8'))
        for layer in m.get('artifact_layers',[]):
            if layer['mediaType'].endswith('.model'):models[layer['digest'].replace(':','-')]=m['name']
    current_time=None;model=None;rows=[]
    with log.open(encoding='utf-8',errors='replace') as f:
        for line in f:
            stamp=re.search(r'time=(\d{4}-\d\d-\d\dT[^ ]+)',line)
            if stamp:
                try:current_time=datetime.datetime.fromisoformat(stamp[1].strip('"')).timestamp()
                except ValueError:pass
            if current_time is None or current_time<begin:continue
            if 'starting' in line and ('--model' in line or 'model=' in line):
                model=next((name for sha,name in models.items() if sha in line),None)
            if any(term in line for term in ('starting llama','offload','offloaded','n_batch','n_threads','CPU_Mapped model buffer','CUDA0 model buffer','--batch-size','--threads')):
                rows.append(dict(timestamp=current_time,model=model,raw_line=line.rstrip(),
                    model_binding='exact artifact blob path in runner-start command' if model else 'unresolved; not guessed'))
    write(OUT/'runtime_placement_log_observations.json',dict(source=str(log),start_timestamp=begin,
        observations=rows,raw_logs_not_modified=True,settings_observed_only=True))
    print('Placement log observations:',len(rows))
if __name__=='__main__':main()
