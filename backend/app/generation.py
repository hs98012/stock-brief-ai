import json
import logging
import os
import re
import time
from contextvars import ContextVar
from datetime import datetime, timezone
from functools import wraps
from typing import Any, Protocol

import httpx
from pydantic import ValidationError

from .schemas import AnalysisRequest, GeneratedAnalysis
from .local_inference import serial_local_inference

generation_request_id = ContextVar("generation_request_id", default=None)
generation_event_sink = ContextVar('generation_event_sink', default=None)


def generation_event(stage: str, provider: str | None = None):
    sink = generation_event_sink.get()
    if sink is not None:
        sink({'type': 'status', 'stage': stage, 'provider': provider})


def observed_generation(function):
    @wraps(function)
    def wrapped(self, prompt):
        started = time.monotonic()
        self._trace = {"request_id": generation_request_id.get(), "provider": self.provider_name,
            "model": self.model, "purpose": "analysis_cards", "started_at": datetime.now(timezone.utc).isoformat(),
            "prompt_chars": len(prompt)}
        context = dict(self._trace)
        status = "success"
        try:
            return function(self, prompt)
        except Exception as exc:
            status = type(exc).__name__
            raise
        finally:
            self._trace.update(context)
            self._trace.update(ended_at=datetime.now(timezone.utc).isoformat(), status=status,
                latency_ms=round((time.monotonic() - started) * 1000, 2))
            logger.info("generation_call %s", json.dumps(self._trace, ensure_ascii=False))
    return wrapped

logger = logging.getLogger(__name__)
GENERATION_HELP = "맥에서 Ollama를 실행하고 `ollama pull gemma3:4b` 후 `ollama list`로 모델을 확인하세요."
RESPONSE_LOG_LIMIT = 1000
KOREAN_ANALYSIS_SYSTEM_PROMPT = (
    "당신은 한국어 금융 문서 분석기입니다. 모든 설명과 제목을 자연스러운 한국어로만 작성하세요. "
    "제공된 근거 밖의 사실을 만들지 말고 투자 권유, 매수·매도·보유 추천을 하지 마세요."
)

# Ollama grammar parser에는 인라인 기본 타입만 전달한다. UUID와 길이 등은 응답 후 Pydantic이 검증한다.
OLLAMA_ANALYSIS_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "positives": {"type": "array", "maxItems": 3, "items": {
            "type": "object", "properties": {
                "title": {"type": "string"}, "reason": {"type": "string"},
                "evidence_chunk_ids": {"type": "array", "items": {"type": "string"}},
            }, "required": ["title", "reason", "evidence_chunk_ids"],
        }},
        "negatives": {"type": "array", "maxItems": 3, "items": {
            "type": "object", "properties": {
                "title": {"type": "string"}, "reason": {"type": "string"},
                "evidence_chunk_ids": {"type": "array", "items": {"type": "string"}},
            }, "required": ["title", "reason", "evidence_chunk_ids"],
        }},
        "insufficient_evidence_note": {"type": ["string", "null"]},
    },
    "required": ["summary", "positives", "negatives", "insufficient_evidence_note"],
}


class GenerationTransientError(RuntimeError): pass
class GenerationConfigurationError(RuntimeError): pass
class GenerationPolicyError(GenerationConfigurationError): pass
class GenerationConnectionError(GenerationConfigurationError, GenerationTransientError): pass
class GenerationOutputError(RuntimeError): pass
class GenerationHTTPError(GenerationOutputError): pass
class GenerationResponseError(GenerationOutputError): pass
class GenerationJSONError(GenerationOutputError): pass
class GenerationRateLimitError(GenerationOutputError, GenerationTransientError): pass
class GenerationServerError(GenerationOutputError, GenerationTransientError): pass
class GenerationSafetyError(GenerationOutputError): pass


class GenerationProvider(Protocol):
    @property
    def provider_name(self) -> str: ...
    @property
    def model(self) -> str: ...
    @property
    def available(self) -> bool: ...
    @property
    def unavailable_reason(self) -> str | None: ...
    def generate(self, prompt: str) -> GeneratedAnalysis: ...


def _response_excerpt(response: httpx.Response) -> str:
    # Error bodies can echo prompts, source text, or credentials.
    return "응답 본문은 기록하지 않습니다"


