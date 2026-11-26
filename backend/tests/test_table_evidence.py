from types import SimpleNamespace
from uuid import uuid4

from app.chunking import split_page
from app.citation_display import citation_display
from app.table_evidence import (extract_page_table_facts, fact_matches_query,
                                temporal_context, verified_table_candidates)

TABLE = '''표 4. 사업부문 실적 (십억원)
1026 2Q26F 2026E 2027E
매출액 12 13 14 15
- 소재 3 4 5 6
영업이익 1 2 3 4
- 소재 5 6 7 8
자료: 연구센터
'''


def rows_for(text, size=45):
    doc = SimpleNamespace(id=uuid4())
    page = SimpleNamespace(id=uuid4(), document_id=doc.id, page_number=4, final_text=text)
    return [(SimpleNamespace(id=uuid4(), page_id=page.id, document_id=doc.id, page_number=4,
                             content=c.content, char_start=c.char_start, char_end=c.char_end), page, doc)
            for c in split_page(text, size)]


def test_period_column_and_parent_metric_preserved_across_chunks():
    pool = verified_table_candidates(rows_for(TABLE), '소재의 2Q26F 영업이익은?')
    fact = next(f for _, f in pool if f['row_label'] == '소재')
    assert (fact['metric'], fact['column_name'], fact['period'], fact['value'], fact['unit']) == (
        '영업이익', '2Q26F', '2Q26F', '6', '십억원')
    assert fact['page_number'] == 4 and fact['status'] == 'forecast'
    assert len(fact['source_chunk_ids']) > 1
    assert fact['quote'] == '- 소재 5 6 7 8'
    for span in fact['source_spans']:
        assert TABLE[span['char_start']:span['char_end']] == span['quote']


def test_damaged_period_never_inferred_and_duplicate_year_not_certified():
    facts = extract_page_table_facts(TABLE, 4)
    assert all(f['period'] != '1Q26' and f['period'] != '1026' for f in facts)
    damaged = TABLE.replace('2027E', '2026E')
    assert not any(f['period'] == '2026E' for f in extract_page_table_facts(damaged, 4))


def test_missing_cell_or_split_row_rejected_not_shifted():
    for replacement in ['- 소재 5 7 8', '- 소재 5 6\n7 8', '- 소재 5 X 7 8']:
        facts = extract_page_table_facts(TABLE.replace('- 소재 5 6 7 8', replacement), 4)
        assert not any(f['metric'] == '영업이익' and f['row_label'] == '소재' for f in facts)


def test_forecast_actual_and_market_expectation_are_distinct_literal_spans():
    facts = extract_page_table_facts(TABLE.replace('1026', '1Q26A'), 4)
    assert {f['status'] for f in facts if f['period'] == '1Q26A'} == {'actual'}
    text = '2Q26 실적은 시장 기대치를 상회했다. 2026E 전망은 전년 대비 증가다.'
    context = temporal_context(text, 17)
    assert [p['status'] for p in context['period_mentions']] == ['unspecified', 'forecast']
    assert {'실적', '시장 기대치', '전망', '전년 대비'} <= {p['text'] for p in context['basis_mentions']}
    for span in context['period_mentions'] + context['basis_mentions']:
        assert text[span['char_start']-17:span['char_end']-17] == span['text']


def test_ordinary_sentence_not_table_and_incomplete_table_falls_back():
    prose = '2Q26 매출액은 12억원, 영업이익은 3억원으로 전년 대비 4% 증가했다.'
    assert extract_page_table_facts(prose, 1) == []
    assert citation_display(prose, 1, prose).kind == 'text'
    broken = '매출액 1 2 3 4\n영업이익 5 6 7 8\n소재 1 2 3 4'
    assert citation_display(broken, 1, broken).kind == 'table_fallback'


def test_missing_header_chunk_or_wrong_page_cannot_certify():
    rows = rows_for(TABLE)
    assert verified_table_candidates(rows, '소재 2Q26F 영업이익')
    assert not verified_table_candidates(rows[1:], '소재 2Q26F 영업이익')
    rows[0][0].page_number = 99
    assert not verified_table_candidates(rows, '소재 2Q26F 영업이익')


