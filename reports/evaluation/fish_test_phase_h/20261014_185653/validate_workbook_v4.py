from __future__ import annotations
import collections, json, pathlib, zipfile
from openpyxl import load_workbook

out=pathlib.Path('reports/evaluation/fish_test_phase_h/20261014_185653')
path=out/'fish_test_evaluation_results_v4.xlsx'
payload=json.loads((out/'workbook_payload_v4.json').read_text(encoding='utf-8-sig'))
expected={s['name']:len(s['rows']) for s in payload['sheets']}
required={'Dashboard','Model_Comparison','Existing_Metrics','Context_Precision','Context_Annotation_QA','Reference_Verification','Arithmetic_Accuracy','Arithmetic_Diagnostic','Logical_Accuracy','Species_Comparison','Category_Comparison','Paired_Comparison','Source_Provenance','Annotation_Errors','Limitations'}
wb=load_workbook(path,data_only=False,read_only=False)
names=wb.sheetnames
counts={s:wb[s].max_row-1 for s in names}
formula_cells=[]
for row in range(2,wb['Context_Precision'].max_row+1):
    val=wb['Context_Precision'][f'S{row}'].value
    if isinstance(val,str) and val.startswith('='): formula_cells.append(val)
context_status=collections.Counter(wb['Context_Annotation_QA'].cell(r,26).value for r in range(2,wb['Context_Annotation_QA'].max_row+1))
p_values=[wb['Context_Precision'].cell(r,13).value for r in range(2,wb['Context_Precision'].max_row+1)]
formula_check_values=[wb['Context_Precision'].cell(r,19).value for r in range(2,wb['Context_Precision'].max_row+1)]
chart_count=len(wb['Dashboard']._charts)
tables={s:len(wb[s].tables) for s in names}
checks={
 'file_exists':path.exists(),'xlsx_zip_valid':zipfile.is_zipfile(path),
 'required_sheets_present':required.issubset(set(names)),'sheet_names':names,'sheet_data_row_counts':counts,
 'expected_row_counts_match':all(counts.get(k)==v for k,v in expected.items()),
 'questions_180_unique':counts.get('Questions')==180 and len({wb['Questions'].cell(r,1).value for r in range(2,182)})==180,
 'generation_rows_720':counts.get('Raw_Generation_Index')==720,'existing_metric_rows_720':counts.get('Existing_Metrics')==720,
 'retrieval_questions_180':counts.get('Retrieval')==180,'context_rows_900':counts.get('Context_Annotation_QA')==900,
 'context_precision_rows_180':counts.get('Context_Precision')==180,
 'source_reference_rows_180':counts.get('Reference_Verification')==180 and counts.get('Source_Provenance')==180,
 'context_status_counts':dict(context_status),'context_p5_values_all_na':all(x is None for x in p_values),
 'context_formula_check_count':len(formula_cells),'context_formula_check_all_na_cache':all(x is None for x in formula_check_values),
 'chart_count_dashboard':chart_count,'tables_by_sheet':tables,
 'no_total_or_winner_policy':'Dashboard lists composite/winner as N/A; scoring policy remains unconfirmed'
}
checks['validation_passed']=all([checks['file_exists'],checks['xlsx_zip_valid'],checks['required_sheets_present'],checks['expected_row_counts_match'],checks['questions_180_unique'],checks['generation_rows_720'],checks['context_rows_900'],checks['context_precision_rows_180'],checks['source_reference_rows_180'],checks['context_p5_values_all_na'],checks['context_formula_check_count']==180,checks['chart_count_dashboard']==1])
(out/'evaluation_v4_validation.json').write_text(json.dumps(checks,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'validation_passed':checks['validation_passed'],'sheets':len(names),'rows':counts,'context_status_counts':dict(context_status),'formula_count':len(formula_cells),'charts':chart_count},ensure_ascii=False))
