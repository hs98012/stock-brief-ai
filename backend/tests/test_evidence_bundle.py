"""Document-independent pack fixtures; no production PDF or answer literals."""
import hashlib
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4
from datetime import date

from app.evidence_bundle import build_evidence_pack, requirements_for
from app.search import rank_rows


QUESTION = '소재 실적 개선 이유와 표의 2Q26F 소재 영업이익을 함께 알려줘.'


def row(text, page_number, *, source='paddle_structure'):
    document_id, page_id, chunk_id = uuid4(), uuid4(), uuid4()
    words = [{'char_start': 0, 'char_end': len(text), 'text': text,
              'bbox': [1, 2, 100, 20], 'source': source, 'confidence': 99}]
    page = SimpleNamespace(id=page_id, document_id=document_id, page_number=page_number,
        final_text=text, extraction=SimpleNamespace(parser_version='fixture-v1', table_facts=[],
            final_text_sha256=hashlib.sha256(text.encode()).hexdigest(),
            provenance={'selected_words': words, 'unsafe_spans': [],
                'native_tables': [dict(bbox=[0, 0, 110, 22], cells=[
                    dict(row=0, column=0, text=text, bbox=[0, 0, 110, 22])])]}))
    chunk = SimpleNamespace(id=chunk_id, page_id=page_id, document_id=document_id,
        page_number=page_number, char_start=0, char_end=len(text), content=text, section_title=None)
    document = SimpleNamespace(id=document_id, filename='fixture.pdf', company_name='가상 회사',
        stock_code=None, issuer='가상 발행사', published_at=date(2026, 1, 1), document_type='broker_report')
    return chunk, page, document


def fact(text, page_number):
    roles = {'row': '소재', 'metric': '영업이익', 'columns': '2Q26F',
             'unit': '십억원', 'value': '424'}
    spans = []
    for role, quote in roles.items():
        start = text.index(quote)
        spans.append({'role': role, 'char_start': start, 'char_end': start + len(quote),
                      'quote': quote, 'bbox': [1, 2, 100, 20], 'source': 'paddle_structure'})
    return {'row_label': '소재', 'metric': '영업이익', 'period': '2Q26F',
            'unit': '십억원', 'value': '424', 'page_number': page_number,
            'char_start': 0, 'char_end': len(text), 'quote': text,
            'source_spans': spans}


def candidates(*rows):
    return [((chunk.id, 0.1, index, index), chunk, page, document, index)
            for index, (chunk, page, document) in enumerate(rows, 1)]


def test_compound_pack_contains_narrative_and_table_on_different_pages():
    narrative = row('소재 실적은 원가 하락 효과로 개선될 것으로 전망한다.', 1)
    table = row('표 소재 영업이익 2Q26F 십억원 424', 2)
    # Both pages must belong to one document, even in an isolated fixture.
    table[1].document_id = narrative[2].id
    table[0].document_id = narrative[2].id
    table = (table[0], table[1], narrative[2])
    requirements = requirements_for(QUESTION)
    pool = candidates(table, narrative)
    pool[1] = (*pool[1][:4], 15)
    pack, complete = build_evidence_pack(QUESTION, requirements, pool,
        {table[0].id: [fact(table[0].content, 2)]}, {})
    assert complete and len(pack) == 2
    assert {item['page_number'] for item in pack} == {1, 2}
    assert {item['rank_source'] for item in pack} == {'hybrid_rrf', 'verified_table'}
    assert next(item for item in pack if item['requirement_id'] == 'narrative_1')['rrf_rank'] == 15
    assert all(item['source_spans'] and item['quote'] for item in pack)
    pages = {1: narrative[1], 2: table[1]}
    assert all(pages[item['page_number']].final_text[span['char_start']:span['char_end']] == span['quote']
               for item in pack for span in item['source_spans'])


def test_missing_requirement_or_broken_table_span_cannot_be_complete():
    narrative = row('소재 실적은 원가 하락 효과로 개선될 것으로 전망한다.', 1)
    table = row('표 소재 영업이익 2Q26F 십억원 424', 2)
    table[1].document_id = narrative[2].id
    table[0].document_id = narrative[2].id
    table = (table[0], table[1], narrative[2])
    requirements = requirements_for(QUESTION)
    pack, complete = build_evidence_pack(QUESTION, requirements, candidates(narrative), {}, {})
    assert not complete and [item['requirement_id'] for item in pack] == ['narrative_1']
    broken = fact(table[0].content, 2)
    broken['source_spans'][-1]['quote'] = '999'
    pack, complete = build_evidence_pack(QUESTION, requirements, candidates(narrative, table),
                                         {table[0].id: [broken]}, {})
    assert not complete and len(pack) == 1


