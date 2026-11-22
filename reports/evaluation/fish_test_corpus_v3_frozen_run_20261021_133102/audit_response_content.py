"""Post-run parser erratum: no-answer text must not masquerade as a result.

Never alters generators, source references, prompts or rubrics. Original derived
score bytes are preserved before a transparent missingness overlay is applied.
"""
from pathlib import Path
import sys,json,re,hashlib,shutil,datetime
W=Path(__file__).resolve().parent;sys.path.insert(0,str(W));sys.stdout.reconfigure(encoding='utf-8')
from frozen_runner import jl,write
from score_frozen_run import visible
def classify(answer,question):
 if answer is None:return 'NO_NONABSTAINED_VISIBLE_ANSWER',None
 a=answer.strip();norm=lambda s:re.sub(r'[\s?？。，,]','',s)
 if norm(a)==norm(question):return 'QUESTION_ECHO_NO_ANSWER','EXACT_QUESTION_ECHO'
 # A final unanswered interrogative has no ensuing answer/result statement.
 if re.search(r'[?？]\s*$',a) and re.search(r'多少|幾|如何|什麼|什么|哪',a) and not re.search(r'答案[是為为]|結果[是為为]|结果[是为]|所以|因此',a):return 'QUESTION_ECHO_NO_ANSWER','UNANSWERED_INTERROGATIVE'
 # A conditional antecedent ending at the bound, without a consequent/result.
 if re.search(r'若採|若采|如果採|如果采',a) and re.search(r'(?:上限|下限)[。.]?\s*$',a) and not re.search(r'對應|对应|答案|結果|结果|總共|总共|合計|合计|總數|总数|等於|等于|=',a):return 'INCOMPLETE_ANTECEDENT_NO_ANSWER','CONDITION_REPEATED_WITHOUT_RESULT'
 return 'SUBSTANTIVE_OR_PARTIAL_ATTEMPT',None
def main(apply=False):
 gens=jl(W/'generator_final_results_720.jsonl');assert len(gens)==720
 classifications=[];mask={}
 for g in gens:
  for layer in ['model','system']:
   answer,why=visible(g,layer);status,reason=classify(answer,g['question']);row={'run_id':g['run_id'],'question_id':g['question_id'],'model_id':g['model_id'],'answer_layer':layer,'content_status':status,'reason':reason or why,'answer_text':answer,'method':'Programmatic observable-response classification; NOT_HUMAN_GOLD; no reference answer consulted'};classifications.append(row)
   if status in {'QUESTION_ECHO_NO_ANSWER','INCOMPLETE_ANTECEDENT_NO_ANSWER'}:mask[(g['question_id'],g['model_id'],layer)]=row
 (W/'response_content_audit_1440.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in classifications),encoding='utf-8')
 write('response_content_parser_erratum.json',{'created_at':datetime.datetime.now().astimezone().isoformat(),'status':'APPLIED' if apply else 'PREVIEW','reason':'Frozen v1 unit-anchor parser could match numbers copied from a question instead of a generated result. Nonanswer text has no reliable accuracy result; do not fabricate an incorrect numeric value.','generation_and_reference_rubrics_changed':False,'frozen_scoring_implementation_preserved':True,'correction_scope':'Missingness/answer-content interpretation only; no numeric Gold, tolerance or conclusion changed','method_source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'flagged_rows':list(mask.values()),'human_gold':False})
 if not apply:print(json.dumps({'flagged':list(mask.values())},ensure_ascii=False));return
 log=[]
 # Judge response-quality scores remain exactly as observed, including poor scores
 # for echoes. BGE has an explicit answer-only view; source accuracy requires an
 # observable conclusion/result. Original v1 values remain available for sensitivity.
 for name,kind in [('bge_relevance_detailed.jsonl','bge'),('logical_accuracy_detailed.jsonl','logical'),('arithmetic_accuracy_detailed.jsonl','arithmetic')]:
  p=W/name;backup=W/(p.stem+'_frozen_parser_v1.jsonl')
  if not backup.exists():shutil.copy2(p,backup)
  rows=jl(backup)
  for r in rows:
   key=(r['question_id'],r['model_id'],r['answer_layer'])
   if key not in mask:continue
   reason=mask[key]['reason'];old={}
   if kind=='bge':old={'cosine':r.get('cosine'),'status':r.get('status')};r.update(cosine=None,status='NOT_EVALUABLE',reason=reason)
   elif kind=='quality':old={k:r.get(k) for k in ['faithfulness','judge_answer_relevance','reason']};r.update(faithfulness=None,judge_answer_relevance=None,reason=reason)
   else:
    old={k:r.get(k) for k in ['verdict','reason','parsed_numeric_value','numeric_valid','unit_valid']};r.update(verdict='not_evaluable',reason=reason)
    if kind=='arithmetic':r.update(parsed_numeric_value=None,numeric_valid=None,unit_valid=None)
   r['parser_erratum']={'status':'NONANSWER_EXCLUDED_FROM_SCORE','original':old,'content_status':mask[key]['content_status'],'rubric_unchanged':True,'preserved_original_file':backup.name}
   log.append({'file':name,'key':list(key),'old':old,'new_reason':reason})
  p.write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows),encoding='utf-8')
 write('score_parser_correction_log.json',{'changes':log,'counts':len(log),'originals_preserved':True,'frozen_reference_rubrics_unchanged':True})
 print('Applied response parser erratum',len(log),flush=True)
if __name__=='__main__':main('--apply' in sys.argv)
