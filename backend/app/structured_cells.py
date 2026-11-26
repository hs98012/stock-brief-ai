"""Observed primitive cells and derived comparisons. No numeric/unit inference."""
import hashlib
import re

from .fact_fusion import PARSER_VERSION, safe_word
from .layout_tables import source_span, status
from .page_layout import overlap, area, geometric_rows
from .table_evidence import NUMBER

PERIOD_CELL = re.compile(r'(?:[1-4]Q\d{2}[FEAP]?|20\d{2}[FEAP]?년?)', re.I)
SHORT_YEAR = re.compile(r"['’](\d{2})년")
UNITS = re.compile(r'(millionUSD|USD|십억원|백만원|억원|조원|천원|원/주|원|백만달러|달러|%pt|%p|%|명|건|개)')
MONEY = {'millionUSD', 'USD', '원', '천원', '백만원', '억원', '십억원', '조원', '달러', '백만달러'}


def metric_type(metric):
    if re.search(r'률|율|마진|비율|YoY|QoQ|growth', metric, re.I):
        return 'ratio'
    if re.search(r'\b(?:EPS|BPS|DPS)\b|주당', metric, re.I):
        return 'per_share'
    if re.search(r'인원|종업원|직원|건수|개수|인수', metric):
        return 'count'
    if re.search(r'매출|이익|손익|잔액|자산|부채|자본|가치|EBITDA|Capex|FCF', metric, re.I):
        return 'money'
    return None


def unit_compatible(metric, unit):
    family = metric_type(metric)
    return (unit in MONEY if family == 'money' else unit == '%' if family == 'ratio'
            else unit in {'원', '원/주'} if family == 'per_share'
            else unit in {'명', '건', '개'} if family == 'count' else True)


def literal_units(word):
    token = word['text'].strip('()[] ')
    canonical = re.sub(r'\s+', '', token)
    return [canonical] if UNITS.fullmatch(canonical) else []


def _id(*items):
    return hashlib.sha256(repr(items).encode()).hexdigest()[:24]


ASSOCIATION_METADATA = {'row_group_id', 'row_group_reason', 'metric_span',
                        'period_span', 'column_association_reason', 'metric_context_ownership'}


def row_groups(table):
    from .verification_cache import active, fingerprint, memoized
    if not active():
        return _row_groups(table)
    # Include identity because downstream topology joins use the actual cells.
    return memoized('row_groups', (id(table), fingerprint(table)),
                    lambda: _row_groups(table), copy=False)


def _row_groups(table):
    """Complete-link y bands, constrained by observed topology; no text ordering."""
    cells = table['cells']
    def aligned(a, b):
        a, b = a['bbox'], b['bbox']
        height = min(a[3]-a[1], b[3]-b[1])
        return (height > 0 and max(0, min(a[3], b[3])-max(a[1], b[1])) / height >= .8
                and abs(a[3]-b[3]) <= .2*height)
    def is_merged(cell):
        box = cell['bbox']
        return cell.get('rowspan', 1) != 1 or any(
            other is not cell and other['row'] != cell['row']
            and max(0, min(box[3], other['bbox'][3])-max(box[1], other['bbox'][1])) > 0
            and box[3]-box[1] > 1.5*(other['bbox'][3]-other['bbox'][1]) for other in cells)
    merged_cells = {id(cell): is_merged(cell) for cell in cells}
    records = []
    for cell in cells:
        box = cell['bbox']
        merged = merged_cells[id(cell)]
        # Shared scopes are parents, not peers of a child metric row.
        peers = [c for c in cells if not merged_cells[id(c)] and aligned(cell, c)]
        reason = ('merged_row_membership_unverified' if merged else
                  'row_topology_geometry_conflict' if any(c['row'] != cell['row'] for c in peers) else
                  'row_band_not_complete_link' if any(not aligned(a, b) for a in peers for b in peers) else
                  'overlapping_cell_boxes' if any(overlap(a['bbox'], b['bbox']) > 0 and
                      (a['column'] == b['column'] or
                       (a['column'] < b['column']) != (a['bbox'][0] < b['bbox'][0]) or
                       (a['column'] < b['column']) != (a['bbox'][2] < b['bbox'][2]))
                      for i, a in enumerate(peers) for b in peers[i+1:]) else None)
        records.append(dict(cell=cell, row_group_id=None if reason else _id(table['bbox'],
            sorted((c['row'], c['column'], c['bbox']) for c in peers)),
            row_group_reason=dict(vertical_overlap_min=.8, baseline_distance_max_height=.2,
                ordered_columns_verified=reason is None,
                member_boxes=[c['bbox'] for c in peers]), rejection_reason=reason))
    return records


def _column_aligned(a, b):
    a, b = a['bbox'], b['bbox']
    width = min(a[2]-a[0], b[2]-b[0])
    return (width > 0 and max(0, min(a[2], b[2])-max(a[0], b[0])) / width >= .9
            and max(abs(a[0]-b[0]), abs(a[2]-b[2])) <= .1*width)


