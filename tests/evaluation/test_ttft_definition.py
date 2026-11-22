import unittest
from src.evaluation.edge.runtime import OllamaEdge
from src.evaluation.edge.core import TTFT_DEFINITION
from tests.evaluation.edge_fixtures import target,FakeSession,events


class TTFTTest(unittest.TestCase):
    def test_thinking_is_not_final_content(self):
        client=FakeSession(events());adapter=OllamaEdge(target(),session=client)
        r=adapter.generation(model='synthetic',system_prompt='fixed',user_prompt='fixed',schema={},thinking_capable=True)
        self.assertGreaterEqual(r['ttft_final_answer_seconds'],r['ttft_any_token_seconds'])
        self.assertEqual(r['ttft_definition'],TTFT_DEFINITION)
        self.assertEqual(r['raw_thinking'],'synthetic thought')

    def test_inline_reasoning_final_ttft_unknown_no_silent_cleaning(self):
        es=events();es[1]['message']['content']='<think>synthetic</think>'+es[1]['message']['content']
        adapter=OllamaEdge(target(),session=FakeSession(es))
        r=adapter.generation(model='synthetic',system_prompt='fixed',user_prompt='fixed',schema={},thinking_capable=True)
        self.assertIsNone(r['ttft_final_answer_seconds']);self.assertIsNotNone(r['parse_error'])
        self.assertIn('<think>',r['raw_output'])

    def test_input_has_no_reference_or_required_flags(self):
        client=FakeSession(events());adapter=OllamaEdge(target(),session=client)
        adapter.generation(model='synthetic',system_prompt='fixed',user_prompt='fixed',schema={})
        body=client.bodies[0]
        self.assertEqual(body['options']['num_predict'],1024)
        self.assertNotIn('reference_answer',body);self.assertNotIn('required_chunks',body)
