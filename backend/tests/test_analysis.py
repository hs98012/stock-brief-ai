from datetime import date
import json
from uuid import uuid4

import httpx
import pytest
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.embeddings import get_embedding_provider
from app.generation import (GenerationConnectionError, GenerationHTTPError, GenerationJSONError,
    GenerationConfigurationError, GenerationOutputError, GenerationRateLimitError,
    GenerationResponseError, GenerationServerError, FallbackGenerationProvider,
    GeminiGenerationProvider, OLLAMA_ANALYSIS_SCHEMA, OllamaGenerationProvider,
    get_generation_provider)
from app.main import app
from app.analysis_service import (_grounded_polarity_fallback, _item_supported_by_quotes,
    _persist_run)
from app.models import AnalysisRun, DocumentType, EmbeddingStatus
from app.schemas import GeneratedAnalysis, GeneratedItem
from tests.test_hybrid_search import FakeEmbeddingProvider, UnavailableEmbeddingProvider, seed_chunk


class FakeGenerationProvider:
    provider_name = "ollama"; model = "gemma3:4b"; available = True; unavailable_reason = None

    def __init__(self, result: GeneratedAnalysis): self.result = result; self.calls = 0
    def generate(self, prompt: str) -> GeneratedAnalysis:
        self.calls += 1
        assert "evidence packet" in prompt and "positive_candidates" in prompt and "negative_candidates" in prompt and "rrf_score" not in prompt
        return self.result


class UnavailableGenerationProvider:
    provider_name = "ollama"; model = "gemma3:4b"; available = False
    unavailable_reason = "Ollama 서버 오류. `ollama pull gemma3:4b`를 실행하세요."

    def generate(self, prompt): raise AssertionError("사용 불가 provider를 호출하면 안 됩니다.")


def ready_document(db, content="HBM 수요 증가가 실적 전망에 긍정적이라는 리포트 해석입니다."):
    document, chunk = seed_chunk(db, content)
    chunk.embedding = FakeEmbeddingProvider().embed([content])[0]
    chunk.embedding_provider = FakeEmbeddingProvider.provider_name
    chunk.embedding_model = FakeEmbeddingProvider.model
    chunk.embedding_dimensions = FakeEmbeddingProvider.dimensions
    document.embedding_status = EmbeddingStatus.completed
    document.embedding_provider = FakeEmbeddingProvider.provider_name
    document.embedding_model = FakeEmbeddingProvider.model
    document.embedding_dimensions = FakeEmbeddingProvider.dimensions
    db.commit()
    return document, chunk


def set_providers(generation):
    app.dependency_overrides[get_embedding_provider] = lambda: FakeEmbeddingProvider()
    app.dependency_overrides[get_generation_provider] = lambda: generation


def test_quote_support_validation_accepts_explicit_korean_english_business_alias() -> None:
    chunk_id = uuid4()
    item = GeneratedItem(title="파운드리 적자", reason="보고서는 파운드리 영업손실을 부담으로 제시합니다.",
        evidence_chunk_ids=[chunk_id])
    allowed = {chunk_id: {"quote": "표 2. 부문별 실적 전망 2026 3Q26F 4Q26F 영업이익 (조원) Foundry/LS -1.4 -2.2 -0.9"}}
    assert _item_supported_by_quotes(item, allowed)


def test_quote_support_validation_rejects_unquoted_price_and_competition_causes() -> None:
    chunk_id = uuid4()
    item = GeneratedItem(title="수익성 부담", reason="제품 가격 하락과 경쟁 심화가 원인입니다.",
        evidence_chunk_ids=[chunk_id])
    allowed = {chunk_id: {"quote": "영업이익률 (%) Foundry/LS -20.0 -33.3 -12.4"}}
    assert not _item_supported_by_quotes(item, allowed)


