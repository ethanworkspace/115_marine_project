"""Preserve vector charts and complete page layouts as visual-search assets."""
from pathlib import Path
import json,sys
import pymupdf as fitz
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tools')]
import expand_unified_all_documents_v5 as x
from src.unified_rag_v4.extraction import store_asset,add_element
con=x.connect();total=0
for document in con.execute('SELECT document_id,metadata_json,sha256 FROM documents').fetchall():
    rec=json.loads(document['metadata_json']);path=Path(rec['parse_path'])
    if path.suffix.lower()!='.pdf':continue
    with fitz.open(path) as doc:
        for i,page in enumerate(doc,1):
            if con.execute("SELECT 1 FROM document_elements WHERE document_id=? AND page=? AND kind='PAGE_RENDER'",(document['document_id'],i)).fetchone():continue
            pix=page.get_pixmap(matrix=fitz.Matrix(1.2,1.2),alpha=False)
            aid=store_asset(con,x.W,pix.tobytes('png'),'png',pix.width,pix.height)
            add_element(con,document['document_id'],i,'PAGE_RENDER','',list(page.rect),aid,{
                'purpose':'Whole-page visual retrieval includes vector charts, nested tables and raster content',
                'original_source_sha256':document['sha256'],'derived_layout_file':str(path),
                'pdf_point_to_pixel_scale':1.2,'not_expert_visual_or_numeric_interpretation':True},ordinal=i)
            total+=1
            if total%20==0:con.commit();print(json.dumps({'stage':'FULL_PAGE_VISUAL_CAPTURE','completed':total}),flush=True)
    con.commit()
con.close();print(json.dumps({'new_page_images':total,'original_files_unchanged':True}),flush=True)