def _baseline_aligned(a, b):
    height = min(a[3]-a[1], b[3]-b[1])
    return (height > 0 and max(0, min(a[3], b[3])-max(a[1], b[1])) / height >= .8
            and abs(a[3]-b[3]) <= .2*height)


def context_membership(text, words, context, metric_candidates, tables=()):
    """A literal shared scope can contain several geometrically separate rows.

    Membership is independent of downstream unit/period/value approval. Headers
    may be shared, while metric row identities may never be shared.
    """
    from .unit_validation import located
    box = context['bbox']
    out = dict(approved=False, status=None, rejection_reason=None,
               context_id=None, context_bbox=box, members=[], context_spans=[], checks={})
    def reject(reason):
        out['rejection_reason'] = reason
        return out
    relevant = [s for s in metric_candidates if s.get('bbox') and
        max(0, min(box[3], s['bbox'][3])-max(box[1], s['bbox'][1])) /
        max(1, s['bbox'][3]-s['bbox'][1]) >= .8 and s['bbox'][0] >= box[0]]
    if not relevant:
        return reject('merged_context_metric_not_unique')
    source = relevant[0].get('source')
    stream = [w for w in words if w['source'] == source]
    unique = {}
    groups_by_table = {}
    horizontal = True
    for span in relevant:
        if not isinstance(span.get('char_start'), int) or not isinstance(span.get('char_end'), int):
            return reject('context_source_span_unverified')
        actual = located(text, stream, span['char_start'], span['char_end'])
        if (not actual or actual['bbox'] != span['bbox'] or actual['quote'] != span['quote']
                or span.get('source') != source):
            return reject('context_source_span_unverified')
        owners = [(t, c) for t in tables for c in t['cells'] if
                  overlap(c['bbox'], span['bbox']) / max(1, area(span['bbox'])) > .8]
        if tables and len(owners) != 1:
            return reject('context_source_multiple_cell_owners')
        label_box = owners[0][1]['bbox'] if owners else span['bbox']
        if not (box[1] <= span['bbox'][1] and span['bbox'][3] <= box[3]):
            return reject('context_metric_vertical_containment_unverified')
        inside = box[0] <= span['bbox'][0] and span['bbox'][2] <= box[2]
        horizontal &= inside or 0 <= label_box[0]-box[2] <= span['bbox'][3]-span['bbox'][1]
        if owners:
            table, cell = owners[0]
            groups = groups_by_table.setdefault(id(table), None)
            if groups is None:
                groups = groups_by_table[id(table)] = row_groups(table)
            record = next(g for g in groups if g['cell'] is cell)
            if record['rejection_reason']:
                return reject('shared_context_metric_row_ambiguous')
            if context.get('rowspan', 1) > 1 and not (
                    context['row'] <= cell['row'] < context['row']+context['rowspan']):
                return reject('shared_context_metric_topology_conflict')
        key = (span['char_start'], span['char_end'])
        unique[key] = dict(metric_span=span, row_bbox=label_box,
                           metric_ownership_id=_id(source, box, *key))
    out['members'] = list(unique.values())
    for i, a in enumerate(out['members']):
        for b in out['members'][i+1:]:
            x, y = a['row_bbox'], b['row_bbox']
            if max(0, min(x[3], y[3])-max(x[1], y[1])) > 0:
                return reject('merged_context_metric_not_unique' if _baseline_aligned(x, y)
                              else 'shared_context_metric_row_ambiguous')
    if not horizontal:
        return reject('context_horizontal_ownership_unverified')
    context_words = [w for w in stream if overlap(box, w['bbox']) / max(1, area(w['bbox'])) > .8
        and not NUMBER.fullmatch(w['text']) and not literal_units(w)
        and not PERIOD_CELL.fullmatch(w['text'])
        and not any(s['char_start'] < w['char_end'] and s['char_end'] > w['char_start'] for s in relevant)]
    if not context_words:
        return reject('context_literal_span_missing')
    for word in context_words:
        actual = located(text, stream, word['char_start'], word['char_end'])
        if not actual or actual['quote'] != word['text'] or actual['bbox'] != word['bbox']:
            return reject('context_literal_span_unverified')
        owners = [c for t in tables for c in t['cells'] if
                  overlap(c['bbox'], word['bbox']) / max(1, area(word['bbox'])) > .8]
        if tables and (len(owners) != 1 or owners[0]['bbox'] != box):
            return reject('context_source_multiple_cell_owners')
    # A merged scope need not repeat its literal label on every child baseline.
    if len(unique) == 1 and not any(_baseline_aligned(w['bbox'], relevant[0]['bbox'])
                                  for w in context_words):
        return reject('context_anchor_baseline_unverified')
    out.update(approved=True, status='shared_metric_context_verified' if len(unique) > 1
        else 'metric_context_verified', context_spans=[source_span(w, 'metric_context', text)
        for w in context_words], context_id=_id(source, box,
            [(w['char_start'], w['char_end']) for w in context_words]))
    out['checks'] = dict(source_span_ownership=True, vertical_containment=True,
                        horizontal_continuity=True, independent_metric_rows=True,
                        literal_context=True)
    return out


