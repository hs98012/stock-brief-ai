"""Literal full-unit spans and conservative value/unit association checks."""
import re

from .page_layout import area, overlap

UNIT = re.compile(r'million\s*USD|USD|십\s*억\s*원|백\s*만\s*원|조\s*원|억\s*원|천\s*원|원/주|원|백만달러|달러|%pt|%p|%|명|건|개')
METADATA = {'unit_surface', 'canonical_unit', 'value_span', 'unit_span',
            'unit_source', 'unit_association'}


def compact(value):
    return re.sub(r'\s+', '', str(value or ''))


def box_union(boxes):
    return [min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes)]


def same_row(a, b):
    return max(0, min(a[3], b[3])-max(a[1], b[1])) / max(1, min(a[3]-a[1], b[3]-b[1])) > .8


def located(text, words, start, end):
    from .fact_fusion import safe_word
    contributors = sorted([w for w in words if w.get('char_start', -1) < end
        and w.get('char_end', -1) > start], key=lambda w: w['char_start'])
    cursor = start
    for w in contributors:
        a, b = w['char_start'], w['char_end']
        if (not w.get('bbox') or not safe_word({**w, 'confidence': w.get('confidence', 0)}) or text[a:b] != w['text'] or
                a > cursor and text[cursor:a].strip()):
            return None
        cursor = max(cursor, b)
    if not contributors or cursor < end:
        return None
    boxes = [w['bbox'] for w in contributors]
    return dict(char_start=start, char_end=end, quote=text[start:end],
                bbox=box_union(boxes), boxes=boxes, source=contributors[0]['source'])


def unit_candidates(text, words, *, suffix=None):
    """Whitespace may join literal tokens only along the same observed baseline."""
    result = []
    if not words:
        return result
    start = min(w.get('char_start', 0) for w in words)
    end = max(w.get('char_end', 0) for w in words)
    for m in UNIT.finditer(text, start, end):
        canonical = compact(m.group())
        if suffix is not None and (canonical == suffix or not canonical.endswith(suffix)):
            continue
        span = located(text, words, m.start(), m.end())
        if not span:
            continue
        if len({w['source'] for w in words if w['char_start'] < m.end()
                and w['char_end'] > m.start()}) != 1:
            continue
        boxes = span['boxes']
        if any(not same_row(a, b) or b[0]-a[2] > max(a[3]-a[1], b[3]-b[1])
               for a, b in zip(boxes, boxes[1:])):
            continue
        result.append(span)
    return result


def _cells(span, table):
    threshold = .5 if span.get('source') == 'paddle_structure' else .8
    x, y = (span['bbox'][0]+span['bbox'][2])/2, (span['bbox'][1]+span['bbox'][3])/2
    return [c for c in table['cells'] if
            c['bbox'][0] < x < c['bbox'][2] and c['bbox'][1] < y < c['bbox'][3]
            and overlap(c['bbox'], span['bbox']) / max(1, area(span['bbox'])) > threshold]


