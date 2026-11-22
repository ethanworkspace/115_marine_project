import unittest

from src.evaluation.generation.protocol_v2 import context_map


class ContextIdMappingTests(unittest.TestCase):
    def test_context_order_deterministically_maps_source_provenance(self):
        contexts = [
            {"context_id": "C1", "chunk_id": "a", "document_id": "doc-a", "page": 2, "text": "one"},
            {"context_id": "C2", "chunk_id": "b", "document_id": "doc-b", "page": 8, "text": "two"},
        ]
        mapping = context_map(contexts)
        self.assertEqual(mapping["C1"]["chunk_id"], "a")
        self.assertEqual(mapping["C2"]["page"], 8)
        with self.assertRaises(ValueError):
            context_map([contexts[0], dict(contexts[1], context_id="C1")])


if __name__ == "__main__":
    unittest.main()