def test_general_summary_fallback_uses_only_available_polarity_candidate() -> None:
    positive_id = uuid4(); negative_id = uuid4(); used = set()
    evidence = [
        {"chunk_id": positive_id, "analysis_perspective": "positive", "quote": "HBM 가격 상승"},
        {"chunk_id": negative_id, "analysis_perspective": "negative",
            "quote": "표 2. 부문별 실적 전망 2026 3Q26F 4Q26F 영업이익률 (%) Foundry/LS -20.0 -33.3"},
    ]
    positive = _grounded_polarity_fallback(evidence, "positive", used, "증권사 리포트 해석")
    negative = _grounded_polarity_fallback(evidence, "negative", used, "증권사 리포트 해석")
    assert positive and positive.evidence_chunk_ids == [positive_id]
    assert negative and negative.evidence_chunk_ids == [negative_id]
    assert negative.title == "파운드리 수익성 부담" and "보고서는" in negative.reason
    assert _grounded_polarity_fallback(evidence, "negative", used, "증권사 리포트 해석") is None


def test_general_summary_fallback_does_not_create_missing_polarity() -> None:
    evidence = [{"chunk_id": uuid4(), "analysis_perspective": "neutral", "quote": "회사 연혁"}]
    assert _grounded_polarity_fallback(evidence, "positive", set(), "증권사 리포트 해석") is None
    assert _grounded_polarity_fallback(evidence, "negative", set(), "증권사 리포트 해석") is None


def test_analysis_returns_verified_citation(client, db) -> None:
    document, chunk = ready_document(db)
    generated = GeneratedAnalysis(summary="HBM 관련 전망을 설명한 보고서입니다.", positives=[GeneratedItem(
        title="HBM 수요", reason="증권사 전망에 따르면 수요 증가는 긍정 요인입니다.", evidence_chunk_ids=[chunk.id])], negatives=[],
        insufficient_evidence_note=None)
    set_providers(FakeGenerationProvider(generated))
    response = client.post("/api/v1/analyses", json={"document_id": str(document.id), "question": "HBM 전망"})
    assert response.status_code == 200
    payload = response.json(); item = payload["positives"][0]; citation = payload["citations"][0]
    assert item["interpretation_label"] == "증권사 리포트 해석"
    assert citation["chunk_id"] == str(chunk.id) and citation["filename"] == document.filename
    assert citation["published_at"] == "2026-08-23" and citation["page_number"] == 1 and citation["quote"] == chunk.content
    assert payload["insufficient_evidence_note"] == "근거가 부족해 추가 항목을 제시하지 않았습니다."
    trace_response = client.post("/internal/evaluations/analysis-trace",
        json={"document_id": str(document.id), "question": "HBM 전망"})
    assert trace_response.status_code == 200
    trace = trace_response.json()
    assert trace["candidates"][0]["page_number"] == 1
    assert trace["generated_selection"]["positive"] == [str(chunk.id)]


def test_unknown_evidence_id_rejects_entire_generation(client, db) -> None:
    document, _ = ready_document(db)
    result = GeneratedAnalysis(summary="요약", positives=[GeneratedItem(title="제목", reason="리포트 해석", evidence_chunk_ids=[uuid4()])], negatives=[])
    set_providers(FakeGenerationProvider(result))
    response = client.post("/api/v1/analyses", json={"document_id": str(document.id), "question": "HBM"})
    assert response.status_code == 502 and "검색 결과에 없는" in response.json()["detail"]
    run = db.query(AnalysisRun).one(); assert run.status == "failed" and "evidence_chunk_id" in run.error_reason


def test_citationless_items_are_removed_and_not_filled(client, db) -> None:
    document, _ = ready_document(db)
    result = GeneratedAnalysis(summary="근거 없는 항목은 표시하지 않습니다.",
        positives=[GeneratedItem(title="근거 없음", reason="표시 금지", evidence_chunk_ids=[])], negatives=[])
    set_providers(FakeGenerationProvider(result))
    payload = client.post("/api/v1/analyses", json={"document_id": str(document.id), "question": "HBM"}).json()
    assert payload["analysis_status"] == "insufficient_evidence"
    assert payload["summary"] == "확인할 수 없습니다" and payload["positives"] == [] and payload["negatives"] == []
    assert payload["insufficient_evidence_note"] == "근거가 부족해 추가 항목을 제시하지 않았습니다."


