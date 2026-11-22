"""Independent Judge and deterministic accuracy; never mutate old scores."""
from __future__ import annotations
import argparse,collections,copy,json,math,re,sys,time,unicodedata
from decimal import Decimal
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tools')]
import evaluate_unified_rag_v6 as ev
import requests,jsonschema

def content_problem(answer,question):
    normalized=lambda s:re.sub(r'[\s，,。?？]','',unicodedata.normalize('NFKC',str(s)))
    if not answer.strip():return 'EMPTY_ANSWER'
    if normalized(answer)==normalized(question):return 'QUESTION_ECHO'
    if re.search(r'[?？]\s*$',answer) and re.search(r'多少|如何|哪|什麼|幾',answer) and not re.search(r'因此|所以|結果|答案|等於',answer):return 'UNANSWERED_INTERROGATIVE'
    if re.search(r'若採|若采|如果',answer) and re.search(r'上限[。.]?\s*$',answer) and not re.search(r'合計|總共|結果|答案|等於|=',answer):return 'INCOMPLETE_CONDITION_ONLY'
    return None

def visible(g,layer):
    if not g.get('api_completed'):return None,'API_INCOMPLETE'
    if layer=='model':
        p=g.get('validation',{}).get('parsed_model_response')
        if not isinstance(p,dict):
            try:p=json.loads(g['raw_model_response'])
            except (ValueError,TypeError):return None,'RAW_JSON_UNPARSABLE_NO_SAFE_ANSWER_EXTRACTION'
        if p.get('answer_status')=='INSUFFICIENT_EVIDENCE':return None,'MODEL_DECLARED_INFORMATION_GAP'
        answer=p.get('answer')
    else:
        p=g['result']
        if p['answer_origin'] not in ('MODEL_GENERATED','DETERMINISTIC_EVIDENCE_EXTRACTION'):return None,'SYSTEM_GUIDANCE_OR_FAILED_VALIDATION_NOT_PROFESSIONAL_ANSWER'
        if p['answer_status'] not in ('ANSWERED_GROUNDED','ANSWERED_PARTIAL'):return None,'SYSTEM_NOT_A_SUPPORTED_ANSWER'
        answer=p['final_answer']
    if not isinstance(answer,str) or not answer.strip():return None,'EMPTY_VISIBLE_ANSWER'
    bad=content_problem(answer,g['question']);return (None,bad) if bad else (answer.strip(),None)

def validated_model_answer(g):
    r=g['result'];v=r['validation_status']
    return bool(g['api_completed'] and r['answer_origin']=='MODEL_GENERATED' and r['answer_status'] in ('ANSWERED_GROUNDED','ANSWERED_PARTIAL') and v.get('raw_json_valid') and v.get('raw_citation_valid'))

def judge_call(w,policy,messages,schema,kind):
    payload={'model':policy['JUDGE'],'messages':messages,'stream':True,'format':schema,'keep_alive':'30m','options':{'temperature':0,'top_p':1,'seed':21021,'num_predict':512,'num_ctx':8192}}
    key=ev.digest({'kind':kind,'messages':messages,'schema':schema,'options':payload['options'],'judge_digest':policy['JDIGEST']});errors=[]
    for attempt in (1,2):
        text=[];events=[];body={};failure=None;t=time.perf_counter();parsed=None
        try:
            with requests.post('http://127.0.0.1:11434/api/chat',json=payload,stream=True,timeout=(30,600)) as response:
                response.raise_for_status()
                for line in response.iter_lines(chunk_size=1):
                    if not line:continue
                    event=json.loads(line);events.append({'elapsed_seconds':time.perf_counter()-t,'event':event});text.append((event.get('message') or {}).get('content',''))
                    if event.get('error'):raise RuntimeError(event['error'])
                    if event.get('done'):body=event
            if not body.get('done'):raise ValueError('JUDGE_STREAM_MISSING_DONE')
            parsed=json.loads(''.join(text));jsonschema.validate(parsed,schema)
        except Exception as exc:failure=type(exc).__name__+': '+str(exc);errors.append(failure)
        ev.append(w/'judge_raw_attempts.jsonl',{'input_key':key,'kind':kind,'attempt':attempt,'at':ev.now(),'judge_tag':policy['JUDGE'],'judge_digest':policy['JDIGEST'],'payload':payload,'raw_response':''.join(text),'stream':events,'error':failure,'wall_seconds':time.perf_counter()-t})
        if failure is None:return {'status':'scored','scores':parsed,'attempt_count':attempt,'errors':errors,'input_key':key,'judge_tag':policy['JUDGE'],'judge_digest':policy['JDIGEST'],'prompt_sha256':ev.digest(messages)}
    return {'status':'judge_error','scores':None,'attempt_count':2,'errors':errors,'input_key':key,'judge_tag':policy['JUDGE'],'judge_digest':policy['JDIGEST'],'prompt_sha256':ev.digest(messages)}

