from src.evaluation.validity.core import MODELS, CONDITIONS, digest


def row(model=MODELS[0], condition='e4_top5', number=0, answer='水質應定期檢查。'):
    text='水質應定期檢查。溶氧濃度為 5.5 mg/L。'
    return {'generator':model,'condition':condition,'question_id':f'q{number:03d}',
        'question':'應如何管理水質？','answer':answer,'status':'answered',
        'query_style':('direct','paraphrase','contextual')[number%3],
        'category':('fact','water_quality','disease','climate','sop')[number%5],
        'species':('吳郭魚','石斑魚','鰻魚')[number%3],'difficulty':'easy',
        'required_evidence_complete_in_top5':number%4!=0,
        'contexts':[text],'context_provenance':[{'context_id':'C1','chunk_id':'chunk1',
            'document_id':'doc1','page':2,'content_checksum':digest(text)}],
        'metrics':{'faithfulness':{'status':'valid','score':(.3,.6,.9)[number%3]}},
        'deterministic_generation':{'citations':['C1'],'required_evidence_citation':
            {'strict_recall_all_questions':float(number%2)},'schema_valid':True}}


def rows():
    return [row(m,c,n) for m in MODELS for c in CONDITIONS for n in range(72)]
