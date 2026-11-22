"""Keep complete native tables intact; blanks are never imputed as zero."""
import json
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tools'))
from build_unified_rag_v4 import db,register_source,add_segment_chunk
from src.unified_rag_v4.segmentation import segment_document
con=db()
for doc in con.execute('SELECT * FROM documents').fetchall():
    rec=json.loads(doc['metadata_json'])
    if not con.execute("SELECT 1 FROM document_elements WHERE document_id=? AND kind='TABLE' LIMIT 1",(doc['document_id'],)).fetchone(): continue
    for seg in con.execute("SELECT segment_id,chunk_id FROM element_chunks WHERE document_id=? AND kind='TABLE_ROWS'",(doc['document_id'],)).fetchall():
        if seg['chunk_id']:
            con.execute('DELETE FROM chunks WHERE chunk_id=?',(seg['chunk_id'],));con.execute('DELETE FROM source_records WHERE source_record_id=?',(seg['segment_id'],))
    con.execute("DELETE FROM element_chunks WHERE document_id=? AND kind='TABLE_ROWS'",(doc['document_id'],))
    units=segment_document(con,doc['document_id'],include_kinds={'TABLE'})
    if rec['usage_policy']['eligible']:
        source=register_source(con,rec)
        for unit in units: add_segment_chunk(con,source,rec,unit)
    con.commit()
con.close();print('Complete source tables rebuilt; null cells retained, long/ambiguous headers remain review-only')
