import json,sys
from pathlib import Path
sys.dont_write_bytecode=True
W=Path(__file__).resolve().parent;sys.path.insert(0,str(W))
from fair_grounded_rag import FairRag,FINAL_SCHEMA,RAW_SCHEMA,content_problem,parse_arithmetic,digest,jl
from fair_grounded_rag import numeric
import jsonschema,pytest
@pytest.fixture(scope='module')
def engine():return FairRag()
@pytest.fixture(scope='module')
def rows():return {r['question_id']:r for r in jl(W/'shared_contexts_180.jsonl')}
def test_profiles_and_no_gold_in_prompt(engine,rows):
 for qid,r in rows.items():
  p,e=engine.payload(r,'M2');assert 'reference_answer' not in p['prompt'] and 'logical_rubric' not in p['prompt'];assert len(r['top5'])<=5 and len({c['chunk_id'] for c in r['top5']})==len(r['top5'])
def test_ids_bound_and_empty_context(engine,rows):
 r={**rows['FT-tilapia-Q09'],'question_id':'UNIT-NO-CONTEXT','top5':[]};e=engine.evidence(r)
 raw=json.dumps({'answer':'缺少來源。','answer_status':'INSUFFICIENT_EVIDENCE','supporting_chunk_ids':[],'missing_information':['沒有合格Context']},ensure_ascii=False);out,v=engine.postprocess(r,'M2',raw,e)
 assert out['question_id']==r['question_id'] and out['model_id']=='M2' and out['answer_status']=='INSUFFICIENT_EVIDENCE';jsonschema.validate(out,FINAL_SCHEMA)
def test_invalid_json_not_uncertain(engine,rows):
 r={**rows['FT-tilapia-Q09'],'question_id':'UNIT-INVALID','top5':[]};out,v=engine.postprocess(r,'M2','not json',engine.evidence(r));assert out['answer_status']=='VALIDATION_FAILED' and not out['validation_status']['raw_json_valid']
def test_wrong_citation_rejected_not_normalized(engine,rows):
 r={**rows['FT-tilapia-Q09'],'question_id':'UNIT-WRONG-CITE','top5':[]};raw=json.dumps({'answer':'錯誤數值99°C','answer_status':'ANSWERED_GROUNDED','supporting_chunk_ids':['OTHER-RANK'],'missing_information':[]});o,v=engine.postprocess(r,'M1',raw,engine.evidence(r));assert not o['validation_status']['raw_citation_valid'] and not o['supporting_chunk_ids'] and '99' not in o['final_answer']
def test_wrong_species_block(engine,rows):
 c=next(c for r in rows.values() for c in r['top5'] if c['species_scope']==['烏魚']);r={'question_id':'UNIT-SPECIES','question':'吳郭魚適宜的第一年放養密度是多少？','species':'吳郭魚','category':'Fact','top5':[c]};e=engine.evidence(r);assert e['state']=='SOURCE_INAPPLICABLE' and e['excluded_contexts']
@pytest.mark.parametrize('text',['停藥期幾天','建議使用劑量多少','每次用量是多少','現行法規准許什麼'])
def test_high_risk_restrictions(engine,rows,text):
 r={**rows['FT-tilapia-Q09'],'question_id':'UNIT-HIGH-RISK','question':text};e=engine.evidence(r);assert e['state']=='HIGH_RISK_SOURCE_UNVERIFIED' and not e['supporting_chunk_ids']
def test_identity_mismatch(engine,rows):
 r={**rows['FT-tilapia-Q09'],'question':'鰻魚劑量多少','species':'鰻魚'};assert engine.evidence(r)['reason']=='QUESTION_PROFILE_IDENTITY_MISMATCH'
@pytest.mark.parametrize('q',['密度是多少？','水溫多少？','如何處理？'])
def test_question_echo(q):assert content_problem(q,q)=='QUESTION_ECHO'
def test_condition_without_result():assert content_problem('3公頃若採20000尾/公頃上限。','計算放養量')=='INCOMPLETE_CONDITION_ONLY'
def test_arithmetic_does_not_read_rate_as_total():
 x=parse_arithmetic('總數為15000尾，來源密度每公頃5000尾/公頃。',{'unit':'尾','expected':'15000','tolerance':'0'});assert x['correct']
def test_arithmetic_wrong_is_wrong():assert not parse_arithmetic('計算結果為300 kg',{'unit':'kg','expected':'120','tolerance':'0.01'})['correct']
def test_arithmetic_chinese_salinity():assert parse_arithmetic('應提高到千分之21',{'unit':'ppt','expected':'21','tolerance':'0.01'})['correct']
def test_full_profiles_remain_fifty(engine):assert sum(bool(r.get('logical_rubric') or r.get('expected_calculation')) for r in engine.refs.values())==50
def test_fixed_denominator_missing_zero_success_not_fake_accuracy():
 verdicts=['correct','incorrect','not_evaluable'];assert sum(v=='correct' for v in verdicts)/3==1/3;assert sum(v=='correct' for v in verdicts)/sum(v in {'correct','incorrect'} for v in verdicts)==.5
def test_shared_context_digest(rows):
 for r in rows.values():assert r['context_digest']==digest(r['top5'])

def test_list_numbers_are_not_domain_values():
 assert numeric('建議：1. 避免投餌；2. 避免換水；3. 水溫1.5°C。')==['1.5']

def test_citation_schema_bounded_to_unique_available_ids(engine,rows):
 p,e=engine.payload(rows['FT-tilapia-Q09'],'M1')
 assert p['format']['properties']['supporting_chunk_ids']['maxItems']==len(e['supporting_chunk_ids'])

def test_duplicate_citation_still_invalid():
 with pytest.raises(jsonschema.ValidationError):jsonschema.validate({'answer':'a','answer_status':'ANSWERED_GROUNDED','supporting_chunk_ids':['a','a'],'missing_information':[]},RAW_SCHEMA)
