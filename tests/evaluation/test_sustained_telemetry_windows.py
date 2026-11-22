import unittest
from src.evaluation.edge.report19a import telemetry_interval


class SustainedTelemetryWindowsTest(unittest.TestCase):
    def test_boundary_sample_belongs_to_next_interval(self):
        rows=[{'timestamp':t} for t in (99,100,399.9,400,699.9,700)]
        self.assertEqual([r['timestamp'] for r in telemetry_interval(rows,100,0)],[100,399.9])
        self.assertEqual([r['timestamp'] for r in telemetry_interval(rows,100,1)],[400,699.9])

    def test_last_request_overrun_does_not_extend_sensor_window(self):
        rows=[{'timestamp':t} for t in (1599,1600,1899.9,1900,1910)]
        self.assertEqual([r['timestamp'] for r in telemetry_interval(rows,100,5)],[1600,1899.9])
        self.assertEqual(telemetry_interval(rows,None,5),[])