def metric_context_ownership(text, words, context, metric_candidates, chain, tables=()):
    """Prove shared membership separately from unique downstream row ownership."""
    from .unit_validation import located
    membership = context_membership(text, words, context, metric_candidates, tables)
    out = dict(approved=False, coverage_complete=False, stage='metric_association',
               rejection_reason=None, context_bbox=context['bbox'],
               context_membership=membership,
               candidate_metrics=[m['metric_span'] for m in membership['members']],
               mode='cell_geometry' if tables else 'literal_geometry_fallback', checks={})
    def reject(reason):
        out['rejection_reason'] = reason
        return out
    spans = [chain.get(role+'_span') for role in ('metric', 'unit', 'period', 'value')]
    if any(not s or not s.get('bbox') or not s.get('source') or
           not isinstance(s.get('char_start'), int) or not isinstance(s.get('char_end'), int) for s in spans):
        return reject('context_chain_span_missing')
    metric, unit, period, value = spans
    stream = [w for w in words if w['source'] == metric['source']]
    box = context['bbox']
    for span in spans:
        actual = located(text, stream, span['char_start'], span['char_end'])
        if (not actual or actual['bbox'] != span['bbox'] or actual['quote'] != span['quote']
                or span['source'] != metric['source']):
            return reject('context_source_span_unverified')
        owners = [(t, c) for t in tables for c in t['cells'] if
                  overlap(c['bbox'], span['bbox']) / max(1, area(span['bbox'])) > .8]
        if tables and len(owners) != 1:
            return reject('context_source_multiple_cell_owners')
    if not membership['approved']:
        return reject(membership['rejection_reason'])
    selected = [m for m in membership['members'] if m['metric_span'] == metric]
    if len(selected) != 1:
        return reject('merged_context_metric_not_unique')
    membership = {**membership, 'metric_ownership_id': selected[0]['metric_ownership_id']}
    out['context_membership'] = membership
    out['context_spans'] = membership['context_spans']
    out['checks'].update(membership['checks'])
    geometry = chain.get('column_association_reason', {})
    # Reject a downstream token matching zero or multiple metric baselines.
    # Period headers are shared column labels, not row-owned values.
    for span in (unit, value):
        owners = [m for m in membership['members'] if
                  _baseline_aligned(m['metric_span']['bbox'], span['bbox'])]
        if len(owners) != 1 or owners[0]['metric_ownership_id'] != membership['metric_ownership_id']:
            return reject('shared_context_value_ownership_conflict' if len(owners) > 1
                          else 'context_downstream_row_chain_unverified')
    if any(not _baseline_aligned(metric['bbox'], s['bbox']) for s in (unit, value)):
        return reject('context_downstream_row_chain_unverified')
    header_box = geometry.get('header_cell', period['bbox'])
    value_box = geometry.get('value_cell', value['bbox'])
    if period['bbox'][3] >= value['bbox'][1] or not _column_aligned(
            {'bbox': header_box}, {'bbox': value_box}):
        return reject('context_period_column_unverified')
    # An alternative header with the same column geometry is ambiguous even
    # when the first one happened to be encountered earlier in the stream.
    period_owners = [w for w in stream if PERIOD_CELL.fullmatch(w['text']) and
        w['bbox'][3] < value['bbox'][1] and _column_aligned(
            {'bbox': next((c['bbox'] for t in tables for c in t['cells'] if
                overlap(c['bbox'], w['bbox']) / max(1, area(w['bbox'])) > .8), w['bbox'])},
            {'bbox': value_box})]
    if len(period_owners) != 1:
        return reject('context_period_column_ambiguous')
    value_owners = [w for w in stream if NUMBER.fullmatch(w['text']) and
        _baseline_aligned(w['bbox'], value['bbox']) and
        overlap(value_box, w['bbox']) / max(1, area(w['bbox'])) > .8]
    if len(value_owners) != 1 or value_owners[0]['char_start'] != value['char_start']:
        return reject('context_downstream_row_chain_ambiguous')
    out['checks']['downstream_row_chain'] = True
    out.update(approved=True, ownership_id=membership['metric_ownership_id'])
    return out


