import json
from fair_grounded_rag_final import FairRag,W,jl
def test_known_partial_gap_is_added_without_rewriting_raw_model():
 rt=FairRag();r=next(r for r in jl(W/'shared_contexts_180.jsonl') if r['question_id']=='FT-tilapia-Q01');e=rt.evidence(r);assert e['state']=='EVIDENCE_PARTIAL'
 p={'answer':'28°C在吳郭魚的最適成長溫度範圍內。','answer_status':'ANSWERED_GROUNDED','supporting_chunk_ids':e['supporting_chunk_ids'],'missing_information':[]}
 out,v=rt.postprocess(r,'M4',json.dumps(p,ensure_ascii=False),e)
 assert out['answer_status']=='ANSWERED_PARTIAL' and out['missing_information'] and out['validation_status']['system_added_missing_information']
 assert not out['validation_status']['raw_partial_disclosure_valid'] and v['parsed_model_response']['missing_information']==[] and v['parsed_model_response']['answer_status']=='ANSWERED_GROUNDED'
 assert out['raw_model_answer']==p['answer']
def test_partial_gap_completion_cannot_accept_unsupported_values():
 rt=FairRag();r=next(r for r in jl(W/'shared_contexts_180.jsonl') if r['question_id']=='FT-tilapia-Q01');e=rt.evidence(r)
 p={'answer':'77°C是最適溫。','answer_status':'ANSWERED_GROUNDED','supporting_chunk_ids':e['supporting_chunk_ids'],'missing_information':[]}
 out,v=rt.postprocess(r,'M4',json.dumps(p,ensure_ascii=False),e);assert out['answer_status']=='VALIDATION_FAILED'
