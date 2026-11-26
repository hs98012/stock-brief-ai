"""Conservative coordinate-aligned tables, retaining every literal source word."""
import re
from statistics import median

from .page_layout import PARSER_VERSION, OCR_MIN_CONFIDENCE, geometric_rows
from .table_evidence import NUMBER, PERIOD

UNIT_TOKEN = re.compile(r'(?<![가-힣])(십억원|백만원|조원|억원|천원|원|백만달러|달러|%)(?![가-힣])')


def center(word):
    return (word['bbox'][0]+word['bbox'][2])/2


def status(period):
    if not period:
        return 'unspecified'
    return {'F':'forecast','E':'forecast','A':'actual','P':'provisional'}.get(period[-1:].upper(),'unspecified')


def source_span(word, role, text):
    a,b = word['char_start'],word['char_end']
    return {'role':role,'char_start':a,'char_end':b,'quote':text[a:b],
            'bbox':word['bbox'],'source':word['source'],'confidence':word['confidence']}


def usable(word, unsafe, *, numeric=False):
    return (not any(word['char_start'] < s['char_end'] and word['char_end'] > s['char_start'] for s in unsafe)
            and (word['source']=='native' or (word['confidence'] >= (OCR_MIN_CONFIDENCE if numeric else 65) or word.get('confirmed_exact', False))))


def extract_layout_facts(text, words, page_number, unsafe=()):
    rows = geometric_rows([w for w in words if 'char_start' in w])
    result = []
    for index, header in enumerate(rows):
        # Column positions must exist literally. Never turn 1026 into 1Q26.
        columns = [w for w in header if PERIOD.fullmatch(w['text']) or re.fullmatch(r'\d{4}[FEAP]?',w['text'], re.I)]
        dated = sum(bool(PERIOD.fullmatch(w['text'])) for w in columns) >= 2
        if not dated:
            # Undated two-column/value tables require explicit generic column labels.
            columns = [w for w in header if w['text'] in ('값','금액','가치','Value','Amount')]
            if len(columns)!=1 or not any(w['text'] in ('구분','항목','내역','Item') for w in header):
                continue
        columns.sort(key=center)
        gap = median(center(b)-center(a) for a,b in zip(columns,columns[1:])) if len(columns)>1 else max(20,columns[0]['bbox'][2]-columns[0]['bbox'][0])*2
        if gap <= 0:
            continue
        header_unit = None
        for previous in reversed(rows[max(0,index-3):index+1]):
            matches = [w for w in previous if UNIT_TOKEN.fullmatch(w['text'].strip('()[] '))]
            if matches:
                header_unit = matches[-1]
                break
        parent = None
        pending = []
        row_count = 0
        for row in rows[index+1:]:
            if any(re.match(r'^(?:자료|출처|표\d)', w['text']) for w in row):
                break
            if sum(bool(PERIOD.fullmatch(w['text'])) for w in row) >= 2:
                break
            numeric = [w for w in row if NUMBER.fullmatch(w['text'])]
            labels = [w for w in row if w['bbox'][2] < columns[0]['bbox'][0] and w not in numeric]
            if not labels or not numeric:
                # Do not bridge paragraphs/section gaps into a later unrelated table.
                if row and row[0]['bbox'][1]-header[0]['bbox'][3] > 3*max(w['bbox'][3]-w['bbox'][1] for w in header) and not pending:
                    break
                continue
            values = {}
            ambiguous = False
            for word in numeric:
                nearest = min(range(len(columns)), key=lambda j:abs(center(word)-center(columns[j])))
                # Numeric table cells are normally right-aligned: use centers and right edges.
                distance = min(abs(center(word)-center(columns[nearest])),abs(word['bbox'][2]-columns[nearest]['bbox'][2]))
                # A neighboring remarks column can contain dates/numbers. It must
                # never substitute a damaged value in the right-aligned value column.
                right_limit = columns[nearest]['bbox'][2] + .5*(columns[nearest]['bbox'][3]-columns[nearest]['bbox'][1])
                if distance > .45*gap or word['bbox'][2] > right_limit:
                    if dated:
                        ambiguous = True
                    continue
                if nearest in values:
                    ambiguous = True
                values[nearest] = word
            if ambiguous or len(values)!=len(columns):
                parent = None
                continue
            row_unit = next((w for w in labels if UNIT_TOKEN.fullmatch(w['text'].strip('()[] '))), None)
            label_words = [w for w in labels if w is not row_unit]
            # Same baseline is not the same text column. Keep the rightmost label
            # cluster adjoining the numeric grid, excluding remote sidebar text.
            label_groups = []
            height = median(w['bbox'][3]-w['bbox'][1] for w in label_words) if label_words else 0
            for word in label_words:
                if not label_groups or word['bbox'][0]-label_groups[-1][-1]['bbox'][2] > 2*height:
                    label_groups.append([])
                label_groups[-1].append(word)
            label_words = label_groups[-1] if label_groups else []
            label = ' '.join(w['text'] for w in label_words).strip()
            if not label or not re.search(r'[가-힣A-Za-z]',label):
                continue
            child = bool(re.match(r'^[-•·ㆍ“]',label))
            if not child:
                parent = label_words
            metric_words = parent if child and dated else label_words if dated else columns
            if not metric_words:
                continue
            unit_word = row_unit or header_unit
            if not unit_word:
                continue
            unit_match = UNIT_TOKEN.search(unit_word['text'])
            if not unit_match:
                continue
            row_count += 1
            for col_index,value in values.items():
                column = columns[col_index]
                period = column['text'] if dated else None
                if dated and (not PERIOD.fullmatch(period) or sum(c['text']==period for c in columns)!=1):
                    continue
                if not all(usable(w,unsafe) for w in label_words+metric_words+[unit_word]):
                    continue
                if not usable(value,unsafe,numeric=True) or not usable(column,unsafe,numeric=dated):
                    continue
                spans = [source_span(w,role,text) for role, group in
                         [('row',label_words),('metric',metric_words),('columns',[column]),
                          ('unit',[unit_word]),('value',[value])] for w in group]
                # The quote stays a literal source excerpt. Other pieces are independent
                # evidence spans, never a synthesized quotation of the table.
                anchor = next(w for w in label_words if re.search(r'[가-힣A-Za-z]',w['text']))
                if len({w['line_id'] for w in label_words}) == 1:
                    a,b = min(w['char_start'] for w in label_words),max(w['char_end'] for w in label_words)
                else:
                    a,b = anchor['char_start'],anchor['char_end']
                pending.append({'row_label':re.sub(r'^[-•·ㆍ“]\s*','',label),
                    'metric':' '.join(w['text'] for w in metric_words), 'column_name':column['text'],
                    'period':period,'period_status':'explicit' if dated else 'not_stated',
                    'status':status(period), 'comparison_basis':None,
                    'unit':'%' if value['text'].endswith('%') else unit_match.group(1), 'value':value['text'],
                    'page_number':page_number,'table_title':None,'char_start':a,'char_end':b,'quote':text[a:b],
                    'source_spans':spans,'processing_version':PARSER_VERSION,'verification':'coordinate_aligned',
                    'source': 'mixed' if len({s['source'] for s in spans})>1 else spans[0]['source'],
                    'header_bbox':[min(w['bbox'][0] for w in header),min(w['bbox'][1] for w in header),
                                   max(w['bbox'][2] for w in header),max(w['bbox'][3] for w in header)]})
        # Ordinary prose with dates/numbers does not suffice: two aligned data rows.
        if row_count >= 2:
            result.extend(pending)
    return result
