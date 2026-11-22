"""Layout/section aware semantic boundaries, atomic table rows and provenance."""
from __future__ import annotations
import json
import re
from collections import defaultdict
import numpy as np
from .common import clean, digest, embed

HEADING=re.compile(r'^(?:第[一二三四五六七八九十百0-9]+[章節條]|[一二三四五六七八九十]+[、．.]|[（(][一二三四五六七八九十0-9]+[)）])')
CONDITION=re.compile(r'^(?:但|其中|惟|若|如|當|因此|所以|註|注|備註|注意|上述|此時|此項)')

def unfinished(text):
    s=text.rstrip()
    if not s: return False
    for a,b in [('（','）'),('(',')'),('「','」'),('『','』'),('[',']')]:
        if s.count(a)>s.count(b): return True
    return not bool(re.search(r'[。！？；;：:]\s*[」』）)]?$',s))

def unwrap(text):
    # Remove only a soft line break inside a Chinese word. Original elements and
    # their PDF coordinates are retained; never repair a fish name or number.
    return re.sub(r'(?<=[\u3400-\u9fff])\n(?=[\u3400-\u9fff])','',text)

def split_long(text, limit=950):
    """Never chop a numeric unit pair or an original table cell."""
    if len(text)<=limit: return [text]
    pieces=re.split(r'(?<=[。！？；;])\s*|\n(?=\S)',text)
    out=[];current=''
    for sentence in pieces:
        if current and len(current)+len(sentence)>limit:
            out.append(current);current=''
        # Oversize indivisible units remain intact and are quality flagged.
        current+=sentence+('\n' if sentence else '')
    if current.strip(): out.append(current.strip())
    return out

