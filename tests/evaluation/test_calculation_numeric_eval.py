import unittest

from src.evaluation.generation.evaluation import calculation_numeric_evaluation


class CalculationNumericTests(unittest.TestCase):
    def test_uses_existing_deterministic_calculation_spec(self):
        spec = {"formula": "biomass_kg * rate_percent / 100", "biomass_kg": 100, "rate_percent": [2, 5], "result_kg": [2, 5]}
        report = calculation_numeric_evaluation("投餌量為 2 至 5 kg。", spec)
        self.assertTrue(report["exact_numeric_match"])

    def test_does_not_apply_unknown_formula(self):
        self.assertEqual(calculation_numeric_evaluation("12", {"formula": "unknown"})["status"], "unsupported_spec")


if __name__ == "__main__":
    unittest.main()
