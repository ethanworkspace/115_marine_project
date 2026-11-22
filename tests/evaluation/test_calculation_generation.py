import unittest

from src.evaluation.grounded.pipeline import build_calculation_answer, extract_simple_feed_rate
from tests.evaluation.grounded_fixtures import make_evidence, make_corpus_record


class CalculationGenerationTests(unittest.TestCase):
    def test_only_explicit_feed_percentage_is_recognized_and_calculated_deterministically(self):
        row = make_corpus_record(
            "feed",
            text="魚體重量2～5%作為投料基準，投餌量應依資料範圍估算。",
        )
        evidence = make_evidence(row)
        formula = extract_simple_feed_rate(evidence)
        self.assertIsNotNone(formula)
        low, high, _quote = formula
        result = build_calculation_answer(100, low, high)
        self.assertEqual(result["result_kg"], [2.0, 5.0])
        self.assertEqual(result["reference_answer"], "依據證據中的魚體重量投料比例 2%–5%，100 kg × 2%–5% = 2–5 kg。")

    def test_no_formula_means_no_calculation(self):
        row = make_corpus_record("plain")
        self.assertIsNone(extract_simple_feed_rate(make_evidence(row)))


if __name__ == "__main__":
    unittest.main()