def _association(table, groups, label_cell, value_cell, header_cell, period_cell,
                 unit_word, spans, *, text='', words=(), metric_candidates=(), tables=()):
    """Prove row/column membership before constructing a primitive fact."""
    out = dict(approved=False, coverage_complete=False, rejection_reason=None,
               **{role+'_span': next(s for s in spans if s['role'] == role)
                  for role in ('metric', 'value', 'period', 'unit')})
    label = next(g for g in groups if g['cell'] is label_cell)
    value = next(g for g in groups if g['cell'] is value_cell)
    out.update(row_group_id=value['row_group_id'], row_group_reason=value['row_group_reason'])
    reason = label['rejection_reason'] or value['rejection_reason']
    for role, expected in [('metric', label_cell), ('value', value_cell),
                           ('period', period_cell)]:
        span = out[role+'_span']
        membership = [c for c in table['cells'] if overlap(c['bbox'], span['bbox']) /
                      max(1, area(span['bbox'])) > .8]
        if len(membership) != 1 or membership[0] is not expected:
            reason = 'overlapping_span_cell_membership_unverified'
            break
    if not reason and (not value['row_group_id'] or label['row_group_id'] != value['row_group_id']):
        reason = 'metric_value_different_row_group'
    if not reason and any(c.get('colspan', 1) != 1 for c in (label_cell, value_cell, header_cell)):
        reason = 'merged_column_membership_unverified'
    if not reason and header_cell.get('rowspan', 1) != 1:
        reason = 'merged_header_row_membership_unverified'
    if not reason and (header_cell['column'] != value_cell['column'] or
                       header_cell['row'] >= value_cell['row'] or
                       out['period_span']['bbox'][3] >= out['value_span']['bbox'][1] or
                       not _column_aligned(header_cell, value_cell)):
        reason = 'header_value_column_geometry_unverified'
    if not reason and period_cell is not header_cell:
        children = [c for c in table['cells'] if c['row'] == header_cell['row']
                    and period_cell['column'] <= c['column'] < period_cell['column']+period_cell.get('colspan', 1)]
        if (period_cell.get('rowspan', 1) != 1 or
                len(children) != period_cell.get('colspan', 1) or
                any(c.get('colspan', 1) != 1 or c['bbox'][0] < period_cell['bbox'][0]
                    or c['bbox'][2] > period_cell['bbox'][2]
                    or c['bbox'][1] < period_cell['bbox'][3] for c in children) or
                any(overlap(a['bbox'], b['bbox']) > 0 for i, a in enumerate(children) for b in children[i+1:])):
            reason = 'multilevel_header_geometry_unverified'
    contexts = [g['cell'] for g in groups if g['rejection_reason'] == 'merged_row_membership_unverified'
               and g['cell']['bbox'][2] <= label_cell['bbox'][0]
               and g['cell']['bbox'][1] < value_cell['bbox'][3]
               and g['cell']['bbox'][3] > value_cell['bbox'][1]
               and g['cell'].get('text', '').strip()]
    out['pre_context_checks'] = dict(row_group=label['row_group_id'] == value['row_group_id'],
        literal_cell_membership=reason != 'overlapping_span_cell_membership_unverified',
        period_column=reason is None)
    if not reason:
        units = [c for c in table['cells'] if overlap(c['bbox'], unit_word['bbox']) /
                 max(1, area(unit_word['bbox'])) > .8]
        if len(units) == 1 and units[0]['row'] == value_cell['row']:
            unit_group = next(g for g in groups if g['cell'] is units[0])
            if not unit_group['row_group_id'] or unit_group['row_group_id'] != value['row_group_id']:
                reason = 'unit_value_different_row_group'
        if len(units) == 1 and units[0]['row'] <= header_cell['row'] and units[0]['column'] > 0:
            if units[0]['column'] != value_cell['column'] or not _column_aligned(units[0], value_cell):
                reason = 'unit_header_column_geometry_unverified'
    out.update(approved=reason is None, rejection_reason=reason,
               stage='row_grouping' if reason and ('row_group' in reason or 'row_membership' in reason)
                   else 'column_association' if reason and ('column' in reason or 'header' in reason)
                   else 'metric_association',
               column_association_reason=dict(header_cell=header_cell['bbox'],
                   period_cell=period_cell['bbox'], value_cell=value_cell['bbox'],
                   metric_cell=label_cell['bbox'], literal_span_membership='unique_overlap_over_0.8',
                   column=value_cell['column'], x_overlap_min=.9, boundary_distance_max_width=.1))
    if not reason and contexts:
        contiguous = [c for c in contexts if 0 <= label_cell['bbox'][0]-c['bbox'][2]
                      <= spans[0]['bbox'][3]-spans[0]['bbox'][1]]
        if len(contiguous) != 1:
            out.update(approved=False, rejection_reason='merged_context_horizontal_ownership_ambiguous')
        else:
            proof = metric_context_ownership(text, words, contiguous[0], metric_candidates,
                                             out, tables or [table])
            out['metric_context_ownership'] = proof
            out.update(approved=proof['approved'], rejection_reason=proof['rejection_reason'])
    return out


def _primitive(text, page, row, metric, header, period, unit_word, unit, value,
               table_id, row_id, column_id, geometry, extra=()):
    if not unit_compatible(metric['text'], unit):
        return None
    spans = [source_span(w, role, text) for role, w in
             [('row', row), ('metric', metric), ('columns', header), ('period', period),
              ('unit', unit_word), ('value', value), *extra]]
    return dict(kind='table', row_label=row['text'], metric=metric['text'],
        row_subject=next((w['text'] for role,w in extra if role=='row_subject'),None),
        column_name=header['text'], period=period['text'], period_status='explicit',
        status=status(period['text']), unit=unit, value=value['text'],
        comparison_basis=None, comparison_cell=None, page_number=page,
        table_id=table_id, row_id=row_id, column_id=column_id,
        cell_fact_id=_id(table_id, row_id, column_id), table_title=None,
        char_start=row['char_start'], char_end=row['char_end'],
        quote=text[row['char_start']:row['char_end']], source_spans=spans,
        bbox=value['bbox'], header_bbox=header['bbox'], context_bbox=geometry['table_bbox'],
        confidence=min(s['confidence'] for s in spans),
        source='native_table' if geometry['source'] == 'native' else geometry['source'],
        processing_version=PARSER_VERSION, verification='structured_primitive_cell',
        cell_geometry=geometry)


