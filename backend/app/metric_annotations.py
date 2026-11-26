"""Query-time, source-backed annotations over already validated metric cells.

Suffix syntax only nominates a candidate. A unique located table footnote and
structural annotation evidence must authorize removal. Raw facts stay intact.
"""
from copy import deepcopy
import re

from .page_layout import area, overlap
from .unit_validation import located
from .extraction_provenance import extraction_matches_page, trusted_page_span

MARKER = re.compile(r'(?:\d+\)|\(\d+\)|\[\d+\]|[⁰¹²³⁴⁵⁶⁷⁸⁹]+|[*†‡])')
SUFFIX = re.compile(r'(?:\d+\)|\(\d+\)|\[\d+\]|[⁰¹²³⁴⁵⁶⁷⁸⁹]+|[*†‡])$')
NOTE = re.compile(r'(?:주\s*[:：)]|주석\s*[:：]?|notes?\s*[:：])', re.I)


def _split(raw):
    match = SUFFIX.search(raw)
    if not match:
        return raw, None
    base = raw[:match.start()].rstrip()
    if not base or not re.search('[가-힣A-Za-z]', base):
        return raw, None
    return base, match.group()


def _span(page, words, start, end):
    if not trusted_page_span(page, start, end):
        return None
    span = located(page.final_text, words, start, end)
    if not span or len({w['source'] for w in words if w['char_start'] < end
                       and w['char_end'] > start}) != 1:
        return None
    return {k: span[k] for k in ('char_start', 'char_end', 'quote', 'bbox', 'source')}


def _rows(page, table, source):
    words = [w for w in page.extraction.provenance.get('selected_words', []) if w['source'] == source]
    from .structured_cells import PERIOD_CELL, literal_units
    from .scope_binding import scope_literal
    from .fact_fusion import PARSER_VERSION
    headers=[c for c in table['cells'] if c['row'] <= 1 and c['column'] > 0 and any(
        PERIOD_CELL.fullmatch(w['text']) and overlap(c['bbox'],w['bbox']) / max(1,area(w['bbox'])) > .8
        for w in words)]
    if not headers:
        return []
    label_limit=min(c['column'] for c in headers)
    header_row=max(c['row'] for c in headers)
    records = []
    for cell in table['cells']:
        if cell['column'] >= label_limit or cell['row'] <= header_row or cell.get('rowspan',1) != 1:
            continue
        tokens = [w for w in words if overlap(cell['bbox'], w['bbox']) / max(1,area(w['bbox'])) > .8]
        for word in tokens:
            if not re.search('[가-힣A-Za-z]',word['text']) or literal_units(word) or (getattr(page.extraction,'parser_version',None)==PARSER_VERSION and scope_literal(word['text'])):
                continue
            span = _span(page,words,word['char_start'],word['char_end'])
            if not span:
                continue
            owners = [c for c in table['cells'] if overlap(c['bbox'],word['bbox']) / max(1,area(word['bbox'])) > .8]
            base,marker = _split(word['text'])
            marker_span = (_span(page,words,word['char_end']-len(marker),word['char_end']) if marker else None)
            separate = False
            if not marker:
                raised = [w for w in tokens if MARKER.fullmatch(w['text']) and
                    0 <= w['bbox'][0]-word['bbox'][2] <= word['bbox'][3]-word['bbox'][1]
                    and w['bbox'][3]-w['bbox'][1] < .8*(word['bbox'][3]-word['bbox'][1])
                    and w['bbox'][1] < word['bbox'][1] and w['bbox'][3] < word['bbox'][3]]
                if len(raised) == 1:
                    m=raised[0]; marker=m['text'];separate=True
                    marker_span=_span(page,words,m['char_start'],m['char_end'])
            records.append(dict(raw_label=word['text'],canonical_label=base,
                annotation=marker,raw_span=span,marker_span=marker_span,
                separate_marker=separate,row=cell['row'],unique_cell=len(owners)==1))
    return records


def _definitions(page,table,source,marker):
    provenance=page.extraction.provenance
    words=[w for w in provenance.get('selected_words',[]) if w['source']==source]
    tables=provenance.get('native_tables',[])+provenance.get('paddle_tables',[])
    definitions=[]
    for word in words:
        if word['text']!=marker or not word.get('line_id'):
            continue
        line=sorted([w for w in words if w.get('line_id')==word['line_id']],key=lambda w:w['bbox'][0])
        body=[w for w in line if w['bbox'][0] >= word['bbox'][2] and
              re.search('[가-힣A-Za-z]',w['text'])]
        prefix=[w for w in line if w['bbox'][2] <= word['bbox'][0]]
        if not body or any(not NOTE.fullmatch(w['text']) for w in prefix):
            continue
        height=max(w['bbox'][3]-w['bbox'][1] for w in body)
        left=min(w['bbox'][0] for w in line);right=max(w['bbox'][2] for w in line)
        top=min(w['bbox'][1] for w in line)
        if height<=0 or body[0]['bbox'][0]-word['bbox'][2]>height:
            continue
        # The whole source line must be outside and adjacent to exactly one
        # table footer. A remote paragraph or another table cannot prove scope.
        owners=[t for t in tables if 0<=top-t['bbox'][3]<=2*height
            and t['bbox'][0]-height <= left and right <= t['bbox'][2]+height]
        if len(owners)!=1 or owners[0] is not table:
            continue
        spans=[_span(page,words,w['char_start'],w['char_end']) for w in line]
        if any(s is None for s in spans):
            continue
        definitions.append(dict(spans=spans,explicit_note=bool(prefix),
            raised_marker=word['bbox'][3]-word['bbox'][1] < .8*height
                and word['bbox'][3] < min(w['bbox'][3] for w in body)))
    return definitions


