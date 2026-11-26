"""Offline by default; fixture-only live path requires explicit scoped approval."""
import argparse
import hashlib
import json
from pathlib import Path
import os
import sys
from types import SimpleNamespace
import time
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
import httpx
from google import genai
from google.genai import types
from app.evidence_facts import supported_claim
from app.generation import GeminiGenerationProvider, check_generation_policy
from app.schemas import AnalysisRequest, GeneratedAnalysis

# Disposable public fixture citation label, never an internal DB identifier.
MODEL = 'gemini-3.8-flash'
MAX_OUTPUT_TOKENS = 2048
THINKING_LEVEL = 'low'
LEDGER_DIR = ROOT / '.e2e-persistent/provider-approval-consumption'

SOURCE_ID = '9cc9be12-219e-57a8-8965-8cba774a2139'
FIXTURE = {
    'question': '합성 테스트 장치의 처리시간 변화를 제공된 근거만으로 설명하세요.',
    'source': {'title': '독립 synthetic 처리시간 fixture v1',
               'origin': '이 테스트에서 독립 작성한 가상 장치 데이터; 실제 기업·실적·관측이 아님',
               'terms': '외부 provider 테스트용으로 작성; 제3자 문서에서 발췌하지 않음'},
    'evidence': [{'citation_id': SOURCE_ID,
                  'quote': '합성 테스트 장치의 처리시간은 기준 대비 20% 감소했습니다.',
                  'metric': '처리시간', 'direction': '감소', 'value': '20',
                  'unit': '%', 'comparison_basis': '기준 대비', 'scope': '합성 테스트 장치'}],
}
MOCK_RESULT = {
    'summary': FIXTURE['evidence'][0]['quote'],
    'positives': [{'title': '처리시간 감소', 'reason': FIXTURE['evidence'][0]['quote'],
                   'evidence_chunk_ids': [SOURCE_ID]}],
    'negatives': [], 'insufficient_evidence_note': None,
}


def prompt():
    return ('독립 synthetic provider 테스트입니다. 실제 금융 사실이나 서비스 성능 평가가 아닙니다. '
            '아래 데이터 밖의 수치·원인·기간·범위를 만들지 마세요. '
            'evidence_chunk_ids에는 citation_id만 사용하세요. 원문 인용은 로컬에서 복원합니다. '
            '각 관점 최대 3개, 중복 금지. 근거 부족 시 확인할 수 없습니다라고 답하세요.\n'
            + json.dumps(FIXTURE, ensure_ascii=False, separators=(',', ':')))


def validate_response(result: GeneratedAnalysis):
    """Fixture-scoped fail-closed gate; production RAG validators are unchanged."""
    quotes = {row['citation_id']: row['quote'] for row in FIXTURE['evidence']}
    # Restrict this tiny smoke test's summary to the literal source or HOLD.
    if result.summary not in {*quotes.values(), '확인할 수 없습니다'}:
        raise ValueError('unsupported summary')
    seen = set()
    citations = []
    for perspective, items in [('positive', result.positives), ('negative', result.negatives)]:
        for item in items:
            ids = [str(value) for value in item.evidence_chunk_ids]
            if not ids or any(value not in quotes for value in ids):
                raise ValueError('unknown or empty citation')
            if perspective != 'positive' or seen.intersection(ids) or len(ids) != 1:
                raise ValueError('wrong perspective or duplicate evidence')
            row = next(row for row in FIXTURE['evidence'] if row['citation_id'] == ids[0])
            if not supported_claim(item.title, item.reason, [{'quote': row['quote'], 'facts': [row]}]):
                raise ValueError('unsupported claim')
            seen.update(ids)
            citations.append({'citation_id': ids[0], 'quote': quotes[ids[0]], 'source': FIXTURE['source']['title']})
    return {'status': 'VERIFIED' if citations else 'HOLD', 'citations': citations}


def fixture_provider(sdk, api_key):
    # Fixture-only config overlay. Keep production defaults and shared adapter intact.
    class Models:
        def generate_content(self, *, model, contents, config):
            return sdk.models.generate_content(model=model, contents=contents, config={
                **config, 'temperature': 0, 'max_output_tokens': MAX_OUTPUT_TOKENS,
                'thinking_config': {'thinking_level': THINKING_LEVEL}})
    return GeminiGenerationProvider(api_key=api_key, model=MODEL,
        client=SimpleNamespace(models=Models()), max_attempts=1, timeout_seconds=30)


