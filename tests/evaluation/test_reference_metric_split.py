import unittest
from src.evaluation.validity.core import REFERENCE_INDEPENDENT,REFERENCE_DEPENDENT


class MetricSplitTest(unittest.TestCase):
    def test_disjoint(self):
        self.assertFalse(set(REFERENCE_INDEPENDENT)&set(REFERENCE_DEPENDENT))

    def test_reference_metric_names(self):
        self.assertIn('silver_reference_correctness',REFERENCE_DEPENDENT)
        self.assertIn('faithfulness',REFERENCE_INDEPENDENT)
        self.assertNotIn('calculation_numeric_match',REFERENCE_DEPENDENT)
