"""Selection must fail closed independently of extraction and hybrid ranks."""
import hashlib
import pytest

from app.evidence_bundle import build_evidence_pack, requirements_for
from tests.test_evidence_bundle import row, candidates


def table_requirements(question):
    from app.evidence_requirements import table_requirements as implementation
    return implementation(question)


def fact_requirement_match(requirement, fact):
    from app.evidence_requirements import fact_requirement_match as implementation
    return implementation(requirement, fact)


def table_fact(record, metric, period='2026F', unit='십억원', value='17'):
    text = record[0].content
    spans = []
    for role, quote in {'row': metric, 'metric': metric, 'columns': period,
                        'unit': unit, 'value': value}.items():
        start = text.index(quote)
        spans.append({'role': role, 'char_start': start, 'char_end': start + len(quote),
                      'quote': quote, 'bbox': [1, 2, 100, 20], 'source': 'paddle_structure'})
    return {'metric': metric, 'row_label': metric, 'period': period, 'unit': unit,
            'value': value, 'page_number': record[1].page_number,
            'quote': text, 'source_spans': spans}


@pytest.mark.parametrize('requested,actual', [
    ('영업이익', '영업이익률'), ('매출', '매출 증가율'), ('순이익', '순이익률'),
    ('영업이익', '영업이익 증가율'), ('EBITDA', '영업이익')])
def test_distinct_metric_rejects_token_collision(requested, actual):
    requirement = table_requirements(f'표의 2026F {requested}을 알려줘.')[0]
    matched, checks = fact_requirement_match(requirement,
        {'metric': actual, 'row_label': actual, 'period': '2026F', 'unit': '%', 'value': '17'})
    assert not matched
    assert any(c['component'] == 'metric' and c['reason'] == 'metric_mismatch' for c in checks)


@pytest.mark.parametrize('wanted,actual', [
    ('2026F', '2025A'), ('2Q26F', '2Q26P'), ('2026', '2026F'),
    ('FY2026', '2026'), ('2026F', '2Q26F')])
def test_period_status_and_granularity_are_exact(wanted, actual):
    requirement = table_requirements(f'표의 {wanted} 영업이익을 알려줘.')[0]
    matched, checks = fact_requirement_match(requirement,
        {'metric': '영업이익', 'row_label': '영업이익', 'period': actual,
         'unit': '십억원', 'value': '17'})
    assert not matched and any(c['reason'] == 'period_mismatch' for c in checks)


@pytest.mark.parametrize('metric,unit', [('영업이익', '%'), ('영업이익률', '십억원')])
def test_unit_family_must_match_metric(metric, unit):
    requirement = table_requirements(f'표의 2026F {metric}을 알려줘.')[0]
    assert not fact_requirement_match(requirement, {'metric': metric, 'row_label': metric,
        'period': '2026F', 'unit': unit, 'value': '17'})[0]


@pytest.mark.parametrize('clause', ['표의 2026F 영업이익을 조원 단위로 알려줘.',
                                  '표의 2026F 영업이익(조원)을 알려줘.'])
def test_explicit_unit_is_not_satisfied_by_another_money_unit(clause):
    requirement = table_requirements(clause)[0]
    assert not fact_requirement_match(requirement, {'metric': '영업이익', 'row_label': '영업이익',
        'period': '2026F', 'unit': '십억원', 'value': '17'})[0]


def test_compound_metrics_are_scoped_to_their_own_clause():
    requirements = requirements_for('2030년 영업이익률 가이던스 상향 이유와 표의 2026F 영업이익을 함께 알려줘.')
    table = next(r for r in requirements if r['kind'] == 'table')
    assert table['metric']['normalized'] == '영업이익'
    assert table['period'] == '2026F' and table['numeric_value_required']


def test_correct_candidate_preference_and_false_complete_regression():
    question = '2030년 영업이익률 가이던스 상향 이유와 표의 2026F 영업이익을 함께 알려줘.'
    narrative = row('영업이익률 가이던스는 비용 감소 효과로 상향되어 수익성이 개선됐다.', 1)
    wrong = row('영업이익률 2026F % 17', 2)
    correct = row('영업이익 2026F 십억원 17', 3)
    document = narrative[2]
    rows = [narrative]
    for chunk, page, _ in (wrong, correct):
        chunk.document_id = page.document_id = document.id
        rows.append((chunk, page, document))
    facts = {wrong[0].id: [table_fact(wrong, '영업이익률', unit='%')],
             correct[0].id: [table_fact(correct, '영업이익')]}
    pack, complete = build_evidence_pack(question, requirements_for(question),
        candidates(*rows), facts, {})
    assert complete
    assert [f['metric'] for item in pack for f in item.get('table_evidence', [])] == ['영업이익']
    pack, complete = build_evidence_pack(question, requirements_for(question),
        candidates(*rows[:2]), facts, {})
    assert not complete and not any(item.get('table_evidence') for item in pack)


def test_comparison_main_cell_alone_cannot_be_complete():
    requirement = table_requirements('표의 2026F 영업이익과 컨센서스를 비교해줘.')[0]
    fact = {'metric': '영업이익', 'row_label': '영업이익', 'period': '2026F',
            'unit': '십억원', 'value': '17'}
    assert not fact_requirement_match(requirement, fact)[0]
    fact['comparison_cell'] = {'label': '컨센서스', 'period': '2026F',
                               'unit': '%', 'value': '19'}
    assert not fact_requirement_match(requirement, fact)[0]