def consume_approval(approval_id, packet):
    """Persist fail-closed consumption before send, including uncertain outcomes."""
    identity = str(UUID(approval_id))
    LEDGER_DIR.mkdir(parents=True, exist_ok=True)
    path = LEDGER_DIR / (identity + '.json')
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, 'w') as output:
            json.dump({'approval_id': identity, 'model': MODEL, 'payload_sha256': packet['sha256'],
                       'state': 'CONSUMED_BEFORE_SEND_OUTCOME_UNKNOWN'}, output)
            output.flush()
            os.fsync(output.fileno())
        directory_fd = os.open(LEDGER_DIR, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except BaseException:
        # Never remove an incomplete marker; ambiguity must not authorize reuse.
        raise
    return path


def capture_payload():
    captured = []
    def handler(request):
        captured.append({'method': request.method, 'url': str(request.url),
                         'body': request.content.decode('utf-8')})
        return httpx.Response(200, json={'candidates': [{'content': {'parts': [
            {'text': json.dumps(MOCK_RESULT, ensure_ascii=False)}]}, 'finishReason': 'STOP'}]})
    transport = httpx.Client(transport=httpx.MockTransport(handler), trust_env=False)
    with genai.Client(api_key='synthetic-test-key', http_options=types.HttpOptions(
            httpx_client=transport, retry_options=types.HttpRetryOptions(attempts=1))) as sdk:
        provider = fixture_provider(sdk, 'synthetic-test-key')
        result = provider.generate(prompt())
    assert len(captured) == 1
    packet = captured[0]
    packet['sha256'] = hashlib.sha256(packet['body'].encode()).hexdigest()
    packet['validation'] = validate_response(result)
    return packet


def execute_approved(scope, packet):
    # This file is an operator consent record, not proof of human identity.
    # Do not create/approve it without the user's explicit authorization.
    for key, expected in {'provider': 'gemini', 'model': MODEL,
            'fixture': 'independent-synthetic-v1', 'payload_sha256': packet['sha256'],
            'maximum_external_attempts': 1, 'fallback': False, 'max_output_tokens': MAX_OUTPUT_TOKENS,
            'thinking_level': THINKING_LEVEL}.items():
        if scope.get(key) != expected:
            raise ValueError('approval scope mismatch: ' + key)
    if scope.get('approved') is not True or scope.get('external_consent') is not True:
        raise ValueError('explicit approval missing')
    approval_id = str(UUID(scope.get('approval_id', '')))
    expected_url = f'https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent'
    if packet['url'] != expected_url or packet['method'] != 'POST':
        raise ValueError('approval endpoint mismatch')
    request = AnalysisRequest(document_id=UUID(SOURCE_ID), execution_mode='EXTERNAL_WITH_CONSENT',
                              external_consent=True)
    check_generation_policy(request)
    key = os.environ.get('GEMINI_API_KEY', '')
    if not key:
        raise ValueError('GEMINI_API_KEY missing; .env is not loaded automatically')

    class ScopedTransport(httpx.BaseTransport):
        def __init__(self):
            self.inner = httpx.HTTPTransport(retries=0)
            self.attempts = 0

        def handle_request(self, outbound):
            if (outbound.method != packet['method'] or str(outbound.url) != packet['url']
                    or hashlib.sha256(outbound.content).hexdigest() != packet['sha256']
                    or self.attempts != 0):
                raise ValueError('unapproved outbound request blocked before send')
            consume_approval(approval_id, packet)
            self.attempts += 1
            return self.inner.handle_request(outbound)

        def close(self):
            self.inner.close()

    started = time.monotonic()
    transport = httpx.Client(transport=ScopedTransport(), trust_env=False)
    with genai.Client(api_key=key, http_options=types.HttpOptions(httpx_client=transport,
            retry_options=types.HttpRetryOptions(attempts=1))) as sdk:
        provider = fixture_provider(sdk, key)
        result = provider.generate(prompt())
        validation = validate_response(result)
        return {'result': result.model_dump(mode='json'), 'validation': validation,
                'seconds': time.monotonic() - started, 'trace': provider.generation_trace}


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--output', type=Path, required=True)
    cli.add_argument('--execute', action='store_true', help='Requires prior user approval, policy and matching payload')
    cli.add_argument('--approval', type=Path)
    args = cli.parse_args()
    packet = capture_payload()
    if args.execute:
        if args.approval is None:
            cli.error('--execute requires --approval')
        # Check local output collision before any potentially billable operation.
        args.output.mkdir(parents=True, exist_ok=False)
        result = execute_approved(json.loads(args.approval.read_text()), packet)
        (args.output / 'approved-result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
        print('Approved fixture call validated')
        return
    if args.approval is not None:
        cli.error('--approval requires --execute')
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / 'fixture.json').write_text(json.dumps(FIXTURE, ensure_ascii=False, indent=2) + '\n')
    (args.output / 'gemini-request-body.json').write_bytes(packet['body'].encode())
    (args.output / 'approval-scope.json').write_text(json.dumps({
        'provider': 'gemini', 'model': MODEL, 'method': packet['method'], 'url': packet['url'],
        'payload_sha256': packet['sha256'], 'fixture': 'independent-synthetic-v1',
        'timeout_seconds': 30, 'maximum_external_attempts': 1, 'fallback': False,
        'max_output_tokens': MAX_OUTPUT_TOKENS, 'thinking_level': THINKING_LEVEL,
        'consent': False, 'server_policy_enabled': False, 'actual_calls': 0,
        'mock_validation': packet['validation'],
        'scope': 'provider/schema/citation smoke only; not financial RAG E2E or performance'
    }, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'payload_sha256': packet['sha256'], 'actual_calls': 0}))


if __name__ == '__main__':
    main()
