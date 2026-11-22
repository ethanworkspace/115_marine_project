import unittest
from collections import Counter
from src.evaluation.generation_models.runner import select_new_repeat

class Phase17JudgeSubsetTests(unittest.TestCase):
    def fixtures(self):
        return [{'generator': m, 'condition': c, 'question_id': str(i), 'status': 'answered',
                 'judge_conflict': False, 'species': str(i%3), 'category': str(i%4), 'query_style': str(i%3)}
                for m in ('deepseek-r1:7b','deepseek-r1:8b') for c in ('oracle','e4_top5') for i in range(20)]
    def test_30_balanced_and_deterministic(self):
        a=self.fixtures(); picked=select_new_repeat(a)
        self.assertEqual(len(picked),30)
        self.assertEqual(Counter(r['generator'] for r in picked),{'deepseek-r1:7b':15,'deepseek-r1:8b':15})
        self.assertEqual(picked,select_new_repeat(list(reversed(a))))
    def test_conflicted_and_invalid_output_not_selected(self):
        a=self.fixtures(); bad=dict(a[0],judge_conflict=True,generator='qwen2.5-coder:7b')
        a.append(bad); a.append(dict(bad,judge_conflict=False,status='generation_error'))
        self.assertFalse(any(r['generator']=='qwen2.5-coder:7b' for r in select_new_repeat(a)))