def test_broken_numeric_span_cannot_enter_pack():
    question = '소재 실적 개선 이유와 2Q26F 영업이익 수치를 함께 알려줘.'
    narrative = row('소재 실적은 원가 하락 효과로 개선될 것으로 전망한다.', 1)
    numeric = row('소재 영업이익 2Q26F 십억원 424', 2)
    numeric[0].document_id = narrative[2].id
    numeric[1].document_id = narrative[2].id
    numeric = (numeric[0], numeric[1], narrative[2])
    text = numeric[0].content
    spans = []
    for role, quote in {'metric': '영업이익', 'period': '2Q26F',
                        'unit': '십억원', 'value': '424'}.items():
        start = text.index(quote)
        spans.append({'role': role, 'char_start': start, 'char_end': start+len(quote),
                      'quote': quote, 'bbox': [1, 2, 100, 20], 'source': 'paddle_structure'})
    spans[-1]['bbox'] = None
    numeric_fact = {'metric': '영업이익', 'period': '2Q26F', 'unit': '십억원',
                    'value': '424', 'page_number': 2, 'quote': text, 'source_spans': spans}
    pack, complete = build_evidence_pack(question, requirements_for(question),
        candidates(narrative, numeric), {}, {numeric[0].id: [numeric_fact]})
    assert not complete and len(pack) == 1


def test_explicit_table_request_cannot_be_satisfied_by_prose_numeric_fact():
    narrative = row('소재 실적은 원가 하락 효과로 개선될 것으로 전망한다.', 1)
    numeric = row('소재 영업이익 2Q26F 십억원 424', 2)
    numeric[0].document_id = narrative[2].id
    numeric[1].document_id = narrative[2].id
    numeric = (numeric[0], numeric[1], narrative[2])
    text = numeric[0].content
    spans = []
    for role, quote in {'metric': '영업이익', 'period': '2Q26F',
                        'unit': '십억원', 'value': '424'}.items():
        start = text.index(quote)
        spans.append({'role': role, 'char_start': start, 'char_end': start+len(quote),
                      'quote': quote, 'bbox': [1, 2, 100, 20], 'source': 'paddle_structure'})
    numeric_fact = {'metric': '영업이익', 'period': '2Q26F', 'unit': '십억원',
                    'value': '424', 'page_number': 2, 'quote': text, 'source_spans': spans}
    pack, complete = build_evidence_pack(QUESTION, requirements_for(QUESTION),
        candidates(narrative, numeric), {}, {numeric[0].id: [numeric_fact]})
    assert not complete and len(pack) == 1


def test_single_fact_ranking_is_unchanged():
    from tests.test_hybrid_search import UnavailableEmbeddingProvider
    first = row('소재 영업이익을 기록했다.', 1)
    second = row('소재 이익이 증가했다.', 2)
    rows = [first, second]
    before = rank_rows(rows, '소재 영업이익', 5, UnavailableEmbeddingProvider(), rerank=False)
    after = rank_rows(rows, '소재 영업이익', 5, UnavailableEmbeddingProvider())
    assert [(item['chunk_id'], item['quote']) for item in before.results] == [
        (item['chunk_id'], item['quote']) for item in after.results]
    assert after.evidence_pack is None and after.coverage_complete is None


def test_pack_never_exceeds_five_and_does_not_cross_documents():
    first = row('소재 실적은 원가 하락 효과로 개선될 것으로 전망한다.', 1)
    second = row('표 소재 영업이익 2Q26F 십억원 424', 2)
    requirements = requirements_for(QUESTION)
    pack, complete = build_evidence_pack(QUESTION, requirements, candidates(first, second),
        {second[0].id: [fact(second[0].content, 2)]}, {}, limit=5)
    assert not complete and len(pack) <= 5


def test_pack_limit_fails_closed_when_six_distinct_facts_are_required():
    rows = [row(f'지표{index}는 비용 감소 효과로 개선될 것으로 전망한다.', index)
            for index in range(1, 7)]
    document = rows[0][2]
    for chunk, page, _ in rows:
        chunk.document_id = document.id
        page.document_id = document.id
    same_document = [(chunk, page, document) for chunk, page, _ in rows]
    requirements = [{'id': f'narrative_{index}', 'kind': 'narrative',
                     'focus_terms': [f'지표{index}']} for index in range(1, 7)]
    pack, complete = build_evidence_pack('각 지표의 개선 이유를 알려줘', requirements,
                                         candidates(*same_document), {}, {}, limit=5)
    assert not complete and len(pack) == 5


def test_bundle_verifier_rejects_missing_manifest():
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
    from verify_evidence_bundle import evaluate
    import pytest
    with pytest.raises(ValueError, match='Missing or changed'):
        evaluate({'manifests': [], 'revisions': []}, {}, {}, {}, {'units': []})


def test_runtime_bundle_contains_no_document_or_gold_shortcuts():
    source = '\n'.join((Path(__file__).resolve().parents[1] / 'app' / name).read_text()
                       for name in ('evidence_bundle.py', 'evidence_requirements.py', 'structured_cells.py', 'primitive_graph.py'))
    for forbidden in ('POSCO', '삼성전자', 'LG CNS', 'DB손해보험',
                      '현대차', '기아', 'SK하이닉스', '신용보증기금',
                      'posco-multi', '424', '7,570', '11,491', 'evals/'):
        assert forbidden not in source
