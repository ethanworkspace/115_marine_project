from __future__ import annotations

import unittest

from src.evaluation.generation.protocol_v22 import same_generation_config


class G0G1SameGenerationConfigTests(unittest.TestCase):
    def test_conditions_share_all_generation_settings(self) -> None:
        shared = {"generator": {"model": "gemma2:9b"}, "generation_parameters": {"num_predict": 1024},
                  "prompt_version": "generation_v2", "prompt_sha256": "p", "schema_sha256": "s",
                  "structured_output_mode": "schema", "retry_policy": {"maximum_attempts": 2}}
        self.assertTrue(same_generation_config(shared, dict(shared)))

    def test_different_budget_fails(self) -> None:
        g0 = {"generation_parameters": {"num_predict": 1024}}
        g1 = {"generation_parameters": {"num_predict": 768}}
        self.assertFalse(same_generation_config(g0, g1))


if __name__ == "__main__":
    unittest.main()
