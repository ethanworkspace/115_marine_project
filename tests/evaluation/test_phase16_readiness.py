import unittest

from src.evaluation.generation.runner_v2 import _readiness


def summary(schema=1.0, parse=1.0, strict=1.0, raw=1.0, alias=0):
    return {
        "raw_output_preservation_rate": raw, "schema_valid_rate": schema,
        "citation_parse_rate": parse, "strict_citation_validity_rate": strict,
        "citation_error_taxonomy": {"chunk_id_in_context": alias},
    }


class Phase16ReadinessTests(unittest.TestCase):
    def test_all_thresholds_must_pass(self):
        self.assertTrue(_readiness({"G0": summary(), "G1": summary()})["phase16_generation_ready"])
        self.assertFalse(_readiness({"G0": summary(), "G1": summary(strict=.94)})["phase16_generation_ready"])
        self.assertFalse(_readiness({"G0": summary(), "G1": summary(alias=1)})["phase16_generation_ready"])


if __name__ == "__main__":
    unittest.main()