def test_investment_recommendation_item_is_removed(client, db) -> None:
    document, chunk = ready_document(db)
    result = GeneratedAnalysis(summary="Buy rating이 포함된 요약", positives=[GeneratedItem(
        title="Strong Buy Rating", reason="The report recommends a Buy rating.", evidence_chunk_ids=[chunk.id])], negatives=[])
    set_providers(FakeGenerationProvider(result))
    payload = client.post("/api/v1/analyses", json={"document_id": str(document.id), "question": "HBM"}).json()
    assert payload["analysis_status"] == "insufficient_evidence" and payload["summary"] == "확인할 수 없습니다"
    assert payload["positives"] == [] and payload["citations"] == []


@pytest.mark.parametrize("summary", [
    "현재 주가는 단기적으로 매력적일 수 있습니다.",
    "주가 충격은 제한적일 것으로 예상됩니다.",
    "향후 주가 상승이 예상되며 확실한 수익을 낼 수 있습니다.",
])
def test_summary_in_service_voice_with_investment_judgment_is_replaced_when_cited(client, db, summary) -> None:
    document, chunk = ready_document(db)
    result = GeneratedAnalysis(summary=summary, positives=[GeneratedItem(
        title="HBM 수요 증가", reason="보고서는 HBM 수요 증가를 긍정 요인으로 제시합니다.",
        evidence_chunk_ids=[chunk.id])], negatives=[])
    set_providers(FakeGenerationProvider(result))
    payload = client.post("/api/v1/analyses", json={"document_id": str(document.id), "question": "HBM 전망"}).json()
    assert payload["summary"].startswith("보고서는")
    assert payload["summary"] != "확인할 수 없습니다"
    assert payload["positives"] and payload["citations"]


def test_attributed_neutral_report_summary_is_kept(client, db) -> None:
    document, chunk = ready_document(db)
    summary = ("보고서는 HBM 수요 증가 가능성을 긍정 요인으로 언급합니다. "
        "초보자는 이 내용이 향후 실적에 영향을 줄 수 있는 근거라는 점을 확인할 수 있습니다.")
    result = GeneratedAnalysis(summary=summary, positives=[GeneratedItem(
        title="HBM 수요 증가", reason="보고서는 HBM 수요 증가를 긍정 요인으로 제시합니다.",
        evidence_chunk_ids=[chunk.id])], negatives=[])
    set_providers(FakeGenerationProvider(result))
    payload = client.post("/api/v1/analyses", json={"document_id": str(document.id), "question": "HBM 전망"}).json()
    assert payload["summary"] == summary


def test_unattributed_outlook_in_summary_is_replaced_when_cited(client, db) -> None:
    document, chunk = ready_document(db)
    result = GeneratedAnalysis(summary="하반기 실적 개선 가능성이 있습니다.", positives=[GeneratedItem(
        title="HBM 수요 증가", reason="보고서는 HBM 수요 증가를 긍정 요인으로 제시합니다.",
        evidence_chunk_ids=[chunk.id])], negatives=[])
    set_providers(FakeGenerationProvider(result))
    payload = client.post("/api/v1/analyses", json={"document_id": str(document.id), "question": "HBM 전망"}).json()
    assert payload["summary"].startswith("보고서는")
    assert payload["summary"] != "확인할 수 없습니다"


def test_service_voice_positive_item_is_removed_and_grounded_default_fallback_is_neutral(client, db) -> None:
    document, chunk = ready_document(db)
    result = GeneratedAnalysis(summary="확인할 수 없습니다", positives=[GeneratedItem(
        title="HBM 수요 증가", reason="초보 투자자에게 긍정적인 요소입니다.",
        evidence_chunk_ids=[chunk.id])], negatives=[])
    set_providers(FakeGenerationProvider(result))
    question = "이 보고서를 읽고 주식 초보자 관점에서 호재와 악재를 각각 최대 3개까지 요약해줘."
    payload = client.post("/api/v1/analyses", json={"document_id": str(document.id), "question": question}).json()
    assert payload["positives"]
    assert all("초보 투자자에게 긍정" not in item["reason"] for item in payload["positives"])
    assert payload["summary"].startswith("보고서는") and payload["summary"] != "확인할 수 없습니다"


