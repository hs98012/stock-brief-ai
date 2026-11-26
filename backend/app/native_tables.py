"""Native cell topology is a constraint, never invented from PDF plain-text order."""
from .page_layout import overlap, area


def observe_tables(page, words):
    observations=[]
    if not hasattr(page,'find_tables'):
        return [],[{'error':'find_tables_unavailable'}]
    try:
        tables=page.find_tables().tables
        for index,table in enumerate(tables):
            matrix=table.extract()
            cells=[]
            for r,row in enumerate(table.rows):
                for c,bbox in enumerate(row.cells):
                    if bbox is not None:
                        cells.append(dict(row=r,column=c,bbox=list(bbox),text=matrix[r][c] or ''))
            observations.append(dict(index=index,bbox=list(table.bbox),row_count=table.row_count,
                column_count=table.col_count,cells=cells))
    except Exception as exc:
        return [],[{'error':type(exc).__name__}]
    return observations,[]


def topology_matches(fact, table):
    def cells_for(role):
        spans=[s for s in fact['source_spans'] if s['role']==role]
        matches=[]
        for span in spans:
            cells=[c for c in table['cells'] if overlap(c['bbox'],span['bbox'])/max(1,area(span['bbox']))>.8]
            if len(cells)!=1:return []
            matches.append(cells[0])
        return matches
    values,columns,rows=cells_for('value'),cells_for('columns'),cells_for('row')
    return bool(values and columns and rows and len(values)==1 and len(columns)==1
        and values[0]['column']==columns[0]['column'] and columns[0]['row']<values[0]['row']
        and all(c['row']==values[0]['row'] and c['column']<values[0]['column'] for c in rows))


def extract_native_facts(text, words, tables, page_number, *, source='native'):
    """Independent cell-based path: row membership comes from PDF table cells."""
    import re
    from .layout_tables import UNIT_TOKEN, source_span, status
    from .table_evidence import NUMBER, PERIOD
    from .fact_fusion import PARSER_VERSION, safe_word
    result=[]
    for table in tables:
        cells=table['cells']
        def contained(cell):
            def belongs(word):
                if source=='native':return overlap(cell['bbox'],word['bbox'])/max(1,area(word['bbox']))>.8
                x=(word['bbox'][0]+word['bbox'][2])/2;y=(word['bbox'][1]+word['bbox'][3])/2
                matches=[c for c in cells if c['bbox'][0]<x<c['bbox'][2] and c['bbox'][1]<y<c['bbox'][3]
                         and overlap(c['bbox'],word['bbox'])/max(1,area(word['bbox']))>.5]
                return len(matches)==1 and matches[0] is cell
            found=sorted([w for w in words if w['source']==source and belongs(w)],key=lambda w:(w['bbox'][1],w['bbox'][0]))
            if source=='paddle_structure' and re.sub(r'\s+','',''.join(w['text'] for w in found))!=re.sub(r'\s+','',cell['text']):
                return []
            return found
        cell_words={(c['row'],c['column']):contained(c) for c in cells}
        headers={}
        for c in cells:
            tokens=cell_words[c['row'],c['column']]
            periods=[w for w in tokens if PERIOD.fullmatch(w['text'])]
            if len(periods)==1 and c['column']>0 and c['row']<=1:
                headers[c['column']]=(c['row'],periods[0])
        dated=bool(headers)
        if source=='paddle_structure' and not dated:
            for r in range(min(2,table['row_count'])):
                labels=cell_words.get((r,0),[])
                if len(labels)!=1 or labels[0]['text'] not in ('구분','항목','내역','Item'):continue
                for c in range(1,table['column_count']):
                    values=cell_words.get((r,c),[])
                    if len(values)==1 and values[0]['text'] in ('값','금액','가치','Value','Amount'):
                        headers[c]=(r,values[0])
        if not headers:continue
        unit_words=[w for w in words if w['source']==source and UNIT_TOKEN.fullmatch(w['text'].strip('()[] '))
                    and table['bbox'][0]-5<=w['bbox'][0]<=table['bbox'][2]+5
                    and table['bbox'][1]-40<=w['bbox'][1]<=table['bbox'][3]]
        table_units = [w for w in unit_words if w['bbox'][3] <=
                       min(c['bbox'][3] for c in cells if c['row'] == 0) + 3]
        pending=[];valid_rows=set();parent=None
        for r in range(table['row_count']):
            labels=[w for w in cell_words.get((r,0),[]) if not NUMBER.fullmatch(w['text'])
                    and not UNIT_TOKEN.fullmatch(w['text'].strip('()[] '))]
            if not labels or not re.search(r'[가-힣A-Za-z]',''.join(w['text'] for w in labels)):continue
            label=' '.join(w['text'] for w in labels)
            child=bool(re.match(r'^[-•·ㆍ“]',label))
            if not child:parent=labels
            metric=parent if child else labels
            if not metric:continue
            for col,(header_row,period) in headers.items():
                if r<=header_row:continue
                values=cell_words.get((r,col),[])
                if len(values)!=1 or not NUMBER.fullmatch(values[0]['text']):continue
                value=values[0]
                row_units=[u for u in cell_words.get((r,0),[]) if u in unit_words]
                column_units=[u for u in cell_words.get((header_row,col),[]) if u in unit_words]
                scoped=row_units or column_units or table_units
                if len(scoped)!=1:continue
                unit=scoped[0]
                metric=metric if dated else [period]
                if not all(safe_word(w) for w in labels+metric+[period,value,unit]):continue
                spans=[source_span(w,role,text) for role,group in (
                    ('row',labels),('metric',metric),('columns',[period]),('unit',[unit]),('value',[value])) for w in group]
                a,b=labels[0]['char_start'],labels[-1]['char_end']
                pending.append(dict(kind='table',row_label=re.sub(r'^[-•·ㆍ“]\s*','',label),
                    metric=' '.join(w['text'] for w in metric),column_name=period['text'],period=period['text'] if dated else None,
                    period_status='explicit' if dated else 'not_stated',status=status(period['text'] if dated else None),comparison_basis=None,
                    unit='%' if value['text'].endswith('%') else UNIT_TOKEN.fullmatch(unit['text'].strip('()[] '))[1],
                    value=value['text'],page_number=page_number,table_title=None,char_start=a,char_end=b,
                    quote=text[a:b],source_spans=spans,processing_version=PARSER_VERSION,source='native_table' if source=='native' else source,
                    verification='native_cell_topology' if source=='native' else 'paddle_cell_topology',bbox=value['bbox'],context_bbox=table['bbox'],confidence=min(s['confidence'] for s in spans),
                    **{('native_cell' if source=='native' else 'paddle_cell'):
                       dict(table_index=table['index'],row=r,column=col)},header_bbox=period['bbox']))
                valid_rows.add(r)
        if len(valid_rows)>=2:result.extend(pending)
    return result
