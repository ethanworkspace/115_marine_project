import json
from pathlib import Path

out = Path('reports/evaluation/fish_test_phase_h/20261014_185653')
def load(name):
    return json.loads((out / name).read_text(encoding='utf-8-sig'))
def save(name, value):
    (out / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

summary = load('pilot_10_question_summary.json')
errors = [json.loads(line) for line in (out / 'pilot_annotation_errors_v2_5.jsonl').read_text(encoding='utf-8-sig').splitlines() if line.strip()]
excerpt = ''.join(a.get('raw_response_excerpt', '') for row in errors for a in row.get('attempts', []))
summary['v2_5_raw_response_replacement_character_count'] = excerpt.count('\ufffd')
summary['reason'] = ('The local Judge misattributed a passage explicitly about mullet to tilapia. At least one relevant citation failed exact source alignment; '
                     'the saved v2.5 excerpt contains no Unicode replacement characters. Strict evidence-quality gates rejected the output.')
save('pilot_10_question_summary.json', summary)

root = load('phase_g_root_cause_analysis.json')
follow = root.get('phase_h_followup', {})
pilot = follow.get('pilot', {})
pilot['v2_5_raw_response_replacement_character_count'] = excerpt.count('\ufffd')
pilot['reason'] = summary['reason']
follow['pilot'] = pilot
qc = follow.get('annotation_quality_control', {})
qc.pop('invalid_quote_encoding', None)
qc['quote_alignment'] = ('A relevant citation failed exact-source alignment. The saved v2.5 response excerpt contains no U+FFFD replacement characters; '
                         'encoding corruption is not confirmed.')
root['phase_h_followup'] = follow
save('phase_g_root_cause_analysis.json', root)

report = out / 'annotation_pipeline_fix_report.md'
body = report.read_text(encoding='utf-8-sig')
body = body.replace('v2.4/v2.5 輸出包含無法對齊的中文替換字元引文，嚴格驗證予以拒收。',
                    'v2.4/v2.5 在 exact-span 檢查拒收至少一個相關引文；保存的 v2.5 回應摘錄沒有 U+FFFD 替換字元，因此不能把問題歸因於編碼損壞。')
report.write_text(body, encoding='utf-8')
print(json.dumps({'pilot_passed': summary.get('pilot_passed'), 'replacement_char_count': excerpt.count('\ufffd')}, ensure_ascii=False))