def test_unattributed_item_inference_is_replaced_with_citation_bound_attribution(client, db) -> None:
    document, chunk = ready_document(db)
    result = GeneratedAnalysis(summary="보고서는 HBM 수요를 언급합니다.", positives=[GeneratedItem(
        title="HBM 수요", reason="이는 삼성전자 실적에 긍정적인 요인으로 작용할 수 있습니다.",
        evidence_chunk_ids=[chunk.id])], negatives=[])
    set_providers(FakeGenerationProvider(result))
    payload = client.post("/api/v1/analyses", json={"document_id": str(document.id), "question": "HBM 전망"}).json()
    assert payload["positives"][0]["reason"] == "보고서는 인용된 원문에서 HBM 수요 관련 내용을 제시합니다."
    assert payload["citations"][0]["chunk_id"] == str(chunk.id)


def test_english_item_is_removed_for_korean_question(client, db) -> None:
    document, chunk = ready_document(db)
    result = GeneratedAnalysis(summary="English summary", positives=[GeneratedItem(
        title="General outlook", reason="A generic industry statement.", evidence_chunk_ids=[chunk.id])], negatives=[])
    set_providers(FakeGenerationProvider(result))
    payload = client.post("/api/v1/analyses", json={"document_id": str(document.id), "question": "HBM 전망"}).json()
    assert payload["positives"] == [] and payload["summary"] == "확인할 수 없습니다"


def test_same_chunk_is_not_reused_across_items(client, db) -> None:
    document, chunk = ready_document(db)
    result = GeneratedAnalysis(summary="근거 중복을 제거한 요약입니다.", positives=[GeneratedItem(
        title="첫 번째 호재", reason="실적 전망이 개선된다는 리포트 해석입니다.", evidence_chunk_ids=[chunk.id]), GeneratedItem(
        title="두 번째 호재", reason="같은 근거를 다시 사용한 설명입니다.", evidence_chunk_ids=[chunk.id])], negatives=[])
    set_providers(FakeGenerationProvider(result))
    payload = client.post("/api/v1/analyses", json={"document_id": str(document.id), "question": "HBM 전망"}).json()
    assert len(payload["positives"]) == 1 and len(payload["citations"]) == 1


def test_item_cannot_borrow_specific_fact_from_another_quote(client, db) -> None:
    document, chunk = ready_document(db, "하반기 실적 개선 모멘텀이 기대된다는 리포트 해석입니다.")
    result = GeneratedAnalysis(summary="실적 전망 요약입니다.", positives=[GeneratedItem(
        title="하반기 실적 개선", reason="일회성 비용 해소로 실적이 개선된다는 전망입니다.", evidence_chunk_ids=[chunk.id])], negatives=[])
    set_providers(FakeGenerationProvider(result))
    payload = client.post("/api/v1/analyses", json={"document_id": str(document.id), "question": "한국어 질문"}).json()
    assert payload["positives"] == [] and payload["citations"] == []


def test_no_search_evidence_skips_generation(client, db) -> None:
    document, _ = ready_document(db, "보고서에 있는 별개의 원문입니다.")
    set_providers(FakeGenerationProvider(GeneratedAnalysis(summary="호출되면 안 됨", positives=[], negatives=[])))
    app.dependency_overrides[get_embedding_provider] = lambda: UnavailableEmbeddingProvider()
    payload = client.post("/api/v1/analyses", json={"document_id": str(document.id), "question": "존재하지않는용어"}).json()
    assert payload["analysis_status"] == "insufficient_evidence" and payload["citations"] == []


def test_generation_unavailable_returns_503(client, db) -> None:
    document, _ = ready_document(db)
    set_providers(UnavailableGenerationProvider())
    response = client.post("/api/v1/analyses", json={"document_id": str(document.id), "question": "HBM"})
    assert response.status_code == 503 and "ollama pull gemma3:4b" in response.json()["detail"]


def test_analysis_run_persistence_recovers_once_without_regeneration(db, monkeypatch) -> None:
    document, _ = ready_document(db)
    run = AnalysisRun(document_id=document.id, question="연결 복구", status="processing",
        generation_provider="ollama", generation_model="gemma3:4b")
    db.add(run); db.commit()
    real_commit = db.commit
    commit_calls = 0

    def fail_first_commit():
        nonlocal commit_calls
        commit_calls += 1
        if commit_calls == 1:
            raise OperationalError("UPDATE analysis_runs", {}, RuntimeError("server closed connection"),
                connection_invalidated=True)
        return real_commit()

    monkeypatch.setattr(db, "commit", fail_first_commit)
    _persist_run(db, run.id, status="completed", result={"summary": "검증된 결과"})
    db.expire_all()
    saved = db.get(AnalysisRun, run.id)
    assert saved.status == "completed" and saved.result == {"summary": "검증된 결과"}
    assert commit_calls == 1


