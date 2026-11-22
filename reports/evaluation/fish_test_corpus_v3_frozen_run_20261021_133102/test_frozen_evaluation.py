import json,sys,collections,hashlib,sqlite3
from pathlib import Path
import pytest
W=Path(__file__).resolve().parent;sys.path.insert(0,str(W))
from frozen_runner import FrozenRag,digest,SCHEMA
from score_frozen_run import arithmetic
@pytest.fixture(scope='module')
def rt():return FrozenRag()
def test_frozen_original_ids(rt):
 assert len(rt.rows)==180 and len(rt.questions)==180 and len(rt.refs)==180
 assert all(r['question']==rt.questions[r['question_id']]['question_text'] for r in rt.rows)
def test_species_counts(rt):assert set(collections.Counter(r['species'] for r in rt.rows).values())=={30}
def test_full_source_qualifications(rt):
 assert sum(bool(r.get('logical_rubric')) for r in rt.refs.values())==37
 assert sum(bool(r.get('expected_calculation')) for r in rt.refs.values())==13
 assert sum(r.get('reference_answer') is not None and r.get('evidence_verification_level')=='ANSWERABLE_AUTO_SOURCE_CHECKED' for r in rt.refs.values())==50
def test_context_digests_and_ids(rt):
 for r in rt.rows:
  assert r['context_digest']==digest(r['top5'])
  assert len(r['top5'])<=5
  assert len({c['chunk_id'] for c in r['top5']})==len(r['top5'])
  assert all(c['question_id']==r['question_id'] for c in r['top5'])
@pytest.mark.parametrize('mid',['M1','M2','M3','M4'])
def test_generator_context_and_schema_same(rt,mid):
 r=rt.rows[0];p,d,_=rt.payload(r,mid);p0,_,_=rt.payload(r,'M1')
 assert p['prompt']==p0['prompt'] and p['format']==p0['format'] and p['options']==p0['options']
 assert p['format']['properties']['citations']['items']['enum']==[c['chunk_id'] for c in r['top5']]
def test_invalid_json_cannot_be_model_success(rt):
 r=rt.retrieval['FT-milkfish-Q04'];d,p=rt.decision(r);x=rt.postprocess(r,'invalid',d,p)
 assert not x['raw_model_structure_valid'] and x['answer_origin']!='MODEL_GENERATED'
def test_wrong_citation_raw_json_still_structural_success(rt):
 r=rt.retrieval['FT-milkfish-Q04'];d,p=rt.decision(r);x=rt.postprocess(r,json.dumps({'answer':'1.3 kg/m³','abstained':False,'reason':'','citations':['WRONG']}),d,p)
 assert x['raw_model_structure_valid'] and x['raw_citation_validation']['status']=='FAIL' and x['answer_origin']!='MODEL_GENERATED'
def test_partial_context_safety_kept(rt):
 r=rt.retrieval['FT-tilapia-Q01'];d,p=rt.decision(r);x=rt.postprocess(r,json.dumps({'answer':'28°C一定安全','abstained':False,'reason':'','citations':[r['top5'][0]['chunk_id']]}),d,p)
 assert x['final_response']['abstained'] and x['system_safety_gate_triggered']
def test_abstentions_not_arithmetic_zero(rt):
 ref=rt.refs['FT-mullet-Q19'];g={'run_id':'test','question_id':ref['question_id'],'model_id':'M2','source_group_ids':[],'answer_origin':'ABSTAINED','raw_model_response':json.dumps({'answer':'證據不足','abstained':True})}
 assert arithmetic(g,ref,'model')['verdict']=='not_evaluable'
@pytest.mark.parametrize('qid,answer',[('FT-mullet-Q19','3萬尾'),('FT-milkfish-Q19','最多780公斤'),('FT-tilapia-Q25','低0.8°C'),('FT-eel-Q26','共有4個間隔')])
def test_decimal_reference(rt,qid,answer):
 g={'run_id':'test','question_id':qid,'model_id':'M2','source_group_ids':[],'answer_origin':'MODEL_GENERATED','raw_model_response':json.dumps({'answer':answer,'abstained':False})}
 assert arithmetic(g,rt.refs[qid],'model')['verdict']=='correct'
def test_p5_n_remains_12():
 p=json.loads((W/'context_precision_label_status.json').read_text(encoding='utf-8'))
 assert len([r for r in p['questions'] if r['p_at_5'] is not None])==12
 assert sum(r['p_at_5'] for r in p['questions'] if r['p_at_5'] is not None)/12==pytest.approx(.3)
def test_unverified_not_rewritten():
 rs=[json.loads(x) for x in (W/'retrieved_chunk_support_labels.jsonl').read_text(encoding='utf-8').splitlines()]
 assert sum(r['support_label']=='UNVERIFIED' for r in rs)==303
def test_retrieval_miss_preserved(rt):
 ref=rt.refs['FT-grouper-Q16'];r=rt.retrieval['FT-grouper-Q16'];assert ref['reference_answer'] is not None
 assert not set(s['chunk_id'] for s in ref['evidence_spans'])<=set(c['chunk_id'] for c in r['top5'])
