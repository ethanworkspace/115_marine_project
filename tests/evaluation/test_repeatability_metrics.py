import unittest

from src.evaluation.generation.protocol_v2 import jaccard, normalize_answer, normalized_answer_similarity


class RepeatabilityMetricTests(unittest.TestCase):
    def test_normalized_answer_and_citation_set_metrics(self):
        self.assertEqual(normalize_answer("  ＡＢC  "), "abc")
        self.assertEqual(normalized_answer_similarity("水質正常", "水質正常"), 1.0)
        self.assertEqual(jaccard({"C1", "C2"}, {"C2"}), .5)


if __name__ == "__main__":
    unittest.main()
