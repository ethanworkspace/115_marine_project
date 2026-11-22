"""Finalize an auditable selection record without changing evaluation results."""
import datetime
import hashlib
import json
from pathlib import Path

directory = Path(__file__).resolve().parent
root = directory.parents[2]
selection = json.loads((directory/'weighted_model_selection.json').read_text(encoding='utf-8'))
validation = json.loads((directory/'weighted_workbook_validation.json').read_text(encoding='utf-8'))
manifest = json.loads((directory/'weighted_selection_artifact_manifest.json').read_text(encoding='utf-8'))

def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()

assert validation['status'] == 'PASS'
for item in manifest['artifacts']:
    assert digest(item['path']) == item['sha256'], item['path']
for item in selection['inputs']:
    assert digest(item['path']) == item['sha256'], item['path']
assert selection['primary']['winner'] == 'M2'
assert validation['ranking'][0]['model_id'] == 'M2'

record_id = directory.name
record_path = directory/'result_record.json'
if record_path.exists():
    record = json.loads(record_path.read_text(encoding='utf-8'))
    assert record['record_id'] == record_id
else:
    names = {'M1':'DeepSeek-R1-Distill-Qwen-7B','M2':'Qwen2.5-Coder-7B-Instruct',
             'M3':'DeepSeek-R1-Distill-Llama-8B','M4':'Gemma2-9B-It'}
    rankings = [dict(row, model_name=names[row['model_id']]) for row in selection['primary']['ranking']]
    key_files = ['weighted_model_selection.json','weighted_scoring_policy.json',
                 'weighted_input_manifest.json','weighted_model_selection_report.md',
                 'weighted_model_selection.xlsx','weighted_workbook_validation.json',
                 'weighted_selection_artifact_manifest.json']
    record = {
        'record_id':record_id,
        'recorded_at':datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).isoformat(),
        'status':'RECORDED_EXPLORATORY_MODEL_SELECTION',
        'source_evaluation_run':selection['source_run'],
        'completed_original_inference_count':720,
        'inference_count_by_model':{'M1':180,'M2':180,'M3':180,'M4':180},
        'owner_weighting_decision':{
            'quality':0.70,'performance':0.30,'status':'USER_CONFIRMED',
            'user_reply':'沿用品質70%、效能30%（建議）',
            'scope':'Parent 70/30 weights confirmed; subweights and normalization are disclosed selection assumptions.'
        },
        'ranking':rankings,
        'recommended_primary_deployment_model':'M2',
        'recommendation_scope':'This evaluated cohort, machine and disclosed 70/30 policy; no automatic deployment.',
        'policy':selection['policy'],
        'sensitivity_checks':[
            {'variant':variant['variant'],'top_model':variant['winner']}
            for variant in selection['sensitivity']
        ],
        'human_gold_count':0,
        'limitations':[
            'Post-evaluation exploratory selection; not an originally preregistered thesis composite.',
            'Composite points are not a percentage of professionally correct answers.',
            '50 source-qualified tasks depend on 10 source groups and 3 original files.',
            'RAM and VRAM are sampled system/device peaks, not model-process-exclusive measurements.',
            'Program-validated task success and source-content accuracy differ; the content-only sensitivity is retained.',
            '636 protected files were not rehashed in this record-only step; prior run verification is not relabeled as new verification.'
        ],
        'artifact_verification':'Existing artifact hashes and scoring-input hashes rechecked successfully.',
        'artifacts':[{'path':str(directory/name),'sha256':digest(directory/name)} for name in key_files],
        'new_inference_executed':False,'historical_results_overwritten':False,
        'corpus_modified':False,'production_modified':False,'production_switched':False
    }
    record_path.write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')

log_path = root/'reports/evaluation/model_selection_results_log.jsonl'
existing = [json.loads(line) for line in log_path.read_text(encoding='utf-8').splitlines() if line.strip()] if log_path.exists() else []
entry = {
    'record_id':record_id,'recorded_at':record['recorded_at'],'record_path':str(record_path),
    'record_sha256':digest(record_path),'source_run':selection['source_run'],
    'quality_weight':0.7,'performance_weight':0.3,
    'top_model':'M2','total_out_of_100':selection['primary']['ranking'][0]['total_out_of_100'],
    'status':record['status'],'human_gold_count':0
}
matches = [row for row in existing if row['record_id'] == record_id]
if matches:
    assert matches == [entry]
else:
    with log_path.open('a',encoding='utf-8',newline='\n') as stream:
        stream.write(json.dumps(entry,ensure_ascii=False)+'\n')
assert json.loads(record_path.read_text(encoding='utf-8'))['ranking'][0]['model_id'] == 'M2'
assert sum(json.loads(line)['record_id']==record_id for line in log_path.read_text(encoding='utf-8').splitlines() if line.strip()) == 1
print(json.dumps({'status':'RECORDED','record':str(record_path),'log':str(log_path),'top_model':'M2','score':entry['total_out_of_100']},ensure_ascii=False))
