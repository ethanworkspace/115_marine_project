import unittest
from src.evaluation.edge.core19b import process_roles

class ProcessTreeTest(unittest.TestCase):
    def test_llama_server_not_missed(self):
        rows=[dict(pid=1,name='python.exe',parent_pid=0),dict(pid=2,name='ollama.exe',parent_pid=0),
              dict(pid=3,name='llama-server.exe',parent_pid=2),dict(pid=4,name='python.exe',parent_pid=1)]
        result={r['pid']:r for r in process_roles(rows,1,4)}
        self.assertIn('ollama_model_runner',result[3]['roles']);self.assertIn('reranker_python',result[4]['roles'])
    def test_descendants_explicitly_observed(self):
        rows=[dict(pid=1,name='python.exe',parent_pid=0),dict(pid=9,name='helper.exe',parent_pid=1)]
        self.assertEqual(len(process_roles(rows,1)),2)
    def test_unavailable_memory_not_guessed(self):
        rows=[dict(pid=1,name='python.exe',parent_pid=0,working_set_bytes=None)]
        self.assertIsNone(process_roles(rows,1)[0]['working_set_bytes'])
