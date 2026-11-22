from src.evaluation.ragas_eval.core import METRICS


def row(qid='q1', condition='oracle', status='answered', hit=True, score=.8):
    return dict(question_id=qid, condition=condition, question='question', answer='answer',
                reference_answer='Silver reference', contexts=['evidence'], benchmark_type='silver',
                silver_reference=True, status=status, required_evidence_complete_in_top5=hit,
                species='unknown', category='fact', query_style='direct', citation_failure=False,
                metrics={m: dict(status='valid', score=score) for m in METRICS})


def export_pair():
    result = [row(condition=c) for c in ('oracle', 'e4_top5')]
    for r in result:
        for key in ('status', 'required_evidence_complete_in_top5', 'citation_failure', 'metrics'):
            r.pop(key)
    return result
