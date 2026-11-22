import unittest
from src.evaluation.edge.exec19b_r2 import primary_rows

class Exclusion(unittest.TestCase):
    def test_partial_kept_out(self):
        blocks=[{'run_id':'partial','completed':False,'runtime_valid':True,'question_ids':[0]},
                {'run_id':'fresh','completed':True,'runtime_valid':True,'question_ids':list(range(60))}]
        rows=[{'run_id':'partial','stage':'formal'},{'run_id':'fresh','stage':'formal'},
              {'run_id':'fresh','stage':'sustained'}]
        self.assertEqual(primary_rows(rows,blocks,range(60)),[rows[1]])
    def test_no_implicit_union_of_partials(self):
        blocks=[{'run_id':str(i),'completed':False,'runtime_valid':True,'question_ids':list(range(i*30,(i+1)*30))} for i in (0,1)]
        self.assertEqual(primary_rows([{'run_id':'0','stage':'formal'}],blocks,range(60)),[])