def _strip_json_fence(raw: str) -> str:
    value = raw.strip()
    match = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", value, flags=re.IGNORECASE | re.DOTALL)
    return match.group(1).strip() if match else value


def _normalize_evidence_ids(decoded: object) -> object:
    if not isinstance(decoded, dict):
        return decoded
    uuid_with_optional_label = re.compile(
        r"^(?:chunk_id\s*:\s*)?([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12})$"
    )
    for section in ("positives", "negatives"):
        items = decoded.get(section)
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict) or not isinstance(item.get("evidence_chunk_ids"), list):
                continue
            normalized = []
            for chunk_id in item["evidence_chunk_ids"]:
                if not isinstance(chunk_id, str):
                    normalized.append(chunk_id)
                    continue
                match = uuid_with_optional_label.fullmatch(chunk_id.strip())
                normalized.append(match.group(1) if match else chunk_id)
            item["evidence_chunk_ids"] = normalized
    return decoded



class OllamaGenerationProvider:
    provider_name = "ollama"

    def __init__(self, base_url: str | None = None, model: str | None = None, client: httpx.Client | None = None) -> None:
        self.base_url = (base_url or os.getenv("OLLAMA_BASE_URL", "http://host.docker.internal:11434")).rstrip("/")
        self._model = model or os.getenv("GENERATION_MODEL", "gemma3:4b")
        self.timeout_seconds = float(os.getenv("OLLAMA_GENERATION_TIMEOUT_SECONDS", "600"))
        self.temperature = float(os.getenv("GENERATION_TEMPERATURE", "0"))
        self.client = client or httpx.Client(base_url=self.base_url, timeout=httpx.Timeout(self.timeout_seconds, connect=5.0))
        self._unavailable_reason: str | None = None
        self._trace: dict[str, Any] = {}

    @property
    def model(self) -> str: return self._model

    @property
    def available(self) -> bool:
        try:
            response = self.client.get("/api/tags")
        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            logger.warning("Ollama tags connection failed base_url=%s error=%s", self.base_url, type(exc).__name__)
            self._unavailable_reason = f"Ollama 서버에 연결할 수 없습니다({self.base_url}). {GENERATION_HELP}"
            return False
        except httpx.RequestError as exc:
            logger.warning("Ollama tags request failed base_url=%s error=%s", self.base_url, type(exc).__name__)
            self._unavailable_reason = f"Ollama 서버 연결 요청에 실패했습니다({self.base_url})."
            return False
        if response.is_error:
            excerpt = _response_excerpt(response)
            logger.error("Ollama tags HTTP error status=%s body=%r", response.status_code, excerpt)
            raise GenerationHTTPError(f"Ollama 모델 목록 API가 HTTP {response.status_code}을 반환했습니다: {excerpt or '응답 본문 없음'}")
        try:
            names = {item.get("name", "") for item in response.json().get("models", [])}
        except (ValueError, AttributeError) as exc:
            logger.error("Ollama tags response parse error body=%r", _response_excerpt(response))
            raise GenerationResponseError("Ollama 모델 목록 응답 형식이 올바르지 않습니다.") from exc
        if self.model not in names:
            self._unavailable_reason = f"Ollama에 `{self.model}` 모델이 없습니다. {GENERATION_HELP}"
            return False
        self._unavailable_reason = None
        return True

    @property
    def unavailable_reason(self) -> str | None: return self._unavailable_reason

    @property
    def generation_trace(self) -> dict[str, Any]: return dict(self._trace)

    @serial_local_inference
    @observed_generation
    def generate(self, prompt: str) -> GeneratedAnalysis:
        payload = {"model": self.model, "system": KOREAN_ANALYSIS_SYSTEM_PROMPT, "prompt": prompt, "stream": False,
            "format": OLLAMA_ANALYSIS_SCHEMA, "options": {"temperature": self.temperature}}
        if os.getenv("STOCK_BRIEF_LOW_MEMORY") == "1":
            payload["keep_alive"] = "60s"
            payload["options"]["num_ctx"] = 4096
        try:
            response = self.client.post("/api/generate", json=payload)
        except httpx.TimeoutException as exc:
            logger.warning("Ollama generation timed out model=%s timeout_seconds=%s", self.model, self.timeout_seconds)
            raise GenerationConnectionError(f"Ollama 생성 요청이 {self.timeout_seconds:g}초 안에 완료되지 않았습니다.") from exc
        except httpx.ConnectError as exc:
            logger.warning("Ollama generation connection failed base_url=%s model=%s", self.base_url, self.model)
            raise GenerationConnectionError(f"Ollama 서버 연결에 실패했습니다({self.base_url}).") from exc
        except httpx.RequestError as exc:
            logger.warning("Ollama generation request failed base_url=%s model=%s error=%s", self.base_url, self.model, type(exc).__name__)
            raise GenerationConnectionError(f"Ollama 생성 요청을 전송하지 못했습니다({self.base_url}).") from exc
        if response.is_error:
            excerpt = _response_excerpt(response)
            logger.error("Ollama generation HTTP error status=%s model=%s body=%r", response.status_code, self.model, excerpt)
            if response.status_code == 404:
                raise GenerationConfigurationError(f"Ollama에 `{self.model}` 모델이 없습니다. {GENERATION_HELP}")
            raise GenerationHTTPError(f"Ollama 생성 API가 HTTP {response.status_code}을 반환했습니다: {excerpt or '응답 본문 없음'}")
        try:
            envelope = response.json()
        except ValueError as exc:
            logger.error("Ollama generation envelope JSON error status=%s body=%r", response.status_code, _response_excerpt(response))
            raise GenerationResponseError("Ollama 생성 응답 본문이 올바른 JSON 형식이 아닙니다.") from exc
        raw = envelope.get("response") if isinstance(envelope, dict) else None
        self._trace = {key: envelope[key] for key in ('model', 'prompt_eval_count', 'eval_count',
            'load_duration', 'prompt_eval_duration', 'eval_duration', 'total_duration')
            if isinstance(envelope, dict) and key in envelope}
        self._trace['keep_alive'] = payload.get('keep_alive', 'server_default')
        self._trace['num_ctx'] = payload['options'].get('num_ctx', 'server_default')
        self._trace['num_batch'] = payload['options'].get('num_batch', 'server_default')
        self._trace['wire_prompt_chars'] = len(prompt)
        duration = self._trace.get('eval_duration', 0)
        if duration:
            self._trace['tokens_per_second'] = self._trace.get('eval_count', 0) / (duration / 1e9)
        if not isinstance(raw, str):
            logger.error("Ollama generation response field missing status=%s body=%r", response.status_code, _response_excerpt(response))
            raise GenerationResponseError("Ollama 생성 응답에 문자열 `response` 필드가 없습니다.")
        cleaned = _strip_json_fence(raw)
        try:
            decoded = _normalize_evidence_ids(json.loads(cleaned))
        except json.JSONDecodeError as exc:
            logger.error("Ollama model JSON parse error model=%s line=%s column=%s", self.model, exc.lineno, exc.colno)
            raise GenerationJSONError(f"Ollama 모델 응답의 JSON 파싱에 실패했습니다(line {exc.lineno}, column {exc.colno}).") from exc
        try:
            return GeneratedAnalysis.model_validate(decoded)
        except ValidationError as exc:
            logger.error("Ollama model schema validation error model=%s errors=%s", self.model, exc.error_count())
            raise GenerationResponseError(f"Ollama 모델 응답이 분석 JSON Schema와 일치하지 않습니다({exc.error_count()}개 검증 오류).") from exc


