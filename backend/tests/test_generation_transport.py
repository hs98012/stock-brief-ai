"""Exercise the installed SDK through an in-memory transport, with no external calls."""
import httpx
import pytest
from google import genai
from google.genai import types

from app.generation import GeminiGenerationProvider, GenerationTransientError, GenerationSafetyError


@pytest.mark.parametrize('status', [429, 500, 502, 503, 504])
def test_sdk_has_no_hidden_retries(status):
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(status, json={'error': {'code': status, 'message': 'synthetic error', 'status': 'UNAVAILABLE'}})
    transport = httpx.Client(transport=httpx.MockTransport(handler))
    sdk = genai.Client(api_key='synthetic-test-key', http_options=types.HttpOptions(httpx_client=transport,
        retry_options=types.HttpRetryOptions(attempts=1)))
    provider = GeminiGenerationProvider(api_key='synthetic-test-key', client=sdk, max_attempts=2, sleep_fn=lambda _: None)
    try:
        with pytest.raises(GenerationTransientError):
            provider.generate('synthetic prompt')
        assert len(requests) == 2
        assert all('generateContent' in str(r.url) for r in requests)
        assert len(provider.generation_trace['calls']) == 2
    finally:
        sdk.close()


def test_real_sdk_schema_usage_and_safety_are_parsed():
    responses = [
        {'candidates': [{'content': {'parts': [{'text': '{"summary":"확인할 수 없습니다",'
            '"positives":[],"negatives":[],"insufficient_evidence_note":null}'}]}, 'finishReason': 'STOP'}],
            'usageMetadata': {'promptTokenCount': 15, 'candidatesTokenCount': 30}},
        {'promptFeedback': {'blockReason': 'SAFETY'}},
    ]
    transport = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=responses.pop(0))))
    sdk = genai.Client(api_key='synthetic-test-key', http_options=types.HttpOptions(httpx_client=transport))
    provider = GeminiGenerationProvider(api_key='synthetic-test-key', client=sdk)
    try:
        assert provider.generate('synthetic prompt').summary == '확인할 수 없습니다'
        assert provider.generation_trace['usage']['prompt_token_count'] == 15
        with pytest.raises(GenerationSafetyError):
            provider.generate('synthetic prompt')
    finally:
        sdk.close()