def test_final_persistence_disconnect_does_not_call_generation_twice(client, db, monkeypatch) -> None:
    document, chunk = ready_document(db)
    provider = FakeGenerationProvider(GeneratedAnalysis(summary="보고서는 HBM 전망을 언급합니다.",
        positives=[GeneratedItem(title="HBM 수요", reason="보고서는 HBM 수요를 긍정 요인으로 제시합니다.",
            evidence_chunk_ids=[chunk.id])], negatives=[]))
    set_providers(provider)
    real_commit = db.commit
    commit_calls = 0

    def fail_final_commit_once():
        nonlocal commit_calls
        commit_calls += 1
        if commit_calls == 3:
            raise OperationalError("UPDATE analysis_runs", {}, RuntimeError("server closed connection"),
                connection_invalidated=True)
        return real_commit()

    monkeypatch.setattr(db, "commit", fail_final_commit_once)
    response = client.post("/api/v1/analyses", json={"document_id": str(document.id), "question": "HBM 전망"})
    assert response.status_code == 200 and provider.calls == 1
    with Session(bind=db.get_bind()) as verification_db:
        saved = verification_db.query(AnalysisRun).filter(AnalysisRun.question == "HBM 전망").one()
        assert saved.status == "completed"


def ollama_client(handler):
    return httpx.Client(base_url="http://ollama.test", transport=httpx.MockTransport(handler))


def test_ollama_generation_http_and_json_schema(monkeypatch) -> None:
    monkeypatch.delenv("GENERATION_TEMPERATURE", raising=False)
    chunk_id = "296bf384-2892-4a2e-a97b-cf806243e249"
    body = '{"summary":"요약입니다.","positives":[{"title":"제목","reason":"이유","evidence_chunk_ids":["chunk_id: ' + chunk_id + '"]}],"negatives":[],"insufficient_evidence_note":null}'
    def handler(request):
        if request.url.path == "/api/tags": return httpx.Response(200, json={"models": [{"name": "gemma3:4b"}]})
        assert request.url.path == "/api/generate" and b'"stream":false' in request.content and b'"format"' in request.content
        assert b'"options":{"temperature":0.0}' in request.content
        assert b'"$defs"' not in request.content and b'"format":"uuid"' not in request.content
        return httpx.Response(200, json={"response": f"  ```json\n{body}\n```  "})
    provider = OllamaGenerationProvider(base_url="http://ollama.test", client=ollama_client(handler))
    assert provider.available
    generated = provider.generate("prompt")
    assert generated.summary == "요약입니다." and str(generated.positives[0].evidence_chunk_ids[0]) == chunk_id


def test_ollama_generation_temperature_is_configurable(monkeypatch) -> None:
    monkeypatch.setenv("GENERATION_TEMPERATURE", "0.25")
    def handler(request):
        assert json.loads(request.content)["options"]["temperature"] == 0.25
        return httpx.Response(200, json={"response": '{"summary":"요약","positives":[],"negatives":[],"insufficient_evidence_note":null}'})
    provider = OllamaGenerationProvider(base_url="http://ollama.test", client=ollama_client(handler))
    assert provider.generate("prompt").summary == "요약"


def test_ollama_server_and_model_errors() -> None:
    def offline(request): raise httpx.ConnectError("offline", request=request)
    provider = OllamaGenerationProvider(base_url="http://ollama.test", client=ollama_client(offline))
    assert not provider.available and "ollama pull gemma3:4b" in provider.unavailable_reason
    missing = OllamaGenerationProvider(base_url="http://ollama.test", client=ollama_client(lambda request: httpx.Response(200, json={"models": []})))
    assert not missing.available and "모델이 없습니다" in missing.unavailable_reason


