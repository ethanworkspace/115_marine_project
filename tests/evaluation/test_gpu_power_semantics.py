import unittest
from unittest.mock import patch
from src.evaluation.edge.hardware19a import gpu_sample
class PowerTest(unittest.TestCase):
    def test_NA_not_estimated(self):
        with patch('subprocess.check_output',return_value='NVIDIA GeForce RTX 4060, 8188, 610.88, 0, 1000, 40, [N/A], 200, 405'):
            r=gpu_sample();self.assertIsNone(r['gpu_board_power_watts'])
    def test_board_only(self):
        with patch('subprocess.check_output',return_value='NVIDIA GeForce RTX 4060, 8188, 610.88, 0, 1000, 40, 20, 200, 405'):
            self.assertEqual(gpu_sample()['gpu_board_power_watts'],20)
