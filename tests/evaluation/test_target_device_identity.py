import unittest,json,platform
from pathlib import Path
from src.evaluation.edge.hardware19a import validate_identity
class IdentityTest(unittest.TestCase):
    def sample(self):
        return dict(CPU={'Name':'i5-14400F','NumberOfCores':10,'NumberOfLogicalProcessors':16},
            memory_modules=[dict(Capacity=32*1024**3,Speed=3200,SMBIOSMemoryType=26)],
            GPU={'DriverVersion':'32.0.16.1088'},OS={'Caption':'Windows 11'},computer={'Name':platform.node(),'TotalPhysicalMemory':32*1024**3})
    def test_matches(self):self.assertTrue(validate_identity(self.sample(),{'name':'NVIDIA GeForce RTX 4060','dedicated_total_bytes':8188*1024**2},'0.35.0')['matched'])
    def test_different_cpu_stops(self):
        c=self.sample();c['CPU']['Name']='different'
        with self.assertRaises(ValueError):validate_identity(c,{'name':'NVIDIA GeForce RTX 4060','dedicated_total_bytes':8188*1024**2},'0.35.0')
