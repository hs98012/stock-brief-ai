"""Guarded service checks against the persistent E2E database only."""
import argparse
import cProfile
import hashlib
import json
import math
from pathlib import Path
import pstats
import resource
import time
from uuid import UUID

from restore_e2e_persistent import BASE, canonical, engine, guard
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.models import Document
from app.embeddings import OllamaEmbeddingProvider

OUT = BASE / 'service-quality'
DOC = UUID('5f4001ad-403f-452e-926a-b0ddeb4b60bb')


def snapshot(db):
    tables = {}
    for table in ('pages', 'page_extractions', 'chunks'):
        key = 'page_id' if table == 'page_extractions' else 'id'
        rows = db.execute(text(f'SELECT row_to_json(t) FROM {table} t ORDER BY {key}')).scalars().all()
        if table == 'chunks':
            for row in rows:
                for key in ('embedding', 'embedding_provider', 'embedding_model', 'embedding_dimensions', 'embedding_error'):
                    row.pop(key, None)
        tables[table] = dict(count=len(rows), sha256=hashlib.sha256(canonical(rows)).hexdigest())
    vectors = db.execute(text('SELECT id, embedding::text FROM chunks ORDER BY id')).all()
    valid = 0
    for _, vector in vectors:
        if vector is None:
            continue
        values = json.loads(vector)
        assert len(values) == 1024 and all(math.isfinite(x) for x in values) and any(values)
        valid += 1
    return dict(sources=tables, vectors=valid, missing=len(vectors)-valid,
                vector_sha256=hashlib.sha256(canonical([tuple(r) for r in vectors])).hexdigest())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['snapshot', 'embed', 'search', 'evidence'])
    parser.add_argument('--label', default='current')
    parser.add_argument('--question', default='이 보고서의 호재와 악재를 근거와 함께 요약해줘')
    parser.add_argument('--no-profile', action='store_true')
    args = parser.parse_args()
    OUT.mkdir(exist_ok=True)
    with Session(engine()) as db:
        guard(db)
        provider = OllamaEmbeddingProvider(base_url='http://127.0.0.1:11434', model='bge-m3', dimensions=1024)
        before = snapshot(db)
        start = time.perf_counter()
        cpu_start = time.process_time()
        if args.mode == 'embed':
            from app.embedding_service import embed_document
            assert provider.available, provider.unavailable_reason
            run = embed_document(db, db.get(Document, DOC), provider)
            result = dict(processed=run.processed, skipped=run.skipped, failed=run.failed)
        elif args.mode in ('search', 'evidence'):
            assert before['vectors'] == 583 and before['missing'] == 0
            profile = cProfile.Profile()
            if not args.no_profile:
                profile.enable()
            if args.mode == 'search':
                from app.search import hybrid_search, SearchFilters
                execution = hybrid_search(db, args.question, 15, SearchFilters(document_id=DOC), provider, diagnostics=True)
                result = vars(execution)
            else:
                from app.analysis_retrieval import collect_analysis_evidence
                diagnostics = {}
                rows = collect_analysis_evidence(db, DOC, args.question, 10, provider, diagnostics)
                result = dict(rows=rows, diagnostics=diagnostics)
            if not args.no_profile:
                profile.disable()
                profile.dump_stats(str(OUT / f'{args.mode}-{args.label}.prof'))
                with (OUT / f'{args.mode}-{args.label}-profile.txt').open('w') as output:
                    pstats.Stats(profile, stream=output).strip_dirs().sort_stats('cumulative').print_stats(40)
        else:
            result = before
        elapsed = time.perf_counter() - start
        cpu_seconds = time.process_time() - cpu_start
        db.commit()
        after = snapshot(db)
        assert before['sources'] == after['sources'], 'Source/provenance changed'
        payload = dict(mode=args.mode, seconds=elapsed, cpu_seconds=cpu_seconds,
            peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            before=before, after=after, result=result)
        (OUT / f'{args.mode}-{args.label}.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        print(json.dumps(dict(mode=args.mode, seconds=round(elapsed, 3), vectors=after['vectors'], missing=after['missing']), ensure_ascii=False))


if __name__ == '__main__':
    main()