def _exception_status(exc: Exception) -> int | None:
    for name in ("code", "status_code"):
        value = getattr(exc, name, None)
        if isinstance(value, int):
            return value
    return None


class GeminiGenerationProvider:
    provider_name = "gemini"

    def __init__(self, api_key: str | None = None, model: str | None = None,
        timeout_seconds: float | None = None, client: Any | None = None,
        max_attempts: int | None = None, retry_base_delay_seconds: float | None = None,
        sleep_fn: Any = time.sleep, monotonic_fn: Any = time.monotonic) -> None:
        self.api_key = api_key if api_key is not None else os.getenv("GEMINI_API_KEY", "")
        self._model = model or os.getenv("GEMINI_MODEL", "gemini-3.7-flash")
        self.timeout_seconds = timeout_seconds if timeout_seconds is not None else float(os.getenv("GEMINI_TIMEOUT_SECONDS", "30"))
        self.temperature = float(os.getenv("GENERATION_TEMPERATURE", "0"))
        configured_attempts = max_attempts if max_attempts is not None else int(os.getenv("GEMINI_MAX_ATTEMPTS", "2"))
        configured_delay = (retry_base_delay_seconds if retry_base_delay_seconds is not None
            else float(os.getenv("GEMINI_RETRY_BASE_DELAY_SECONDS", "1")))
        if configured_attempts < 1:
            raise GenerationConfigurationError("GEMINI_MAX_ATTEMPTS는 1 이상이어야 합니다.")
        if configured_delay < 0:
            raise GenerationConfigurationError("GEMINI_RETRY_BASE_DELAY_SECONDS는 0 이상이어야 합니다.")
        self.max_attempts = configured_attempts
        self.retry_base_delay_seconds = configured_delay
        self._sleep = sleep_fn
        self._monotonic = monotonic_fn
        self._trace: dict[str, Any] = {}
        self.client = client
        if self.client is None and self.api_key:
            try:
                from google import genai
                from google.genai import types
            except ImportError as exc:
                raise GenerationConfigurationError('Gemini SDK가 없습니다. backend/requirements.txt의 고정 dependency를 설치하세요.') from exc
            self.client = genai.Client(api_key=self.api_key,
                http_options=types.HttpOptions(timeout=int(self.timeout_seconds * 1000),
                    # GenerateContent counts the original request as attempt 1.
                    # The application loop alone owns transient retries.
                    retry_options=types.HttpRetryOptions(attempts=1)))

    @property
    def model(self) -> str: return self._model

    @property
    def available(self) -> bool: return bool(self.api_key)

    @property
    def unavailable_reason(self) -> str | None:
        return None if self.api_key else "GEMINI_API_KEY가 설정되지 않았습니다. 프로젝트 루트 `.env`에 키를 설정하세요."

    @property
    def generation_trace(self) -> dict[str, Any]:
        return dict(self._trace)

    def _raise_request_error(self, exc: Exception) -> None:
        status = _exception_status(exc)
        if isinstance(exc, httpx.TimeoutException) or "timeout" in type(exc).__name__.casefold():
            raise GenerationConnectionError(f"Gemini 생성 요청이 {self.timeout_seconds:g}초 안에 완료되지 않았습니다.") from exc
        if isinstance(exc, (httpx.ConnectError, httpx.NetworkError, httpx.RequestError)):
            raise GenerationConnectionError("Gemini API 네트워크 연결에 실패했습니다.") from exc
        if status == 429:
            raise GenerationRateLimitError("Gemini API 요청 한도를 초과했습니다(HTTP 429).") from exc
        if status in (500, 502, 503, 504):
            raise GenerationServerError(f"Gemini API가 일시적인 서버 오류를 반환했습니다(HTTP {status}).") from exc
        if status in (401, 403):
            raise GenerationConfigurationError(f"Gemini API 인증에 실패했습니다(HTTP {status}). GEMINI_API_KEY를 확인하세요.") from exc
        if status == 404:
            raise GenerationConfigurationError(f"Gemini 모델 `{self.model}`을 찾을 수 없습니다. GEMINI_MODEL을 확인하세요.") from exc
        if status is None:
            raise GenerationOutputError("Gemini 요청 입력 또는 SDK 설정이 올바르지 않습니다.") from exc
        raise GenerationOutputError(f"Gemini API 요청이 거부되었습니다(HTTP {status}). 요청과 모델 설정을 확인하세요.") from exc

    @observed_generation
    def generate(self, prompt: str) -> GeneratedAnalysis:
        if not self.available:
            raise GenerationConfigurationError(self.unavailable_reason or "Gemini 설정이 올바르지 않습니다.")
        started = self._monotonic()
        self._trace = {"provider": self.provider_name, "model": self.model, "attempts": 0,
            "http_statuses": [], "fallback_used": False, "latency_ms": 0, "calls": []}
        response = None
        for attempt in range(1, self.max_attempts + 1):
            attempt_started = self._monotonic()
            self._trace["attempts"] = attempt
            try:
                response = self.client.models.generate_content(
                    model=self.model,
                    contents=prompt,
                    config={"temperature": self.temperature,
                        "system_instruction": KOREAN_ANALYSIS_SYSTEM_PROMPT,
                        "response_mime_type": "application/json", "response_json_schema": OLLAMA_ANALYSIS_SCHEMA,
                        "http_options": {"timeout": int(self.timeout_seconds * 1000),
                            "retry_options": {"attempts": 1}}},
                )
                self._trace['calls'].append({"attempt": attempt, "status": "success",
                    "latency_ms": round((self._monotonic() - attempt_started) * 1000, 2)})
                logger.info("generation_attempt provider=gemini model=%s attempt=%s status=success latency_ms=%s",
                    self.model, attempt, round((self._monotonic() - attempt_started) * 1000, 2))
                break
            except Exception as exc:
                status_code = _exception_status(exc)
                try:
                    self._raise_request_error(exc)
                except Exception as classified:
                    if status_code is not None:
                        setattr(classified, "status_code", status_code)
                        self._trace["http_statuses"].append(status_code)
                    else:
                        self._trace["http_statuses"].append(type(exc).__name__)
                    retry = isinstance(classified, GenerationTransientError) and attempt < self.max_attempts
                    self._trace['calls'].append({"attempt": attempt, "status": type(classified).__name__,
                        "http_status": status_code, "retry": retry,
                        "timeout": isinstance(classified, GenerationConnectionError) and
                            (isinstance(exc, httpx.TimeoutException) or "timeout" in type(exc).__name__.casefold()),
                        "latency_ms": round((self._monotonic() - attempt_started) * 1000, 2)})
                    self._trace["latency_ms"] = round((self._monotonic() - started) * 1000, 2)
                    logger.warning(
                        "generation_attempt provider=gemini model=%s attempt=%s http_status=%s error_type=%s retry=%s latency_ms=%s",
                        self.model, attempt, status_code, type(classified).__name__, retry,
                        round((self._monotonic() - attempt_started) * 1000, 2))
                    if not retry:
                        raise classified
                    self._sleep(self.retry_base_delay_seconds * (2 ** (attempt - 1)))
        self._trace["latency_ms"] = round((self._monotonic() - started) * 1000, 2)
        assert response is not None
        usage = getattr(response, 'usage_metadata', None)
        self._trace['usage'] = {key: getattr(usage, key, None) for key in
            ('prompt_token_count', 'candidates_token_count', 'thoughts_token_count')}
        status = str(getattr(response, "status", "")).casefold()
        feedback = getattr(response, 'prompt_feedback', None)
        blocked = getattr(feedback, 'block_reason', None)
        unsafe_finish = any(str(getattr(item, 'finish_reason', '')).split('.')[-1] in
            ('SAFETY', 'BLOCKLIST', 'PROHIBITED_CONTENT', 'SPII', 'RECITATION')
            for item in (getattr(response, 'candidates', None) or []))
        if status in ("blocked", "failed", "cancelled") or blocked or unsafe_finish:
            logger.warning("Gemini generation safety blocked provider=gemini model=%s", self.model)
            raise GenerationSafetyError("Gemini 안전 필터가 분석 생성을 차단했습니다.")
        try:
            raw = response.text
        except Exception as exc:
            raise GenerationResponseError("Gemini 응답에서 텍스트를 읽을 수 없습니다.") from exc
        if not isinstance(raw, str) or not raw.strip():
            raise GenerationResponseError("Gemini 생성 응답에 분석 JSON 텍스트가 없습니다.")
        cleaned = _strip_json_fence(raw)
        try:
            decoded = _normalize_evidence_ids(json.loads(cleaned))
        except json.JSONDecodeError as exc:
            logger.warning("Gemini model JSON parse error provider=gemini model=%s line=%s column=%s",
                self.model, exc.lineno, exc.colno)
            raise GenerationJSONError(f"Gemini 모델 응답의 JSON 파싱에 실패했습니다(line {exc.lineno}, column {exc.colno}).") from exc
        try:
            return GeneratedAnalysis.model_validate(decoded)
        except ValidationError as exc:
            logger.warning("Gemini model schema validation error provider=gemini model=%s errors=%s",
                self.model, exc.error_count())
            raise GenerationResponseError(f"Gemini 모델 응답이 분석 JSON Schema와 일치하지 않습니다({exc.error_count()}개 검증 오류).") from exc