def derive_comparisons(facts):
    """Keep primitive identity; derived edges carry both cells' literal positions."""
    result = []
    for original in facts:
        fact = dict(original)
        compatible = [f for f in facts if f['table_id'] == fact['table_id']
            and f['row_id'] == fact['row_id'] and f['metric'] == fact['metric']
            and f['unit'] == fact['unit'] and f['period'] != fact['period']]
        # Only an unambiguous pair. More periods require query-specific selection,
        # rather than silently choosing whichever happens to precede this cell.
        benchmark = [f for f in facts if f['table_id'] == fact['table_id']
            and f['row_id'] == fact['row_id'] and f['metric'] == fact['metric']
            and f['unit'] == fact['unit'] and f['period'] == fact['period']
            and re.fullmatch(r'Old|기존|컨센서스|시장예상치', f['column_name'], re.I)
            and not re.fullmatch(r'Old|기존|컨센서스|시장예상치', fact['column_name'], re.I)]
        if len(benchmark) == 1:
            compatible = benchmark
        if len(compatible) == 1:
            other = compatible[0]
            same_period = other['period'] == fact['period']
            spans = [{**s, 'role': {'columns': 'comparison_columns' if same_period else 'comparison_column_alias',
                'period': 'comparison_period' if same_period else 'comparison_columns',
                'unit': 'comparison_unit', 'value': 'comparison_value'}[s['role']]}
                for s in other['source_spans'] if s['role'] in {'columns', 'period', 'unit', 'value'}]
            fact['source_spans'] = [*fact['source_spans'], *spans]
            fact['comparison_basis'] = other['column_name'] if same_period else other['period']
            fact['comparison_cell'] = dict(label=fact['comparison_basis'], period=other['period'],
                unit=other['unit'], value=other['value'], bbox=other['bbox'], source_spans=spans,
                table_id=other['table_id'], row_id=other['row_id'], column_id=other['column_id'],
                cell_fact_id=other['cell_fact_id'])
            fact['comparison_derivation'] = dict(lhs=original['cell_fact_id'], rhs=other['cell_fact_id'],
                operation='same_metric_comparison_cells', primitive_cells=[original, other])
        result.append(fact)
    return result


