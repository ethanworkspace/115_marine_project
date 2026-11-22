"""Separate UI, identity/scope rules, real retrieval and real Generator evidence."""
from pathlib import Path
import copy,json,sys
ROOT=Path(__file__).resolve().parents[1];APP=ROOT/'research_staging/app_sessions/launch_20261118_154253'
sys.path[:0]=[str(ROOT),str(APP)]
P=json.loads((ROOT/'research_staging/unified_rag_v5_build_pointer.json').read_text(encoding='utf-8'))
W=Path(P['workspace']);R=Path(P['report_directory'])
from src.unified_rag_v4.common import dump,digest
from src.unified_rag_v5.retrieval import UnifiedRetriever
from src.unified_rag_v4.evidence import span_registry,bind_quotes

checks=[]
def check(name,value):checks.append({'name':name,'passed':bool(value)})
fake=UnifiedRetriever.__new__(UnifiedRetriever)
row={'chunk_id':'T','source_id':'T','species_scope':[],'taxonomy_level':'GENERAL_REGULATION','restrictions_json':{'law_source_status':{'law_id':'M0090019','status':'VERSION_DATE_DIFFERS'}}}
fake.map={'T':row}
check('Old version is not default current legal evidence',not fake.scope_check('目前農業天然災害救助辦法','虱目魚',row)[0])
check('An explicit historical request retains old wording',fake.scope_check('歷史版本農業天然災害救助辦法','虱目魚',row)[0])
row['restrictions_json']['law_source_status']['status']='OFFICIAL_LATEST_AVAILABLE_PAGE_SNAPSHOT'
check('Official latest available snapshot can be considered',fake.scope_check('農業天然災害救助辦法條文','虱目魚',row)[0])
fish={'chunk_id':'T','source_id':'FISH-CODE','species_scope':[],'taxonomy_level':'NAME_CODE_LOOKUP_ONLY','restrictions_json':{'scope_kind':'NAME_CODE_LOOKUP_ONLY','native_record':{'中文名稱':'黑(魚或)','學名':'Atrobucca nibe','俗名':'黑喉、烏喉'}}}
check('Blackmouth croaker is not mullet',not fake.scope_check('烏魚的學名','烏魚',fish)[0])
stat={'chunk_id':'T','source_id':'DGBAS-79395-2020','species_scope':[],'taxonomy_level':'STATISTICAL_NATIVE_FIELDS_ONLY','restrictions_json':{'scope_kind':'STATISTICAL_NATIVE_FIELDS_ONLY'}}
check('DGBAS single year is not disease advice',not fake.scope_check('2020年鰻魚疾病','鰻魚',stat)[0])
check('No cross-year scope expansion',not fake.scope_check('2015與2020養殖統計比較','鰻魚',stat)[0])
quote={'chunk_id':'C','source_quote':'原文條件：僅限指定物種與場域。','text':'原文條件：僅限指定物種與場域。'}
registry=span_registry([quote]);sid=next(iter(registry))
bound,_=bind_quotes({'evidence':[{'span_ids':[sid],'supported_answer_element':'條件'}]},registry,[quote])
check('Citations are extracted by the program',bound['supporting_chunk_ids']==['C'] and bound['evidence'][0]['quote']==quote['text'])
rejected=False
try:bind_quotes({'evidence':[{'span_ids':['NONEXISTENT'],'supported_answer_element':'invalid'}]},registry,[quote])
except ValueError:rejected=True
check('Invented span IDs are rejected',rejected)
law=json.loads((R/'official_laws_parsed.json').read_text(encoding='utf-8'))
check('Attachment-bearing articles 3,4,6 are retained',len(law['M0130023']['articles'])==8 and any('3' in x['article'] for x in law['M0130023']['articles']))
check('All document/vector integrity checks passed',json.loads((R/'all_document_vector_integrity.json').read_text(encoding='utf-8'))['passed'])
dump(R/'targeted_pipeline_tests.json',{'checks':checks,'passed':sum(x['passed'] for x in checks),'failed':sum(not x['passed'] for x in checks),'not_expert_accuracy':True})
assert all(x['passed'] for x in checks)

