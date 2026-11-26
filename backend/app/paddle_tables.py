"""Literal HTML cells plus model-reported cell boxes; ambiguous tables abstain."""
from html.parser import HTMLParser
import math
import re

from .page_layout import area


class CellParser(HTMLParser):
    def __init__(self):
        super().__init__();self.rows=[];self.cell=None;self.ambiguous=False;self.spans=[]
    def handle_starttag(self,tag,attrs):
        if tag=='tr':self.rows.append([]);self.spans.append([])
        if tag in ('td','th'):
            self.cell=[]
            attrs=dict(attrs)
            try:
                self.span=(int(attrs.get('rowspan','1')),int(attrs.get('colspan','1')))
                self.ambiguous |= any(v < 1 or v > 64 for v in self.span)
            except (TypeError,ValueError):
                self.ambiguous=True;self.span=(1,1)
    def handle_data(self,data):
        if self.cell is not None:self.cell.append(data)
    def handle_endtag(self,tag):
        if tag in ('td','th') and self.cell is not None:
            if self.rows:
                self.rows[-1].append(''.join(self.cell));self.spans[-1].append(self.span)
            self.cell=None


def decode_tables(raw,sx,sy):
    tables=[]
    for index,result in enumerate(raw.get('table_res_list',[])):
        parser=CellParser();parser.feed(result.get('pred_html',''))
        rows=parser.rows;boxes=result.get('cell_box_list',[])
        if (parser.ambiguous or len(rows)<3 or not rows[0] or sum(map(len,rows))!=len(boxes)):
            continue
        cells=[]
        occupied=set();positions=[]
        for r,row in enumerate(rows):
            col=0
            for value,(rowspan,colspan) in zip(row,parser.spans[r],strict=True):
                while (r,col) in occupied:col+=1
                covered={(y,x) for y in range(r,r+rowspan) for x in range(col,col+colspan)}
                if occupied & covered or r+rowspan>len(rows):parser.ambiguous=True;break
                occupied.update(covered);positions.append((r,col,rowspan,colspan,value));col+=colspan
        widths=[sum(y==r for y,x in occupied) for r in range(len(rows))]
        if parser.ambiguous or len(set(widths))!=1:continue
        for (r,col,rowspan,colspan,value),box in zip(positions,boxes,strict=True):
            if len(box)!=4 or not all(math.isfinite(float(v)) for v in box) or area(box)<=0:break
            cells.append(dict(row=r,column=col,rowspan=rowspan,colspan=colspan,text=value,
                bbox=[box[0]*sx,box[1]*sy,box[2]*sx,box[3]*sy]))
        if len(cells)!=len(boxes):continue
        # Do not infer a row/column order that contradicts reported geometry.
        if any(cells[i]['bbox'][0]>=cells[i+1]['bbox'][0] for i in range(len(cells)-1)
               if cells[i]['row']==cells[i+1]['row']):continue
        if any(a['bbox'][1]>=b['bbox'][1] for a in cells for b in cells
               if a['column']==b['column'] and a['row']<b['row']):continue
        tables.append(dict(index=index,cells=cells,row_count=len(rows),column_count=widths[0],
            bbox=[min(c['bbox'][0] for c in cells),min(c['bbox'][1] for c in cells),
                  max(c['bbox'][2] for c in cells),max(c['bbox'][3] for c in cells)]))
    return tables


def extract_paddle_facts(text,words,tables,page_number):
    from .native_tables import extract_native_facts
    return extract_native_facts(text,words,tables,page_number,source='paddle_structure')
