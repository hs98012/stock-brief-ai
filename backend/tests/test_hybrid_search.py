from datetime import date

import pytest
import httpx
from pathlib import Path

from app.embeddings import EmbeddingConfigurationError, OllamaEmbeddingProvider, get_embedding_provider
from app.main import app
from app.models import (EMBEDDING_DIMENSIONS, Chunk, Document, DocumentStatus, DocumentType,
    EmbeddingStatus, Page, TextSource)
from app.search import reciprocal_rank_fusion, tokenize


class FakeEmbeddingProvider:
    provider_name = "ollama"
    model = "fake-embedding-model"
    dimensions = EMBEDDING_DIMENSIONS
    available = True
    unavailable_reason = None

    def embed(self, texts):
        vectors = []
        for text in texts:
            vector = [0.0] * EMBEDDING_DIMENSIONS
            lowered = text.casefold()
            if "파운드리" in lowered or "semiconductor manufacturing" in lowered:
                vector[0] = 1.0
            elif "hbm" in lowered:
                vector[1] = 1.0
            else:
                vector[2] = 1.0
            vectors.append(vector)
        return vectors


class UnavailableEmbeddingProvider:
    provider_name = "ollama"; model = "bge-m3"; dimensions = EMBEDDING_DIMENSIONS
    available = False; unavailable_reason = "Ollama test unavailable"

    def embed(self, texts):
        raise AssertionError("BM25-only 검색에서 embed를 호출하면 안 됩니다.")


def seed_chunk(db, content: str, *, ticker: str = "005930", company: str = "삼성전자", publisher: str = "테스트 발행기관", document_type=DocumentType.broker_report):
    document = Document(company_name=company, stock_code=ticker, document_type=document_type, issuer=publisher,
        published_at=date(2026, 8, 23), filename=f"{ticker}.pdf", storage_path=f"/data/{ticker}.pdf",
        file_hash=(ticker + content).encode().hex()[:64].ljust(64, "0"), status=DocumentStatus.completed, total_pages=1)
    db.add(document); db.flush()
    page = Page(document_id=document.id, page_number=1, native_text=content, final_text=content, text_source=TextSource.native)
    db.add(page); db.flush()
    chunk = Chunk(document_id=document.id, page_id=page.id, page_number=1, content=content, char_start=0, char_end=len(content))
    db.add(chunk); db.commit()
    return document, chunk


def test_fake_embedding_and_same_model_skip(client, db) -> None:
    document, chunk = seed_chunk(db, "HBM 관련 원문 청크")
    app.dependency_overrides[get_embedding_provider] = lambda: FakeEmbeddingProvider()
    first = client.post(f"/api/v1/documents/{document.id}/embeddings")
    second = client.post(f"/api/v1/documents/{document.id}/embeddings")
    assert first.status_code == 200
    assert first.json()["processed_chunk_count"] == 1
    assert second.json()["processed_chunk_count"] == 0 and second.json()["skipped_chunk_count"] == 1
    db.refresh(chunk)
    assert len(chunk.embedding) == EMBEDDING_DIMENSIONS and chunk.embedding_model == "fake-embedding-model"
    status = client.get(f"/api/v1/documents/{document.id}/embedding-status").json()
    assert status["embedding_status"] == "completed" and status["embedded_chunk_count"] == 1


def test_unavailable_ollama_returns_configuration_error(client, db) -> None:
    document, _ = seed_chunk(db, "설정 오류 검증용 일반 문장")
    app.dependency_overrides[get_embedding_provider] = lambda: UnavailableEmbeddingProvider()
    response = client.post(f"/api/v1/documents/{document.id}/embeddings")
    assert response.status_code == 503
    assert response.json()["detail"] == "Ollama test unavailable"


@pytest.mark.parametrize("keyword", ["HBM", "파운드리", "목표주가"])
def test_bm25_exact_financial_terms(client, db, keyword: str) -> None:
    document, _ = seed_chunk(db, f"문서에 보존된 핵심 용어는 {keyword} 입니다.", ticker=f"{len(keyword):06d}")
    app.dependency_overrides[get_embedding_provider] = lambda: UnavailableEmbeddingProvider()
    response = client.post("/api/v1/search", json={"query": keyword})
    assert response.status_code == 200
    payload = response.json(); result = payload["results"][0]
    assert result["document_id"] == str(document.id) and result["bm25_rank"] == 1 and result["vector_rank"] is None
    assert payload["vector_search_used"] is False and payload["vector_search_unavailable_reason"] == "Ollama test unavailable"


