"""Local-only, guarded E2E analysis with host samples; never reingests documents."""
import argparse
import json
import os
import subprocess
import threading
import time

from restore_e2e_persistent import ROOT, engine, guard

OUT = ROOT / '.e2e-persistent/service-quality'


def sample():
    result = {'at': time.time()}
    commands = {
        'swap': ['sysctl', 'vm.swapusage'], 'vm': ['vm_stat'],
        'pressure': ['memory_pressure', '-Q'], 'thermal': ['pmset', '-g', 'therm'],
        'processes': ['ps', '-axo', 'pid,pcpu,rss,comm'],
        'ollama': ['curl', '-sf', 'http://127.0.0.1:11434/api/ps'],
    }
    for key, command in commands.items():
        try:
            output = subprocess.run(command, capture_output=True, text=True, timeout=5)
            result[key] = output.stdout if output.returncode == 0 else 'NOT_VERIFIED'
        except subprocess.TimeoutExpired:
            result[key] = 'NOT_VERIFIED'
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--label', required=True)
    parser.add_argument('--low-memory', action='store_true')
    parser.add_argument('--question', default='이 보고서를 읽고 주식 초보자 관점에서 호재와 악재를 각각 최대 3개까지 요약해줘.')
    args = parser.parse_args()
    if args.low_memory:
        os.environ['STOCK_BRIEF_LOW_MEMORY'] = '1'
    # Only the fixed, guarded E2E database and local Ollama.
    target = engine()
    with target.connect() as conn:
        guard(conn)
    os.environ['DATABASE_URL'] = target.url.render_as_string(hide_password=False)
    from sqlalchemy.orm import Session
    from service_e2e import snapshot, DOC
    from app.models import Document, AnalysisRun
    from app.analysis_service import analyze_document
    from app.embeddings import OllamaEmbeddingProvider
    from app.generation import FallbackGenerationProvider, OllamaGenerationProvider
    from app.schemas import AnalysisRequest

    path = OUT / f'optimization-{args.label}.json'
    assert not path.exists(), 'Refusing artifact overwrite'
    samples = []
    stop = threading.Event()
    def monitor():
        while not stop.is_set():
            samples.append(sample())
            (OUT / f'optimization-{args.label}-memory.json').write_text(json.dumps(samples))
            stop.wait(3)
    worker = threading.Thread(target=monitor, daemon=True)
    worker.start()
    with Session(target) as db:
        before = snapshot(db)
        assert before['vectors'] == 583 and before['missing'] == 0
        request = AnalysisRequest(document_id=DOC, question=args.question, top_k=10)
        provider = FallbackGenerationProvider(OllamaGenerationProvider(base_url='http://127.0.0.1:11434'))
        started = time.perf_counter()
        payload = {'low_memory': args.low_memory, 'before': before}
        try:
            result = analyze_document(db, db.get(Document, DOC), request,
                OllamaEmbeddingProvider(base_url='http://127.0.0.1:11434'), provider)
            payload['result'] = result.model_dump(mode='json')
            payload['trace'] = db.get(AnalysisRun, result.run_id).result['_evaluation_trace']
        except Exception as exc:
            db.rollback()
            payload['error'] = type(exc).__name__
            raise
        finally:
            payload['seconds'] = time.perf_counter() - started
            payload['after'] = snapshot(db)
            stop.set()
            worker.join(timeout=35)
            samples.append(sample())
            payload['samples'] = samples
            payload['source_vector_unchanged'] = before == payload['after']
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
            print(json.dumps({k: payload.get(k) for k in ('seconds', 'error', 'source_vector_unchanged')}))
    assert payload['source_vector_unchanged']


if __name__ == '__main__':
    main()
