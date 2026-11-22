"""Synthetic unit fixtures only; never submitted to the real human audit history."""
from src.evaluation.human_support.core import digest, pairs_for


def record():
    text = '水質應定期檢查。'
    return dict(answer_id='A_test', question_id='Q_test', question='如何管理水質？', answer=text,
        answer_sha256=digest(text), citations=['C1'],
        claims=[dict(answer_id='A_test', claim_id='K_test', claim_text=text, claim_text_sha256=digest(text),
            answer_start=0, answer_end=len(text), context_heading=None, citation_binding='answer_level_only',
            linked_citations=[], answer_level_citations=['C1'], audit_citation_set=['C1'], warnings=[],
            extraction_method='synthetic_test_fixture', atomicity_human_verified=False)],
        contexts=[dict(context_id='C1', chunk_id='chunk1', document_id='doc1', page=1, text=text, content_checksum=digest(text)),
                  dict(context_id='C2', chunk_id='chunk2', document_id='doc1', page=2, text='其他 context',content_checksum=digest('其他 context'))])


def submission(r=None, support='fully_supported', atomicity='atomic'):
    r = r or record()
    return dict(atomicity=atomicity, cited_set_support=support,
        elsewhere_support='not_applicable' if support=='fully_supported' else 'not_supported_anywhere',
        elsewhere_context_ids=[], notes='synthetic test only', human_confirmed=True,
        citations=[dict(pair_id=p['pair_id'], support=support,
            elsewhere_support='not_applicable' if support=='fully_supported' else 'not_supported_anywhere',
            elsewhere_context_ids=[], provenance='valid', notes='synthetic test only') for p in pairs_for(r,r['claims'][0])])


def register(store, name='R_test', assignment='primary'):
    return store.register(name, 'synthetic unittest fixture', assignment, True)


def previous_shortlist():
    return dict(models={m:dict(status=s, schema_validity=1.0, citation_audit={'human_verified':False}) for m,s in (
        ('gemma2:9b','conditional_candidate'), ('deepseek-r1:8b','low_priority'),
        ('deepseek-r1:7b','low_priority'), ('qwen2.5-coder:7b','evaluation_unresolved'))}, no_composite_score=True)


CRITERIA = dict(qwen_conditional_min_fully_supported=.8,
    qwen_conditional_max_unsupported_by_context=.05, qwen_conditional_max_cannot_determine=.1)
