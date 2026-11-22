import unittest
from collections import Counter
from src.evaluation.validity.core import edge_subset
from tests.evaluation.phase18_fixtures import rows


class EdgeSubsetTest(unittest.TestCase):
    def test_fixed_60_coverage(self):
        a,c=edge_subset(rows());b,d=edge_subset(list(reversed(rows())))
        self.assertEqual([r['question_id'] for r in a],[r['question_id'] for r in b])
        self.assertEqual(c,d);self.assertEqual(len(a),60)
        self.assertEqual(set(Counter(r['query_style'] for r in a).values()),{20})
        self.assertEqual(len({r['question_id'] for r in a}),60)

    def test_same_context_not_modified(self):
        r=rows();before=str(r);edge_subset(r)
        self.assertEqual(str(r),before)