def _identities(page,fact,cache=None):
    geometry=fact.get('cell_geometry') or {}
    span=fact.get('metric_span')
    if geometry.get('mode')!='cell' or not span or not extraction_matches_page(page):
        return []
    provenance=page.extraction.provenance
    tables=provenance.get('native_tables',[])+provenance.get('paddle_tables',[])
    matches=[(t,c) for t in tables for c in t['cells'] if c['bbox']==geometry.get('label_cell')
        and overlap(c['bbox'],span['bbox']) / max(1,area(span['bbox'])) > .8]
    if len(matches)!=1:
        return []
    table,cell=matches[0]
    key=(id(table),span['source'])
    if cache is not None and key in cache:
        return cache[key]
    rows=_rows(page,table,span['source'])
    for row in rows:
        row.update(proof_level='not_annotated',annotation_type=None,definition_spans=[],
                   proof_checks={},rejection_reason=None)
        if not row['annotation']:
            continue
        defs=_definitions(page,table,span['source'],row['annotation'])
        repeated=len({r['row'] for r in rows if r['annotation']==row['annotation']})>1
        row['proof_level']='probable_annotation' if defs or row['separate_marker'] else 'unverified_suffix'
        row['rejection_reason']='metric_annotation_unverified'
        if len(defs)!=1 or not row['marker_span'] or not row['unique_cell']:
            continue
        definition=defs[0]
        verified=definition['explicit_note'] or definition['raised_marker'] and (repeated or row['separate_marker'])
        row['definition_spans']=definition['spans']
        row['proof_checks']=dict(unique_footer_definition=True,unique_metric_cell=True,
            explicit_note=definition['explicit_note'],raised_definition_marker=definition['raised_marker'],
            repeated_table_convention=repeated,separate_superscript=row['separate_marker'])
        if verified:
            row.update(proof_level='verified_annotation',annotation_type='footnote',rejection_reason=None)
    from .query_scope import source_memberships
    memberships = source_memberships(page, table, rows)
    for row in rows:
        row['source_scope'] = memberships.get(row['raw_span']['char_start'])
    if cache is not None:
        cache[key]=rows
    return rows


def metric_identity(page,fact,cache=None):
    """Keep potential collisions, including rows with no approved value chain."""
    rows=_identities(page,fact,cache)
    start=fact.get('metric_span',{}).get('char_start')
    selected=[r for r in rows if r['raw_span']['char_start']==start and r['raw_label']==fact.get('metric')]
    if len(selected)!=1:
        return None
    row=selected[0]
    compact=lambda s:re.sub(r'\s+','',s).casefold()
    collisions=[r for r in rows if compact(r['canonical_label'])==compact(row['canonical_label'])]
    related=any(r['annotation'] for r in collisions)
    if not row['annotation'] and not related and len(collisions) == 1 and not row['source_scope']:
        return None
    out=deepcopy(row)
    # Only verified removal exposes a canonical label. Candidate bases remain
    # in scope_metrics to block uncertain competing rows conservatively.
    if row['annotation'] and row['proof_level']!='verified_annotation':
        out['canonical_label']=row['raw_label']
    out['scope_metrics']=[dict(raw_label=r['raw_label'],candidate_label=r['canonical_label'],
        canonical_label=r['canonical_label'] if r['proof_level']=='verified_annotation' else r['raw_label'],
        proof_level=r['proof_level'],raw_span=r['raw_span'],source_scope=r['source_scope']) for r in rows]
    out['collision_spans']=[r['raw_span'] for r in collisions] if len(collisions)>1 else []
    if out['collision_spans']:
        out['rejection_reason']='canonical_metric_collision'
    return out


def annotate_metric_facts(page,facts):
    result=[];cache={}
    from .scope_binding import with_namespace
    for fact in facts:
        fact=with_namespace(fact,page)
        identity=metric_identity(page,fact,cache)
        if identity is None:
            result.append(fact)
        else:
            result.append({**fact,'metric_identity':identity})
    return result


def annotation_valid(fact,page,requirement=None):
    """Re-derive every proof from the page; caller-supplied metadata is no authority."""
    expected=metric_identity(page,fact)
    actual=fact.get('metric_identity')
    if expected!=actual:
        return False
    return actual is None or query_label(fact, requirement)[1]


def annotation_spans(fact):
    identity=fact.get('metric_identity') or {}
    result=[]
    for span in identity.get('definition_spans',[]):
        result.append({**span,'role':'metric_annotation_definition'})
    if identity.get('marker_span'):
        result.append({**identity['marker_span'],'role':'metric_annotation_marker'})
    return result


def query_label(fact, requirement=None):
    """A self-consistency gate; publication additionally requires page rederivation."""
    identity=fact.get('metric_identity')
    if identity is None:
        return fact.get('metric') or '',True
    raw=fact.get('metric') or ''
    marker=identity.get('annotation')
    rejection = identity.get('rejection_reason')
    if rejection == 'canonical_metric_collision' and requirement is not None:
        from .query_scope import scope_selection
        if (requirement.get('scope') or fact.get('scope_binding')) and scope_selection(requirement, fact)[0]:
            rejection = None
    valid=(identity.get('raw_label')==raw and identity.get('raw_span',{}).get('quote')==raw
        and not rejection and identity.get('proof_level') in {'verified_annotation','not_annotated'})
    if marker:
        valid=valid and identity.get('annotation_type')=='footnote' and bool(identity.get('definition_spans'))
        valid=valid and identity.get('marker_span',{}).get('quote')==marker
        base,candidate=_split(raw)
        valid=valid and (identity.get('separate_marker') and identity.get('canonical_label')==raw
            or candidate==marker and identity.get('canonical_label')==base)
    return identity.get('canonical_label') or raw,bool(valid)
