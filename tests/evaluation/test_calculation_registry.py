import unittest

from src.evaluation.phase20_1_protocol import calculation_registry_ready


class CalculationRegistryTests(unittest.TestCase):
    def test_empty_registry_is_not_ready(self):
        self.assertFalse(calculation_registry_ready([]))


if __name__ == "__main__":
    unittest.main()
