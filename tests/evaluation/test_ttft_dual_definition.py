import unittest
from tests.evaluation.edge_fixtures import target,FakeSession,events
from src.evaluation.edge.runtime import OllamaEdge
class TtftTest(unittest.TestCase):
    def test_thinking_not_final(self):
        r=OllamaEdge(target(),session=FakeSession(events())).generation(model='synthetic',system_prompt='s',user_prompt='q',schema={},thinking_capable=True)
        self.assertLessEqual(r['ttft_any_token_seconds'],r['ttft_final_answer_seconds'])
        self.assertFalse(r['token_metrics']['reasoning_token_separation_available']);self.assertIsNone(r['token_metrics']['visible_answer_tps'])