def test_ollama_generation_http_error_is_distinct(caplog) -> None:
    provider = OllamaGenerationProvider(base_url="http://ollama.test", client=ollama_client(
        lambda request: httpx.Response(400, json={"error": "failed to parse grammar"})))
    with pytest.raises(GenerationHTTPError, match="HTTP 400"):
        provider.generate("prompt")
    assert "failed to parse grammar" in caplog.text


def test_ollama_generation_connection_error_is_distinct() -> None:
    def offline(request): raise httpx.ConnectError("offline", request=request)
    provider = OllamaGenerationProvider(base_url="http://ollama.test", client=ollama_client(offline))
    with pytest.raises(GenerationConnectionError, match="서버 연결"):
        provider.generate("prompt")


def test_invalid_generation_json_is_rejected(caplog) -> None:
    provider = OllamaGenerationProvider(base_url="http://ollama.test", client=ollama_client(
        lambda request: httpx.Response(200, json={"response": "not-json"})))
    with pytest.raises(GenerationJSONError, match="JSON 파싱"):
        provider.generate("prompt")
    assert "not-json" in caplog.text


def test_invalid_ollama_envelope_is_rejected() -> None:
    provider = OllamaGenerationProvider(base_url="http://ollama.test", client=ollama_client(
        lambda request: httpx.Response(200, text="not-an-envelope")))
    with pytest.raises(GenerationResponseError, match="응답 본문"):
        provider.generate("prompt")


def test_ollama_schema_uses_supported_inline_types() -> None:
    serialized = str(OLLAMA_ANALYSIS_SCHEMA)
    assert "$defs" not in serialized and "$ref" not in serialized and "uuid" not in serialized
    assert OLLAMA_ANALYSIS_SCHEMA["properties"]["positives"]["maxItems"] == 3


class GeminiResponse:
    def __init__(self, text: str, *, blocked: bool = False) -> None:
        self.output_text = text
        self.status = "blocked" if blocked else "completed"


class GeminiInteractions:
    def __init__(self, outcome):
        self.outcomes = list(outcome) if isinstance(outcome, list) else [outcome]
        self.calls = 0; self.kwargs = None
    def create(self, **kwargs):
        self.calls += 1; self.kwargs = kwargs
        outcome = self.outcomes[min(self.calls - 1, len(self.outcomes) - 1)]
        if isinstance(outcome, Exception): raise outcome
        return outcome


class GeminiClient:
    def __init__(self, outcome): self.interactions = GeminiInteractions(outcome)


class GeminiAPIError(Exception):
    def __init__(self, code: int): self.code = code; super().__init__(f"HTTP {code}")


def valid_gemini_body(chunk_id: str | None = None) -> str:
    ids = [] if chunk_id is None else [chunk_id]
    return json.dumps({"summary": "보고서는 실적을 설명합니다.",
        "positives": [] if not ids else [{"title": "실적", "reason": "보고서는 실적을 제시합니다.", "evidence_chunk_ids": ids}],
        "negatives": [], "insufficient_evidence_note": None}, ensure_ascii=False)


def test_gemini_provider_returns_existing_schema_and_structured_config() -> None:
    client = GeminiClient(GeminiResponse(valid_gemini_body()))
    provider = GeminiGenerationProvider(api_key="test-only", model="configured-model", timeout_seconds=12, client=client)
    result = provider.generate("evidence prompt")
    assert isinstance(result, GeneratedAnalysis) and result.summary.startswith("보고서는")
    assert client.interactions.kwargs["model"] == "configured-model"
    assert client.interactions.kwargs["store"] is False
    assert client.interactions.kwargs["timeout"] == 12
    response_format = client.interactions.kwargs["response_format"]
    assert response_format["mime_type"] == "application/json"
    assert response_format["schema"] == OLLAMA_ANALYSIS_SCHEMA


class CountingProvider:
    available = True; unavailable_reason = None
    def __init__(self, name, outcome): self.provider_name = name; self._model = f"{name}-model"; self.outcome = outcome; self.calls = 0
    @property
    def model(self): return self._model
    def generate(self, prompt):
        self.calls += 1
        if isinstance(self.outcome, Exception): raise self.outcome
        return self.outcome