def _cell_topology(text, words, tables, page, association_audit=None, scope_contract=True):
    from .unit_validation import UNIT, unit_candidates
    from .scope_binding import scope_literal
    result = []
    for table in tables:
        cells = table['cells']
        groups = row_groups(table)
        if association_audit is not None:
            association_audit.extend(dict(stage='row_grouping', coverage_complete=False, **g)
                                     for g in groups if g['rejection_reason'])
        tokens = {}
        for cell in cells:
            tokens[cell['row'], cell['column']] = [w for w in words if
                overlap(cell['bbox'], w['bbox']) / max(1, area(w['bbox'])) > .8]
            if words[0]['source'] == 'paddle_structure' and re.sub(r'\s+', '', cell.get('text','')) != re.sub(
                    r'\s+', '', ''.join(w['text'] for w in tokens[cell['row'], cell['column']])):
                tokens[cell['row'], cell['column']] = []
            observed = tokens[cell['row'], cell['column']]
            expanded = []
            for word in observed:
                inline = re.fullmatch(r'([-+]?\d+(?:,\d{3})*(?:\.\d+)?)(\s*(?:'+UNIT.pattern+r'))', word['text'])
                if inline and not word['text'].endswith('%'):
                    for start, end in [inline.span(1), inline.span(2)]:
                        while word['text'][start:end].startswith(' '):
                            start += 1
                        expanded.append({**word, 'text': word['text'][start:end],
                            'char_start': word['char_start']+start, 'char_end': word['char_start']+end})
                else:
                    expanded.append(word)
                    if NUMBER.fullmatch(word['text']) and word['text'].endswith('%'):
                        expanded.append({**word, 'text': '%', 'char_start': word['char_end']-1})
            fragments = any(re.search(r'(?:조|억|천|십|백|만|million)$', w['text']) for w in observed)
            for span in unit_candidates(text, observed) if fragments else []:
                contributors = [w for w in observed if w['char_start'] < span['char_end']
                                and w['char_end'] > span['char_start']]
                if len(contributors) > 1 and literal_units({'text': span['quote']}):
                    first = contributors[0]
                    prefix = text[first['char_start']:span['char_start']]
                    if prefix and NUMBER.fullmatch(prefix):
                        expanded = [w for w in expanded if w is not first]
                        expanded.append({**first, 'text': prefix, 'char_end': span['char_start']})
                    expanded = [w for w in expanded if not (span['char_start'] <= w['char_start']
                                and w['char_end'] <= span['char_end'])]
                    expanded.append({**contributors[0], 'text': span['quote'],
                        'char_start': span['char_start'], 'char_end': span['char_end'],
                        'bbox': span['bbox'], 'confidence': min(w['confidence'] for w in contributors)})
            tokens[cell['row'], cell['column']] = expanded
        # A year-shaped number under an earlier date header remains a value
        # when the same observed row has a metric label. Header scanning must
        # not reinterpret an admitted metric row as a second period owner.
        data_rows = {cell['row'] for cell in cells
            if any(NUMBER.fullmatch(w['text']) for w in tokens[cell['row'], cell['column']])
            and any(left['row'] == cell['row'] and left['column'] < cell['column']
                and any(metric_type(w['text']) is not None and not literal_units(w)
                        for w in tokens[left['row'], left['column']]) for left in cells)
            and any(parent['row'] < cell['row']
                and parent['column'] <= cell['column'] < parent['column']+parent.get('colspan', 1)
                and any(PERIOD_CELL.fullmatch(w['text'])
                        for w in tokens[parent['row'], parent['column']]) for parent in cells)}
        parents = [(cell, next(w for w in tokens[cell['row'], cell['column']]
                              if PERIOD_CELL.fullmatch(w['text']))) for cell in cells
            if cell['row'] <= 1 and cell['row'] not in data_rows and cell['column'] > 0
            and len([w for w in tokens[cell['row'], cell['column']] if not literal_units(w)]) == 1
            and any(PERIOD_CELL.fullmatch(w['text']) for w in tokens[cell['row'], cell['column']])]
        headers=[]
        for parent, period in parents:
            children=[c for c in cells if parent['row'] < c['row'] <= 2
                and parent['column'] <= c['column'] < parent['column']+parent.get('colspan',1)
                and len(tokens[c['row'],c['column']]) == 1
                and re.fullmatch(r'New|Old|당사|발표치|실적치|컨센서스|시장예상치|기존|신규',
                                 tokens[c['row'],c['column']][0]['text'],re.I)
                and parent['bbox'][0] <= (c['bbox'][0]+c['bbox'][2])/2 <= parent['bbox'][2]]
            if children:
                headers.extend((c, period, tokens[c['row'],c['column']][0], parent) for c in children)
            else:
                headers.append((parent,period,period,parent))
        if not headers:
            continue
        metric_candidates = [source_span(w, 'metric', text) for c in cells
            if c['row'] > max(h['row'] for h, _, _, _ in headers)
            and c['column'] < min(h['column'] for h, _, _, _ in headers)
            and next(g for g in groups if g['cell'] is c)['rejection_reason'] != 'merged_row_membership_unverified'
            for w in tokens.get((c['row'], c['column']), [])
            if not literal_units(w) and not (scope_contract and scope_literal(w['text'])) and re.search('[가-힣A-Za-z]', w['text'])]
        table_id = _id(page, table['bbox'], words[0]['source'])
        for row_index in range(max(c['row'] for c, _, _, _ in headers)+1, table['row_count']):
            label_candidates = [(c, w) for c in cells if c['row'] == row_index
                and c['column'] < min(h['column'] for h, _, _, _ in headers)
                and next(g for g in groups if g['cell'] is c)['row_group_id']
                for w in tokens.get((row_index, c['column']), [])
                if not literal_units(w) and not (scope_contract and scope_literal(w['text'])) and re.search('[가-힣A-Za-z]', w['text'])]
            labels = [w for _, w in label_candidates]
            # Fragmented/merged metric labels are deferred, never concatenated guesses.
            if len(labels) != 1 or not re.search('[가-힣A-Za-z]', labels[0]['text']):
                continue
            label = labels[0]
            label_cell = label_candidates[0][0]
            for header_cell, period, header, period_cell in headers:
                cell = next((c for c in cells if c['row'] == row_index
                             and c['column'] == header_cell['column']), None)
                values = tokens.get((row_index, header_cell['column']), [])
                numbers = [w for w in values if NUMBER.fullmatch(w['text'])]
                if cell is None or len(numbers) != 1:
                    continue
                value = numbers[0]
                from .unit_binding import applicable_units
                owners = applicable_units(text, words, table, label_cell, cell, header_cell)
                chosen = [{**owner['span'], 'text': owner['span']['quote'],
                    'confidence': min(w['confidence'] for w in words
                        if w['char_start'] < owner['span']['char_end']
                        and w['char_end'] > owner['span']['char_start'])} for owner in owners]
                if len(chosen) == 1:
                    wrappers = [w for w in words if (literal_units(w) or re.fullmatch(
                        r'[([]\s*단위\s*[:：]\s*(?:'+UNIT.pattern+r')\s*[)\]]', w['text']))
                        and w['char_start'] <= chosen[0]['char_start']
                        and w['char_end'] >= chosen[0]['char_end']]
                    if len(wrappers) == 1:
                        chosen = wrappers
                if len(chosen) != 1:
                    continue
                unit_word = chosen[0]; unit = re.sub(r'\s+', '', owners[0]['span']['quote'])
                association = _association(table, groups, label_cell, cell, header_cell,
                    period_cell, unit_word, [source_span(w, role, text) for role, w in
                        [('metric', label), ('value', value), ('period', period), ('unit', unit_word)]],
                    text=text, words=words, metric_candidates=metric_candidates, tables=tables)
                if association_audit is not None:
                    association_audit.append(association)
                if not association['approved']:
                    continue
                from .period_binding import table_binding
                binding = table_binding(text, page, table_id, table, tokens, period_cell,
                    header_cell, cell, [association[role+'_span']
                        for role in ('metric', 'period', 'value', 'unit')], data_rows=data_rows)
                if not binding['approved']:
                    association.update(approved=False, rejection_reason=binding['rejection_reason'])
                    continue
                if value['text'].endswith('%'):
                    if unit != '%':
                        continue
                geometry = dict(mode='cell', source=words[0]['source'], table_bbox=table['bbox'],
                    row=row_index, column=header_cell['column'], value_cell=cell['bbox'],
                    header_cell=header_cell['bbox'], label_cell=label_cell['bbox'],
                    unit_scope=owners[0]['scope'])
                f = _primitive(text, page, label, label, header, period, unit_word, unit, value,
                    table_id, _id(table_id, row_index), _id(table_id, header_cell['column']), geometry)
                if f:
                    f['period_binding'] = binding
                    f.update({k: association[k] for k in ASSOCIATION_METADATA if k in association})
                    f['source_spans'].extend(association.get('metric_context_ownership', {}).get('context_spans', []))
                    f['confidence'] = min(s['confidence'] for s in f['source_spans'])
                    result.append(f)
                else:
                    association.update(approved=False, rejection_reason='metric_unit_incompatible')
    return result


