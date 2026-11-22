import unittest
from src.evaluation.edge.core19b import frozen_context_check

class FrozenContextTest(unittest.TestCase):
    def contexts(self):return [dict(context_id='C'+str(i+1),chunk_id=str(i),document_id='doc',page=i,text='evidence') for i in range(5)]
    def test_content_and_provenance_match(self):
        self.assertTrue(frozen_context_check(self.contexts(),self.contexts()))
    def test_no_text_or_order_change(self):
        rows=self.contexts();rows[0]['text']='changed'
        self.assertFalse(frozen_context_check(self.contexts(),rows))
        self.assertFalse(frozen_context_check(self.contexts(),self.contexts()[::-1]))
