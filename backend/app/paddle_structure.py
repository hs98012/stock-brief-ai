"""PP-StructureV3 transport and literal coordinate observations, no correction."""
from dataclasses import dataclass
import math
import os
import re

import fitz
import httpx

from .page_layout import area, overlap


@dataclass
class StructureObservation:
    words: list
    groups: list
    raw: dict
    model: str
    tables: list
    fingerprint_sha256: str | None = None


def decode_result(payload, width, height):
    raw=payload['result']
    sx,sy=width/payload['width'],height/payload['height']
    ocr=raw['overall_ocr_res']
    texts,scores=ocr['rec_texts'],ocr['rec_scores']
    boxes=ocr.get('rec_boxes')
    if boxes is None:
        boxes=[[min(p[0] for p in poly),min(p[1] for p in poly),
                max(p[0] for p in poly),max(p[1] for p in poly)] for poly in ocr['rec_polys']]
    if not len(texts)==len(scores)==len(boxes):
        raise ValueError('Misaligned Paddle OCR observations')
    blocks=raw.get('parsing_res_list',[])
    if not blocks:
        raise ValueError('Paddle returned no document structure')
    words=[];groups={}
    for i,(text,score,box) in enumerate(zip(texts,scores,boxes,strict=True)):
        if not text.strip():continue
        if (len(box)!=4 or not all(math.isfinite(float(v)) for v in box)
                or not math.isfinite(score) or not 0<=score<=1 or area(box)<=0):
            raise ValueError('Invalid Paddle position/confidence')
        matches=[(overlap(box,b['block_bbox'])/max(1,area(box)),j) for j,b in enumerate(blocks)]
        coverage,block=max(matches)
        # Units/captions can sit just outside a detected block. Preserve their
        # measured boxes as isolated observations, never merge them into prose.
        b=blocks[block] if coverage>=.8 else {'block_label':'unassigned'}
        if coverage<.8:block=len(blocks)+i
        word=dict(text=text,bbox=[box[0]*sx,box[1]*sy,box[2]*sx,box[3]*sy],
            confidence=score*100,source='paddle_structure',line_id=f'paddle:{i}',
            model=payload['model'],bbox_granularity='recognized_text_region',
            region_id=block,ocr_stream='paddle_structure',block_label=b['block_label'],
            block_order=b.get('block_order'),observation_index=i)
        # A model region may contain both a row label and its parenthesized unit.
        # Split literal character spans, keeping the SAME observed region bbox.
        # This is not recognition correction or invented per-word geometry.
        from .layout_tables import UNIT_TOKEN
        suffix=re.fullmatch(r'(.+?)(\([^()]+\))',text)
        parts=[(0,len(text))]
        if suffix and UNIT_TOKEN.fullmatch(suffix[2][1:-1]):
            parts=[(0,suffix.start(2)),(suffix.start(2),len(text))]
        for start,end in parts:
            part={**word,'text':text[start:end],'observation_char_span':[start,end]}
            words.append(part);groups.setdefault(block,[]).append(part)
    if not words:raise ValueError('Paddle returned no positioned text')
    from .fact_fusion import safe_word
    if not any(safe_word(w) for w in words):raise ValueError('Paddle returned no usable confidence')
    # parsing_res_list is already the model's reading order. Within each block,
    # retain OCR reading order; do not interleave words from adjacent columns.
    ordered=[groups[j] for j in sorted(groups)]
    from .paddle_tables import decode_tables
    return StructureObservation(words,ordered,raw,payload['model'],decode_tables(raw,sx,sy),
                                payload.get('fingerprint_sha256'))


def extract_structure(page):
    url=os.getenv('PADDLE_STRUCTURE_URL','').rstrip('/')
    if not url:raise RuntimeError('Paddle worker not configured')
    pix=page.get_pixmap(matrix=fitz.Matrix(3,3),alpha=False)
    response=httpx.post(url+'/parse',content=pix.tobytes('png'),
        headers={'Content-Type':'image/png'},timeout=float(os.getenv('PADDLE_STRUCTURE_TIMEOUT_SECONDS','600')))
    response.raise_for_status()
    return decode_page_result(response.json(),page)


def decode_page_result(payload,page):
    observation=decode_result(payload,page.rect.width,page.rect.height)
    for word in observation.words:
        word['bbox']=list(fitz.Rect(word['bbox'])*page.derotation_matrix)
    for table in observation.tables:
        table['bbox']=list(fitz.Rect(table['bbox'])*page.derotation_matrix)
        for cell in table['cells']:
            cell['bbox']=list(fitz.Rect(cell['bbox'])*page.derotation_matrix)
    return observation
