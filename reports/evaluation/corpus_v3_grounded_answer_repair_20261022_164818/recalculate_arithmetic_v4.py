import sys
sys.dont_write_bytecode=True
from decimal import Decimal
from fair_grounded_rag_final import W,jl,append
from score_regression_final import visible
from arithmetic_parser_v4 import parse_arithmetic
def main():
 refs={r['question_id']:r for r in jl(W/'verified_reference_answers_v3.jsonl')};out=[]
 for g in jl(W/'regression_results_200_final.jsonl'):
  ref=refs[g['question_id']];calc=ref.get('expected_calculation')
  if not calc:continue
  a,b=Decimal(calc['a']),Decimal(calc['b']);n={'multiply':lambda:a*b,'subtract':lambda:a-b,'divide':lambda:a/b}[calc['operation']]();assert n==Decimal(calc['expected'])
  for layer in ['model','system']:
   answer,reason=visible(g,layer);row={'run_id':g['run_id'],'question_id':g['question_id'],'model_id':g['model_id'],'species':g['species'],'category':g['category'],'answer_layer':layer,'answer_origin':g['result']['answer_origin'],'source_group_ids':g['source_group_ids'],'rubric_sha256':ref['rubric_sha256'],'verification_level':'AUTO_SOURCE_VERIFIED; DETERMINISTIC_DECIMAL; NOT_HUMAN_GOLD','verdict':'not_evaluable','reason':reason,'fixed_denominator_success':False,'validated_task_success':False,'formula':calc,'decimal_reference_result':str(n),'parser_version':'EXPLICIT_RESULT_ROLE_V4'}
   if answer:
    c=parse_arithmetic(answer,calc);row.update(numeric_check=c,verdict=('correct' if c['correct'] else 'incorrect') if c['evaluable'] else 'not_evaluable',reason=c['reason'])
   row['fixed_denominator_success']=row['verdict']=='correct';vs=g['result']['validation_status'];valid=g['result']['answer_status']=='ANSWERED_GROUNDED' and (layer=='system' or (g['result']['answer_origin']=='MODEL_GENERATED' and vs['raw_json_valid'] and vs['raw_citation_valid']));row['validated_task_success']=row['verdict']=='correct' and valid;out.append(row)
 assert len(out)==104
 import json
 (W/'arithmetic_regression_detailed_v4.jsonl').write_text(''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in out),encoding='utf-8')
 print('Saved104 arithmetic evaluations; fixed13 denominators, expected references unchanged',flush=True)
if __name__=='__main__':main()
