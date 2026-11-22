"""Start the current knowledge platform without modifying frozen research files."""
from pathlib import Path
import runpy
import sys
sys.dont_write_bytecode = True
runpy.run_path(str(Path(__file__).resolve().parent / 'professional_platform.py'), run_name='__main__')
