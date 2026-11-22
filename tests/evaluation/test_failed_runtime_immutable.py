import tempfile
import unittest
from pathlib import Path
from scripts.phase19b1_prepare import record
class ImmutableTest(unittest.TestCase):
    def test_hash_size_mtime_record(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'dll';p.write_bytes(b'frozen');before=record(p)
            self.assertEqual(before,record(p));self.assertEqual(before['size'],6)
            p.write_bytes(b'changed');self.assertNotEqual(before,record(p))
