from copy import deepcopy
from src.evaluation.generation_models.core import COMMON_OPTIONS

def manifest():
    return {'generators': [{'name': 'gemma2:9b', 'digest': 'g', 'availability': 'available'}, {'name': 'other', 'digest': 'x', 'availability': 'available'}], 'generation_options': dict(COMMON_OPTIONS), 'question_count': 169, 'maximum_attempts': 2}

def row(qid='q1', condition='e4_top5', score=.5):
    return {'question_id': qid, 'condition': condition, 'question': 'Q', 'reference_answer': 'R', 'contexts': ['evidence'], 'context_provenance': [{'context_id': 'C1', 'chunk_id': 'c', 'document_id': 'd', 'page': 1}], 'status': 'answered', 'required_evidence_complete_in_top5': True, 'metrics': {m: {'status': 'valid', 'score': score} for m in ('faithfulness', 'answer_relevancy', 'silver_reference_correctness')}, 'deterministic_generation': {'silver_reference_similarity': {'f1': score}, 'required_evidence_citation': {'strict_recall_all_questions': score}}}
