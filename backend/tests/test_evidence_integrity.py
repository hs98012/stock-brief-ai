"""Adversarial provenance tests; not financial evaluation samples."""
import pytest

from app.document_candidates import document_candidates
from app.search import SearchFilters, hybrid_search
from tests.test_hybrid_search import UnavailableEmbeddingProvider, seed_chunk


@pytest.mark.parametrize("corruption", ["content", "page_number", "offset", "document_id"])
def test_corrupt_stored_chunk_cannot_be_evidence(db, corruption):
    document, chunk = seed_chunk(db, "영업이익은 전년 대비 증가할 전망입니다.")
    # Equal text on another company's page must still fail document provenance.
    _, other_chunk = seed_chunk(db, chunk.content, ticker="000660")
    if corruption == "content":
        chunk.content = "영업이익은 전년 대비 감소할 전망입니다."
    elif corruption == "page_number":
        chunk.page_number = 2
    elif corruption == "offset":
        chunk.char_start = -1
    else:
        chunk.page_id = other_chunk.page_id
    db.commit()
    assert document_candidates(db, document.id) == []
    assert hybrid_search(db, "영업이익", 5, SearchFilters(document_id=document.id),
        UnavailableEmbeddingProvider()).results == []


def test_partial_chunk_cannot_certify_uncovered_fact(db):
    text = "기업의 설명입니다. 영업이익은 전년 대비 증가할 전망입니다."
    document, chunk = seed_chunk(db, text)
    chunk.char_end = text.index("증가")
    chunk.content = text[:chunk.char_end]
    db.commit()
    assert not any(row["analysis_perspective"] == "positive"
        for row in document_candidates(db, document.id))


def test_absent_requested_year_cannot_borrow_other_year_fact(db):
    from app.analysis_retrieval import collect_analysis_evidence
    document, _ = seed_chunk(db, "2026년 보험 수익성은 개선될 전망입니다.")
    provider = UnavailableEmbeddingProvider()
    assert collect_analysis_evidence(db, document.id, "2099년 보험 수익성을 알려줘", 5, provider) == []
    assert collect_analysis_evidence(db, document.id, "2026년 보험 수익성을 알려줘", 5, provider)


def test_changed_source_during_generation_is_never_published(client, db):
    from app.models import AnalysisRun
    from app.schemas import GeneratedAnalysis, GeneratedItem
    from tests.test_analysis import FakeGenerationProvider, ready_document, set_providers
    document, chunk = ready_document(db, "영업이익은 전년 대비 증가할 전망입니다.")

    class MutatingProvider(FakeGenerationProvider):
        def generate(self, prompt):
            result = super().generate(prompt)
            chunk.content = "변경된 다른 근거"
            db.commit()
            return result

    generated = GeneratedAnalysis(summary="요약", positives=[GeneratedItem(
        title="영업이익 증가 전망", reason="보고서는 증가를 전망합니다.", evidence_chunk_ids=[chunk.id])], negatives=[])
    set_providers(MutatingProvider(generated))
    response = client.post("/api/v1/analyses", json={"document_id": str(document.id), "question": "영업이익"})
    assert response.status_code == 502
    assert db.query(AnalysisRun).one().status == "failed"


def test_sdk_retry_budget_is_bounded():
    pytest.importorskip("google.genai")
    from app.generation import GeminiGenerationProvider
    from google.genai._gaos.google_genai import _translate_retry_config

    provider = GeminiGenerationProvider(api_key="test-only")
    try:
        options = provider.client._api_client._http_options
        assert options.retry_options.attempts == 1
        # Exercise installed SDK's actual mapping, not a mock accepting arbitrary kwargs.
        assert _translate_retry_config(options).max_retries == 1
    finally:
        provider.client.close()


@pytest.mark.parametrize("ending,certainty", [("상회했다.", "reported"), ("상회할 전망이다.", "forecast")])
def test_market_expectation_is_not_itself_a_forecast(ending, certainty):
    from app.evidence_facts import economic_facts
    # LG 2026-08-14 p3: the benchmark word 기대 must not turn an actual into a forecast.
    facts = economic_facts("2Q26 연결영업이익은5,330억원으로전년동기대비92.5% 증가하며시장기대를" + ending)
    assert facts and facts[0]["certainty"] == certainty
