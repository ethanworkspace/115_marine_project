import importlib.util
import json
import pathlib

script = pathlib.Path(__file__).with_name('annotation_pipeline_repaired.py')
spec = importlib.util.spec_from_file_location('annotation_pipeline_repaired', script)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

passages = [
    {'top5_rank': 1, 'chunk_id': 'c1', 'document_id': 'd1', 'text': '烏魚最適水溫為20至28度。', 'source_title': '烏魚資料', 'source_species_label': '烏魚'},
    {'top5_rank': 2, 'chunk_id': 'c2', 'document_id': 'd2', 'text': '吳郭魚適合水溫28°C。', 'source_title': '吳郭魚資料', 'source_species_label': '吳郭魚'},
    {'top5_rank': 3, 'chunk_id': 'c3', 'document_id': 'd3', 'text': '石斑魚是海水魚。', 'source_title': '石斑魚資料', 'source_species_label': '石斑魚'},
    {'top5_rank': 4, 'chunk_id': 'c4', 'document_id': 'd4', 'text': '鰻魚為降河洄游魚類。', 'source_title': '鰻魚資料', 'source_species_label': '鰻魚'},
    {'top5_rank': 5, 'chunk_id': 'c5', 'document_id': 'd5', 'text': '虱目魚常見養殖於魚塭。', 'source_title': '虱目魚資料', 'source_species_label': '虱目魚'},
]
base = {'label': 'IRRELEVANT', 'reason_code': 'species_mismatch', 'reason': '來源物種與問題不同。', 'species_applicability': 'mismatch', 'quoted_evidence': ''}
obj = {'passages': [dict(base) for _ in range(5)], 'answer_support_sufficiency': 'partial', 'answer_support_reason': '只有一段直接提到問題魚種。'}
obj['passages'][1] = {'label': 'RELEVANT', 'reason_code': 'direct_support', 'reason': '段落直接說明吳郭魚水溫。', 'species_applicability': 'direct', 'quoted_evidence': '吳郭魚適合水溫28°C。'}
clean = module.validate_obj(obj, passages, '吳郭魚')
assert [x['rank'] for x in clean] == [1, 2, 3, 4, 5]
assert [x['chunk_id'] for x in clean] == ['c1', 'c2', 'c3', 'c4', 'c5']
assert clean[1]['quote_exact'] is True and clean[1]['exact_span_start'] == 0
assert clean[0]['label'] == 'IRRELEVANT' and clean[0]['species_applicability'] == 'mismatch'

bad_extra = json.loads(json.dumps(obj))
bad_extra['unexpected'] = True
try:
    module.validate_schema(bad_extra)
    raise AssertionError('extra root key was accepted')
except ValueError:
    pass

bad_missing = json.loads(json.dumps(obj))
del bad_missing['passages'][0]['reason']
try:
    module.validate_schema(bad_missing)
    raise AssertionError('missing required key was accepted')
except (ValueError, KeyError):
    pass

bad_quote = json.loads(json.dumps(obj))
bad_quote['passages'][1]['quoted_evidence'] = '烏魚最適水溫為20至28度。'
try:
    module.validate_obj(bad_quote, passages, '吳郭魚')
    raise AssertionError('cross-rank quote was accepted')
except ValueError as e:
    assert 'quote not exact' in str(e)

print(json.dumps({'status': 'passed', 'checks': ['program_bound_rank_chunk_ids', 'exact_quote_span', 'explicit_species_mismatch_guard', 'reject_extra_schema_key', 'reject_missing_schema_key', 'reject_cross_rank_quote'], 'external_judge_called': False}, ensure_ascii=False))