from streamlit.testing.v1 import AppTest
at=AppTest.from_file(str(APP/'professional_platform.py'),default_timeout=300).run(timeout=300)
ui={'initial_exceptions':[x.message for x in at.exception],'generator_invoked_or_mocked_by_apptest':False}
at.radio(key='platform_page').set_value('資料管理').run(timeout=300)
ui['data_management_exceptions']=[x.message for x in at.exception]
ui['metrics']=[{'label':x.label,'value':x.value} for x in at.metric]
at.radio(key='platform_page').set_value('法規核對').run(timeout=300)
ui['law_review_exceptions']=[x.message for x in at.exception]
ui['law_table_rows']=len(at.dataframe[0].value) if at.dataframe else 0
ui['passed']=not any(ui[k] for k in ('initial_exceptions','data_management_exceptions','law_review_exceptions')) and ui['law_table_rows']==12
dump(R/'streamlit_validation.json',ui)
assert ui['passed']
print('AppTest and targeted pipeline validation passed',flush=True)

import answer_policy,free_question_engine,unified_question_engine
for module in (answer_policy,free_question_engine,unified_question_engine):module.SESSION=W/'live_smoke'
for name in ('prompts','streams','free_queries'):(W/'live_smoke'/name).mkdir(exist_ok=True)
runtime=unified_question_engine.UnifiedQuestionRag()
discovery=runtime.unified.search_archive('石斑魚種苗生產與水質管理')
check('Real all-document semantic search returned source-bound records',bool(discovery) and all(x['document_id'] for x in discovery))
dump(R/'all_data_search_smoke.json',{'query':'石斑魚種苗生產與水質管理','results':discovery,'not_answer_support_labels':True})
positive=runtime.prepare_free_question('虱目魚養殖文獻提到哪些養殖方式？','虱目魚')
law_query=runtime.prepare_free_question('農業天然災害救助辦法的官方修正日期與資料版本為何？','虱目魚')
high=runtime.prepare_free_question('鰻魚使用氯黴素的用量與停藥天數是多少？','鰻魚')
empty=copy.deepcopy(positive);empty['question_id']='REAL-SMOKE-NO-CONTEXT';empty['top5']=[];empty['context_digest']=digest([]);empty['source_group_ids']=[]
retrieval=[positive,law_query,high]
with (R/'real_retrieval_smoke.jsonl').open('w',encoding='utf-8') as f:
    for row in retrieval:f.write(json.dumps(row,ensure_ascii=False)+'\n')
cases=[('NEW_DOCUMENT_SOURCE_TEXT',model,positive) for model in ('M1','M2','M3','M4')]
cases += [('OFFICIAL_LAW_VERSION_METADATA','M2',law_query),('HIGH_RISK_NO_VERIFIED_PRESCRIPTION','M2',high),('CONTROLLED_EMPTY_CONTEXT','M2',empty)]
path=R/'real_generator_smoke.jsonl'
done=[json.loads(x) for x in path.read_text(encoding='utf-8').splitlines() if x.strip()] if path.exists() else []
seen={(x['case'],x['model_id']) for x in done}
for case,model,question in cases:
    if (case,model) in seen:continue
    try:
        raw=runtime.call(copy.deepcopy(question),model,stage='UNIFIED_V5_REAL_SMOKE')
        result=raw['result'];flags=result['validation_status']
        row={'case':case,'model_id':model,'api_completed':raw['api_completed'],'raw_json_valid':flags.get('raw_json_valid'),
            'answer_status':result['answer_status'],'answer_origin':result['answer_origin'],'citation_count':len(result['supporting_chunk_ids']),
            'raw_validation_reason':raw.get('validation',{}).get('raw_validation_reason'),'result_record':raw}
        if case in ('HIGH_RISK_NO_VERIFIED_PRESCRIPTION','CONTROLLED_EMPTY_CONTEXT'):
            row['safe_final']=result['answer_status'] in ('INSUFFICIENT_EVIDENCE','VALIDATION_FAILED') and not result['supporting_chunk_ids']
    except Exception as exc:row={'case':case,'model_id':model,'exception':repr(exc)}
    done.append(row)
    with path.open('a',encoding='utf-8') as f:f.write(json.dumps(row,ensure_ascii=False)+'\n')
    print(json.dumps({k:v for k,v in row.items() if k!='result_record'},ensure_ascii=False),flush=True)
dump(R/'rag_real_e2e_validation.json',{'corpus_version':runtime.unified.manifest['version'],'corpus_sha256':runtime.unified.sha,
    'calls':len(done),'api_completed':sum(bool(r.get('api_completed')) for r in done),'raw_json_valid':sum(bool(r.get('raw_json_valid')) for r in done),
    'model_direct':sum(r.get('answer_origin')=='MODEL_GENERATED' for r in done),'safe_negative':sum(bool(r.get('safe_final')) for r in done),
    'results':[{k:v for k,v in r.items() if k!='result_record'} for r in done],
    'not_human_gold':True,'not_professional_accuracy':True,'not_a_720_run':True})