def test_vector_semantic_search_and_required_citation_metadata(client, db) -> None:
    document, chunk = seed_chunk(db, "파운드리 공정에 관한 원문 인용문")
    chunk.embedding = FakeEmbeddingProvider().embed([chunk.content])[0]; chunk.embedding_provider = FakeEmbeddingProvider.provider_name
    chunk.embedding_model = FakeEmbeddingProvider.model; chunk.embedding_dimensions = FakeEmbeddingProvider.dimensions
    db.commit()
    app.dependency_overrides[get_embedding_provider] = lambda: FakeEmbeddingProvider()
    response = client.post("/api/v1/search", json={"query": "semiconductor manufacturing"})
    result = response.json()["results"][0]
    assert result["vector_rank"] == 1 and result["bm25_rank"] is None
    assert result["document_name"] == document.filename and result["published_at"] == "2026-08-23"
    assert result["publisher"] == document.issuer and result["document_type"] == "broker_report"
    assert result["page_number"] == 1 and result["quote"] == chunk.content


def test_metadata_filter_is_applied_before_search(client, db) -> None:
    seed_chunk(db, "HBM 문서 첫 번째", ticker="005930", company="삼성전자", publisher="기관A")
    selected, _ = seed_chunk(db, "HBM 문서 두 번째", ticker="000660", company="SK하이닉스", publisher="기관B", document_type=DocumentType.dart_filing)
    app.dependency_overrides[get_embedding_provider] = lambda: UnavailableEmbeddingProvider()
    response = client.post("/api/v1/search", json={"query": "HBM", "ticker": "000660", "publisher": "기관B", "document_type": "dart_filing"})
    payload = response.json()
    assert [item["document_id"] for item in payload["results"]] == [str(selected.id)]
    assert payload["applied_filters"] == {"ticker": "000660", "document_type": "dart_filing", "publisher": "기관B"}


def test_rrf_combines_ranks_deterministically() -> None:
    from uuid import uuid4
    first, second, third = uuid4(), uuid4(), uuid4()
    fused = reciprocal_rank_fusion([first, second], [second, third])
    assert fused[0][0] == second and fused[0][2:] == (2, 1)
    assert {item[0] for item in fused} == {first, second, third}


def test_tokenizer_preserves_korean_english_numbers_and_ticker() -> None:
    assert tokenize("삼성전자 HBM 악재 005930 목표주가") == ["삼성전자", "hbm", "악재", "005930", "목표주가"]


def test_no_search_evidence_returns_explicit_empty_status(client) -> None:
    app.dependency_overrides[get_embedding_provider] = lambda: UnavailableEmbeddingProvider()
    payload = client.post("/api/v1/search", json={"query": "존재하지않는검색어"}).json()
    assert payload["status"] == "no_evidence" and payload["results"] == []


def ollama_client(handler) -> httpx.Client:
    return httpx.Client(base_url="http://ollama.test", transport=httpx.MockTransport(handler))


def test_ollama_embed_http_response() -> None:
    vector = [0.25] * EMBEDDING_DIMENSIONS
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "bge-m3:latest"}]})
        assert request.url.path == "/api/embed" and b'"model":"bge-m3"' in request.content
        return httpx.Response(200, json={"embeddings": [vector]})
    provider = OllamaEmbeddingProvider(base_url="http://ollama.test", client=ollama_client(handler))
    assert provider.available is True
    assert provider.embed(["로컬 임베딩 테스트"]) == [vector]


def test_ollama_server_unavailable_message() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=request)
    provider = OllamaEmbeddingProvider(base_url="http://ollama.test", client=ollama_client(handler))
    assert provider.available is False
    assert "ollama pull bge-m3" in (provider.unavailable_reason or "")


def test_ollama_model_missing_message() -> None:
    provider = OllamaEmbeddingProvider(base_url="http://ollama.test", client=ollama_client(lambda request: httpx.Response(200, json={"models": []})))
    assert provider.available is False
    assert "모델이 없습니다" in (provider.unavailable_reason or "") and "ollama pull bge-m3" in (provider.unavailable_reason or "")


def test_ollama_wrong_vector_dimensions() -> None:
    provider = OllamaEmbeddingProvider(base_url="http://ollama.test", client=ollama_client(
        lambda request: httpx.Response(200, json={"embeddings": [[0.1] * 3]})))
    with pytest.raises(EmbeddingConfigurationError, match="1024차원"):
        provider.embed(["dimension check"])


def test_ollama_migration_contract() -> None:
    migration = (Path(__file__).parents[1] / "alembic/versions/20260823_0003_ollama_embeddings.py").read_text()
    assert "embedding IS NOT NULL" in migration and "vector(1024)" in migration
    assert "ix_chunks_embedding_hnsw" in migration and "자동 삭제·변환하지 않습니다" in migration
