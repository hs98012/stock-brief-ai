"""Coordinate reading order and independent candidate fusion for new extractions."""
import re
from statistics import median
from PIL import ImageDraw
import numpy as np
from .page_layout import area, overlap, geometric_rows

PARSER_VERSION = 'fact-fusion-paddle-v6'


def box_of(words):
    return [min(w['bbox'][0] for w in words),min(w['bbox'][1] for w in words),
            max(w['bbox'][2] for w in words),max(w['bbox'][3] for w in words)]


def reading_groups(words):
    """Recursive vertical whitespace cuts, then paragraph gaps; never plain text order."""
    if not words:
        return []
    words = sorted(words,key=lambda w:w['bbox'][0])
    bounds=box_of(words);height=median(max(1,w['bbox'][3]-w['bbox'][1]) for w in words)
    right=words[0]['bbox'][2];cuts=[]
    for i,w in enumerate(words[1:],1):
        gap=w['bbox'][0]-right
        if gap > 2*height:
            cuts.append((gap,i))
        right=max(right,w['bbox'][2])
    if cuts:
        _,i=max(cuts)
        left,right=words[:i],words[i:]
        # A narrow label is a column too; tables are handled independently.
        if len(left)>=2 and len(right)>=2:
            return reading_groups(left)+reading_groups(right)
    groups=[]
    previous=None
    for row in geometric_rows(words):
        y=min(w['bbox'][1] for w in row)
        if previous is None or y-previous > 1.1*height:
            groups.append([])
        groups[-1].extend(row)
        previous=max(w['bbox'][3] for w in row)
    return groups


def missing_regions(image, covered):
    """Whitespace segmentation on rendered uncovered ink, coordinates in input pixels.

    Remove only native coverage. Broad vertical gutters separate text columns;
    horizontal gaps separate paragraphs/tables without cutting interline spaces.
    """
    image=image.convert('L').copy();draw=ImageDraw.Draw(image)
    for x0,y0,x1,y1 in covered:
        draw.rectangle((x0-1,y0-1,x1+1,y1+1),fill=255)
    ink=np.asarray(image)<180
    yy,xx=np.nonzero(ink)
    if len(xx)<10:
        return []
    bounds=(int(xx.min()),int(yy.min()),int(xx.max()+1),int(yy.max()+1))
    def gaps(mask):
        runs=[];start=None
        for i,blank in enumerate([*mask,False]):
            if blank and start is None:start=i
            if not blank and start is not None:runs.append((start,i));start=None
        return runs
    def split(box, depth=0):
        x0,y0,x1,y1=box;block=ink[y0:y1,x0:x1]
        if depth==0:
            cuts=[(a,b) for a,b in gaps(block.mean(axis=0)<.015)
                  if b-a>=10 and a>.15*(x1-x0) and b<.85*(x1-x0)]
            if cuts:
                a,b=max(cuts,key=lambda p:p[1]-p[0]);mid=x0+(a+b)//2
                return split((x0,y0,mid,y1),1)+split((mid,y0,x1,y1),1)
        cuts=[(a,b) for a,b in gaps(block.any(axis=1)==False) if b-a>=12 and a>0 and b<y1-y0]
        starts=[y0]+[y0+(a+b)//2 for a,b in cuts]+[y1]
        result=[]
        for a,b in zip(starts,starts[1:]):
            ys,xs=np.nonzero(ink[a:b,x0:x1])
            if len(xs)>=10:
                result.append([max(0,x0+int(xs.min())-3),max(0,a+int(ys.min())-3),
                    min(image.width,x0+int(xs.max())+4),min(image.height,a+int(ys.max())+4)])
        return result
    return split(bounds)


def sentence_groups(groups):
    """Retain coordinates while keeping a damaged later sentence out of a valid claim."""
    result=[]
    for group in groups:
        current=[]
        for word in group:
            current.append(word)
            if word['text'].endswith('다.') or (word['text']=='.' and len(current)>1 and current[-2]['text'].endswith('다')):
                result.append(current);current=[]
        if current:result.append(current)
    return result


def serialize_groups(groups):
    text='';selected=[];segments=[]
    for group in groups:
        if not group:continue
        if text:text+='\n\n'
        start=len(text)
        for i,original in enumerate(group):
            if i:text+=' '
            word=dict(original);a=len(text);text+=word['text']
            word.update(char_start=a,char_end=len(text));selected.append(word)
        segments.append(dict(char_start=start,char_end=len(text),bbox=box_of(group),
                             source=group[0]['source']))
    return text,selected,segments


def fuse_candidates(candidates):
    """Prefer validated native paths at the same location; equal-priority conflicts abstain."""
    priority={'paddle_structure':5,'native_table':4,'native_text':3,'ocr_table':2,'ocr_text':1}
    buckets=[]
    for candidate in candidates:
        # Paddle may locate a whole line containing several distinct amounts.
        # A benchmark amount and a percent are not competing readings of one value.
        numeric_identity=(candidate.get('metric'),candidate.get('unit'),candidate.get('comparison_basis'))
        key=(candidate.get('kind'), numeric_identity if candidate.get('kind')=='text_numeric' else None,
             tuple(round(v,1) for v in candidate.get('bbox', [])) if candidate.get('kind')=='text_numeric' and candidate.get('bbox') else None)
        bucket=next((b for b in buckets if b[0]==key and b[1][0]['page_number']==candidate['page_number']
            and overlap(b[1][0]['bbox'],candidate['bbox'])/max(1,max(area(b[1][0]['bbox']),area(candidate['bbox'])))>.7),None)
        if bucket:bucket[1].append(candidate)
        else:buckets.append((key,[candidate]))
    selected=[];rejected=[]
    for _,items in buckets:
        items.sort(key=lambda f:(priority.get(f['source'],0),f.get('confidence',0)),reverse=True)
        top=priority.get(items[0]['source'],0)
        peers=[f for f in items if priority.get(f['source'],0)==top]
        identities={tuple(re.sub(r'\s+','',str(f.get(k,''))).casefold()
                          for k in ('row_label','metric','period','unit','comparison_basis','value')) for f in peers}
        if len(identities)>1:
            fields=[k for k in ('row_label','metric','period','unit','comparison_basis','value')
                    if len({re.sub(r'\s+','',str(f.get(k,''))).casefold() for f in peers})>1]
            rejected.extend(dict(candidate=f,reason='equal_priority_conflict',conflicting_fields=fields) for f in items)
            continue
        selected.append(items[0])
        rejected.extend(dict(candidate=f,reason='duplicate' if f.get('value')==items[0].get('value') else
                             'lower_priority_source_conflict') for f in items[1:])
    return selected,rejected


def safe_word(word):
    if '\ufffd' in word['text']:return False
    return word['source']=='native' or word.get('confirmed_exact') or word['confidence'] >= (
        80 if re.search(r'\d',word['text']) else 65)
