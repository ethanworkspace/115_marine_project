"""Conservative image-caption association and derived-layout provenance."""
import json
import sys
from pathlib import Path
from PIL import Image
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tools'))
from build_unified_rag_v4 import db,WORK,REPORT,register_source,add_segment_chunk
from src.unified_rag_v4.common import sha_file,dump
from src.unified_rag_v4.extraction import local_caption
from src.unified_rag_v4.segmentation import segment_document

con=db();stats={'images_reassociated':0,'captions_with_exact_geometric_scope':0,'ocr_only_not_answer_evidence':0,'derived_layouts':0}
for row in con.execute('SELECT * FROM documents').fetchall():
    rec=json.loads(row['metadata_json']);parse=Path(rec['parse_path']);original=Path(rec['primary_path'])
    if parse!=original and parse.is_file():
        rec['derived_layout']={'file':str(parse),'sha256':sha_file(parse),'page_numbers_are_rendered_copy':True,'source_document_not_modified':True}
        stats['derived_layouts']+=1
    first=rec.get('first_page','');rec['source_version_evidence']=first[:1000]
    con.execute('UPDATE documents SET metadata_json=? WHERE document_id=?',(json.dumps(rec,ensure_ascii=False),rec['document_id']))
    for image in con.execute('SELECT * FROM document_elements WHERE document_id=? AND kind="IMAGE"',(rec['document_id'],)).fetchall():
        meta=json.loads(image['metadata_json']);bbox=json.loads(image['bbox_json'])
        blocks=[(i,json.loads(p['bbox_json']),p['text']) for i,p in enumerate(con.execute('SELECT bbox_json,text FROM document_elements WHERE document_id=? AND page=? AND kind="PARAGRAPH"',(rec['document_id'],image['page']))) if json.loads(p['bbox_json'])]
        caption=local_caption(blocks,bbox)
        ocr=con.execute('SELECT ocr_text FROM media_assets WHERE asset_id=?',(image['asset_id'],)).fetchone()
        meta.update(caption=caption,caption_association='NEAREST_BELOW_WITH_HORIZONTAL_OVERLAP; WIDE_AMBIGUOUS_CAPTIONS_REJECTED')
        text='\n'.join(t for t in [caption,ocr[0] if ocr else ''] if t)
        con.execute('UPDATE document_elements SET text=?,metadata_json=? WHERE element_id=?',(text,json.dumps(meta,ensure_ascii=False),image['element_id']))
        stats['images_reassociated']+=1;stats['captions_with_exact_geometric_scope']+=bool(caption);stats['ocr_only_not_answer_evidence']+=not bool(caption)
    previous=con.execute('SELECT segment_id,chunk_id FROM element_chunks WHERE document_id=? AND kind="IMAGE_OCR_CAPTION"',(rec['document_id'],)).fetchall()
    for seg in previous:
        if seg['chunk_id']:
            con.execute('DELETE FROM chunks WHERE chunk_id=?',(seg['chunk_id'],));con.execute('DELETE FROM source_records WHERE source_record_id=?',(seg['segment_id'],))
    con.execute('DELETE FROM element_chunks WHERE document_id=? AND kind="IMAGE_OCR_CAPTION"',(rec['document_id'],))
    segments=segment_document(con,rec['document_id'],include_kinds={'IMAGE'})
    if rec['usage_policy']['eligible']:
        source=register_source(con,rec)
        for seg in segments: add_segment_chunk(con,source,rec,seg)
    con.commit()
for asset in con.execute('SELECT * FROM media_assets WHERE ocr_status="OK"').fetchall():
    meta=json.loads(asset['metadata_json']);ocrpath=WORK/'assets'/(asset['sha256']+'_ocr.png')
    if ocrpath.exists():
        with Image.open(ocrpath) as im: width,height=im.size
        meta['coordinate_space']={'ocr_input_file':str(ocrpath),'ocr_width':width,'ocr_height':height,'original_width':asset['width'],'original_height':asset['height'],'scale_to_original_x':asset['width']/width,'scale_to_original_y':asset['height']/height}
        con.execute('UPDATE media_assets SET metadata_json=? WHERE asset_id=?',(json.dumps(meta,ensure_ascii=False),asset['asset_id']))
con.execute('CREATE INDEX IF NOT EXISTS document_elements_doc_page ON document_elements(document_id,page,kind)')
con.execute('CREATE INDEX IF NOT EXISTS element_chunks_doc ON element_chunks(document_id)')
con.commit();con.close();dump(REPORT/'image_span_and_layout_validation.json',stats);print(json.dumps(stats))
