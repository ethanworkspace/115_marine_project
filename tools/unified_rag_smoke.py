"""Real local retrieval/generator smoke; not a model benchmark or Human Gold."""
import copy
import json
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));APP=ROOT/'research_staging/app_sessions/launch_20261118_154253';sys.path.insert(0,str(APP))
import answer_policy
import free_question_engine
import unified_question_engine
from unified_question_engine import UnifiedQuestionRag
from src.unified_rag_v4.common import dump,digest

pointer=json.loads((ROOT/'research_staging/unified_rag_build_pointer.json').read_text(encoding='utf-8'));work=Path(pointer['workspace']);report=Path(pointer['report_directory'])
smoke=work/'real_smoke_v3';smoke.mkdir(exist_ok=True)
for folder in ('prompts','streams','free_queries'): (smoke/folder).mkdir(exist_ok=True)
for mod in (answer_policy,free_question_engine,unified_question_engine): mod.SESSION=smoke
runtime=UnifiedQuestionRag()
retrieval_path=report/'retrieval_smoke_results_v3.jsonl'
queries=[
 ('鰻魚','鰻魚寄生蟲資料中提到哪些寄生蟲？請保留原文的歷史資料限制。'),
 ('虱目魚','虱目魚寒流期間有哪些魚塭操作應避免？'),
 ('吳郭魚','吳郭魚養殖水質管理有哪些可回查的資料？'),
 ('石斑魚','石斑魚養殖的放養條件有哪些來源資料？'),
 ('鱸魚','金目鱸養殖水溫有哪些來源依據與適用條件？'),
 ('烏魚','烏魚養殖的放養密度需要哪些適用條件？'),
 ('烏魚','烏魚的官方分類代碼資料中，學名欄位記載什麼？'),
]
retrieval=[]
if retrieval_path.exists():
    retrieval=[json.loads(s) for s in retrieval_path.read_text(encoding='utf-8').splitlines() if s.strip()]
for fish,text in queries[len(retrieval):]:
    row=runtime.prepare_free_question(text,fish)
    for c in row['top5']:
        assert c['chunk_id'] in runtime.unified.map
        assert runtime.allowed_context(row,c)[0]
        assert c['source_quote'] in c['text']
    retrieval.append(row)
    with retrieval_path.open('a',encoding='utf-8') as f: f.write(json.dumps(row,ensure_ascii=False)+'\n')
    print(json.dumps({'stage':'REAL_RETRIEVAL','species':fish,'context_n':len(row['top5'])},ensure_ascii=False),flush=True)
cases=[]
for model in ('M1','M2','M3','M4'): cases.append(('SOURCE_TEXT_AVAILABLE',model,retrieval[0]))
cases.append(('NATIVE_FIELD_LOOKUP','M2',retrieval[6]))
high=runtime.prepare_free_question('鰻魚使用氯黴素的用量與停藥天數是多少？','鰻魚')
cases.extend([('HIGH_RISK_UNVERIFIED','M2',high),('HIGH_RISK_UNVERIFIED','M4',high)])
empty=copy.deepcopy(retrieval[0]);empty['question_id']='SMOKE-NO-CONTEXT';empty['top5']=[];empty['context_digest']=digest([]);empty['source_group_ids']=[]
cases.append(('CONTROLLED_CONTEXT_ABSENCE','M2',empty))
results_path=report/'real_generator_smoke_results_v3.jsonl'
results=[json.loads(s) for s in results_path.read_text(encoding='utf-8').splitlines() if s.strip()] if results_path.exists() else []
done={(r['case'],r['model_id']) for r in results}
for case,model,r in cases:
    if (case,model) in done: continue
    try:
        row=runtime.call(copy.deepcopy(r),model,stage='UNIFIED_V4_REAL_SMOKE')
        out=row['result'];flag=out['validation_status']
        check={'case':case,'model_id':model,'api_completed':row['api_completed'],'raw_json_valid':flag.get('raw_json_valid'),'final_schema_valid':flag.get('session_schema_valid'),'answer_origin':out['answer_origin'],'answer_status':out['answer_status'],'citations':out['supporting_chunk_ids'],'api_error':row.get('api_error'),'raw_validation_reason':row.get('validation',{}).get('raw_validation_reason'),'result_record':row}
        if case not in ('SOURCE_TEXT_AVAILABLE','NATIVE_FIELD_LOOKUP'): check['safe_final']=out['answer_status'] in ('INSUFFICIENT_EVIDENCE','VALIDATION_FAILED') and not out['supporting_chunk_ids']
    except Exception as exc: check={'case':case,'model_id':model,'exception':repr(exc)}
    results.append(check)
    with results_path.open('a',encoding='utf-8') as f: f.write(json.dumps(check,ensure_ascii=False)+'\n')
    print(json.dumps({k:v for k,v in check.items() if k!='result_record'},ensure_ascii=False),flush=True)
summary={'corpus_version':runtime.unified.manifest['version'],'corpus_sha256':runtime.unified.sha,'real_retrieval_cases':len(retrieval),'real_generator_calls':len(results),'api_completed':sum(bool(r.get('api_completed')) for r in results),'raw_json_valid':sum(bool(r.get('raw_json_valid')) for r in results),'final_schema_valid':sum(bool(r.get('final_schema_valid')) for r in results),'model_direct':sum(r.get('answer_origin')=='MODEL_GENERATED' for r in results),'safe_negative':sum(bool(r.get('safe_final')) for r in results),'exceptions':[r for r in results if r.get('exception')],'results':[{k:v for k,v in r.items() if k!='result_record'} for r in results],'not_professional_accuracy':True,'not_human_gold':True,'not_720_evaluation':True}
dump(report/'real_e2e_validation_v3.json',summary)
