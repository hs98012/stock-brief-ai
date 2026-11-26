"""Geometry fixtures have no company, report, or expected-answer shortcuts."""
from copy import deepcopy
from hashlib import sha256
from types import SimpleNamespace
from app.spatial_tables import extract_spatial_facts


def grid(rows, *, unit='(십억원, %)'):
    text = ''
    words = []
    for line, cells in enumerate(rows):
        for x, token in cells:
            if text:
                text += ' '
            start = len(text)
            text += token
            words.append(dict(text=token, char_start=start, char_end=len(text),
                bbox=[x, 20 + line * 20, x + max(15, len(token) * 5), 32 + line * 20],
                source='paddle_structure', confidence=99, line_id=f'p:{line}'))
    return text, words


def test_two_level_header_keeps_period_and_comparison_cells():
    from app.table_evidence import fact_matches_query
    text, words = grid([
        [(0, '표'), (30, '(십억원, %)'), (260, '2Q26F')],
        [(100, '1Q26'), (200, '발표치'), (300, '컨센서스'), (400, '차이')],
        [(0, '영업이익'), (100, '11'), (200, '12'), (300, '13'), (400, '-7.7')],
        [(0, '영업이익률'), (100, '8.1'), (200, '8.2'), (300, '8.3'), (400, '-0.1')],
    ])
    facts = extract_spatial_facts(text, words, 2)
    target = next(f for f in facts if f['row_label'] == '영업이익' and f['column_name'] == '발표치')
    assert (target['period'], target['unit'], target['value']) == ('2Q26F', '십억원', '12')
    assert (target['comparison_cell']['label'], target['comparison_cell']['value']) == ('컨센서스', '13')
    assert fact_matches_query(target, '표의 2Q26F 영업이익 발표치와 컨센서스를 알려줘')
    without_comparison = deepcopy(target)
    without_comparison['comparison_cell'] = None
    assert not fact_matches_query(without_comparison, '표의 2Q26F 영업이익 발표치와 컨센서스를 알려줘')
    assert all(text[s['char_start']:s['char_end']] == s['quote'] for s in target['source_spans'])
    assert not any(f['row_label'] == '영업이익률' and f['unit'] == '십억원' for f in facts)
    assert not any(f['row_label'] == '영업이익' and f['value'] == '11' and f['period'] == '2Q26F' for f in facts)


def test_ambiguous_unit_and_nearby_number_abstain():
    text, words = grid([
        [(0, '표'), (30, '(원, 조원, %, %pt)'), (210, '3Q26F')],
        [(150, 'New'), (250, 'Old'), (350, '변경률')],
        [(0, '영업이익'), (150, '73.2'), (250, '79.3'), (350, '-7.7')],
        [(0, '영업이익률'), (150, '78.0'), (250, '79.0'), (350, '-1.0')],
    ])
    facts = extract_spatial_facts(text, words, 2)
    assert not any(f['row_label'] == '영업이익' and f['column_name'] in {'New', 'Old'} for f in facts)
    assert not any(f['row_label'] == '영업이익률' for f in facts)


def test_cell_table_unit_does_not_leak_from_previous_rate_row():
    from app.fact_fusion import serialize_groups
    from app.native_tables import extract_native_facts
    entries = [('(십억원)', [0, 0, 60, 10]), ('2Q26F', [100, 0, 140, 10]),
        ('YoY', [0, 20, 40, 30]), ('(%)', [42, 20, 60, 30]), ('12.0', [110, 20, 140, 30]),
        ('영업이익', [0, 40, 60, 50]), ('2,629', [110, 40, 140, 50])]
    text, words, _ = serialize_groups([[dict(text=token, bbox=box, source='native',
        confidence=100, line_id=str(i)) for i, (token, box) in enumerate(entries)]])
    cells = [dict(row=r, column=c, bbox=[c*100, r*20, (c+1)*100, (r+1)*20], text='')
             for r in range(3) for c in range(2)]
    table = dict(index=0, bbox=[0, 0, 200, 60], row_count=3, column_count=2, cells=cells)
    facts = extract_native_facts(text, words, [table], 1)
    assert next(f for f in facts if f['row_label'] == '영업이익')['unit'] == '십억원'


def test_spatial_validator_rejects_crossed_row_period_and_comparison():
    from app.spatial_tables import spatial_fact_valid
    text, words = grid([
        [(0, '표'), (30, '(십억원, %)'), (260, '2Q26F')],
        [(200, '발표치'), (300, '컨센서스')],
        [(0, '영업이익'), (200, '12'), (300, '13')],
        [(0, '순이익'), (200, '10'), (300, '11')],
    ])
    fact = next(f for f in extract_spatial_facts(text, words, 2)
                if f['row_label'] == '영업이익' and f['column_name'] == '발표치')
    assert spatial_fact_valid(fact)
    for role in ('row', 'period', 'unit', 'comparison_value'):
        damaged = deepcopy(fact)
        span = next(span for span in damaged['source_spans'] if span['role'] == role)
        span['bbox'][1] += 100
        span['bbox'][3] += 100
        assert not spatial_fact_valid(damaged), role


def test_missing_comparison_column_is_not_filled_by_nearby_number():
    text, words = grid([
        [(0, '표'), (30, '(십억원)'), (260, '2Q26F')],
        [(200, '발표치'), (300, '컨센서스'), (400, '차이')],
        [(0, '영업이익'), (200, '12'), (245, '99'), (400, '-1')],
        [(0, '순이익'), (200, '10'), (245, '88'), (400, '-2')],
    ])
    facts = extract_spatial_facts(text, words, 2)
    primary = next(f for f in facts if f['row_label'] == '영업이익' and f['column_name'] == '발표치')
    assert primary['comparison_cell'] is None
    assert not any(f['column_name'] == '컨센서스' for f in facts)


def test_stored_spatial_fact_is_rederived_and_tampering_is_rejected():
    from app.extraction_provenance import validated_stored_facts
    from app.fact_fusion import PARSER_VERSION
    text, words = grid([
        [(0, '표'), (30, '(십억원)'), (250, '2Q26F')],
        [(200, '발표치'), (300, '컨센서스')],
        [(0, '영업이익'), (200, '12'), (300, '13')],
        [(0, '순이익'), (200, '10'), (300, '11')],
    ])
    facts = extract_spatial_facts(text, words, 2)
    page = SimpleNamespace(page_number=2, final_text=text, extraction=SimpleNamespace(
        parser_version=PARSER_VERSION, final_text_sha256=sha256(text.encode()).hexdigest(),
        provenance=dict(selected_words=words, native_tables=[], paddle_tables=[], unsafe_spans=[]),
        table_facts=facts))
    assert any(f['row_label'] == '영업이익' and f['comparison_cell']['value'] == '13'
               for f in validated_stored_facts(page))
    changed = deepcopy(facts)
    changed[0]['comparison_cell']['value'] = '99'
    page.extraction.table_facts = changed
    assert changed[0] not in validated_stored_facts(page)
