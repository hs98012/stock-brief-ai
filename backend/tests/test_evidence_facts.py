from uuid import uuid4

import pytest

from app.analysis_retrieval import evidence_spans, collect_analysis_evidence
from app.evidence_facts import economic_facts, grounded_card, supported_claim
from app.document_candidates import document_candidates
from app.search import SearchExecution
from tests.test_hybrid_search import seed_chunk


@pytest.mark.parametrize('company', ['가람', '누리', 'Aster'])
@pytest.mark.parametrize('metric,direction,polarity', [
    ('매출', '증가', 'positive'), ('영업이익', '시장 기대치를 상회', 'positive'),
    ('영업이익', '시장 기대치를 하회', 'negative'), ('판매량', '증가', 'positive'),
    ('수요', '증가', 'positive'), ('원가', '증가', 'negative'),
    ('충당금', '증가', 'negative'), ('손실', '증가', 'negative'),
    ('손해율', '하락', 'positive'), ('수요', '둔화', 'negative'),
    ('제품 가격', '하락', 'negative'), ('충당금', '감소', 'positive'),
])
def test_sector_independent_metric_direction(company, metric, direction, polarity):
    quote = f'{company} 부문의 {metric}는 {direction}할 전망입니다.'
    spans = evidence_spans({'chunk_id': uuid4(), 'quote': quote, 'page_number': 1}, '')
    candidate = next(span for span in spans if span['quality_status'] == 'valid')
    assert candidate['analysis_perspective'] == polarity
    title, reason = grounded_card(candidate, polarity)
    assert metric.split()[-1] in title and direction.split()[-1] in title
    assert reason.startswith('보고서는') and '긍정 요인' not in title
    assert quote[candidate['char_start']:candidate['char_end']] == candidate['quote']
    assert grounded_card(candidate, 'negative' if polarity == 'positive' else 'positive') is None


@pytest.mark.parametrize('quote', ['기업은 여러 사업을 운영합니다.', '원가는 증가하지 않았습니다.',
    '가격이 상승했습니다.', '영업이익이 증가한다면 수익성을 살펴야 합니다.'])
def test_no_clear_direction_no_card(quote):
    for span in evidence_spans({'chunk_id': uuid4(), 'quote': quote, 'page_number': 1}, ''):
        assert grounded_card(span, 'positive') is None
        assert grounded_card(span, 'negative') is None


def _price_fact(quote: str) -> dict:
    return next(fact for fact in economic_facts(quote) if fact['metric'] == '가격')


def test_price_increase_with_asp_context_is_selling_price():
    # ASP (average selling price) in the same clause marks 가격 as a selling price.
    quote = '가람 부문은 HBM 가격 인상 효과로 DRAM ASP 상승세를 이어갈 전망입니다.'

    assert _price_fact(quote)['polarity'] == 'positive'
    span = next(span for span in evidence_spans({'chunk_id': uuid4(), 'quote': quote, 'page_number': 1}, '')
        if span['quality_status'] == 'valid')
    assert span['analysis_perspective'] == 'positive'
    title, _ = grounded_card(span, 'positive')
    assert '가격' in title and '인상' in title


def test_price_with_asp_and_cost_context_stays_cost():
    quote = '원재료 가격 인상으로 ASP 상승 효과가 상쇄될 전망입니다.'

    assert _price_fact(quote)['polarity'] == 'negative'


@pytest.mark.parametrize('quote', [
    '가람 부문은 메모리 가격 인하로 ASP 하락이 이어질 전망입니다.',
    '가람 부문은 메모리 가격 하락으로 ASPs 약세가 예상됩니다.',
])
def test_price_decrease_with_asp_context_is_negative(quote):
    assert _price_fact(quote)['polarity'] == 'negative'


def test_price_with_plural_asps_is_selling_price():
    assert _price_fact('HBM 가격 인상으로 DRAM ASPs가 오를 전망입니다.')['polarity'] == 'positive'


@pytest.mark.parametrize('quote', [
    'HBM 가격 인상이 ASPECT 분석에 반영될 전망입니다.',
    'WASP 가격 인상이 예상됩니다.',
    'GASPED 가격 인상이 예상됩니다.',
])
def test_asp_inside_other_word_is_not_selling_context(quote):
    assert _price_fact(quote)['polarity'] == 'ambiguous'