def bge_scores(w,gens):
    fn=w/'bge_relevance_detailed.jsonl';old=ev.jl(fn);done={(x['question_id'],x['model_id'],x['answer_layer']) for x in old};pending=[];ev.unload()
    for g in gens:
        for layer in ('model','system'):
            key=g['question_id'],g['model_id'],layer
            if key in done:continue
            answer,reason=visible(g,layer)
            if answer:pending.append((g,layer,answer))
            else:ev.append(fn,{'run_id':w.name,'question_id':g['question_id'],'model_id':g['model_id'],'answer_layer':layer,'cosine':None,'reason':reason,'status':'NOT_EVALUABLE'})
    vector_cache={}
    texts=list(dict.fromkeys([value for g,layer,answer in pending for value in (g['question'],answer)]))
    failures={}
    for start in range(0,len(texts),16):
        batch=texts[start:start+16]
        try:
            response=requests.post('http://127.0.0.1:11434/api/embed',json={'model':ev.BGE['tag'],'input':batch,'truncate':False,'keep_alive':'30m'},timeout=(30,600));response.raise_for_status();vectors=response.json()['embeddings'];assert len(vectors)==len(batch)
            for t,v in zip(batch,vectors):assert len(v)==1024 and all(math.isfinite(x) for x in v);vector_cache[t]=v
        except Exception as exc:
            # Isolate a long/failing answer; never invent zero or silently
            # truncate/pool away part of the generated answer.
            for t in batch:
                try:
                    response=requests.post('http://127.0.0.1:11434/api/embed',json={'model':ev.BGE['tag'],'input':[t],'truncate':False,'keep_alive':'30m'},timeout=(30,600));response.raise_for_status();v=response.json()['embeddings'][0];assert len(v)==1024;vector_cache[t]=v
                except Exception as single:failures[t]=type(single).__name__+': '+str(single)
        ev.emit({'stage':'bge_texts','completed':min(start+16,len(texts)),'target':len(texts)})
    for g,layer,answer in pending:
        score=None;reason=None
        if g['question'] in vector_cache and answer in vector_cache:
            qv,av=vector_cache[g['question']],vector_cache[answer];qn=math.sqrt(sum(x*x for x in qv));an=math.sqrt(sum(x*x for x in av))
            if qn and an:score=sum(a*b for a,b in zip(qv,av))/(qn*an)
            else:reason='ZERO_NORM_EMBEDDING'
        else:reason=failures.get(answer,failures.get(g['question'],'EMBEDDING_UNAVAILABLE'))
        ev.append(fn,{'run_id':w.name,'question_id':g['question_id'],'model_id':g['model_id'],'answer_layer':layer,'cosine':score,'status':'SCORED_VISIBLE_NONABSTAINED_ANSWER' if score is not None else 'NOT_EVALUABLE','reason':reason,'model':ev.BGE['tag'],'digest':ev.BGE['digest'],'dimension':1024,'normalization':'Explicit L2 cosine, no prefix, truncate=False; question and visible answer only','answer_sha256':ev.digest(answer)})
    ev.unload()

