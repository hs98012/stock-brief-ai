"""Conservative, page-local table cells with exact source ranges.

Unknown/OCR-damaged columns keep their position but never acquire an inferred
period. Equal row/header cardinality is mandatory. No number normalization.
These records are derived from stored page text, not model-written claims.
"""
import re
from collections import Counter

PROCESSING_VERSION = 'table-spans-v1'
PERIOD = re.compile(r'(?:[1-4]Q\d{2}(?:[FEAP])?|20\d{2}(?:[FEAP])?)', re.I)
NUMBER = re.compile(r'[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?%?')
TITLE = re.compile(r'^\s*(?:표|#)\s*\d+[.\s]')
UNIT = re.compile(r'\(\s*(십억원|백만원|조원|억원|천원|원|백만달러|달러|%)\s*(?:[,/]\s*%\s*)?\)')


def temporal_context(text: str, offset: int = 0) -> dict:
    """Literal metadata; market expectations do not turn actual results into forecasts."""
    periods = [{'text': m.group(), 'char_start': offset+m.start(), 'char_end': offset+m.end(),
                'status': 'forecast' if m.group()[-1:].upper() in {'F', 'E'} else
                          'actual' if m.group()[-1:].upper() == 'A' else
                          'provisional' if m.group()[-1:].upper() == 'P' else 'unspecified'}
               for m in re.finditer(r'\b(?:[1-4]Q\d{2}[FEAP]?|20\d{2}[FEAP]?)\b', text, re.I)]
    bases = [{'text': m.group(), 'char_start': offset+m.start(), 'char_end': offset+m.end()}
             for m in re.finditer(r'전년\s*(?:동기\s*)?대비|전분기\s*대비|YoY|QoQ|시장\s*(?:기대치|예상치)|컨센서스|실제|잠정|실적|전망|추정', text, re.I)]
    return {'period_mentions': periods, 'basis_mentions': bases}


def extract_page_table_facts(text: str, page_number: int) -> list[dict]:
    lines = []
    offset = 0
    for raw in text.splitlines(keepends=True):
        stripped = raw.strip()
        if stripped:
            start = offset + raw.index(stripped)
            lines.append((stripped, start, start+len(stripped)))
        offset += len(raw)
    title = unit = header = parent = None
    facts = []
    for line, start, end in lines:
        if TITLE.match(line):
            title, unit, header, parent = (line, start, end), None, None, None
            match = UNIT.search(line)
            if match:
                unit = (match.group(1), start+match.start(), start+match.end())
            continue
        if title is None:
            continue
        if re.match(r'^(?:자료|주\s*:|출처)', line):
            title = unit = header = parent = None
            continue
        match = UNIT.fullmatch(line)
        if match:
            unit = (match.group(1), start, end)
            continue
        tokens = line.split()
        # Retain damaged labels such as 1026 as unknown columns; never repair them.
        if len(tokens) >= 2 and sum(bool(PERIOD.fullmatch(t)) for t in tokens) >= 2:
            if all(re.fullmatch(r'[\dA-Za-z%()./-]+|컨센서스', t) for t in tokens):
                header, parent = (tokens, start, end), None
                continue
        if not header or not unit:
            continue
        row = re.match(r'(?P<label>.+?)\s+(?P<values>[-+]?\d.*)$', line)
        if not row:
            # Unknown prose/column fragments must not leak a previous parent metric.
            header = parent = None
            continue
        label = row['label'].strip()
        values = row['values'].split()
        if not re.search(r'[A-Za-z가-힣]', label) or not all(NUMBER.fullmatch(v) for v in values):
            parent = None
            continue
        child = bool(re.match(r'^[-•·]\s*', label))
        if not child:
            parent = (label, start, start+len(label))
        metric = parent if child else (label, start, start+len(label))
        if metric is None or len(values) != len(header[0]):
            continue
        columns = Counter(header[0])
        for column, value in zip(header[0], values, strict=True):
            if not PERIOD.fullmatch(column) or columns[column] != 1:
                continue
            status = ('forecast' if column[-1:].upper() in {'F', 'E'} else
                      'actual' if column[-1:].upper() == 'A' else
                      'provisional' if column[-1:].upper() == 'P' else 'unspecified')
            row_label = re.sub(r'^[-•·]\s*', '', label)
            spans = [dict(role=role, char_start=a, char_end=b, quote=text[a:b]) for role, a, b in
                     [('title', title[1], title[2]), ('unit', unit[1], unit[2]),
                      ('columns', header[1], header[2]), ('metric', metric[1], metric[2]), ('row', start, end)]]
            facts.append({'row_label': row_label, 'metric': metric[0], 'column_name': column,
                          'period': column, 'status': status, 'comparison_basis': None,
                          'unit': '%' if value.endswith('%') else unit[0], 'value': value,
                          'page_number': page_number, 'table_title': title[0],
                          'char_start': start, 'char_end': end, 'quote': text[start:end],
                          'source_spans': spans, 'processing_version': PROCESSING_VERSION})
    return facts