def test_same_paragraph_separate_sentences_and_mixed_sentence():
    row = {'chunk_id': uuid4(), 'page_number': 2, 'quote': '매출은 증가했습니다. 비용은 증가했습니다.'}
    spans = evidence_spans(row, '')
    assert [span['analysis_perspective'] for span in spans] == ['positive', 'negative']
    assert spans[0]['char_end'] <= spans[1]['char_start']
    mixed = evidence_spans({**row, 'quote': '매출은 증가했지만 비용도 증가했습니다.'}, '')
    assert mixed[0]['analysis_perspective'] == 'ambiguous'


def test_metadata_noise_excludes_only_affected_sentence():
    spans = evidence_spans({'chunk_id': uuid4(), 'page_number': 1,
        'quote': 'Analyst 연구원 test@example.com\n매출은 증가했습니다. Bae enue 비용 증가. 손실은 감소했습니다.'}, '')
    valid = [span for span in spans if span['quality_status'] == 'valid']
    assert len(valid) == 2
    assert all('@' not in span['quote'] and 'enue' not in span['quote'] for span in valid)


def test_claim_cannot_borrow_company_numbers_metric_or_cause():
    quote = '가람 부문의 매출은 12% 증가했습니다.'
    rows = [{'quote': quote, 'facts': economic_facts(quote)}]
    assert supported_claim('가람 부문의 매출 증가', '보고서는 매출 증가를 제시합니다.', rows)
    for title in ['누리 매출 증가', '가람 매출 21% 증가', '가람 영업이익 증가', '긍정 요인: 실적 개선 기대']:
        assert not supported_claim(title, '', rows)
    assert not supported_claim('매출 증가', '보고서는 인수로 매출이 증가했다고 제시합니다.', rows)


@pytest.mark.parametrize('quote,wrong_metric', [
    ('영업이익은 기타 원료와 운임비 상승 영향에도 판매량 증가로 개선될 전망이다.', '영업이익'),
    ('별도순이익은 법인세부담감소가기여했다.', '순이익'),
    ('순이익의 배분과 지주사 할인율 축소 계획이다.', '순이익'),
    ('수주가 성장을 견인하고 있다.', '수주'),
    ('매출은 늘었고 시장 예상치(영업이익 12억원)를 상회했다.', '영업이익'),
])
def test_direction_cannot_attach_to_unrelated_metric(quote, wrong_metric):
    assert not any(fact['metric'] == wrong_metric and fact['polarity'] != 'ambiguous'
        for fact in economic_facts(quote))


def test_full_document_scan_keeps_fact_not_in_retrieval_topk(db, monkeypatch):
    source = '기업 소개입니다. ' * 40 + '영업이익은 시장 기대치를 하회했습니다.'
    document, chunk = seed_chunk(db, source)
    monkeypatch.setattr('app.analysis_retrieval.hybrid_search', lambda *a, **kw: SearchExecution([], False, 'offline'))
    result = collect_analysis_evidence(db, document.id, '호재와 악재를 요약해줘', 10, object())
    assert len(result) == 1 and result[0]['analysis_perspective'] == 'negative'
    assert result[0]['quote'] == '영업이익은 시장 기대치를 하회했습니다.'
    assert result[0]['source_chunk_ids'] == [chunk.id]


@pytest.mark.parametrize('complete', [True, False])
def test_table_requires_title_unit_period_alignment(db, complete):
    source = ('표 4. 부문 실적 (억원, %)\n구분 2030 2031F 2032F\n' if complete else '')
    source += '영업이익 1 2 3\n유통 -7 -5 -2\n영업이익률 1 2 3\n'
    document, _ = seed_chunk(db, source)
    rows = document_candidates(db, document.id)
    cards = [grounded_card(row, 'negative') for row in rows]
    assert any(cards) is complete
    if complete:
        table = next(row for row in rows if row.get('table_verified'))
        assert table['table_facts']['values'][0] == {'period': '2030', 'value': '-7'}
