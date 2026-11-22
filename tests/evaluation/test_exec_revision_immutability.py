import unittest
from pathlib import Path

class Immutability(unittest.TestCase):
    def test_new_output_only(self):
        root=Path(__file__).resolve().parents[2]
        for name in ('phase19b_r2_prepare.py','phase19b_r2_execute.py'):
            text=(root/'scripts'/name).read_text(encoding='utf-8')
            self.assertIn("OUT=ROOT/'reports/evaluation/edge/phase19B_exec_r2'",text)
            self.assertIn("open('x'",text)
            self.assertNotIn('pip install',text)
    def test_loader_no_bytecode_write(self):
        text=(Path(__file__).resolve().parents[2]/'scripts/phase19b_r2_execute.py').read_text(encoding='utf-8')
        self.assertIn("'PYTHONDONTWRITEBYTECODE':'1'",text)
        self.assertIn("RERANKER_PYTHON),'-B'",text)
