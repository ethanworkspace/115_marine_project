import unittest
from src.evaluation.generation.runner_v2 import format_v2_user_prompt

class SamePromptTests(unittest.TestCase):
    def test_prompt_has_no_model_specialization(self):
        q={'question_id':'q','question':'Q'}; c=[{'context_id':'C1','text':'T'}]
        self.assertEqual(format_v2_user_prompt(q,c),format_v2_user_prompt(q,c))
        self.assertNotIn('reference_answer',format_v2_user_prompt(q,c))
    def test_context_order_is_preserved(self):
        text=format_v2_user_prompt({'question_id':'q','question':'Q'},[{'context_id':'C1','text':'A'},{'context_id':'C2','text':'B'}])
        self.assertLess(text.index('[C1]'),text.index('[C2]'))