def professional(w,gens,refs,policy):
    sys.path.insert(0,str(w/'scoring'));from arithmetic_parser_v4 import parse_arithmetic
    for metric in ('arithmetic','logical'):
        fn=w/(metric+'_accuracy_detailed.jsonl');old=ev.jl(fn);done={(x['question_id'],x['model_id'],x['answer_layer']) for x in old};cache={x['input_key']:x['evaluation'] for x in old if x.get('evaluation',{}).get('status')=='scored'}
        for g in gens:
            ref=refs[g['question_id']]
            if not ref.get('v6_professional_eligible') or not ref.get('expected_calculation' if metric=='arithmetic' else 'logical_rubric'):continue
            for layer in ('model','system'):
                if (g['question_id'],g['model_id'],layer) in done:continue
                answer,reason=visible(g,layer);row={'run_id':w.name,'question_id':g['question_id'],'model_id':g['model_id'],'species':g['species'],'category':g['category'],'answer_layer':layer,'answer_origin':g['result']['answer_origin'],'reference_source_group_ids':ref['reference_source_group_ids'],'rubric_sha256':ref['rubric_sha256'],'verification_level':'AUTO_SOURCE_VERIFIED; AI_ASSISTED; NOT_HUMAN_GOLD','verdict':'not_evaluable','reason':reason,'raw_answer_text':answer}
                if answer and metric=='arithmetic':
                    calc=ref['expected_calculation'];a,b=Decimal(calc['a']),Decimal(calc['b']);result={'multiply':lambda:a*b,'subtract':lambda:a-b,'divide':lambda:a/b}[calc['operation']]();assert result==Decimal(calc['expected']);check=parse_arithmetic(answer,calc);row.update(formula=calc,decimal_reference_result=str(result),numeric_check=check,verdict=('correct' if check['correct'] else 'incorrect') if check['evaluable'] else 'not_evaluable',reason=check['reason'])
                elif answer:
                    sources=[{k:s.get(k) for k in ('source_id','source_version','exact_evidence_span','evidence_locator','source_sha256')} for s in ref['evidence_spans']]
                    messages=[{'role':'system','content':policy['J_SYSTEM']},{'role':'user','content':policy['L_POLICY']+'\nQuestion: '+g['question']+'\nSpecies: '+g['species']+'\nFrozen rubric: '+json.dumps(ref['logical_rubric'],ensure_ascii=False)+'\nSource: '+json.dumps(sources,ensure_ascii=False)+'\nAnswer: '+answer}]
                    key=ev.digest({'kind':'LOGICAL','messages':messages,'schema':policy['LS'],'options':{'temperature':0,'top_p':1,'seed':21021,'num_predict':512,'num_ctx':8192},'judge_digest':policy['JDIGEST']});reuse=key in cache;evaluation=cache[key] if reuse else judge_call(w,policy,messages,policy['LS'],'LOGICAL');row.update(input_key=key,evaluation=evaluation,identical_input_cache_reuse=reuse)
                    if evaluation['status']=='scored':
                        cache[key]=evaluation;s=evaluation['scores'];verdict=s['verdict'];why=s['reason']
                        if verdict=='correct' and (not s['required_conditions_satisfied'] or s['material_contradictions']):verdict='not_evaluable';why='JUDGE_INTERNAL_CONTRADICTION'
                        row.update(verdict=verdict,reason=why)
                    else:row['reason']='JUDGE_ERROR'
                row['content_task_success']=row['verdict']=='correct'
                valid=validated_model_answer(g) if layer=='model' else g['api_completed'] and g['result']['answer_origin'] in ('MODEL_GENERATED','DETERMINISTIC_EVIDENCE_EXTRACTION') and g['result']['answer_status'] in ('ANSWERED_GROUNDED','ANSWERED_PARTIAL')
                row['validated_task_success']=bool(row['verdict']=='correct' and valid);ev.append(fn,row);ev.emit({'stage':metric,'question_id':g['question_id'],'model':g['model_id'],'layer':layer,'verdict':row['verdict']})

def quality(w,gens,contexts,policy):
    fn=w/'judge_quality_detailed.jsonl';old=ev.jl(fn);done={(x['question_id'],x['model_id'],x['answer_layer']) for x in old};cache={x['input_key']:x['evaluation'] for x in old if x.get('evaluation',{}).get('status')=='scored'}
    for i,g in enumerate(gens,1):
        context=contexts[g['question_id']];source='\n\n'.join('['+c['chunk_id']+'] '+c['source_version']+' '+str(c['exact_locator'])+'\n'+c['source_quote'] for c in context['top5'])
        for layer in ('model','system'):
            if (g['question_id'],g['model_id'],layer) in done:continue
            answer,reason=visible(g,layer);row={'run_id':w.name,'question_id':g['question_id'],'model_id':g['model_id'],'answer_layer':layer,'answer_origin':g['result']['answer_origin'],'context_digest':g['context_digest'],'faithfulness':None,'judge_answer_relevance':None,'reason':reason,'human_gold':False,'context_is_exact_generator_source_quote':True}
            if answer:
                messages=[{'role':'system','content':policy['J_SYSTEM']},{'role':'user','content':policy['J_POLICY']+'\nQuestion: '+g['question']+'\nContext:\n'+source+'\nAnswer:\n'+answer}];key=ev.digest({'kind':'QUALITY','messages':messages,'schema':policy['JS'],'options':{'temperature':0,'top_p':1,'seed':21021,'num_predict':512,'num_ctx':8192},'judge_digest':policy['JDIGEST']});reuse=key in cache;evaluation=cache[key] if reuse else judge_call(w,policy,messages,policy['JS'],'QUALITY')
                if evaluation['status']=='scored':cache[key]=evaluation;row.update(faithfulness=evaluation['scores']['faithfulness'],judge_answer_relevance=evaluation['scores']['answer_relevance'])
                row.update(input_key=key,evaluation=evaluation,identical_input_cache_reuse=reuse)
            ev.append(fn,row)
        if i%5==0:ev.emit({'stage':'judge_quality','generator_rows_completed':i,'target':len(gens)})

def main():
    w=ev.work();ev.verify_freeze(w,True);gens=ev.jl(w/'generator_final_results_720.jsonl');assert len(gens)==len({(g['question_id'],g['model_id']) for g in gens})==720
    refs={r['question_id']:r for r in ev.jl(w/'verified_reference_answers_v6.jsonl')};contexts={r['question_id']:r for r in ev.jl(w/'shared_contexts_180.jsonl')};policy=ev.read(w/'scoring/judge_policy_frozen.json');ev.model_identity()
    bge_scores(w,gens);professional(w,gens,refs,policy);quality(w,gens,contexts,policy);ev.unload();ev.verify_freeze(w,True);ev.emit({'stage':'all_scoring_complete'})

if __name__=='__main__':main()
