import os
from collections.abc import Sequence
from typing import Protocol

import httpx

from .models import EMBEDDING_DIMENSIONS

OLLAMA_HELP = "맥에서 Ollama를 실행하고 `ollama pull bge-m3` 후 `ollama list`로 모델을 확인하세요."


class EmbeddingConfigurationError(RuntimeError):
    pass


class EmbeddingProvider(Protocol):
    @property
    def provider_name(self) -> str: ...
    @property
    def model(self) -> str: ...
    @property
    def dimensions(self) -> int: ...
    @property
    def available(self) -> bool: ...
    @property
    def unavailable_reason(self) -> str | None: ...
    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


class OllamaEmbeddingProvider:
    provider_name = "ollama"

    def __init__(self, base_url: str | None = None, model: str | None = None, dimensions: int | None = None, client: httpx.Client | None = None) -> None:
        self.base_url = (base_url or os.getenv("OLLAMA_BASE_URL", "http://host.docker.internal:11434")).rstrip("/")
        self._model = model or os.getenv("EMBEDDING_MODEL", "bge-m3")
        self._dimensions = dimensions or int(os.getenv("EMBEDDING_DIMENSIONS", "1024"))
        self.client = client or httpx.Client(base_url=self.base_url, timeout=httpx.Timeout(60.0, connect=2.0))
        self._unavailable_reason: str | None = None

    @property
    def model(self) -> str:
        return self._model

    @property
    def dimensions(self) -> int:
        return self._dimensions

    def _probe(self) -> bool:
        if self.dimensions != EMBEDDING_DIMENSIONS:
            self._unavailable_reason = f"EMBEDDING_DIMENSIONS는 DB vector 차원과 같은 {EMBEDDING_DIMENSIONS}이어야 합니다."
            return False
        try:
            response = self.client.get("/api/tags")
            response.raise_for_status()
            names = {item.get("name", "") for item in response.json().get("models", [])}
        except (httpx.HTTPError, ValueError, AttributeError):
            self._unavailable_reason = f"Ollama 서버에 연결할 수 없습니다({self.base_url}). {OLLAMA_HELP}"
            return False
        if not any(name == self.model or name.split(":", 1)[0] == self.model for name in names):
            self._unavailable_reason = f"Ollama에 `{self.model}` 모델이 없습니다. {OLLAMA_HELP}"
            return False
        self._unavailable_reason = None
        return True

    @property
    def available(self) -> bool:
        return self._probe()

    @property
    def unavailable_reason(self) -> str | None:
        return self._unavailable_reason

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        try:
            response = self.client.post("/api/embed", json={"model": self.model, "input": list(texts)})
            if response.status_code == 404:
                raise EmbeddingConfigurationError(f"Ollama에 `{self.model}` 모델이 없습니다. {OLLAMA_HELP}")
            response.raise_for_status()
            vectors = response.json().get("embeddings")
        except EmbeddingConfigurationError:
            raise
        except (httpx.HTTPError, ValueError, AttributeError) as exc:
            raise EmbeddingConfigurationError(f"Ollama 임베딩 요청에 실패했습니다({self.base_url}). {OLLAMA_HELP}") from exc
        if not isinstance(vectors, list) or len(vectors) != len(texts):
            raise EmbeddingConfigurationError("Ollama 임베딩 응답 개수가 요청 청크 수와 다릅니다.")
        if any(not isinstance(vector, list) or len(vector) != self.dimensions for vector in vectors):
            raise EmbeddingConfigurationError(f"Ollama `{self.model}` 임베딩은 {self.dimensions}차원이어야 합니다. 모델과 EMBEDDING_DIMENSIONS 설정을 확인하세요.")
        return vectors


def get_embedding_provider() -> EmbeddingProvider:
    provider = os.getenv("EMBEDDING_PROVIDER", "ollama").casefold()
    if provider != "ollama":
        raise EmbeddingConfigurationError("EMBEDDING_PROVIDER는 현재 `ollama`만 지원합니다.")
    return OllamaEmbeddingProvider()
