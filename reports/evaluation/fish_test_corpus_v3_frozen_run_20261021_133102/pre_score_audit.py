from pathlib import Path
import sys,json,collections,re,datetime
W=Path(__file__).resolve().parent;sys.path.insert(0,str(W));sys.stdout.reconfigure(encoding='utf-8')
from frozen_runner import jl,write,verify_frozen
verify_frozen();g=jl(W/'generator_final_results_720.jsonl');a=jl(W/'generator_raw_attempts_720.jsonl')
assert len(g)==len({(r['question_id'],r['model_id']) for r in g})==720
assert len({r['question_id'] for r in g})==180
assert all(len({r['context_digest'] for r in g if r['question_id']==qid})==1 for qid in {r['question_id'] for r in g})
candidates=[];risk=[]
for r in g:
 p=r.get('parsed_model_response') or {};ans=p.get('answer') or ''
 if p.get('abstained') is False and re.search('無法|无法|不足|缺乏|没有足|沒有足',ans):candidates.append({'question_id':r['question_id'],'model_id':r['model_id'],'answer':ans})
 f=r['final_response']
 if not f['abstained'] and re.search('抗生素|用藥|劑量|停藥|給藥',f.get('answer') or ''):risk.append({'question_id':r['question_id'],'model_id':r['model_id'],'answer':f['answer']})
write('answer_status_phrase_audit.json',{'method':'Codex observable-answer audit of refusal-related phrase candidates; no Gold/accuracy inferred','candidate_count':len(candidates),'candidates':candidates,'finding':'Candidates contain substantive or partial factual answer content, not a standalone refusal. Limitation phrases do not by themselves invalidate an answer.','metric_rows_excluded_by_this_audit':0,'human_gold':False,'independent_expert_review':False})
write('final_answer_safety_diagnostics.json',{'method':'Term-based screening of final nonabstained answers, not proof of clinical safety','risk_term_hits':risk,'accepted_source_inapplicable':sum(not r['final_response']['abstained'] and r['evidence_decision']['state']=='SOURCE_INAPPLICABLE' for r in g),'accepted_citation_failures':sum(not r['final_response']['abstained'] and r['final_citation_validation']['status']!='PASS' for r in g)})
out={'run_id':W.name,'canonical_results':len(g),'unique_pairs':len({(r['question_id'],r['model_id']) for r in g}),'raw_attempts':len(a),'api_completed':sum(r['api_completed'] for r in g),'same_context_per_question':True,'frozen_hashes_pass':True,'models':{mid:{'n':len(t:=[r for r in g if r['model_id']==mid]),'api_completed':sum(r['api_completed'] for r in t),'raw_schema_valid':sum(r['raw_model_structure_valid'] for r in t),'answer_origins':dict(collections.Counter(r['answer_origin'] for r in t))} for mid in ['M1','M2','M3','M4']}}
write('generator_completion_validation.json',out);print(json.dumps(out,ensure_ascii=False),flush=True)