def _confirmed_year(short, metric, value, words):
    """Expand only against a local literal sentence with the SAME metric/value."""
    suffix = SHORT_YEAR.fullmatch(short['text'])[1]
    for row in geometric_rows([w for w in words if w['source'] == 'native']):
        if not row or not (0 < short['bbox'][1]-row[0]['bbox'][1] < 90):
            continue
        # No cross-column corroboration or a remote date on the same page.
        if not row[0]['bbox'][0] <= short['bbox'][0] <= row[-1]['bbox'][2]:
            continue
        if not any(metric['text'].replace(' ', '') in w['text'].replace(' ', '') for w in row):
            continue
        for index, w in enumerate(row[:-1]):
            if (re.fullmatch(r'20'+suffix+'년', w['text']) and
                    row[index+1]['text'].startswith(value['text']) and
                    (len(row[index+1]['text']) == len(value['text']) or
                     row[index+1]['text'][len(value['text']):] in {'에서', '로', '으로', '이다.'})):
                return w, row
    return None


def _vertical(text, words, all_words, page):
    """A metric heading above two aligned period/value rows, including bar labels."""
    result = []; rows = geometric_rows(words)
    for index, row in enumerate(rows):
        headers = [w for w in row if PERIOD_CELL.fullmatch(w['text']) or SHORT_YEAR.fullmatch(w['text'])]
        for header in headers:
            numbers = [w for w in row if NUMBER.fullmatch(w['text']) and w['bbox'][0] > header['bbox'][2]
                       and w['bbox'][0]-header['bbox'][2] < 60]
            if len(numbers) != 1:
                continue
            value = numbers[0]
            headings = [w for prior in rows[:index] for w in prior
                if metric_type(w['text']) and w['bbox'][0] <= header['bbox'][0]+15
                and w['bbox'][2] >= value['bbox'][0]-20
                and 0 < header['bbox'][1]-w['bbox'][3] < 35]
            if len(headings) != 1:
                continue
            heading = headings[0]
            metric = next((w for w in all_words if w['source'] == 'native'
                and metric_type(w['text']) and w['text'] in heading['text']
                and overlap(w['bbox'], heading['bbox'])/max(1,area(w['bbox'])) > .6), heading)
            period = header; extra = []
            prefix=heading['text'].removesuffix(metric['text']).strip() if heading['text'].endswith(metric['text']) else ''
            subjects=[w for w in all_words if w['source']=='native' and w['text']==prefix
                      and overlap(w['bbox'],heading['bbox'])/max(1,area(w['bbox']))>.6]
            if len(subjects)==1:
                extra.append(('row_subject',subjects[0]))
            if SHORT_YEAR.fullmatch(header['text']):
                confirmation = _confirmed_year(header, metric, value, all_words)
                if not confirmation:
                    continue
                period, corroboration = confirmation
                extra.extend(('period_confirmation', w) for w in corroboration)
            if not value['text'].endswith('%') or not unit_compatible(metric['text'], '%'):
                continue
            bounds = [heading['bbox'][0], heading['bbox'][1], max(heading['bbox'][2],value['bbox'][2]),
                      heading['bbox'][3]+70]
            table_id = _id(page, heading['bbox'], heading['source'])
            geometry = dict(mode='vertical', source=heading['source'], table_bbox=bounds,
                            unit_scope='value_suffix')
            f = _primitive(text, page, heading, metric, header, period, value, '%', value,
                table_id, _id(table_id, metric['text']), _id(table_id, header['text']), geometry, extra)
            if f:
                result.append(f)
    # A lone number under a heading is not a table or a comparison.
    return [f for f in result if sum(g['table_id'] == f['table_id'] for g in result) == 2
            and len({g['period'] for g in result if g['table_id'] == f['table_id']}) == 2]


