import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from src.evaluation.edge.report19a import compile_all
if __name__=='__main__':print(compile_all())
