import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from src.evaluation.edge.execution19a import execute
if __name__=='__main__':execute(resume='--resume-report-interruption' in sys.argv)