def segment_document(con, document_id, semantic=False, include_kinds=None):
    elements=[]
    for r in con.execute('SELECT * FROM document_elements WHERE document_id=? ORDER BY page,rowid',(document_id,)):
        item=dict(r);item['metadata']=json.loads(item['metadata_json']);elements.append(item)
    units=[];section='';table_units=[];image_units=[]
    for el in elements:
        if include_kinds is not None and el['kind'] not in include_kinds: continue
        text=el['text']
        if el['kind']=='TABLE':
            meta=el['metadata'];cells=meta['cells'];headers=cells[:1]
            prefix='\n'.join(x for x in meta.get('caption_context',[])[-1:] if re.search(r'表\s*[\d一二三四五六七八九十]|Table',x,re.I))
            foot='\n'.join(x for x in meta.get('footnote_candidates',[]) if re.match(r'^(?:註|注|備註|說明)[：:、\s]',x))
            whole=len(el['text'])<=2800
            for start in ([0] if whole else range(1,len(cells),5)):
                rows=cells if whole else headers+cells[start:start+5]
                body='\n'.join(' | '.join('' if c is None else c.replace('\n',' ') for c in r) for r in rows)
                quality=('TABLE_NATIVE_CELLS_WITH_BLANKS_NOT_INFERRED' if meta.get('missing_cells') else 'TABLE_STRUCTURE_CHECKED_NOT_EXPERT_VALIDATED') if whole else 'TABLE_MULTIROW_HEADER_REQUIRES_REVIEW'
                table_units.append({'text':'\n'.join(t for t in [prefix,body,foot] if t),'elements':[el['element_id']], 'page_start':el['page'],'page_end':el['page'],'section':section,'kind':'TABLE_ROWS','row_range':[0,len(cells)] if whole else [start,min(start+5,len(cells))],'quality':quality})
            continue
        if el['kind']=='IMAGE':
            caption=el['metadata'].get('caption','')
            if text.strip(): image_units.append({'text':caption or text,'elements':[el['element_id']],'page_start':el['page'],'page_end':el['page'],'section':section,'kind':'IMAGE_OCR_CAPTION','quality':'NATIVE_CAPTION_NOT_EXPERT_VISUAL_INTERPRETATION' if caption else 'OCR_ONLY_REQUIRES_REVIEW'})
            continue
        if el['kind'] not in ('PARAGRAPH','HTML_TEXT'): continue
        if el['metadata'].get('ocr_page'): continue
        if not text.strip(): continue
        first=text.splitlines()[0]
        if len(first)<100 and HEADING.match(first): section=first
        for part in split_long(text):
            candidate={'text':unwrap(part),'elements':[el['element_id']],'page_start':el['page'],'page_end':el['page'],'section':section,'kind':'TEXT','quality':'NATIVE_TEXT_LAYOUT_BOUND' if len(part)<=4000 else 'OVERSIZE_UNIT_REVIEW'}
            # Assemble logical paragraphs before embedding. A visual PDF line
            # ending in "車" or an open species list is not a semantic boundary.
            if units and unfinished(units[-1]['text']) and units[-1]['section']==candidate['section'] and not HEADING.match(candidate['text']) and len(units[-1]['text'])+len(candidate['text'])<=5500:
                sep='' if re.search(r'[\u3400-\u9fff]$',units[-1]['text']) and re.match(r'^[\u3400-\u9fff]',candidate['text']) else '\n'
                units[-1]['text']+=sep+candidate['text'];units[-1]['elements']+=candidate['elements'];units[-1]['page_end']=candidate['page_end']
                if len(units[-1]['text'])>4000: units[-1]['quality']='OVERSIZE_UNIT_REVIEW'
            else: units.append(candidate)
    vectors=[]
    if semantic and units:
        for start in range(0,len(units),32):
            vectors.extend(embed([x['text'][:6500] for x in units[start:start+32]]))
    grouped=[];current=None
    for idx,unit in enumerate(units):
        cosine=float(np.dot(vectors[idx-1],vectors[idx])) if semantic and idx else None
        reason='FIRST_UNIT'
        split=current is None
        if current is not None:
            reason='CONTINUE'
            if unit['section']!=current['section']: split=True;reason='SECTION_CHANGE'
            elif unit['page_start'] is not None and current['page_end'] is not None and unit['page_start']>current['page_end']+1: split=True;reason='PAGE_GAP'
            elif len(current['text'])+len(unit['text'])>1100 and not unfinished(current['text']): split=True;reason='MAX_CONTEXT_LENGTH_AT_UNIT_BOUNDARY'
            elif semantic and len(current['text'])>=180 and cosine<.62 and not CONDITION.match(unit['text']) and not unfinished(current['text']): split=True;reason='BGE_PARAGRAPH_TOPIC_BOUNDARY'
            elif not semantic and len(current['text'])>=550 and not CONDITION.match(unit['text']): split=True;reason='STRUCTURAL_BOUNDARY_PENDING_USAGE_BASIS'
        if idx: con.execute('INSERT INTO semantic_boundaries VALUES(?,?,?,?,?)',(document_id,units[idx-1]['elements'][0],unit['elements'][0],cosine,reason))
        if split:
            if current: grouped.append(current)
            current={**unit,'elements':list(unit['elements'])}
        else:
            current['text']+='\n\n'+unit['text'];current['elements']+=unit['elements'];current['page_end']=unit['page_end']
            if len(current['text'])>4000 or unit['quality']=='OVERSIZE_UNIT_REVIEW': current['quality']='OVERSIZE_UNIT_REVIEW'
    if current: grouped.append(current)
    for unit in grouped+table_units+image_units:
        unit['segment_id']='SEG-'+digest([document_id,unit['kind'],unit['elements'],unit['text']])[:24]
        method='ATOMIC_TABLE_ROWS_WITH_HEADERS_AND_FOOTNOTES' if unit['kind']=='TABLE_ROWS' else 'IMAGE_CAPTION_AND_OCR' if unit['kind']=='IMAGE_OCR_CAPTION' else 'BGE_M3_PARAGRAPH_LIST_CONDITION_V2' if semantic else 'STRUCTURE_PARAGRAPH_LIST_CONDITION_PENDING_USAGE_BASIS'
        unit['method']=method
        con.execute('INSERT OR IGNORE INTO element_chunks VALUES(?,?,?,?,?,?,?,?,?,?,?)',(unit['segment_id'],document_id,json.dumps(unit['elements']),unit['kind'],unit['text'],unit['page_start'],unit['page_end'],unit['section'],method,unit['quality'],None))
    return grouped+table_units+image_units
