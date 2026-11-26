"""Unique source-owned unit applicability, without proximity or scope ranking."""
from copy import deepcopy
from hashlib import sha256
import re

CONTRACT = 'source-owned-unit-v1'


def applicable_units(text, words, table, metric_cell, value_cell, header_cell, *, header_margin=25):
    from .unit_validation import UNIT, unit_candidates, _cells, compact
    def declaration(literal):
        if not re.fullmatch(r'[([][^()\[\]]+[)\]]', literal):
            return False
        residual = UNIT.sub('', re.sub(r'^단위[:：]', '', literal[1:-1]))
        return bool(re.fullmatch(r'[,/]*', residual))
    bounds = table['bbox']
    words = [w for w in words if w.get('bbox')
        and bounds[0] <= (w['bbox'][0]+w['bbox'][2])/2 <= bounds[2]
        and bounds[1]-header_margin <= (w['bbox'][1]+w['bbox'][3])/2 <= bounds[3]]
    result = []
    for source in {w['source'] for w in words}:
        stream = [w for w in words if w['source'] == source]
        for span in unit_candidates(text, stream):
            owners = _cells(span, table)
            scope = None
            if len(owners) == 1:
                cell = owners[0]
                if cell.get('rowspan', 1) != 1 or cell.get('colspan', 1) != 1:
                    continue
                if cell is value_cell:
                    scope = 'cell'
                elif cell['row'] == value_cell['row'] and cell['column'] < value_cell['column']:
                    # A numeric sibling cell cannot declare units for this value.
                    observed = [w for w in stream if _cells(w, table) == [cell]]
                    literal = compact(' '.join(w['text'] for w in observed))
                    canonical = compact(span['quote'])
                    if (literal.strip('()[]') == canonical or cell is metric_cell and
                            literal.endswith('('+canonical+')')):
                        scope = 'row'
                elif (cell['column'] == value_cell['column'] and
                      cell['row'] <= header_cell['row']):
                    scope = 'column'
                elif cell['column'] == 0 and cell['row'] <= header_cell['row']:
                    observed = [w for w in stream if _cells(w, table) == [cell]]
                    literal = compact(' '.join(w['text'] for w in observed))
                    if declaration(literal):
                        scope = 'table'
            elif not owners:
                # Only an explicit, isolated wrapper declaration in the table's
                # header band. Never treat arbitrary page text as a declaration.
                observed = [w for w in stream if w['char_start'] < span['char_end']
                            and w['char_end'] > span['char_start']]
                literal = compact(' '.join(w['text'] for w in observed))
                if (declaration(literal)
                        and table['bbox'][0] <= span['bbox'][0] <= table['bbox'][2]
                        and table['bbox'][1]-header_margin <= span['bbox'][1]
                        and span['bbox'][3] <= header_cell['bbox'][3]):
                    scope = 'table'
            if scope:
                result.append(dict(span=span, scope=scope,
                    cell=deepcopy(owners[0]) if owners else None))
    return result



def external_table_owner_unique(candidate, table, tables, *, header_margin):
    """An external declaration cannot belong to a neighboring table/header band."""
    from .unit_validation import _cells
    if candidate['scope'] != 'table' or candidate['cell'] is not None:
        return True
    span = candidate['span']
    for other in tables:
        if other['bbox'] == table['bbox']:
            continue
        if _cells(span, other):
            return False
        headers = [c for c in other['cells'] if c['row'] == 0]
        bounds = other['bbox']
        if (headers and bounds[0] <= span['bbox'][0] <= bounds[2]
                and bounds[1]-header_margin <= span['bbox'][1]
                and span['bbox'][3] <= max(c['bbox'][3] for c in headers)):
            return False
    return True

def binding(fact, audit, text, words, tables):
    """Rebuild every candidate's applicability; duplicate declarations also HOLD."""
    from .unit_validation import _cells
    spans = fact.get('source_spans', [])
    metric = [s for s in spans if s['role'] == 'metric']
    headers = [s for s in spans if s['role'] == 'columns']
    if len(metric) != 1 or len(headers) != 1 or not fact.get('period_binding', {}).get('approved'):
        return None
    matches = []
    for table in tables:
        if table['bbox'] != fact.get('context_bbox'):
            continue
        mc, vc, hc = (_cells(s, table) for s in (metric[0], audit['value_span'], headers[0]))
        if any(len(c) != 1 for c in (mc, vc, hc)):
            continue
        mc, vc, hc = mc[0], vc[0], hc[0]
        if mc['row'] != vc['row'] or hc['column'] != vc['column'] or hc['row'] >= vc['row']:
            continue
        stream = [w for w in words if w['source'] == metric[0]['source']]
        candidates = applicable_units(text, stream, table, mc, vc, hc)
        if len(candidates) != 1 or candidates[0]['span'] != audit['unit_span']:
            continue
        candidate = candidates[0]
        if not external_table_owner_unique(candidate, table, tables, header_margin=25):
            continue
        matches.append(dict(contract=CONTRACT, approved=True,
            source_text_sha256=sha256(text.encode()).hexdigest(),
            page_number=fact['page_number'], table_id=fact['table_id'],
            row_id=fact['row_id'], column_id=fact['column_id'],
            row_group_id=fact.get('row_group_id'),
            row_group_reason=deepcopy(fact.get('row_group_reason')),
            unit_primitive_id=audit['unit_dependency']['unit_primitive_id'],
            metric_span=deepcopy(metric[0]), value_span=deepcopy(audit['value_span']),
            unit_span=deepcopy(audit['unit_span']), scope=candidate['scope'],
            metric_cell=deepcopy(mc), value_cell=deepcopy(vc), header_cell=deepcopy(hc),
            unit_cell=candidate['cell'], table_bbox=deepcopy(table['bbox']),
            context=deepcopy(fact.get('metric_context_ownership')),
            period_binding=deepcopy(fact['period_binding']),
            unit_dependency=deepcopy(audit['unit_dependency'])))
    return matches[0] if len(matches) == 1 else None


def topology_owner_valid(fact, audit, text, words, tables):
    """Protect older topology fallback with its existing validator header band."""
    from .unit_validation import _cells
    spans = fact.get('source_spans', [])
    metrics = [s for s in spans if s['role'] == 'metric']
    headers = [s for s in spans if s['role'] == 'columns']
    if len(metrics) != 1 or len(headers) != 1:
        return False
    matches = []
    for table in tables:
        if table['bbox'] != audit['unit_association'].get('table_bbox'):
            continue
        cells = [_cells(s, table) for s in (metrics[0], audit['value_span'], headers[0])]
        if any(len(c) != 1 for c in cells):
            continue
        mc, vc, hc = [c[0] for c in cells]
        if mc['row'] != vc['row'] or hc['column'] != vc['column'] or hc['row'] >= vc['row']:
            continue
        candidates = applicable_units(text, [w for w in words if w['source'] == metrics[0]['source']],
            table, mc, vc, hc, header_margin=40)
        matches.append(len(candidates) == 1 and candidates[0]['span'] == audit['unit_span']
            and external_table_owner_unique(candidates[0], table, tables, header_margin=40))
    return len(matches) == 1 and matches[0]
