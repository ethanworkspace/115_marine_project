import unittest

from src.evaluation.phase20_protocol import validate_calculation_record


class CalculationGoldTests(unittest.TestCase):
    def test_numeric_gold_requires_deterministic_formula_evidence(self):
        record = {"formula": "V*d", "input": {"V": 4, "d": 2}, "unit": "kg",
                  "expected_numeric_output": 8, "rounding": "none", "tolerance": 0,
                  "evidence": {"chunk_id": "c1"}, "gold_answer_source": "deterministic_code"}
        self.assertEqual(validate_calculation_record(record), [])
        record["gold_answer_source"] = "candidate_llm"
        self.assertIn("candidate_llm_cannot_create_numeric_gold", validate_calculation_record(record))


if __name__ == "__main__":
    unittest.main()
