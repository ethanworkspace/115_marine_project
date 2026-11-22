"""Read-only checks of the exported workbook and immutable scoring inputs."""
import datetime
import hashlib
import json
import math
from pathlib import Path
from zipfile import ZipFile
import openpyxl

OUT = Path(__file__).resolve().parent
data = json.loads((OUT / 'weighted_model_selection.json').read_text(encoding='utf-8'))
workbook_path = OUT / 'weighted_model_selection.xlsx'
formula_book = openpyxl.load_workbook(workbook_path, data_only=False)
value_book = openpyxl.load_workbook(workbook_path, data_only=True)
assert formula_book.sheetnames == ['Model_Ranking','Scoring_Detail','Policy_Sensitivity']
with ZipFile(workbook_path) as archive:
    assert archive.testzip() is None

def close(actual, expected):
    assert isinstance(actual, (int, float)) and math.isclose(actual, expected, abs_tol=1e-8), (actual, expected)

detail = value_book['Scoring_Detail']
assert detail.max_row == 48
keys = set()
for row in range(5, 49):
    metric_name, group, weight, model_id, raw_value, valid_n, direction, mode, score, points, scope = [detail.cell(row,c).value for c in range(1,12)]
    original = next(r for r in data['primary']['metric_contributions'] if r['model_id'] == model_id and r['metric'] == metric_name)
    keys.add((model_id, original['metric_id']))
    close(weight, original['weight'])
    close(raw_value, original['raw_value'])
    close(valid_n, original['valid_n'])
    close(score, original['normalized_score'])
    close(points, original['weighted_points'])
    close(points, 100*weight*score)
    assert 0 <= score <= 1
    assert formula_book['Scoring_Detail'].cell(row,9).data_type == 'f'
    assert formula_book['Scoring_Detail'].cell(row,10).data_type == 'f'
assert len(keys) == 44
ranking = []
for row, expected in zip(range(5,9), data['primary']['ranking']):
    values = [value_book['Model_Ranking'].cell(row,c).value for c in range(1,8)]
    assert values[0] == expected['rank'] and values[1] == expected['model_id']
    close(values[3], expected['quality_points_out_of_70'])
    close(values[4], expected['performance_points_out_of_30'])
    close(values[5], expected['total_out_of_100'])
    close(values[6], 1)
    contributions = [r for r in data['primary']['metric_contributions'] if r['model_id']==values[1]]
    close(sum(r['weight'] for r in contributions if r['group']=='quality'), .7)
    close(sum(r['weight'] for r in contributions if r['group']=='performance'), .3)
    ranking.append({'rank':values[0], 'model_id':values[1], 'total':values[5]})
assert ranking[0]['model_id'] == 'M2'
for row, variant in zip(range(5,9), [data['primary'], *data['sensitivity']]):
    for col, model in enumerate(['M1','M2','M3','M4'],2):
        close(value_book['Policy_Sensitivity'].cell(row,col).value, next(r['total_out_of_100'] for r in variant['ranking'] if r['model_id']==model))
    assert value_book['Policy_Sensitivity'].cell(row,6).value == variant['winner']
errors = [{'sheet':s.title,'cell':cell.coordinate,'value':cell.value} for s in value_book for row in s for cell in row if cell.data_type=='e']
assert not errors, errors
formula_count = sum(cell.data_type=='f' for s in formula_book for row in s for cell in row)
chart_count = sum(len(s._charts) for s in formula_book)
assert formula_count == 108 and chart_count == 1

def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()

input_checks = []
for record in data['inputs']:
    actual = sha(record['path'])
    assert actual == record['sha256'], record['path']
    input_checks.append({'path':record['path'],'sha256':actual,'unchanged':True})
original_excel = Path(data['inputs'][0]['path']).parent/'rag_v6_evaluation_results.xlsx'
assert sha(original_excel) == '1adb1fc2bdfb725086d9d059559d2279d778efcd345f7e8a0daf6ad94ff30240'
report = {
    'validated_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'status':'PASS','sheets':formula_book.sheetnames,'contribution_rows':44,
    'formula_count':formula_count,'chart_count':chart_count,'excel_error_cells':errors,
    'reopened_with_openpyxl':True,'cached_results_match_source_json':True,
    'zip_integrity':'PASS','weights_sum':1,'quality_weight':.7,'performance_weight':.3,
    'ranking':ranking,'visual_previews_reviewed':True,
    'scoring_inputs_unchanged':input_checks,'historical_excel_unchanged':True,
    'new_inference':False,'production_switch':False,
    'frozen_636_full_rehash_this_weighted_reporting_step':False,
    'scope':'New derived selection files only; prior frozen verification remains recorded in original run.'
}
(OUT/'weighted_workbook_validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
artifacts = [{'path':str(p),'bytes':p.stat().st_size,'sha256':sha(p)} for p in sorted(OUT.iterdir()) if p.is_file() and p.name!='weighted_selection_artifact_manifest.json']
(OUT/'weighted_selection_artifact_manifest.json').write_text(json.dumps({'artifacts':artifacts,'no_historical_overwrite':True},ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'status':'PASS','formulas':formula_count,'chart_count':chart_count,'winner':ranking[0],'inputs_unchanged':len(input_checks)},ensure_ascii=False))
