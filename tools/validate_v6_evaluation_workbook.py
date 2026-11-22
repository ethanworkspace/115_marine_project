"""Read-only Excel/JSON reconciliation after export; never authors a workbook."""
import collections,json,math,pathlib,sys,zipfile
ROOT=pathlib.Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tools')]
import evaluate_unified_rag_v6 as ev
import openpyxl

def main():
    w=ev.work();p=w/'rag_v6_evaluation_results.xlsx';formula=openpyxl.load_workbook(p,data_only=False,read_only=False);cached=openpyxl.load_workbook(p,data_only=True,read_only=False)
    expected=['Dashboard','Model_Comparison','Source_QC','Species_Category','Paired_Source_Groups','Per_Question','Accuracy_Detail','Retrieval_P5','Context_Labels','References','Settings_Limitations','Provenance'];assert formula.sheetnames==cached.sheetnames==expected
    metrics=ev.read(w/'evaluation_metrics_11.json');rows=ev.jl(w/'per_question_metrics.jsonl');acc=ev.jl(w/'logical_accuracy_detailed.jsonl')+ev.jl(w/'arithmetic_accuracy_detailed.jsonl');cp=ev.jl(w/'context_precision_detailed.jsonl');checks=[]
    assert formula['Per_Question'].max_row==724 and len({(r[1].value,r[0].value) for r in formula['Per_Question'].iter_rows(min_row=5,max_row=724)})==720
    assert formula['Accuracy_Detail'].max_row==len(acc)+4 and formula['Context_Labels'].max_row==64 and formula['References'].max_row==54
    for sheet in cached:
        for row in sheet:
            for c in row:assert c.data_type!='e',f'Excel error {sheet.title}!{c.coordinate}: {c.value}'
    close=lambda a,b: a in (None,'') and b is None or isinstance(a,(int,float)) and b is not None and math.isclose(a,b,rel_tol=1e-8,abs_tol=1e-10)
    for j,m in enumerate(metrics['models']):
        item=metrics['models'][m];col=3+j*2
        expected_values={5:item['layers']['model']['faithfulness'],6:item['layers']['model']['judge_answer_relevance'],7:item['layers']['model']['bge_m3_cosine'],8:{'mean':item['raw_schema']['rate'],'n':180},9:item['timing_memory']['ttft_seconds'],10:item['timing_memory']['tps'],11:item['timing_memory']['peak_system_ram_gib'],12:item['timing_memory']['peak_dedicated_vram_gib'],13:{'mean':metrics['shared_context_precision']['mean'],'n':12},14:{'mean':item['layers']['model']['logical_accuracy']['conditional_accuracy'],'n':item['layers']['model']['logical_accuracy']['conditional_n']},15:{'mean':item['layers']['model']['arithmetic_accuracy']['conditional_accuracy'],'n':item['layers']['model']['arithmetic_accuracy']['conditional_n']},16:{'mean':item['layers']['model']['source_50_task_success']['rate'],'n':50},17:{'mean':item['layers']['model']['logical_accuracy']['fixed_validated_success']['rate'],'n':37},18:{'mean':item['layers']['model']['arithmetic_accuracy']['fixed_validated_success']['rate'],'n':13},19:{'mean':item['model_validated_answer_rate']['rate'],'n':180},20:{'mean':item['model_declared_gap_rate']['rate'],'n':180},21:item['layers']['system']['faithfulness'],22:item['layers']['system']['judge_answer_relevance'],23:item['layers']['system']['bge_m3_cosine']}
        expected_values.update({24:{'mean':item['layers']['model']['source_50_content_correct_rate']['rate'],'n':50},25:{'mean':item['layers']['model']['logical_accuracy']['fixed_content_success']['rate'],'n':37},26:{'mean':item['layers']['model']['arithmetic_accuracy']['fixed_content_success']['rate'],'n':13}})
        for row,x in expected_values.items():
            actual=cached['Model_Comparison'].cell(row,col).value;n=cached['Model_Comparison'].cell(row,col+1).value;assert close(actual,x['mean']),(m,row,actual,x['mean']);assert n==x['n'],(m,row,n,x['n']);checks.append({'model':m,'cell':cached['Model_Comparison'].cell(row,col).coordinate,'json_value':x['mean'],'excel_value':actual,'n':n})
    qc=ev.read(w/'evaluation_metrics_11_source_qc.json')
    for j,m in enumerate(qc['models']):
        z=qc['models'][m]['layers']['model'];a=z['logical_accuracy'];r0=5+j*4
        expectations=[(a['conditional_accuracy'],a['conditional_n']),(a['fixed_content_success']['rate'],37),(z['source_50_content_correct_rate']['rate'],50),(z['source_50_task_success']['rate'],50)]
        for offset,(value,n) in enumerate(expectations):
            assert close(cached['Source_QC'].cell(r0+offset,8).value,value),(m,offset,'QA score');assert cached['Source_QC'].cell(r0+offset,6).value==n
        assert close(cached['Dashboard'].cell(j+5,4).value,z['source_50_task_success']['rate']);assert close(cached['Dashboard'].cell(j+5,5).value,a['fixed_validated_success']['rate'])
    for i,r in enumerate(rows,5):
        assert cached['Per_Question'].cell(i,2).value==r['question_id'];assert close(cached['Per_Question'].cell(i,11).value,r['model_faithfulness']);assert close(cached['Per_Question'].cell(i,14).value,r['ttft_seconds']);assert cached['Per_Question'].cell(i,35).value==r['model_digest']
    for i,r in enumerate(cp,5):assert close(cached['Retrieval_P5'].cell(i,5).value,r['p_at_5'])
    formula_n=sum(c.data_type=='f' for s in formula for row in s for c in row);assert formula_n>100
    chart_n=sum(len(s._charts) for s in formula);assert chart_n==2
    z=zipfile.ZipFile(p);assert z.testzip() is None
    output={'workbook':str(p),'sha256':ev.sha(p),'reopened_with':'openpyxl read-only-in-effect inspection; no save','sheets':formula.sheetnames,'raw_observations':720,'accuracy_layer_records':len(acc),'reference_questions':50,'reviewed_contexts':60,'formulas':formula_n,'charts':chart_n,'cached_formula_values_match_json':True,'formula_comparison_count':len(checks),'no_excel_error_cells':True,'na_preserved_blank_not_zero':True,'zip_integrity':True,'checks':checks}
    ev.dump(w/'workbook_validation.json',output);formula.close();cached.close();ev.verify_freeze(w,True);ev.emit({k:v for k,v in output.items() if k!='checks'})

if __name__=='__main__':main()