class FallbackGenerationProvider:
    def __init__(self, primary: GenerationProvider, fallback: GenerationProvider | None = None) -> None:
        self.primary = primary
        self.fallback = fallback
        self._active = primary
        self._trace: dict[str, Any] = {"primary_provider": primary.provider_name,
            "primary_model": primary.model, "final_provider": primary.provider_name,
            "final_model": primary.model, "primary_attempts": 0, "http_statuses": [],
            "fallback_used": False, "latency_ms": 0}

    @property
    def provider_name(self) -> str: return self._active.provider_name
    @property
    def model(self) -> str: return self._active.model
    @property
    def available(self) -> bool: return self.primary.available
    @property
    def unavailable_reason(self) -> str | None: return self.primary.unavailable_reason

    @property
    def generation_trace(self) -> dict[str, Any]: return dict(self._trace)

    def generate(self, prompt: str) -> GeneratedAnalysis:
        self._active = self.primary
        started = time.monotonic()
        self._trace = {"primary_provider": self.primary.provider_name, "primary_model": self.primary.model,
            "final_provider": self.primary.provider_name, "final_model": self.primary.model,
            "primary_attempts": 0, "http_statuses": [], "fallback_used": False, "latency_ms": 0}
        try:
            result = self.primary.generate(prompt)
            primary_trace = getattr(self.primary, "generation_trace", {})
            self._trace.update({"primary_attempts": primary_trace.get("attempts", 1),
                "http_statuses": primary_trace.get("http_statuses", []),
                'final_runtime': primary_trace,
                "latency_ms": round((time.monotonic() - started) * 1000, 2)})
            return result
        except GenerationTransientError as exc:
            primary_trace = getattr(self.primary, "generation_trace", {})
            self._trace.update({"primary_attempts": primary_trace.get("attempts", 1),
                "primary_runtime": primary_trace,
                "http_statuses": primary_trace.get("http_statuses", []),
                "latency_ms": round((time.monotonic() - started) * 1000, 2)})
            if self.fallback is None:
                raise
            logger.warning("generation_fallback primary=%s fallback=%s error_type=%s http_status=%s attempts=%s",
                self.primary.provider_name, self.fallback.provider_name, type(exc).__name__,
                getattr(exc, "status_code", None), self._trace["primary_attempts"])
            if not self.fallback.available:
                raise GenerationConfigurationError(self.fallback.unavailable_reason or "Fallback provider를 사용할 수 없습니다.") from exc
            self._active = self.fallback
            self._trace.update({"final_provider": self.fallback.provider_name,
                "final_model": self.fallback.model, "fallback_used": True})
            generation_event('fallback', self.fallback.provider_name)
            try:
                return self.fallback.generate(prompt)
            finally:
                self._trace['final_runtime'] = dict(getattr(self.fallback, 'generation_trace', {}))
                self._trace["latency_ms"] = round((time.monotonic() - started) * 1000, 2)


