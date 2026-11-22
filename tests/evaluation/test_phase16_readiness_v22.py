from __future__ import annotations

import unittest

from src.evaluation.generation.protocol_v22 import readiness_v22


def summary() -> dict:
    return {"raw_output_preservation_rate": 1, "schema_valid_rate": 1, "citation_parse_rate": 1,
            "strict_citation_validity_rate": .99, "citation_error_taxonomy": {}}


class Phase16ReadinessV22Tests(unittest.TestCase):
    def test_missing_or_truncated_input_blocks_readiness(self) -> None:
        audit = [{"condition": condition, "input_truncated": False, "remaining_context_margin": 2000}
                 for condition in ("G0", "G1")]
        self.assertTrue(readiness_v22(g0_summary=summary(), g1_summary=summary(),
                                     attempts_preserved=True, budget_audits=audit)["phase16_generation_ready"])
        audit[0]["input_truncated"] = True
        self.assertFalse(readiness_v22(g0_summary=summary(), g1_summary=summary(),
                                      attempts_preserved=True, budget_audits=audit)["phase16_generation_ready"])


if __name__ == "__main__":
    unittest.main()