def test_explicit_narrative_factors_are_separate_requirements():
    requirements = requirements_for('원가 및 환율의 개선 영향과 표의 2026F 영업이익을 함께 알려줘.')
    narratives = [r for r in requirements if r['kind'] == 'narrative']
    assert len(narratives) == 2


def test_partial_explicit_narrative_factors_cannot_be_complete():
    question = '원가 및 환율의 개선 영향과 표의 2026F 영업이익을 함께 알려줘.'
    narrative = row('원가 하락 효과로 영업이익이 개선됐다.', 1)
    table = row('영업이익 2026F 십억원 17', 2)
    table[0].document_id = table[1].document_id = narrative[2].id
    table = (table[0], table[1], narrative[2])
    pack, complete = build_evidence_pack(question, requirements_for(question),
        candidates(narrative, table), {table[0].id: [table_fact(table, '영업이익')]}, {})
    assert not complete


def test_conditions_cannot_be_pooled_from_different_incomplete_facts():
    question = '표의 2026F 영업이익을 알려줘.'
    rows = [row('영업이익률 2026F % 17', 1), row('영업이익 2025A 십억원 17', 2),
            row('영업이익 2026F % 17', 3)]
    document = rows[0][2]
    for chunk, page, _ in rows:
        chunk.document_id = page.document_id = document.id
    pool = [(chunk, page, document) for chunk, page, _ in rows]
    facts = {rows[0][0].id: [table_fact(rows[0], '영업이익률', unit='%')],
             rows[1][0].id: [table_fact(rows[1], '영업이익', period='2025A')],
             rows[2][0].id: [table_fact(rows[2], '영업이익', unit='%')]}
    audit = {}
    pack, complete = build_evidence_pack(question, requirements_for(question),
                                         candidates(*pool), facts, {}, audit=audit)
    assert not complete and pack == []
    assert not audit['coverage'][0]['matched']
    assert {c['component'] for entry in audit['candidates'] for c in entry['checks']
            if not c['matched']} >= {'metric', 'period', 'unit'}


def test_absent_table_facts_are_incomplete_even_with_numeric_prose():
    question = '표의 2024년 리스크인수율을 2023년과 비교해줘.'
    narrative = row('리스크인수율은 2024년 3%에서 개선 효과가 나타났다.', 1)
    pack, complete = build_evidence_pack(question, requirements_for(question),
                                         candidates(narrative), {}, {})
    assert not complete and pack == []


def test_segment_must_match_the_same_fact():
    requirement = table_requirements('표의 2026F 소재 영업이익을 알려줘.')[0]
    assert not fact_requirement_match(requirement, {'metric': '영업이익', 'row_label': '기계',
        'period': '2026F', 'unit': '십억원', 'value': '17'})[0]


def test_comparison_requires_both_verified_cell_spans():
    question = '표의 2026F 영업이익과 컨센서스를 비교해줘.'
    table = row('영업이익 2026F 십억원 17 컨센서스 19', 1)
    fact = table_fact(table, '영업이익')
    spans = []
    for role, quote in (('comparison_columns', '컨센서스'), ('comparison_value', '19')):
        start = table[0].content.index(quote)
        spans.append({'role': role, 'char_start': start, 'char_end': start+len(quote),
                      'quote': quote, 'bbox': [1, 2, 100, 20], 'source': 'paddle_structure'})
    fact['source_spans'] += spans
    fact['comparison_cell'] = {'label': '컨센서스', 'period': '2026F', 'unit': '십억원',
                               'value': '19', 'source_spans': spans}
    pack, complete = build_evidence_pack(question, requirements_for(question),
        candidates(table), {table[0].id: [fact]}, {})
    assert complete and pack[0]['table_evidence'][0]['comparison_cell']['value'] == '19'
    fact['comparison_cell'] = {**fact['comparison_cell'], 'source_spans': [{**spans[1], 'quote': '99'}]}
    pack, complete = build_evidence_pack(question, requirements_for(question),
        candidates(table), {table[0].id: [fact]}, {})
    assert not complete and pack == []


def test_equivalent_verified_fact_prefers_existing_narrative_page():
    question = '수익성 개선 이유와 표의 2026F 영업이익을 함께 알려줘.'
    discussion = row('수익성은 원가 하락 효과로 개선됐다. 영업이익 2026F 십억원 17', 1)
    appendix = row('영업이익 2026F 십억원 17', 3)
    appendix[0].document_id = appendix[1].document_id = discussion[2].id
    appendix = (appendix[0], appendix[1], discussion[2])
    pool = candidates(discussion, appendix)
    pool[0] = (*pool[0][:4], 15)
    pack, complete = build_evidence_pack(question, requirements_for(question), pool,
        {discussion[0].id: [table_fact(discussion, '영업이익')],
         appendix[0].id: [table_fact(appendix, '영업이익')]}, {})
    assert complete and {item['page_number'] for item in pack} == {1}
    # Different values are not equivalent and must keep their original ranks.
    appendix[1].final_text = appendix[0].content = '영업이익 2026F 십억원 19'
    appendix[1].extraction.final_text_sha256 = hashlib.sha256(appendix[1].final_text.encode()).hexdigest()
    appendix[1].extraction.provenance['selected_words'][0]['text'] = appendix[1].final_text
    pack, complete = build_evidence_pack(question, requirements_for(question), pool,
        {discussion[0].id: [table_fact(discussion, '영업이익')],
         appendix[0].id: [table_fact(appendix, '영업이익', value='19')]}, {})
    assert complete
    assert next(item for item in pack if item.get('table_evidence'))['page_number'] == 3