def validate_unit(fact, text, words, tables=()):
    """Return an audit record; never repair a rejected suffix or infer scaling."""
    spans = fact.get('source_spans', [])
    units = [s for s in spans if s['role'] == 'unit']
    values = [s for s in spans if s['role'] == 'value']
    out = dict(approved=False, rejection_reason='unit_span_unlocated',
               unit_surface=None, canonical_unit=compact(fact.get('unit')),
               unit_source=None, unit_association={})
    if not units or len(values) != 1:
        return out
    if any(not isinstance(s.get('char_start'), int) or not isinstance(s.get('char_end'), int)
           or not 0 <= s['char_start'] < s['char_end'] <= len(text)
           or text[s['char_start']:s['char_end']] != s.get('quote') for s in units+values):
        return out
    a, b = min(s['char_start'] for s in units), max(s['char_end'] for s in units)
    stream = [w for w in words if w.get('source') == units[0].get('source',
        (units[0].get('sources') or [None])[0])]
    unit = located(text, stream, a, b)
    v = values[0]
    value = located(text, words, v['char_start'], v['char_end'])
    out.update(unit_span=unit, value_span=value)
    if not unit or not value:
        return out
    for span in units+values:
        actual = located(text, words, span['char_start'], span['char_end'])
        if not actual or (span.get('bbox') is not None and span['bbox'] != actual['bbox']) or (
                span.get('boxes') is not None and span['boxes'] != actual['boxes']):
            out['rejection_reason'] = 'unit_value_bbox_mismatch'
            return out
    # Wrapper punctuation is preserved in source_spans; surface is the unit itself.
    matches = list(UNIT.finditer(unit['quote']))
    selected = next((m for m in matches if compact(m.group()) == out['canonical_unit']), None)
    longer = next((m for m in matches if compact(m.group()) != out['canonical_unit']
                   and compact(m.group()).endswith(out['canonical_unit'])), None)
    if selected is None and longer is not None:
        out.update(rejection_reason='unit_suffix_conflict', unit_surface=unit['quote'],
            conflicting_unit=located(text, stream, a+longer.start(), a+longer.end()))
        return out
    residual = UNIT.sub('', unit['quote'])
    residual = re.sub(r'단위\s*[:：]', '', residual).strip('()[], /\t\r\n')
    percent_suffix = (out['canonical_unit'] == '%' and unit['quote'] == v['quote']
                      and re.fullmatch(r'[-+]?\d+(?:\.\d+)?%', v['quote']))
    if not selected or residual and not percent_suffix:
        out['rejection_reason'] = 'unit_surface_mismatch'
        return out
    ua, ub = a+selected.start(), a+selected.end()
    out['unit_surface'] = text[ua:ub]
    out['unit_span'] = located(text, stream, ua, ub)
    nearby = [w for w in words if same_row(w['bbox'], unit['bbox']) or overlap(w['bbox'], unit['bbox']) > 0]
    candidates = unit_candidates(text, nearby, suffix=out['canonical_unit'])
    for longer in candidates:
        canonical = compact(longer['quote'])
        if canonical != out['canonical_unit'] and canonical.endswith(out['canonical_unit']):
            intersects = longer['char_start'] < ub and longer['char_end'] > ua
            shared = overlap(longer['bbox'], unit['bbox']) > 0 or same_row(longer['bbox'], unit['bbox'])
            if intersects or shared:
                out.update(rejection_reason='unit_suffix_conflict', conflicting_unit=longer)
                return out
    if compact(out['unit_surface']) != out['canonical_unit']:
        return out
    for table in tables:
        bounds = fact.get('context_bbox') or fact.get('cell_geometry', {}).get('table_bbox')
        if bounds and bounds != table['bbox']:
            continue
        vc, uc = _cells(value, table), _cells(unit, table)
        headers = [s for s in spans if s['role'] == 'columns']
        hc = _cells(headers[0], table) if len(headers) == 1 else []
        declaration = (not uc and len(vc) == 1 and len(hc) == 1 and
            hc[0]['column'] == vc[0]['column'] and hc[0]['row'] < vc[0]['row'] and
            unit['quote'].startswith(('(', '[')) and
            re.sub(r'단위[:：]', '', compact(unit['quote'])).strip('()[]') == out['canonical_unit'] and
            table['bbox'][0]-5 <= unit['bbox'][0] <= table['bbox'][2]+5 and
            table['bbox'][1]-40 <= unit['bbox'][1] and unit['bbox'][3] <= hc[0]['bbox'][3])
        if declaration:
            out.update(approved=True, rejection_reason=None, unit_source='column_header',
                unit_association=dict(table_bbox=table['bbox'], value_cell=vc[0],
                    header_cell=hc[0], declaration_span=unit))
            break
        if len(vc) != 1 or len(uc) != 1:
            continue
        vc, uc = vc[0], uc[0]
        if any(c.get('rowspan', 1) != 1 or c.get('colspan', 1) != 1 for c in (vc, uc)):
            continue
        scope = None
        row_spans = [s for s in spans if s['role'] == 'row']
        label_unit = (uc['column'] == 0 and row_spans and not re.search(r'\d', uc.get('text', ''))
            and all(_cells(s, table) == [uc] for s in row_spans)
            and compact(uc.get('text', '')).endswith('('+out['canonical_unit']+')'))
        if vc is uc:
            scope = 'same_cell'
        elif (vc['row'] == uc['row'] and uc['column'] < vc['column']
              and (compact(uc.get('text', '')).strip('()[]') == out['canonical_unit'] or label_unit)
              and not any(re.search(r'20\d{2}|[1-4]Q\d{2}', c.get('text', ''))
                          for c in table['cells'] if c['column'] == uc['column'] and c['row'] < uc['row'])):
            scope = 'same_row'
        elif uc['row'] < vc['row']:
            if len(hc) == 1 and hc[0]['column'] == vc['column']:
                if uc['column'] == vc['column'] and uc['row'] <= hc[0]['row']:
                    scope = 'column_header'
                # An explicit parenthesized table declaration applies through
                # observed column topology, never by mere distance to a header.
                elif (uc['column'] == 0 and uc['row'] <= hc[0]['row'] and
                      re.fullmatch(r'\s*[([]\s*(?:단위\s*[:：]\s*)?'+re.escape(out['unit_surface'])+r'\s*[)\]]\s*', unit['quote'])):
                    scope = 'column_header'
        if scope:
            out.update(approved=True, rejection_reason=None, unit_source=scope,
                unit_association=dict(table_bbox=table['bbox'], value_cell=vc, unit_cell=uc))
            break
    if not tables:
        geometry = fact.get('cell_geometry', {})
        # Numeric prose and verified vertical charts carry a literal value suffix.
        suffix = (same_row(unit['bbox'], value['bbox']) and
                  value['char_end'] <= ub and not text[value['char_end']:ua].strip() and
                  (ua >= value['char_end'] or v['quote'].endswith(out['unit_surface'])))
        if suffix and (fact.get('kind') == 'text_numeric' or geometry.get('mode') == 'vertical'):
            out.update(approved=True, rejection_reason=None, unit_source='same_cell',
                       unit_association=dict(literal_value_suffix=True))
        elif fact.get('verification') in {'coordinate_aligned', 'spatial_multilevel_grid'}:
            # These paths are rederived by their own grid validator. Their unit
            # must belong to the metric baseline or an explicit grid declaration.
            rows = [s for s in spans if s['role'] == 'row']
            header = fact.get('header_bbox')
            if rows and same_row(unit['bbox'], value['bbox']) and unit['bbox'][2] <= value['bbox'][0]:
                out.update(approved=True, rejection_reason=None, unit_source='same_row',
                           unit_association=dict(row_spans=rows))
            elif header and unit['quote'].startswith(('(', '[')) and unit['bbox'][3] <= header[3]:
                out.update(approved=True, rejection_reason=None, unit_source='column_header',
                           unit_association=dict(header_bbox=header, verification=fact['verification']))
    if not out['approved']:
        out['rejection_reason'] = 'unit_association_unverified'
    if out['approved']:
        from .unit_dependencies import unit_dependency
        proof = unit_dependency(fact, out, text, words)
        if proof is None:
            out.update(approved=False, rejection_reason='unit_component_membership_unverified')
        else:
            out['unit_dependency'] = proof
    if (out['approved'] and fact.get('cell_geometry', {}).get('mode') == 'cell'
            and (fact.get('period_binding') or fact.get('unit_binding'))):
        from .unit_binding import binding
        proof = binding(fact, out, text, words, tables)
        if proof is None:
            out.update(approved=False, rejection_reason='unit_ownership_ambiguous_or_missing')
        elif 'unit_binding' in fact and fact['unit_binding'] != proof:
            out.update(approved=False, rejection_reason='unit_binding_mismatch')
        else:
            out['unit_binding'] = proof
    from .fact_fusion import PARSER_VERSION
    if (out['approved'] and fact.get('processing_version') in {PARSER_VERSION, 'fact-fusion-paddle-v5'}
            and fact.get('kind') == 'table' and tables
            and fact.get('cell_geometry', {}).get('mode') != 'cell'
            and out.get('unit_association', {}).get('value_cell')):
        # A new table observation cannot evade source ownership by falling
        # back to an older topology candidate after the structured path HOLDs.
        from .unit_binding import topology_owner_valid
        if not topology_owner_valid(fact, out, text, words, tables):
            out.update(approved=False, rejection_reason='unit_ownership_ambiguous_or_missing')
    for key in METADATA:
        if key in fact and fact[key] != out.get(key):
            out.update(approved=False, rejection_reason='unit_metadata_mismatch')
    return out


def metadata(audit):
    return {key: audit[key] for key in METADATA}
