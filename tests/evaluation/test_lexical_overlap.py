import unittest

from src.evaluation.grounded.pipeline import lexical_overlap


class LexicalOverlapTests(unittest.TestCase):
    def test_direct_question_has_more_overlap_than_unrelated_question(self):
        evidence = "吳郭魚養殖資料記載池塘管理需要保持水質穩定，並定期觀察魚群攝食狀況。"
        direct = lexical_overlap("吳郭魚池塘管理要觀察魚群什麼狀況？", evidence)
        unrelated = lexical_overlap("鰻魚病害如何診斷與治療？", evidence)
        self.assertGreater(direct, unrelated)
        self.assertGreaterEqual(direct, 0)
        self.assertLessEqual(direct, 1)


if __name__ == "__main__":
    unittest.main()

