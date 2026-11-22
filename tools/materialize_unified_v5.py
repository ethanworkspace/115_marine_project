"""Sequential, resumable materialization. No activation or Generator batch."""
from pathlib import Path
import sys,json
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tools')]
import expand_unified_all_documents_v5 as x
import verify_and_ingest_official_laws_v5 as laws
print('REFRESH_ATOMIC_OFFICIAL_ARTICLES',flush=True);laws.ingest()
print('COMPLETE_NORMALIZED_TEXT_VECTOR_ARCHIVE',flush=True);x.archive_vectors()
print('COMPLETE_ALL_IMAGE_VECTORS',flush=True);x.images()
print('ALL_TEXT_AND_IMAGE_MATERIALIZATION_COMPLETE',flush=True)