def extract_cell_facts(text, words, tables, page_number, *, association_audit=None, scope_contract=True):
    from .unit_validation import validate_unit, metadata
    trusted = [w for w in words if 'char_start' in w and safe_word(w)
               and text[w['char_start']:w['char_end']] == w['text']]
    facts = []
    for source in dict.fromkeys(w['source'] for w in trusted):
        stream = [w for w in trusted if w['source'] == source]
        if not stream:
            continue
        facts.extend(_cell_topology(text, stream, tables, page_number, association_audit, scope_contract))
        facts.extend(_vertical(text, stream, trusted, page_number))
    approved = []
    for fact in facts:
        audit = validate_unit(fact, text, trusted,
                              tables if fact['cell_geometry']['mode'] == 'cell' else ())
        if audit['approved']:
            approved.append({**fact, **metadata(audit),
                **({'unit_binding': audit['unit_binding']} if 'unit_binding' in audit else {})})
        if association_audit is not None and fact.get('row_group_id') and not audit['approved']:
            value_start = next(s['char_start'] for s in fact['source_spans'] if s['role'] == 'value')
            for record in association_audit:
                if (record.get('metric_span') == fact.get('metric_span') and
                        record.get('value_span', {}).get('char_start') == value_start):
                    record.update(approved=False,
                        rejection_reason=audit['rejection_reason'], stage='unit_association')
    from .scope_binding import enrich
    if scope_contract:
        approved = enrich(approved, text, trusted, tables, page_number)
    return derive_comparisons(approved)


def merge_cell_facts(existing, structured):
    """Enrich identical observed cells without creating equal-priority conflicts."""
    def equivalent(a, b):
        return a.get('source') == b.get('source') and a.get('bbox') == b.get('bbox') and all(
            a.get(k) == b.get(k) for k in ('row_label','metric','period','unit','value'))
    return [f for f in existing if not any(equivalent(f,g)
            and (not f.get('comparison_cell') or f['comparison_cell'] == g.get('comparison_cell'))
            for g in structured)] + structured


def cell_fact_valid(fact, text, words, tables=(), *, derived=None):
    from .unit_validation import METADATA, validate_unit
    if (fact.get('processing_version') in {PARSER_VERSION, 'fact-fusion-paddle-v4', 'fact-fusion-paddle-v5'}
            and fact.get('cell_geometry', {}).get('mode') == 'cell'
            and not fact.get('period_binding')):
        return False
    if (fact.get('processing_version') in {PARSER_VERSION, 'fact-fusion-paddle-v5'}
            and fact.get('cell_geometry', {}).get('mode') == 'cell'
            and not fact.get('unit_binding')):
        return False
    if (fact.get('processing_version') == PARSER_VERSION
            and fact.get('cell_geometry', {}).get('mode') == 'cell'
            and not fact.get('scope_binding')):
        return False
    if not validate_unit(fact, text, words,
            tables if fact.get('cell_geometry', {}).get('mode') == 'cell' else ())['approved']:
        return False
    if fact.get('verification') != 'structured_primitive_cell' or not unit_compatible(fact.get('metric',''), fact.get('unit')):
        return False
    # Exact rederivation validates scope, cell geometry, primitive identities and
    # both sides of every comparison. Token presence alone is insufficient.
    candidates=(extract_cell_facts(text, words, tables, fact['page_number'],
                    scope_contract=fact.get('processing_version') == PARSER_VERSION)
                if derived is None else [f for f in derived if f.get('verification')=='structured_primitive_cell'])
    def matches(actual, expected):
        if isinstance(expected, dict):
            shared = expected.get('metric_context_ownership', {}).get('context_membership', {})
            if shared.get('status') == 'shared_metric_context_verified' and (
                    not isinstance(actual, dict) or not actual.get('metric_context_ownership')):
                return False
            return isinstance(actual, dict) and all(matches(actual.get(k), value)
                for k, value in expected.items() if k != 'processing_version'
                and (k not in METADATA | ASSOCIATION_METADATA | {'period_binding', 'unit_binding', 'scope_binding'} or k in actual))
        if isinstance(expected, list):
            return isinstance(actual, list) and len(actual) == len(expected) and all(
                matches(a, b) for a, b in zip(actual, expected, strict=True))
        return actual == expected
    return any(matches(fact, candidate) for candidate in candidates)