def fact_matches_query(fact: dict, query: str) -> bool:
    """Require subject/row AND metric AND requested column, never just page overlap."""
    if fact.get('metric_identity'):
        from .evidence_requirements import table_requirements, fact_requirement_match
        return any(fact_requirement_match(r, fact)[0] for r in table_requirements(query))
    # A forecast cell alone cannot satisfy a requested comparison benchmark.
    requested_basis = re.search(r'시장\s*(?:기대치|예상치)|컨센서스|기존\s*추정치|Old|전년\s*(?:동기\s*)?대비|전분기\s*대비|YoY|QoQ', query, re.I)
    if requested_basis:
        basis = fact.get('comparison_basis') or ''
        expected = requested_basis.group()
        equivalent = ({'컨센서스', '시장예상치'} if re.search(r'컨센서스|시장', expected) else
                      {'Old', '기존'} if re.search(r'기존|Old', expected, re.I) else {expected})
        if basis not in equivalent or not fact.get('comparison_cell'):
            return False
    compact = re.sub(r'\s+', '', query).casefold()
    if fact['row_label'].casefold().replace(' ', '') not in compact:
        return False
    undated_fused = (fact.get('processing_version', '').startswith('fact-fusion-')
                     and fact['period'] is None)
    if fact['metric'].casefold().replace(' ', '') not in compact:
        if not undated_fused or not re.search(r'값|가치|금액|단위', compact):
            return False
    period_pattern=(r'(?<![A-Za-z0-9])(?:[1-4]Q\d{2}[FEAP]?|20\d{2}[FEAP]?)(?![A-Za-z0-9])'
                    if fact.get('processing_version','').startswith('fact-fusion-paddle-') else
                    r'\b(?:[1-4]Q\d{2}[FEAP]?|20\d{2}[FEAP]?)\b')
    requested = [m.group().casefold() for m in re.finditer(period_pattern, query, re.I)]
    if undated_fused:
        return not requested
    period = fact['period']
    if fact.get('verification') in {'structured_primitive_cell', 'primitive_graph_comparison'} and period:
        # Literal Korean year suffix is typography, not a different time period.
        period = period.removesuffix('년')
    return bool(requested) and bool(period) and period.casefold() in requested


def verified_table_candidates(rows: list, query: str) -> list[tuple[object, dict]]:
    """Separate table pool; all header/row fragments must resolve to intact chunks."""
    from .evidence_integrity import span_is_covered
    pages = {}
    for chunk, page, document in rows:
        pages.setdefault(page.id, (page, document, []))[2].append(chunk)
    candidates = []
    for page, _, chunks in pages.values():
        from .extraction_provenance import validated_stored_facts
        page_facts = (validated_stored_facts(page) if getattr(page, 'extraction', None) is not None
                      else extract_page_table_facts(page.final_text, page.page_number))
        from .metric_annotations import annotate_metric_facts, annotation_spans
        page_facts = annotate_metric_facts(page, page_facts)
        from .evidence_requirements import table_requirements
        requirements = table_requirements(query)
        if any(len(r.get('requested_periods', [])) == 2 for r in requirements):
            from .primitive_graph import comparison_candidates
            comparisons = comparison_candidates(page, requirements)
            # Only explicit requested pairs on validated structured pages.
            page_facts = [f for f in page_facts if f.get('verification') != 'structured_primitive_cell'] + comparisons
        compact_query = re.sub(r'\s+', '', query).casefold()
        requested_rows = {f['row_label'] for f in page_facts if f['row_label'] != f['metric']
                          and f['row_label'].replace(' ', '').casefold() in compact_query}
        for fact in page_facts:
            if requested_rows and fact['row_label'] not in requested_rows:
                continue
            if not fact_matches_query(fact, query):
                continue
            observation = getattr(page, 'extraction', None)
            if observation is not None:
                from .unit_validation import validate_unit
                from .unit_dependencies import unit_is_covered
                provenance = observation.provenance
                audit = validate_unit(fact, page.final_text, provenance.get('selected_words', []),
                    () if fact.get('cell_geometry', {}).get('mode') == 'vertical' or
                    fact.get('verification') in {'coordinate_aligned', 'spatial_multilevel_grid'} else
                    provenance.get('native_tables', []) + provenance.get('paddle_tables', []))
                if not audit['approved'] or not unit_is_covered(page, chunks, audit['unit_dependency']):
                    continue
            source_ids = set()
            valid = True
            for span in [*fact['source_spans'], *annotation_spans(fact)]:
                covering = [c for c in chunks if c.char_start < span['char_end'] and c.char_end > span['char_start']]
                if not span_is_covered(page, covering, span['char_start'], span['char_end'], span['quote']):
                    valid = False
                    break
                source_ids.update(c.id for c in covering)
            if not valid:
                continue
            anchors = [c for c in chunks if c.char_start <= fact['char_start'] < c.char_end]
            if not anchors:
                continue
            anchor = min(anchors, key=lambda c: str(c.id))
            candidates.append((anchor.id, {**fact, 'document_id': page.document_id,
                'page_id': page.id, 'source_chunk_ids': sorted(source_ids, key=str)}))
    return sorted(candidates, key=lambda pair: (str(pair[1]['document_id']), pair[1]['page_number'],
                                               pair[1]['char_start'], pair[1]['period'] or ''))
