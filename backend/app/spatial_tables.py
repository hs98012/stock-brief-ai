"""Conservative fallback for OCR grids omitted by the table-structure model.

Every relation is made from observed word boxes. Mixed-unit declarations are
usable only when the row/column identifies one of their literal units.
"""
import re
from statistics import median

from .fact_fusion import PARSER_VERSION, safe_word
from .layout_tables import UNIT_TOKEN, source_span, status
from .page_layout import geometric_rows
from .table_evidence import NUMBER, PERIOD

CHILD = re.compile(r'^(?:New|Old|당사|발표치|실적치|컨센서스|시장예상치|기존|신규|YoY|QoQ|차이|변경률|변경율)$', re.I)
RATE = re.compile(r'률|비율|마진|수익률|증감|YoY|QoQ', re.I)
RATE_COLUMN = re.compile(r'YoY|QoQ|차이|변경률|변경율', re.I)
BENCHMARK = re.compile(r'컨센서스|시장예상치|Old|기존', re.I)
MONEY = {'십억원', '백만원', '조원', '억원', '천원', '원', '백만달러', '달러'}


def _center(word):
    return (word['bbox'][0] + word['bbox'][2]) / 2


def _yc(word):
    return (word['bbox'][1] + word['bbox'][3]) / 2


def _units(word):
    value = word['text'].strip()
    if not (value.startswith('(') and value.endswith(')')):
        return []
    parts = [part.strip() for part in value[1:-1].split(',')]
    return parts if parts and all(UNIT_TOKEN.fullmatch(part) or part == '%pt' for part in parts) else []


def _unit(row, column, value, declaration):
    units = _units(declaration)
    explicit = [word for word in (row, column) if _units(word)]
    if len(explicit) == 1 and len(_units(explicit[0])) == 1:
        chosen = _units(explicit[0])[0]
        return (chosen, explicit[0], 'cell_or_header') if chosen in units else None
    if value['text'].endswith('%') and '%' in units:
        return '%', declaration, 'value_suffix'
    if value['text'].endswith('%p') and '%pt' in units:
        return '%pt', declaration, 'value_suffix'
    if RATE.search(row['text']) or RATE_COLUMN.search(column['text']):
        rates = [unit for unit in units if unit in {'%', '%pt'}]
        return (rates[0], declaration, 'row_or_column_rate') if len(rates) == 1 else None
    amounts = [unit for unit in units if unit in MONEY]
    return (amounts[0], declaration, 'table_single_amount') if len(amounts) == 1 else None


def _column_for(value, columns):
    x = _center(value)
    for index, column in enumerate(columns):
        left = (_center(columns[index-1]) + _center(column)) / 2 if index else column['bbox'][0] - 25
        right = (_center(column) + _center(columns[index+1])) / 2 if index+1 < len(columns) else column['bbox'][2] + 25
        spacing = min(_center(column)-_center(columns[index-1]) if index else float('inf'),
                      _center(columns[index+1])-_center(column) if index+1 < len(columns) else float('inf'))
        if left <= x < right and abs(x-_center(column)) <= max(20, .35*spacing):
            return index
    return None