def test_metric_and_period_required_no_page_only_matching():
    fact = next(f for f in extract_page_table_facts(TABLE, 4)
                if f['row_label'] == '소재' and f['metric'] == '영업이익')
    assert not fact_matches_query(fact, '소재 매출액 2Q26F')
    assert not fact_matches_query(fact, '소재 영업이익 2Q27F')
    assert not fact_matches_query(fact, '영업이익 2Q26F')


def test_explicit_business_row_does_not_promote_consolidated_total():
    pool = verified_table_candidates(rows_for(TABLE), '소재 2Q26F 영업이익')
    assert {f['row_label'] for _, f in pool} == {'소재'}


def test_unknown_basis_is_not_guessed_from_the_current_date():
    text = TABLE.replace('1026', '1Q26').replace('2Q26F', '2Q26')
    facts = extract_page_table_facts(text, 4)
    assert {f['status'] for f in facts if f['period'] == '2Q26'} == {'unspecified'}


def test_separate_table_pool_recovers_missing_candidate_without_changing_rrf(db, monkeypatch):
    from datetime import date
    from app.models import Document, Page, Chunk, TextSource, DocumentType, DocumentStatus
    from app.search import hybrid_search, SearchFilters
    doc = Document(company_name='가상기업', stock_code=None, document_type=DocumentType.broker_report,
                   issuer='테스트', published_at=date(2026, 1, 1), filename='fixture',
                   storage_path='/unused', file_hash='0'*64, status=DocumentStatus.completed, total_pages=7)
    db.add(doc)
    db.flush()
    for number, content in enumerate([TABLE] + ['방해 소재 2Q26F 영업이익']*6, 1):
        page = Page(document_id=doc.id, page_number=number, final_text=content, text_source=TextSource.native)
        db.add(page)
        db.flush()
        for span in split_page(content, 45):
            db.add(Chunk(document_id=doc.id, page_id=page.id, page_number=number,
                         content=span.content, char_start=span.char_start, char_end=span.char_end))
    db.flush()
    class DistractorScores:
        def __init__(self, tokens):
            self.tokens = tokens
        def get_scores(self, query):
            return [100 if '방해' in tokens else 0 for tokens in self.tokens]
    class NoEmbedding:
        available = False
        unavailable_reason = 'offline fixture'
    monkeypatch.setattr('app.search.BM25Okapi', DistractorScores)
    query = '소재 2Q26F 영업이익'
    before = hybrid_search(db, query, 5, SearchFilters(document_id=doc.id), NoEmbedding(), rerank=False)
    after = hybrid_search(db, query, 5, SearchFilters(document_id=doc.id), NoEmbedding())
    assert all(r['page_number'] != 1 for r in before.results)
    first = after.results[0]
    assert first['page_number'] == 1
    assert first['retrieval_reason'] == 'verified_table_conditions'
    assert first['table_evidence'][0]['value'] == '6'
    from app.schemas import SearchResultItem
    payload = SearchResultItem(**first).model_dump(mode='json')
    assert isinstance(payload['table_evidence'][0]['document_id'], str)
    assert payload['table_evidence'][0]['source_spans']
    assert first['rrf_rank'] is None or first['rrf_rank'] > 5
    assert [(r['chunk_id'], r['rrf_score']) for r in after.results[1:]] == [
        (r['chunk_id'], r['rrf_score']) for r in before.results[:4]]


def test_forecast_cell_cannot_satisfy_missing_comparison_basis():
    fact = next(f for f in extract_page_table_facts(TABLE, 4)
                if f['row_label'] == '소재' and f['metric'] == '영업이익' and f['period'] == '2Q26F')
    assert not fact_matches_query(fact, '소재 2Q26F 영업이익 시장 기대치를 알려줘')
    assert not fact_matches_query(fact, '소재 2Q26F 영업이익 전년 대비 증가율')
    assert not fact_matches_query(fact, '소재 2Q26A 영업이익 실제 실적')