@pytest.mark.parametrize("code", [429, 503, 504])
def test_gemini_retryable_http_errors_attempt_twice_then_fallback_once(code) -> None:
    result = GeneratedAnalysis(summary="보고서는 근거를 제시합니다.", positives=[], negatives=[])
    client = GeminiClient([GeminiAPIError(code), GeminiAPIError(code)])
    delays = []
    gemini = GeminiGenerationProvider(api_key="test-only", client=client, max_attempts=2,
        retry_base_delay_seconds=1, sleep_fn=delays.append)
    ollama = CountingProvider("ollama", result)
    provider = FallbackGenerationProvider(gemini, ollama)
    assert provider.generate("prompt") is result
    assert client.interactions.calls == 2 and delays == [1] and ollama.calls == 1
    assert provider.provider_name == "ollama"
    assert provider.generation_trace["primary_attempts"] == 2
    assert provider.generation_trace["fallback_used"] is True
    assert provider.generation_trace["final_provider"] == "ollama"


@pytest.mark.parametrize("error", [
    httpx.ConnectError("offline", request=httpx.Request("POST", "https://gemini.test")),
    httpx.ReadTimeout("slow", request=httpx.Request("POST", "https://gemini.test")),
])
def test_gemini_connection_and_timeout_retry_then_fallback_once(error) -> None:
    result = GeneratedAnalysis(summary="보고서는 근거를 제시합니다.", positives=[], negatives=[])
    client = GeminiClient([error, error]); ollama = CountingProvider("ollama", result)
    provider = FallbackGenerationProvider(GeminiGenerationProvider(api_key="test-only", client=client,
        max_attempts=2, retry_base_delay_seconds=0, sleep_fn=lambda _: None), ollama)
    assert provider.generate("prompt") is result
    assert client.interactions.calls == 2 and ollama.calls == 1


def test_gemini_success_never_calls_ollama() -> None:
    result = GeneratedAnalysis(summary="보고서는 근거를 제시합니다.", positives=[], negatives=[])
    gemini = CountingProvider("gemini", result); ollama = CountingProvider("ollama", None)
    provider = FallbackGenerationProvider(gemini, ollama)
    assert provider.generate("prompt") is result
    assert gemini.calls == 1 and ollama.calls == 0
    assert provider.generation_trace["final_provider"] == "gemini"
    assert provider.generation_trace["fallback_used"] is False


def test_fallback_none_retries_gemini_but_never_calls_ollama() -> None:
    client = GeminiClient([GeminiAPIError(503), GeminiAPIError(503)])
    ollama = CountingProvider("ollama", None)
    provider = FallbackGenerationProvider(GeminiGenerationProvider(api_key="test-only", client=client,
        max_attempts=2, retry_base_delay_seconds=0, sleep_fn=lambda _: None))
    with pytest.raises(GenerationServerError): provider.generate("prompt")
    assert client.interactions.calls == 2 and ollama.calls == 0
    assert provider.generation_trace["fallback_used"] is False


def test_failed_ollama_fallback_trace_records_final_provider_once() -> None:
    client = GeminiClient([GeminiAPIError(504), GeminiAPIError(504)])
    ollama = CountingProvider("ollama", GenerationOutputError("fallback failed"))
    provider = FallbackGenerationProvider(GeminiGenerationProvider(api_key="test-only", client=client,
        max_attempts=2, retry_base_delay_seconds=0, sleep_fn=lambda _: None), ollama)
    with pytest.raises(GenerationOutputError, match="fallback failed"):
        provider.generate("prompt")
    assert client.interactions.calls == 2 and ollama.calls == 1
    assert provider.generation_trace["final_provider"] == "ollama"
    assert provider.generation_trace["fallback_used"] is True


@pytest.mark.parametrize("error", [GenerationConfigurationError("key/auth/model"), GenerationJSONError("json"), GenerationResponseError("schema")])
def test_non_transient_gemini_errors_never_fallback(error) -> None:
    gemini = CountingProvider("gemini", error); ollama = CountingProvider("ollama", None)
    with pytest.raises(type(error)): FallbackGenerationProvider(gemini, ollama).generate("prompt")
    assert ollama.calls == 0


