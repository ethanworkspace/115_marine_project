import unittest

from src.evaluation.phase20_protocol import plan_ifr


class PlanIFRTests(unittest.TestCase):
    def test_plan_ifr_is_structured_output_rate_and_empty_is_na(self):
        self.assertEqual(plan_ifr(99, 100), 0.99)
        self.assertIsNone(plan_ifr(0, 0))


if __name__ == "__main__":
    unittest.main()
