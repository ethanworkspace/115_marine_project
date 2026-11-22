"""Read-only Excel reopen, cached formula checks, source/key integrity."""
from pathlib import Path
import json,sys,zipfile,math,hashlib
import openpyxl
W=Path(__file__).resolve().parent
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def main():
 p=W/'fish_test_final_fixed_denominator_evaluation.xlsx';before=sha(p)
 with zipfile.ZipFile(p) as z:
  assert z.testzip() is None;chart_n=len([n for n in z.namelist() if '/charts/chart' in n and n.endswith('.xml')]);assert chart_n==2
 f=openpyxl.load_workbook(p,read_only=True,data_only=False);v=openpyxl.load_workbook(p,read_only=True,data_only=True)
 # Artifact export omits the optional worksheet dimension element.
 # Read the actual XML cells before asserting the real row boundaries.
 for book in (f,v):
  for sheet in book:
   sheet.calculate_dimension(force=True)
 m=json.loads((W/'evaluation_metrics_11.json').read_text(encoding='utf-8'));b=json.loads((W/'workbook_build_validation.json').read_text(encoding='utf-8'));assert f.sheetnames==b['sheets'] and len(f.sheetnames)==18
 assert f['Per_Question'].max_row==725 and f['Raw_Generation'].max_row==725;keys=[(r[0],r[1]) for r in v['Per_Question'].iter_rows(min_row=6,max_row=725,max_col=2,values_only=True)];assert len(keys)==len(set(keys))==720
 checks=[]
 for i,(mid,x) in enumerate(m['models'].items(),6):
  expected={'B':180,'C':x['fixed_rates']['raw_schema_valid']['numerator'],'D':x['fixed_rates']['raw_schema_valid']['rate'],'I':x['professional']['model']['source50']['fixed_validated_task_success']['numerator'],'J':x['professional']['model']['source50']['fixed_validated_task_success']['rate'],'K':x['professional']['model']['logical']['fixed_validated_task_success']['numerator'],'M':x['professional']['model']['arithmetic']['fixed_validated_task_success']['numerator']}
  for col,value in expected.items():
   actual=v['Fixed_Denominators'][f'{col}{i}'].value;assert isinstance(f['Fixed_Denominators'][f'{col}{i}'].value,str) and f['Fixed_Denominators'][f'{col}{i}'].value.startswith('=');assert isinstance(actual,(int,float)) and abs(actual-value)<1e-9,(mid,col,actual,value);checks.append({'sheet':'Fixed_Denominators','cell':f'{col}{i}','actual':actual,'expected':value})
  assert v['Dashboard'][f'A{i}'].value==mid
  assert abs(v['Dashboard'][f'B{i}'].value-x['professional']['model']['source50']['fixed_validated_task_success']['rate'])<1e-9
 order=['faithfulness','judge_answer_relevance','bge_cosine','raw_schema_valid','ttft_seconds','tps','system_ram_peak_gib','dedicated_vram_peak_gib','p5','logical','arithmetic']
 for i,(mid,x) in enumerate(m['models'].items()):
  for j,key in enumerate(order):
   r=6+i*11+j;actual=v['Metrics_11'][f'C{r}'].value;an=v['Metrics_11'][f'D{r}'].value
   if key in x['metrics']:expected=x['metrics'][key]['mean'];n=x['metrics'][key]['n']
   elif key=='raw_schema_valid':expected=x['fixed_rates'][key]['rate'];n=180
   elif key=='p5':expected=m['shared_context_precision']['mean'];n=m['shared_context_precision']['n']
   else:expected=x['professional']['model'][key]['conditional_accuracy'];n=x['professional']['model'][key]['conditional_n']
   assert an==n,(mid,key,'N',an,n)
   if expected is None:assert actual in (None,'n.a.')
   else:assert isinstance(actual,(int,float)) and abs(actual-expected)<1e-8,(mid,key,actual,expected)
 errors=[];formulas=0
 for s in f:
  for row in s.iter_rows():
   for c in row:
    if c.data_type=='f':formulas+=1
 for s in v:
  for row in s.iter_rows():
   for c in row:
    if c.data_type=='e':errors.append([s.title,c.coordinate,c.value])
 assert not errors,errors
 f.close();v.close();assert sha(p)==before
 (W/'excel_reopen_validation.json').write_text(json.dumps({'passed':True,'read_only_reopen':True,'file_sha256':before,'sheets':b['sheets'],'source_rows':720,'unique_keys':720,'cached_metrics_checked':44,'fixed_denominator_checks':checks,'formula_cells':formulas,'formula_errors':errors,'native_charts':chart_n,'authoring_engine':'artifact-tool','reopen_engine':'openpyxl read_only; no write or native Excel application claim','file_unchanged_by_reopen':True},ensure_ascii=False,indent=2),encoding='utf-8')
 print('Excel reopened;720keys;44metrics+N; all fixed rates;2charts; cached formulas verified')
if __name__=='__main__':main()
