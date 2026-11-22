"""Conservative website presentation guard; never rewrites research raw outputs.

Citation existence is not claim entailment. This bounded check blocks unrequested
management numbers and medication advice without a verified indication protocol.
It does not claim to establish scientific correctness for all other prose.
"""
from copy import deepcopy
import re

VERSION = 'website-answer-guard-v1'
MEDICATION = re.compile(r'用[藥药]|[藥药](?:品|物|劑|剂)|有[機机]磷|[四季]級[銨铵]|[四季]级[銨铵]|抗生素|停[藥药]')
MANAGEMENT = re.compile(r'放[養养]密度|每公[頃顷]|水[溫温]|適[溫温]|[鹽盐]度|[濃浓]度|溶氧|pH|投[餌饵]|飼料|饲料|[劑剂]量')
NUMERIC_QUESTION = re.compile(r'多少|幾|几|數值|数值|範圍|范围|密度|溫|温|[鹽盐]度|濃度|浓度|溶氧|pH|比例|頻率|频率|投[餌饵]|飼料|饲料|計算|计算|重量|體重|体重|尺寸|[0-9]')


def protect_website_answer(record):
    result = record.get('result', {})
    if result.get('answer_status') not in ('ANSWERED_GROUNDED', 'ANSWERED_PARTIAL'):
        return record
    answer = str(result.get('final_answer', ''))
    question = str(record.get('question') or record.get('question_payload', {}).get('question') or '')
    reasons = []
    if MEDICATION.search(answer):
        # Current public adapter has no independently verified drug/indication,
        # current permit, dose and withdrawal protocol bundle. Fail closed.
        reasons.append('MEDICATION_PROTOCOL_NOT_INDEPENDENTLY_VERIFIED')
    if not NUMERIC_QUESTION.search(question):
        for sentence in re.split(r'[。；;\n]', answer):
            if MANAGEMENT.search(sentence) and re.search(r'[0-9０-９]', sentence):
                reasons.append('UNREQUESTED_MANAGEMENT_NUMERIC_CLAIM')
                break
    if not reasons:
        return record
    guarded = deepcopy(record)
    final = guarded['result']
    final.update(answer_status='VALIDATION_FAILED', answer_origin='VALIDATION_FAILED',
                 final_answer='這次回答包含尚未充分核實的管理數值或用藥內容，已暫停顯示。請補充魚種、養殖條件與需要查核的項目，或切換其他模型重新提問。',
                 supporting_chunk_ids=[], missing_information=['需要逐項核對數值、適用魚種及用藥依據。'])
    final.setdefault('validation_status', {})['website_claim_guard'] = {
        'version': VERSION, 'passed': False, 'reasons': reasons,
        'raw_model_answer_preserved': True, 'semantic_correctness_guaranteed': False}
    # Do not publish uncited context/media as support for the blocked answer.
    guarded.setdefault('question_payload', {})['top5'] = []
    return guarded
