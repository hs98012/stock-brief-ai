"""Source-owned period proofs. No nearest-token or inferred-date authority."""
from copy import deepcopy
import hashlib
import re

CONTRACT = 'source-owned-period-v1'


def table_binding(text, page, table_id, table, tokens, period_cell, header_cell,
                  value_cell, spans, *, data_rows=()):
    """One literal period owner for the value's observed column group.

    Geometry, row/metric membership and units are independently checked by the
    caller. Include even unsupported/multiple header tokens in ambiguity checks.
    """
    column = value_cell['column']
    from .structured_cells import PERIOD_CELL
    owners = [(cell, word) for cell in table['cells']
        if cell['row'] <= 2 and cell['row'] not in data_rows and cell['row'] < value_cell['row']
        and cell['column'] <= column < cell['column'] + cell.get('colspan', 1)
        for word in tokens.get((cell['row'], cell['column']), [])
        if PERIOD_CELL.fullmatch(word['text'])
        or re.search(r'(?:20\d{2}|[1-4]\s*Q\s*\d{2}|\d{2}\s*년|[1-4]\s*분\s*기)', word['text'], re.I)]
    period = next(s for s in spans if s['role'] == 'period')
    if (len(owners) != 1 or owners[0][0] is not period_cell
            or owners[0][1]['char_start'] != period['char_start']
            or owners[0][1]['char_end'] != period['char_end']):
        return dict(approved=False, rejection_reason='period_column_owner_ambiguous_or_missing')
    qualifiers = [word['text'] for cell in table['cells']
        if cell['row'] <= 2 and cell['row'] not in data_rows and cell['row'] < value_cell['row']
        and cell['column'] <= column < cell['column'] + cell.get('colspan', 1)
        for word in tokens.get((cell['row'], cell['column']), [])]
    actual = any(re.fullmatch(r'실적(?:치)?|실제|확정', q) for q in qualifiers)
    forecast = any(re.fullmatch(r'예상(?:치)?|전망|추정(?:치)?|Forecast', q, re.I) for q in qualifiers)
    if ((actual and forecast)
            or actual and re.search(r'[FE]$', period['quote'], re.I)
            or forecast and re.search(r'A$', period['quote'], re.I)):
        return dict(approved=False, rejection_reason='period_actual_forecast_conflict')
    return dict(contract=CONTRACT, approved=True, mode='table_column',
        source_text_sha256=hashlib.sha256(text.encode()).hexdigest(), page_number=page,
        table_id=table_id, table_bbox=deepcopy(table['bbox']),
        row=value_cell['row'], column=column,
        column_group=[period_cell['column'], period_cell['column']+period_cell.get('colspan', 1)],
        period_cell=deepcopy(period_cell['bbox']), header_cell=deepcopy(header_cell['bbox']),
        value_cell=deepcopy(value_cell['bbox']),
        source_spans=deepcopy([s for s in spans if s['role'] in {'metric', 'period', 'value', 'unit'}]))


def sentence_segments(text, segments):
    """Split explicit sentence boundaries, never numeric decimal points."""
    for segment in segments:
        a, b = segment['char_start'], segment['char_end']
        start = a
        for boundary in re.finditer(r'다\s*\.|[!?]|\n\n', text[a:b]):
            end = a + boundary.end()
            yield {**segment, 'char_start': start, 'char_end': end}
            start = end
        if start < b:
            yield {**segment, 'char_start': start, 'char_end': b}


def explicit_claim_gap(gap, *, prior_values=False):
    """Only literal particles and benchmark amounts link the supported clause.

    Unknown words may introduce another subject/metric; they never authorize a
    period or value merely because our metric recognizer does not know them.
    """
    if prior_values:
        from .numeric_evidence import _VALUE
        gap = _VALUE.sub('', gap)
    gap = re.sub(r'컨\s*센\s*서\s*스|시\s*장\s*(?:예\s*상\s*치|기\s*대\s*치)', '', gap)
    return bool(re.fullmatch(r'[\s():은는이가]*', gap))


def paragraph_binding(text, page, segment, spans):
    sources = {source for s in spans for source in s['sources']}
    if len(sources) != 1:
        return None
    return dict(contract=CONTRACT, approved=True, mode='explicit_sentence',
        source_text_sha256=hashlib.sha256(text.encode()).hexdigest(), page_number=page,
        char_start=segment['char_start'], char_end=segment['char_end'],
        source=next(iter(sources)), source_spans=deepcopy(spans))


def numeric_binding_valid(fact, page):
    """Rebuild ownership from source sentences before accepting stored metadata."""
    from .fact_fusion import PARSER_VERSION
    if 'period_binding' not in fact:
        # Preserve the existing validator for old immutable observations; do
        # not claim the new ownership contract for them. New extractions may
        # never downgrade their contract by deleting the proof.
        return page.extraction.parser_version not in {PARSER_VERSION, 'fact-fusion-paddle-v4', 'fact-fusion-paddle-v5'}
    from .fused_extraction import _numeric
    from .fact_fusion import box_of
    provenance = page.extraction.provenance
    words = provenance.get('selected_words', [])
    segments = provenance.get('paragraph_segments')
    if segments is None:
        # Older observations lack segments; blank-line ranges are still physical
        # source boundaries, not arbitrary joins of all words on the page.
        segments = []
        for match in re.finditer(r'[^\n]+(?:\n(?!\n)[^\n]+)*', page.final_text):
            contributors = [w for w in words if match.start() <= w['char_start'] < match.end()]
            if contributors:
                segments.append(dict(char_start=match.start(), char_end=match.end(),
                    bbox=box_of(contributors), source=contributors[0]['source']))
    candidates = _numeric(page.final_text, words, segments, page.page_number)
    fields = ('metric', 'period', 'value', 'unit', 'status', 'comparison_basis',
              'char_start', 'char_end', 'quote', 'source_spans')
    return any(all(fact.get(k) == candidate.get(k) for k in fields)
        and ('period_binding' not in fact or fact['period_binding'] == candidate['period_binding'])
        for candidate in candidates)
