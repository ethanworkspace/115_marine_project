import unittest
from collections import Counter
from src.evaluation.edge.inputs import load_bundle
from src.evaluation.edge.core import summary


class ContextGroupsTest(unittest.TestCase):
    def test_original_bands_not_resampled(self):
        rows,m=load_bundle()
        self.assertEqual(Counter(r['subset_row']['context_band'] for r in rows),{'short':20,'medium':21,'long':19})

    def test_unmeasured_values_null_with_denominator(self):
        s=summary([],180)
        self.assertIsNone(s['mean']);self.assertIsNone(s['p95']);self.assertEqual(s['n_missing'],180)

    def test_per_model_native_context_kept_separate_from_experiment(self):
        import json
        from src.evaluation.edge.inputs import OUT
        m=json.loads((OUT/'model_manifests/qwen2.5-coder_7b.json').read_text(encoding='utf-8'))
        self.assertEqual(m['native_context_length'],32768);self.assertEqual(m['experimental_context_length'],8192)
