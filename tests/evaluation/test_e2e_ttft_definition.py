import unittest
from src.evaluation.edge.core19b import e2e_ttft_ms

class TTFTTest(unittest.TestCase):
    def test_starts_at_question_accepted_excludes_reasoning(self):
        events=[dict(monotonic=11,thinking='reasoning'),dict(monotonic=14,content='{')]
        self.assertEqual(e2e_ttft_ms(10,events),4000)
    def test_no_content_means_unmeasurable(self):
        self.assertIsNone(e2e_ttft_ms(10,[dict(monotonic=11,thinking='reasoning')]))