@pytest.mark.parametrize("code,expected", [(429, GenerationRateLimitError), (503, GenerationServerError),
    (504, GenerationServerError), (500, GenerationOutputError), (401, GenerationConfigurationError),
    (403, GenerationConfigurationError), (404, GenerationConfigurationError)])
def test_gemini_http_errors_are_classified(code, expected) -> None:
    provider = GeminiGenerationProvider(api_key="test-only", client=GeminiClient(GeminiAPIError(code)),
        max_attempts=1, retry_base_delay_seconds=0)
    with pytest.raises(expected): provider.generate("prompt")


def test_gemini_invalid_json_and_missing_key_do_not_fallback() -> None:
    provider = GeminiGenerationProvider(api_key="test-only", client=GeminiClient(GeminiResponse("not-json")))
    with pytest.raises(GenerationJSONError): provider.generate("prompt")
    missing = GeminiGenerationProvider(api_key="", client=GeminiClient(GeminiResponse(valid_gemini_body())))
    assert not missing.available and "GEMINI_API_KEY" in missing.unavailable_reason


def test_gemini_network_error_is_transient_and_safety_block_is_not() -> None:
    request = httpx.Request("POST", "https://gemini.test")
    network = GeminiGenerationProvider(api_key="test-only", client=GeminiClient(httpx.ConnectError("offline", request=request)),
        max_attempts=1)
    with pytest.raises(GenerationConnectionError): network.generate("prompt")
    blocked = GeminiGenerationProvider(api_key="test-only", client=GeminiClient(GeminiResponse("", blocked=True)))
    with pytest.raises(GenerationOutputError, match="안전 필터"): blocked.generate("prompt")


def test_gemini_invalid_json_safety_and_auth_never_retry_or_fallback() -> None:
    outcomes = [GeminiResponse("not-json"), GeminiResponse("", blocked=True), GeminiAPIError(401),
        GeminiAPIError(403), GeminiAPIError(404)]
    expected = [GenerationJSONError, GenerationOutputError, GenerationConfigurationError,
        GenerationConfigurationError, GenerationConfigurationError]
    for outcome, error_type in zip(outcomes, expected, strict=True):
        client = GeminiClient(outcome); ollama = CountingProvider("ollama", None)
        primary = GeminiGenerationProvider(api_key="test-only", client=client, max_attempts=2,
            retry_base_delay_seconds=0, sleep_fn=lambda _: None)
        with pytest.raises(error_type): FallbackGenerationProvider(primary, ollama).generate("prompt")
        assert client.interactions.calls == 1 and ollama.calls == 0


def test_citation_validation_failure_does_not_trigger_provider_fallback(client, db) -> None:
    document, _ = ready_document(db)
    invalid = GeneratedAnalysis(summary="보고서는 근거를 설명합니다.", positives=[GeneratedItem(
        title="실적", reason="보고서는 실적을 제시합니다.", evidence_chunk_ids=[uuid4()])], negatives=[])
    primary = CountingProvider("gemini", invalid); fallback = CountingProvider("ollama", invalid)
    provider = FallbackGenerationProvider(primary, fallback)
    set_providers(provider)
    response = client.post("/api/v1/analyses", json={"document_id": str(document.id), "question": "실적"})
    assert response.status_code == 502
    assert primary.calls == 1 and fallback.calls == 0
    run = db.query(AnalysisRun).one()
    trace = run.result["_evaluation_trace"]["generation"]
    assert run.generation_provider == "gemini" and trace["fallback_used"] is False


def test_provider_selection_supports_gemini_and_existing_ollama(monkeypatch) -> None:
    monkeypatch.setenv("ANALYSIS_LLM_PROVIDER", "gemini"); monkeypatch.setenv("ANALYSIS_LLM_FALLBACK_PROVIDER", "none")
    monkeypatch.setenv("GEMINI_API_KEY", "test-only")
    monkeypatch.setattr("app.generation.GeminiGenerationProvider", lambda: CountingProvider("gemini", None))
    selected = get_generation_provider()
    assert selected.provider_name == "gemini"
    monkeypatch.setenv("ANALYSIS_LLM_PROVIDER", "ollama")
    monkeypatch.setattr("app.generation.OllamaGenerationProvider", lambda: CountingProvider("ollama", None))
    assert get_generation_provider().provider_name == "ollama"
