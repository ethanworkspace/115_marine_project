import unittest
from src.evaluation.phase20_1r_protocol import judge_calibration_ready

class JudgeCalibrationTests(unittest.TestCase):
    def test_both_full_passes_and_zero_failures_are_required(self):
        judge={"artifact_digest":"b"*64,"is_candidate":False}
        candidates=[{"artifact_digest":"a"*64}]
        calibration={"target_outputs":30,"first_pass_completed":30,"second_pass_completed":30,"first_pass_schema_parse_rate":1.0,"second_pass_schema_parse_rate":1.0,"technical_failure_count":0,"completion_truncation_count":0}
        self.assertTrue(judge_calibration_ready(judge,calibration,candidates))
        calibration["completion_truncation_count"]=1
        self.assertFalse(judge_calibration_ready(judge,calibration,candidates))