def check_generation_policy(request: AnalysisRequest, provider: GenerationProvider | None = None):
    external = request.execution_mode != 'LOCAL_ONLY'
    if external and (not request.external_consent or os.getenv('ANALYSIS_EXTERNAL_ENABLED') != '1'):
        raise GenerationPolicyError('외부 분석은 서버 정책 활성화와 이번 요청의 전송 동의가 필요합니다.')
    if request.execution_mode == 'FALLBACK_ALLOWED' and os.getenv('ANALYSIS_OLLAMA_FALLBACK_ENABLED') != '1':
        raise GenerationPolicyError('서버 정책에서 로컬 fallback을 허용하지 않았습니다.')
    if provider is not None:
        primary = getattr(provider, 'primary', provider)
        fallback = getattr(provider, 'fallback', None)
        expected = 'gemini' if external else 'ollama'
        if primary.provider_name != expected:
            raise GenerationPolicyError('요청 실행 모드와 provider가 일치하지 않습니다.')
        if fallback is not None and (request.execution_mode != 'FALLBACK_ALLOWED' or fallback.provider_name != 'ollama'):
            raise GenerationPolicyError('이번 요청에서 허용하지 않은 fallback provider입니다.')


def get_generation_provider(request: AnalysisRequest) -> GenerationProvider:
    # Environment/key presence never supplies consent or changes the default mode.
    check_generation_policy(request)
    if request.execution_mode == 'LOCAL_ONLY':
        return FallbackGenerationProvider(OllamaGenerationProvider())
    primary = GeminiGenerationProvider()
    fallback = OllamaGenerationProvider() if request.execution_mode == 'FALLBACK_ALLOWED' else None
    return FallbackGenerationProvider(primary, fallback)