def spatial_fact_valid(fact):
    """Check the stored relationship, not merely the presence of quoted tokens."""
    if fact.get('verification') != 'spatial_multilevel_grid':
        return False
    roles = {}
    for span in fact.get('source_spans', []):
        roles.setdefault(span.get('role'), []).append(span)
    if any(len(roles.get(role, [])) != 1 for role in ('row', 'metric', 'columns', 'period', 'unit', 'value')):
        return False
    row, column, period, unit, value = (roles[role][0] for role in
                                         ('row', 'columns', 'period', 'unit', 'value'))
    if any(span.get('source') != 'paddle_structure' or not span.get('bbox')
           for spans in roles.values() for span in spans):
        return False
    if (row['quote'] != fact.get('row_label') or roles['metric'][0]['quote'] != fact.get('metric')
            or column['quote'] != fact.get('column_name') or period['quote'] != fact.get('period')
            or value['quote'] != fact.get('value')):
        return False
    if abs(_yc(row) - _yc(value)) > max(row['bbox'][3]-row['bbox'][1], value['bbox'][3]-value['bbox'][1]):
        return False
    if column['bbox'][1] >= value['bbox'][1] or period['bbox'][1] >= value['bbox'][1]:
        return False
    if abs(_center(column) - _center(value)) > 30:
        return False
    declaration = {'text': unit['quote'], 'bbox': unit['bbox']}
    if fact.get('unit') not in _units(declaration) or unit['bbox'][1] >= value['bbox'][1]:
        return False
    # Re-evaluate the declared unit scope against the literal row/header/value.
    resolved = _unit({'text': row['quote']}, {'text': column['quote']},
                     {'text': value['quote']}, declaration)
    if not resolved or resolved[0] != fact['unit'] or resolved[2] != fact['spatial_table']['unit_scope']:
        return False
    comparison = fact.get('comparison_cell')
    if comparison:
        if any(len(roles.get(role, [])) != 1 for role in ('comparison_columns', 'comparison_value')):
            return False
        header, cell = roles['comparison_columns'][0], roles['comparison_value'][0]
        if (header['quote'] != comparison.get('label') or cell['quote'] != comparison.get('value')
                or comparison.get('period') != fact['period'] or comparison.get('unit') != fact['unit']
                or fact.get('comparison_basis') != comparison['label']
                or abs(_yc(row)-_yc(cell)) > max(row['bbox'][3]-row['bbox'][1], cell['bbox'][3]-cell['bbox'][1])
                or header['bbox'][1] >= cell['bbox'][1] or abs(_center(header)-_center(cell)) > 30
                or comparison.get('bbox') != cell['bbox']
                or comparison.get('source_spans') != [header, cell]):
            return False
    elif fact.get('comparison_basis') or 'comparison_value' in roles or 'comparison_columns' in roles:
        return False
    return True


