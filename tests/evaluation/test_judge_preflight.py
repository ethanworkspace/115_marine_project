import unittest

from src.evaluation.phase20_1_protocol import judge_preflight_ready


class JudgePreflightTests(unittest.TestCase):
    def test_requires_two_complete_parseable_30_output_passes(self):
        report = {
            "judge_digest": "e" * 64, "calibration_target": 30,
            "first_pass_completed": 30, "second_pass_completed": 30,
            "schema_parse_rate": 1.0, "truncation_count": 0,
            "technical_failure_count": 0, "metrics_parseable": True,
        }
        self.assertTrue(judge_preflight_ready(report, ["a" * 64, "b" * 64, "c" * 64, "d" * 64]))
        report["second_pass_completed"] = 29
        self.assertFalse(judge_preflight_ready(report, ["a" * 64, "b" * 64, "c" * 64, "d" * 64]))


if __name__ == "__main__":
    unittest.main()
