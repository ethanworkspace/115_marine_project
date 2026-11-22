from pathlib import Path
import runpy
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'tools'))
import build_unified_rag_v4 as b
b.archive()
runpy.run_path(str(ROOT/'tools/unified_structured_records.py'),run_name='__main__')
runpy.run_path(str(ROOT/'tools/unified_native_sources.py'),run_name='__main__')
b.index()
runpy.run_path(str(ROOT/'tools/refine_unified_provenance.py'),run_name='__main__')
runpy.run_path(str(ROOT/'tools/unified_table_repair.py'),run_name='__main__')
runpy.run_path(str(ROOT/'tools/unified_source_versions.py'),run_name='__main__')
b.index()
b.image_vectors()
b.finalize()
print('UNIFIED_CORPUS_BUILD_COMPLETE',flush=True)
