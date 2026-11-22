"""Post-run explicit-result audit; does not alter frozen runtime or task validation.

Apply the same role grammar to every model/system arithmetic answer. Never select
a number because it matches the reference. Preserve all original parser results.
"""
import sys,json,re,unicodedata
from decimal import Decimal
sys.dont_write_bytecode=True
from fair_grounded_rag_final import W,jl,write
rows=jl(W/'arithmetic_accuracy_detailed.jsonl');assert len(rows)==104
audited=[];changes=[]
for x in rows:
 y=dict(x);y['original_automatic_verdict']=x['verdict'];y['original_automatic_reason']=x['reason'];y['original_automatic_numeric_check']=x.get('numeric_check');y['content_audit_method']='Exact explicit requested-result phrase + unit; all104 rows reviewed by same deterministic grammar; no expected-value-directed selection';a=x.get('raw_answer_text');calc=x.get('formula');candidates=[]
 if a and calc:
  # Normalize only thousands separators, full-width characters and scientific symbols.
  t=unicodedata.normalize('NFKC',a);t=re.sub(r'(?<=\d)[,，](?=\d{3}(?:\D|$))','',t)
  if calc['unit']=='尾':
   pattern=r'(?:一共(?:需要|需|為|为|是)?|總共(?:需要|需|為|为|是)?|总共(?:需要|需|為|为|是)?|總數(?:為|为|是)|总数(?:為|为|是))\s*(-?\d+(?:\.\d+)?)\s*(萬|万)?\s*尾'
  elif calc['unit']=='kg' and calc['operation']=='subtract':
   pattern=r'(?:超出(?:了)?|超過(?:了)?|超過建議值(?:為|为)?|超出建議值(?:為|为)?|差額(?:為|为)|差额(?:為|为))\s*(-?\d+(?:\.\d+)?)\s*(萬|万)?\s*(?:kg|公斤|千克)'
  else:pattern=None
  if pattern:
   for m in re.finditer(pattern,t,re.I):
    if re.match(r'\s*[/／]',t[m.end():]):continue
    # A described starting load (e.g. "超出900公斤的建議值為...") is not the final excess.
    if re.match(r'\s*的(?:建議|建议|上限|下限)',t[m.end():]):continue
    value=Decimal(m.group(1))*(10000 if m.group(2) else 1);candidates.append({'exact_text':m.group(),'normalized_start':m.start(),'normalized_end':m.end(),'value':str(value),'unit':calc['unit']})
  values={z['value'] for z in candidates}
  if len(values)==1:
   value=Decimal(next(iter(values)));correct=abs(value-Decimal(calc['expected']))<=Decimal(calc['tolerance']);verdict='correct' if correct else 'incorrect'
   y.update(verdict=verdict,reason='CONTENT_AUDIT_EXPLICIT_REQUESTED_RESULT_UNIT',numeric_check={'evaluable':True,'correct':correct,'parsed':str(value),'expected':calc['expected'],'unit':calc['unit'],'unit_valid':True,'selection_uses_expected_value':False,'candidates':candidates},fixed_denominator_success=correct)
   # The actual frozen system rejected the two missed-role answers. Never retroactively credit them.
   y['validated_task_success']=x['validated_task_success']
   if verdict!=x['verdict'] or str((x.get('numeric_check') or {}).get('parsed'))!=str(value):changes.append({'question_id':x['question_id'],'model_id':x['model_id'],'answer_layer':x['answer_layer'],'original_verdict':x['verdict'],'audited_verdict':verdict,'original_parsed':(x.get('numeric_check') or {}).get('parsed'),'audited_parsed':str(value),'exact_result_evidence':candidates,'task_success_unchanged':y['validated_task_success']==x['validated_task_success'],'raw_model_answer':a})
 y['content_audit_candidates']=candidates;audited.append(y)
(W/'arithmetic_accuracy_audited.jsonl').write_text(''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in audited),encoding='utf-8')
write('arithmetic_content_audit_report.json',{'all_rows':len(audited),'changes':changes,'reference_formula_unit_tolerance_unchanged':True,'frozen_runtime_and_original_grades_unchanged':True,'all_fixed_validated_task_success_flags_unchanged':all(a['validated_task_success']==b['validated_task_success'] for a,b in zip(rows,audited)),'no_human_gold_added':True,'scoring_interpretation':'Content accuracy recovers observable correct totals. Operational task success still requires the actual frozen runtime validation, so the two M1 rejections stay unsuccessful. This is a disclosed post-run parser audit, not a new Prompt, new generation, or changed reference.'})
print('Audited104 arithmetic rows; changes',len(changes),'operational task success unchanged',flush=True)