def extract_spatial_facts(text, words, page_number, *, observations=None):
    """Recover only multi-row OCR grids with explicit period and unit headers."""
    words = [word for word in words if word.get('source') == 'paddle_structure' and
             'char_start' in word and safe_word(word)]
    rows = geometric_rows(words)
    result = []
    for index, row in enumerate(rows):
        declarations = [word for word in row if _units(word)]
        if len(declarations) != 1 or index + 2 >= len(rows):
            continue
        declaration = declarations[0]
        nearby_title = [word for heading in rows[max(0,index-2):index+1] for word in heading
                        if re.match(r'^표(?:\d|\s|$)', word['text'])
                        and 0 <= declaration['bbox'][1]-word['bbox'][1] <= 40
                        and abs(word['bbox'][0]-declaration['bbox'][0]) <= 65]
        if not nearby_title:
            continue
        header_window = [word for header_row in rows[index:index+2] for word in header_row
                         if _yc(declaration)-10 <= _yc(word) <= _yc(declaration)+25]
        children = [word for word in header_window if CHILD.fullmatch(word['text'])
                    and _yc(word) >= _yc(declaration)+3]
        upper = [word for word in header_window if PERIOD.fullmatch(word['text'])]
        if len(children) < 2 or not upper or not any(BENCHMARK.fullmatch(word['text']) for word in children):
            continue
        # The upper row carries periods; the lower row carries subcolumns.
        # Periods on the lower row are independent columns, not parents.
        child_y = median(_yc(word) for word in children)
        parents = [word for word in upper if _yc(word) <= child_y-10]
        direct = [word for word in upper if word not in parents]
        columns = sorted([*direct, *children], key=_center)
        if len({round(_center(word)) for word in columns}) != len(columns):
            continue
        def period_for(column):
            if PERIOD.fullmatch(column['text']):
                return column
            if not parents:
                return None
            chosen = min(parents, key=lambda word: abs(_center(word)-_center(column)))
            # A lone upper period spans the labelled subcolumns, but not
            # independent dated columns to their left.
            if len(parents) == 1 and direct and _center(column) <= max(_center(w) for w in direct):
                return None
            return chosen
        height = median(w['bbox'][3]-w['bbox'][1] for w in children)
        data = []
        for data_row in rows[index+1:]:
            if median(_yc(w) for w in data_row) <= child_y+3:
                continue
            if _yc(data_row[0]) - child_y > 14 * max(height, 1):
                break
            labels = [word for word in data_row if word['bbox'][2] < columns[0]['bbox'][0]
                      and re.search(r'[가-힣A-Za-z]', word['text'])]
            numbers = [word for word in data_row if NUMBER.fullmatch(word['text'])]
            if not labels or len(numbers) < 2:
                if data:
                    break
                continue
            label = max(labels, key=lambda word: word['bbox'][2])
            aligned = {}
            for number in numbers:
                col = _column_for(number, columns)
                if col is not None and col not in aligned:
                    aligned[col] = number
            if len(aligned) < 2:
                continue
            data.append((label, aligned))
        if len(data) < 2:
            continue
        for label, aligned in data:
            for col, value in aligned.items():
                column = columns[col]
                period = period_for(column)
                if not period:
                    continue
                unit = _unit(label, column, value, declaration)
                if observations is not None:
                    import hashlib
                    identity=lambda *v:hashlib.sha256(repr(v).encode()).hexdigest()[:24]
                    table_id=identity(page_number,declaration['bbox'])
                    observations.append(dict(table_id=table_id,
                        row_id=identity(table_id,label['bbox']),column_id=identity(table_id,column['bbox']),
                        metric=label['text'],period=period['text'],column_name=column['text'],
                        value=value['text'],unit=unit[0] if unit else None,
                        declared_units=_units(declaration),
                        state='unit_resolved' if unit else 'unit_ambiguous',
                        source_spans=[source_span(w,role,text) for role,w in
                            [('metric',label),('columns',column),('period',period),
                             ('unit',declaration),('value',value)]]))
                if not unit:
                    continue
                unit_name, unit_word, unit_scope = unit
                same_period = [(other_col, other_value) for other_col, other_value in aligned.items()
                               if other_col != col and period_for(columns[other_col]) is period]
                comparisons = [(c, v) for c, v in same_period if BENCHMARK.fullmatch(columns[c]['text'])]
                comparison = comparisons[0] if len(comparisons) == 1 and not BENCHMARK.fullmatch(column['text']) else None
                spans = [source_span(word, role, text) for role, word in
                         [('row', label), ('metric', label), ('columns', column),
                          ('period', period), ('unit', unit_word), ('value', value)]]
                comparison_cell = None
                if comparison:
                    comp_col, comp_value = comparison
                    comp_unit = _unit(label, columns[comp_col], comp_value, declaration)
                    if comp_unit and comp_unit[0] == unit_name:
                        comp_header = columns[comp_col]
                        comp_spans = [source_span(word, role, text) for role, word in
                                      [('comparison_columns', comp_header), ('comparison_value', comp_value)]]
                        spans.extend(comp_spans)
                        comparison_cell = dict(label=comp_header['text'], period=period['text'],
                            unit=unit_name, value=comp_value['text'], bbox=comp_value['bbox'],
                            source_spans=comp_spans, column_index=comp_col)
                result.append(dict(kind='table', row_label=label['text'], metric=label['text'],
                    column_name=column['text'], period=period['text'], period_status='explicit',
                    status=status(period['text']), comparison_basis=comparison_cell['label'] if comparison_cell else None,
                    comparison_cell=comparison_cell, unit=unit_name, value=value['text'],
                    page_number=page_number, table_title=None, char_start=label['char_start'],
                    char_end=label['char_end'], quote=text[label['char_start']:label['char_end']],
                    source_spans=spans, processing_version=PARSER_VERSION, source='paddle_structure',
                    verification='spatial_multilevel_grid', bbox=value['bbox'],
                    context_bbox=[min(w['bbox'][0] for w in [declaration,*columns,label,value]),
                                  min(w['bbox'][1] for w in [declaration,*columns,label,value]),
                                  max(w['bbox'][2] for w in [declaration,*columns,label,value]),
                                  max(w['bbox'][3] for w in [declaration,*columns,label,value])],
                    header_bbox=column['bbox'], confidence=min(span['confidence'] for span in spans),
                    spatial_table=dict(header_row=index+1, unit_scope=unit_scope,
                        column_index=col, header_count=len(columns))))
    return result
