from pathlib import Path
import json,sqlite3,sys,hashlib
import pytest
W=Path(__file__).resolve().parent;sys.path.insert(0,str(W))
from rag_v3_runtime import RagV3Runtime
import retrieve_and_verify_180 as r
def jl(n):return [json.loads(s) for s in (W/n).read_text(encoding='utf-8').splitlines()]
def test_original_question_identity():
 old=jl('questions_original_180.jsonl');new=jl('corpus_evidence_availability_180.jsonl');assert len(old)==len(new)==180
 assert {(q['question_id'],q['question_text']) for q in old}=={(q['question_id'],q['original_question']) for q in new}
def test_current_index_integrity():
 c=sqlite3.connect(W/'corpus/marine_hybrid_rag_corpus_v3.sqlite3')
 assert c.execute('pragma integrity_check').fetchone()[0]=='ok'
 assert c.execute('select count(*) from chunks where retrieval_eligible=1').fetchone()[0]==c.execute('select count(*) from chunks_fts').fetchone()[0]
 assert c.execute('select count(*) from chunks where retrieval_eligible=1 and (length(embedding)!=4096 or embedding_dimension!=1024)').fetchone()[0]==0
def test_old_snapshot_immutable():
 p=W.parents[2]/'reports/evaluation/fish_test_corpus_v3_integration_20261021_003519/corpus/marine_hybrid_rag_corpus_v3.sqlite3'
 assert hashlib.sha256(p.read_bytes()).hexdigest()=='323f9c4c1913d9d7322d695f68d021b8c20323bab30cf8a094083d8dab5cd821'
def test_source_availability_not_conditioned_on_top5():
 rows=jl('retrieval_evidence_hits_180.jsonl')
 assert all(x['corpus_evidence_availability']=='FULL_SUPPORT' for x in rows if x['gap_classification']=='SOURCE_SUPPORTED_NOT_RETRIEVED')
 assert any(x['gap_classification']=='SOURCE_SUPPORTED_NOT_RETRIEVED' for x in rows)
def test_retrieval_identity_and_original_text():
 c=sqlite3.connect(W/'corpus/marine_hybrid_rag_corpus_v3.sqlite3');c.row_factory=sqlite3.Row
 for q in jl('retrieval_results_alignment_final_180.jsonl'):
  assert [x['rank'] for x in q['top5']]==list(range(1,len(q['top5'])+1))
  assert len({x['source_record_id'] for x in q['top5']})==len(q['top5'])
  for x in q['top5']:
   row=c.execute('select * from chunks where chunk_id=?',(x['chunk_id'],)).fetchone();assert x['text']==row['text'] and x['source_record_id']==row['source_record_id'] and x['question_id']==q['question_id']
def test_full_support_source_locations():
 refs=jl('verified_reference_answers_v3.jsonl')
 for ref in refs:
  if ref.get('evidence_verification_level')!='ANSWERABLE_AUTO_SOURCE_CHECKED':continue
  assert ref['evidence_spans'] and all(s['original_quote_verified'] for s in ref['evidence_spans'])
  assert ref['human_review_status'].startswith('NOT_HUMAN_GOLD')
def test_no_accuracy_for_missing_reference():
 for ref in jl('verified_reference_answers_v3.jsonl'):
  if ref.get('reference_answer') is None:assert not ref.get('logical_rubric') and not ref.get('expected_calculation')
def test_13_old_candidates_not_all_promoted():
 rows=jl('previous_13_answers_revalidation.jsonl');assert len(rows)==13
 assert sum(x['current_evidence_verification']=='ANSWERABLE_AUTO_SOURCE_CHECKED' for x in rows)==12
def test_finite_fact_not_fulltext_index():
 rows=jl('finite_fact_provenance.jsonl')
 for x in rows:
  if 'original_expression_indexed' in x:assert x['original_expression_indexed'] is False and x['fulltext_license_claimed'] is False
@pytest.mark.parametrize('record_no',[257,414,424,470,477,495,529,928,956])
def test_other_taxa_are_blocked(record_no):
 row={'source_id':'MOA-TFRI-OPEN-114846','chunk_id':f'TFRI-114846-{record_no:04}-C01','species_scope_list':['鰻魚','虱目魚','鱸魚']}
 ok,reason=r.source_applicability(row,{'original_question':'魚的最佳水溫多少？','target_species':'鱸魚'}, {})
 assert not ok and 'OTHER_TAXON' in reason
def test_numeric_commas_do_not_reject_equivalent_value():
 assert RagV3Runtime._value_supported('5000',[{'text':'5,000尾'}])
 assert not RagV3Runtime._value_supported('6000',[{'text':'5,000尾'}])
def test_p5_denominator_and_missingness():
 x=json.loads((W/'context_precision_label_status.json').read_text(encoding='utf-8'))
 labels=jl('retrieved_chunk_support_labels.jsonl')
 for q in x['questions']:
  ls=[a for a in labels if a['question_id']==q['question_id']]
  if q['p_at_5'] is not None:
   assert len(ls)==5 and all(a['reliable_binary_label_for_exploratory_p5'] for a in ls)
   assert q['p_at_5']==sum(a['relevance_label']==1 for a in ls)/5
def test_rubric_precedes_generator_freeze():
 a=json.loads((W/'evaluation_rubrics_v3_frozen.json').read_text(encoding='utf-8'));b=json.loads((W/'runtime_evidence_profiles_frozen.json').read_text(encoding='utf-8'))
 assert a['created_at']<=b['created_at'] and a['human_gold']==0
def test_atomic_fact_keeps_multiclause_applicability():
 import importlib.util
 spec=importlib.util.spec_from_file_location('atomic_engine_test',W/'runtime/grounded_answer_engine_v2.py');m=importlib.util.module_from_spec(spec);sys.modules[spec.name]=m;spec.loader.exec_module(m)
 text='Specified scope；value1.3 kg/m3.'
 s=m.EvidenceSpan('s','c','source','snapshot','abc','abc','record/field',text,text,0,len(text),text,('fish',),'VERIFIED_EXACT',None,'RESEARCH_FACT_CARD_NONPUBLIC',True)
 p={'risk_class':'LOW_RISK_FACT','target_species':'fish','species_applicability':{'status':'VERIFIED_EXACT'},'allow_multisentence_atomic_record':True,'required_answer_elements':[{'element_id':'e','required':True,'required_literals':[text],'evidence_span_ids':['s']}]}
 d=m.assess_evidence(p,[s]);x=m.deterministic_extract(p,[s],d)
 assert x['answer_origin']=='DETERMINISTIC_EVIDENCE_EXTRACTION' and 'Specified scope' in x['final_response']['answer']
def test_calculated_answer_is_not_replaced_by_an_input_quote():
 rt=RagV3Runtime.__new__(RagV3Runtime)
 assert rt.deterministic_fallback('query','fish',{'top5':[]},{'state':'EVIDENCE_SUFFICIENT'},{'source_chunk_ids':['a'],'required_calculation':True}) is None
def test_semantic_sibling_clause_counts_as_hit_without_exact_string_equality():
 rows=jl('retrieval_evidence_hits_180.jsonl');r=next(x for x in rows if x['question_id']=='FT-eel-Q13')
 assert r['retrieval_evidence_hit'] is True and r['equivalent_quote_hits']['TFRI-114846-0348-C09']

