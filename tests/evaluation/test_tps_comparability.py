import unittest

from src.evaluation.phase20_protocol import tps_comparable


class TPSComparabilityTests(unittest.TestCase):
    def test_reasoning_and_visible_tps_semantics_must_match(self):
        rows = [{"tps_definition": "runtime_eval_count", "reasoning_separation_reliable": True} for _ in range(4)]
        self.assertTrue(tps_comparable(rows))
        rows[0]["reasoning_separation_reliable"] = False
        self.assertFalse(tps_comparable(rows))


if __name__ == "__main__":
    unittest.main()
