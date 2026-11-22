import json
import unittest
from pathlib import Path
from phase_t_rag import PhaseTRAG

class PhaseTRAGTests(unittest.TestCase):
    def test_reranked_trace_identity_and_span_integrity(self):
        base=Path(__file__).parent.parent
        rows=[json.loads(x) for x in (base/'retrieval_results_v3.jsonl').read_text(encoding='utf-8').splitlines() if x.strip()]
        self.assertEqual(len(rows),180)
        self.assertEqual(len({r['question_id'] for r in rows}),180)
        for r in rows:
            self.assertEqual(len(r['reranked_top5']),r['final_top5_count'])
            self.assertLessEqual(r['final_top5_count'],5)
            ids=set()
            for i,c in enumerate(r['reranked_top5'],1):
                self.assertEqual(c['rank'],i)
                self.assertNotIn(c['chunk_id'],ids); ids.add(c['chunk_id'])
                self.assertTrue(c['source_id'] and c['source_sha256'])
                self.assertTrue(c['page'] is not None or c['locator'])
                self.assertTrue(c['content_sha256'])

    def test_answer_fails_closed_without_verified_reference(self):
        obj=object.__new__(PhaseTRAG)
        result=obj.answer({'question_text':'test'},'deepseek-r1:7b',answer_gate={'answer_verified':False,'support_sufficient':False})
        self.assertEqual(result['status'],'insufficient_evidence')
        self.assertFalse(result['generator_called'])

    def test_evaluation_generator_file_is_empty(self):
        p=Path(__file__).parent.parent/'generator_results_v3.jsonl'
        self.assertTrue(p.exists()); self.assertEqual(p.stat().st_size,0)

if __name__=='__main__': unittest.main()
