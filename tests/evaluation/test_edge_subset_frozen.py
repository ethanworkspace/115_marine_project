import json
import unittest
from collections import Counter
from pathlib import Path
from src.evaluation.edge.inputs import load_bundle,SUBSET
from src.evaluation.generation.frozen import sha256_file


class SubsetFrozenTest(unittest.TestCase):
    def test_frozen_file_checksum_preserved(self):
        rows,m=load_bundle()
        self.assertEqual(sha256_file(SUBSET),m['source_subset_sha256'])
        self.assertEqual(m['source_subset_sha256'],'ad948e43888fb15c985b2aa49d8d911dd03b8e2e057922c5389694f4eec1edcf')
        self.assertEqual(len(rows),60)

    def test_order_and_styles_identical(self):
        rows,m=load_bundle()
        self.assertEqual([r['question']['question_id'] for r in rows],m['question_ids'])
        self.assertEqual(Counter(r['subset_row']['query_style'] for r in rows),{'direct':20,'paraphrase':20,'contextual':20})

    def test_no_resampling_implementation(self):
        source=Path('src/evaluation/edge/inputs.py').read_text(encoding='utf-8')
        self.assertNotIn('coverage_sample(',source);self.assertNotIn('edge_subset(',source)
