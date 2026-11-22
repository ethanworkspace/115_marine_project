import tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from src.evaluation.edge.execution19a import write
class ReportWriteTest(unittest.TestCase):
    def test_transient_windows_share_lock_retries_report_only(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'progress.json';original=Path.replace;calls=[]
            def replace(a,b):
                calls.append(str(b))
                if len(calls)==1:raise PermissionError('synthetic share lock')
                return original(a,b)
            with patch.object(Path,'replace',replace),patch('time.sleep'):
                write(p,{'completed':38})
            self.assertEqual(len(calls),2);self.assertIn('38',p.read_text())
