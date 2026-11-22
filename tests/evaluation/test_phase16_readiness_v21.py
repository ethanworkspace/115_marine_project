from __future__ import annotations

import unittest

from src.evaluation.generation.retry_v21 import readiness


def summary(*, schema: float = 1.0, citation_parse: float = 1.0, strict: float = 0.95,
            taxonomy: dict[str, int] | None = None) -> dict:
    return {"raw_output_preservation_rate": 1.0, "schema_valid_rate": schema,
            "citation_parse_rate": citation_parse, "strict_citation_validity_rate": strict,
            "citation_error_taxonomy": taxonomy or {}}


class Phase16ReadinessV21Tests(unittest.TestCase):
    def test_ready_requires_every_final_gate(self) -> None:
        result = readiness(g0_summary=summary(), g1_summary=summary(), all_raw_attempts_preserved=True)
        self.assertTrue(result["phase16_generation_ready"])

    def test_retry_does_not_hide_first_pass_failures_but_final_gates_decide_readiness(self) -> None:
        result = readiness(g0_summary=summary(), g1_summary=summary(schema=.988, citation_parse=.988),
                           all_raw_attempts_preserved=True)
        self.assertFalse(result["phase16_generation_ready"])

    def test_missing_attempt_integrity_blocks_readiness(self) -> None:
        result = readiness(g0_summary=summary(), g1_summary=summary(), all_raw_attempts_preserved=False)
        self.assertFalse(result["phase16_generation_ready"])


if __name__ == "__main__":
    unittest.main()
