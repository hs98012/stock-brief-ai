"""Offline artifact audit and empty, explicitly isolated PostgreSQL restoration.

Never calls ingestion, OCR, retrieval, embedding, or generation services.
"""
import argparse
from collections import Counter
from datetime import date, datetime
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / '.e2e-persistent'
ARCHIVE = BASE / 'preserved'
OLD = Path('/private/tmp/stock-brief-service-e2e-20261012')
RECOVERY = Path('/private/tmp/stock-brief-service-e2e-recovery-20261012')
DB_NAME = 'stock_brief_e2e_restore'
sys.path.insert(0, str(ROOT / 'backend'))


def digest(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), default=str).encode()


def save(name, value):
    BASE.mkdir(exist_ok=True)
    (BASE / name).write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + '\n')


def load(path):
    return json.loads(path.read_text())


def inventory(path):
    result = []
    for file in sorted(path.rglob('*')):
        if not file.is_file():
            continue
        name = str(file.relative_to(path))
        category = ('pdf' if file.suffix.lower() == '.pdf' else
                    'extraction_and_chunk_metadata' if file.name.startswith('page-') and file.suffix == '.json' else
                    'historical_evidence' if file.name.startswith('observations') else
                    'historical_search' if 'search' in file.name else 'other')
        stat = file.stat()
        result.append(dict(path=name, size=stat.st_size, sha256=digest(file.read_bytes()),
                           mode=stat.st_mode, flags=stat.st_flags, category=category))
    return sorted(result, key=lambda x: x['path'])


def archive():
    before = inventory(OLD)
    all_expected = load(RECOVERY / 'prior-artifacts-before.json')
    links = [x for x in all_expected if (OLD / x['path']).is_symlink()]
    save('preserved-symlinks.json', links)
    expected = [x for x in all_expected if not (OLD / x['path']).is_symlink()]
    assert len(before) == len(expected) == 2993
    assert [(x['path'], x['size'], x['sha256']) for x in before] == [
        (x['path'], x['size'], x['sha256']) for x in sorted(expected, key=lambda x: x['path'])]
    save('files-before.json', before)
    if ARCHIVE.exists():
        raise RuntimeError('Archive exists; refusing to overwrite preserved bytes')
    shutil.copytree(OLD, ARCHIVE, copy_function=shutil.copy2, symlinks=True)
    assert inventory(ARCHIVE) == before
    save('archive-integrity.json', {'files': len(before), 'sha256': digest(canonical(before)),
                                   'all_sizes_hashes_modes_flags_match': True})
    shutil.copytree(RECOVERY, BASE / 'prior-recovery', copy_function=shutil.copy2)


def page_objects():
    from app.models import Page, PageExtraction, TextSource
    doc = load(ARCHIVE / 'document-status.json')
    pages = []
    for number in range(1, 10):
        raw = load(ARCHIVE / f'page-{number}-raw.json')
        assert raw['page_number'] == number
        # Dump did not retain Page.id: this is an explicit NEW restoration ID.
        page_id = uuid.uuid5(uuid.UUID(doc['id']), f'persistent-restoration-page:{number}')
        page = Page(id=page_id, document_id=uuid.UUID(doc['id']), page_number=number,
                    native_text=raw['native_text'], ocr_text=raw['ocr_text'], final_text=raw['final_text'],
                    text_source=TextSource(raw['text_source']), ocr_error=raw['ocr_error'], page_image_path=None)
        page.extraction = PageExtraction(page_id=page_id, **raw['extraction'])
        pages.append((page, raw))
    return doc, pages


def audit():
    from app.chunking import structured_spans
    from app.extraction_provenance import validated_stored_facts
    doc, pages = page_objects()
    pdf = ARCHIVE / 'data/raw' / (doc['id'] + '.pdf')
    expected_pdf = load(BASE / 'prior-recovery/recoverability.json')['existing_pdf_copy'][0]['sha256']
    assert digest(pdf.read_bytes()) == expected_pdf
    import fitz
    with fitz.open(pdf) as original:
        assert original.page_count == doc['total_pages'] == len(pages) == 9
        for page, raw in pages:
            box = original[page.page_number - 1].rect
            size = raw['extraction']['provenance']['page_size']
            assert abs(size[0] - box.width) < 0.1 and abs(size[1] - box.height) < 0.1
    chunks = {c['id']: (p, c) for p, raw in pages for c in raw['chunks']}
    assert len(chunks) == sum(len(raw['chunks']) for _, raw in pages) == 583
    results, fact_links, spans, coordinates = [], 0, 0, 0
    for page, raw in pages:
        text, ext = page.final_text, raw['extraction']
        assert digest(text.encode()) == ext['final_text_sha256']
        expected = structured_spans(text, ext['provenance'])
        assert [(c['content'], c['char_start'], c['char_end']) for c in raw['chunks']] == [
            (c.content, c.char_start, c.char_end) for c in expected]
        for c in raw['chunks']:
            uuid.UUID(c['id'])
            assert 0 <= c['char_start'] < c['char_end'] <= len(text)
            assert text[c['char_start']:c['char_end']] == c['content']
        facts = validated_stored_facts(page)
        recorded = load(ARCHIVE / f'page-{page.page_number}-verified.json')['verified_table_facts']
        assert canonical(facts) == canonical(recorded)
        for fact in ext['table_facts']:
            assert fact['page_number'] == page.page_number
            for cid in fact.get('source_chunk_ids', []):
                assert cid in chunks and chunks[cid][0].page_number == page.page_number
                fact_links += 1
        def inspect(value):
            nonlocal spans, coordinates
            if isinstance(value, dict):
                if all(k in value for k in ('char_start', 'char_end', 'quote')):
                    a, b = value['char_start'], value['char_end']
                    assert 0 <= a < b <= len(text) and text[a:b] == value['quote']
                    spans += 1
                if 'bbox' in value and value['bbox'] is not None:
                    box = value['bbox']
                    assert len(box) == 4 and all(isinstance(v, (int, float)) and math.isfinite(v) for v in box)
                    assert box[0] <= box[2] and box[1] <= box[3]
                    coordinates += 1
                for v in value.values():
                    inspect(v)
            elif isinstance(value, list):
                for v in value:
                    inspect(v)
        # Verify authoritative facts and admitted dependencies, not rejected observations.
        inspect(ext['table_facts'])
        inspect(ext['provenance'].get('dependency_groups', []))
        words = ext['provenance'].get('selected_words', [])
        for w in words:
            assert text[w['char_start']:w['char_end']] == w['text']
        groups = ext['provenance'].get('dependency_groups', [])
        results.append(dict(page_number=page.page_number, restored_page_id=str(page.id),
                            raw_sha256=digest((ARCHIVE / f'page-{page.page_number}-raw.json').read_bytes()),
                            final_text_sha256=ext['final_text_sha256'], chunks=len(raw['chunks']),
                            admitted_chunk_count=len(expected), verified_facts=len(facts),
                            selected_words=len(words), native_tables=len(ext['provenance'].get('native_tables', [])),
                            paddle_tables=len(ext['provenance'].get('paddle_tables', [])),
                            dependency_groups=len(groups), coordinate_system=ext['provenance'].get('coordinate_system'),
                            page_size=ext['provenance'].get('page_size'),
                            ownership_present=sum(g.get('ownership_id') is not None for g in groups),
                            context_present=sum(g.get('context_id') is not None for g in groups)))
    events = [json.loads(s) for s in (ARCHIVE / 'observations.jsonl').read_text().splitlines()]
    rows = next(e['data']['rows'] for e in events if e['kind'] == 'analysis_evidence')
    assert len(rows) == 3
    evidence = []
    for row in rows:
        cid = row['source_chunk_id']
        page, chunk = chunks[cid]
        assert row['document_id'] == doc['id'] and row['page_number'] == page.page_number
        assert page.final_text[row['char_start']:row['char_end']] == row['quote']
        assert chunk['char_start'] <= row['char_start'] < row['char_end'] <= chunk['char_end']
        assert all(x in chunks for x in row.get('source_chunk_ids', []))
        evidence.append(dict(historical_evidence_chunk_id=row['chunk_id'], source_chunk_id=cid,
                             page_number=page.page_number, char_start=row['char_start'], char_end=row['char_end']))
    report = dict(pdf_sha256=expected_pdf, pages=results, chunks=583, fact_chunk_links=fact_links,
                  checked_quote_spans=spans, checked_coordinate_boxes=coordinates,
                  historical_evidence=evidence, analysis_runs_restored=0, vectors_restored=0,
                  missing_metadata=['Original Page UUIDs: absent; explicit uuid5 restoration IDs used',
                                    'Page image path: absent in dump; NULL',
                                    'Chunk section_title: absent in dump; NULL, not claimed identical',
                                    'Explicit searchable column: absent in schema; admission ranges checked',
                                    'Legacy ownership/context IDs: NULL preserved, not inferred',
                                    'Embedding vectors and analysis_runs: lost; not reconstructed',
                                    'Historical evidence DB PK/answer_item IDs: absent; artifact-only'])
    save('restoration-audit.json', report)
    save('embedding-targets.json', dict(provider='ollama', model='bge-m3', dimensions=1024,
        status='not_started', chunks=[dict(chunk_id=cid, page_number=p.page_number,
        content_sha256=digest(c['content'].encode()), char_start=c['char_start'], char_end=c['char_end'])
        for cid, (p, c) in sorted(chunks.items())]))
    print('Audit: 9 pages, 583 chunks, 3 historical evidence rows; no external service calls')


def prepare_inputs():
    from types import SimpleNamespace
    from app.fused_index import searchable, retrieval_text
    _, pages = page_objects()
    inputs = []
    for page, raw in pages:
        for chunk in raw['chunks']:
            source = SimpleNamespace(**chunk)
            value = retrieval_text(source, page)
            inputs.append(dict(chunk_id=chunk['id'], document_id=str(page.document_id),
                restored_page_id=str(page.id), page_number=page.page_number,
                char_start=chunk['char_start'], char_end=chunk['char_end'],
                searchable=searchable(source, page), content_sha256=digest(chunk['content'].encode()),
                embedding_input=value, embedding_input_sha256=digest(value.encode()),
                embedding_present=False, provider='ollama', model='bge-m3', dimensions=1024))
    path = BASE / 'embedding-inputs.jsonl'
    path.write_text(''.join(json.dumps(x, ensure_ascii=False) + '\n' for x in inputs))
    save('embedding-input-summary.json', dict(targets=len(inputs),
        searchable=sum(x['searchable'] for x in inputs),
        non_searchable=sum(not x['searchable'] for x in inputs), input_file_sha256=digest(path.read_bytes()),
        source='Current fused_index.retrieval_text on preserved extraction/chunks; offline string preparation only',
        no_embedding_or_retrieval_executed=True))
    print(f"Prepared {len(inputs)} embedding input strings offline")


def engine():
    from sqlalchemy import create_engine
    from sqlalchemy.engine import URL
    # Never accepts DATABASE_URL or arbitrary target. Read ONLY dedicated password.
    values = [line.split('=', 1)[1].strip() for line in (ROOT / '.env').read_text().splitlines()
              if line.startswith('E2E_PERSISTENT_DB_PASSWORD=')]
    assert len(values) == 1 and values[0]
    url = URL.create('postgresql+psycopg', username=DB_NAME, password=values[0],
                     host='127.0.0.1', port=55433, database=DB_NAME)
    return create_engine(url)


def guard(connection):
    from sqlalchemy import text
    identity = connection.execute(text('SELECT current_database(), current_user')).one()
    assert tuple(identity) == (DB_NAME, DB_NAME), 'Refusing non-E2E database'


def migrate():
    from alembic.config import Config
    from alembic import command
    e = engine()
    with e.connect() as conn:
        guard(conn)
    # Alembic env takes DATABASE_URL: override temporarily with the fixed guarded target.
    previous = os.environ.get('DATABASE_URL')
    os.environ['DATABASE_URL'] = e.url.render_as_string(hide_password=False)
    cwd = Path.cwd()
    try:
        os.chdir(ROOT / 'backend')
        command.upgrade(Config('alembic.ini'), 'head')
    finally:
        os.chdir(cwd)
        if previous is None:
            os.environ.pop('DATABASE_URL', None)
        else:
            os.environ['DATABASE_URL'] = previous


def restore():
    from sqlalchemy import text
    from sqlalchemy.orm import Session
    from app.models import Document, Chunk, DocumentType, DocumentStatus, EmbeddingStatus
    audit()
    doc, pages = page_objects()
    e = engine()
    with Session(e) as session, session.begin():
        guard(session)
        for table in ('documents', 'pages', 'chunks', 'page_extractions', 'analysis_runs'):
            assert session.execute(text(f'SELECT count(*) FROM {table}')).scalar_one() == 0, 'Refusing nonempty DB'
        document = Document(id=uuid.UUID(doc['id']), company_name=doc['company_name'], stock_code=doc['stock_code'],
            document_type=DocumentType(doc['document_type']), issuer=doc['issuer'], published_at=date.fromisoformat(doc['published_at']),
            filename=doc['filename'], storage_path=str(ARCHIVE / 'data/raw' / (doc['id'] + '.pdf')),
            file_hash=load(BASE / 'restoration-audit.json')['pdf_sha256'], status=DocumentStatus(doc['status']),
            error_reason=doc['error_reason'], total_pages=doc['total_pages'], created_at=datetime.fromisoformat(doc['created_at']),
            embedding_status=EmbeddingStatus.not_started, embedding_provider='ollama', embedding_model='bge-m3',
            embedding_dimensions=1024, embedding_completed_at=None,
            embedding_failure_reason='Previous tmpfs vectors lost; regeneration not executed')
        session.add(document)
        session.flush()
        for page, raw in pages:
            session.add(page)
            session.flush()
            for c in raw['chunks']:
                session.add(Chunk(id=uuid.UUID(c['id']), document_id=document.id, page_id=page.id,
                    page_number=page.page_number, section_title=None, content=c['content'],
                    char_start=c['char_start'], char_end=c['char_end'], embedding=None,
                    embedding_provider='ollama', embedding_model='bge-m3', embedding_dimensions=1024,
                    embedding_error='Vector lost in previous tmpfs DB; not regenerated'))
    print('Restored into isolated E2E DB only')


def snapshot(name):
    from sqlalchemy import text
    e = engine()
    result = {}
    with e.connect() as conn:
        guard(conn)
        for table in ('documents', 'pages', 'page_extractions', 'chunks', 'analysis_runs', 'shadow_revisions', 'shadow_pages', 'shadow_chunks', 'alembic_version'):
            rows = [dict(r) for r in conn.execute(text(f'SELECT * FROM {table}')).mappings()]
            serialized = sorted(canonical(r).decode() for r in rows)
            result[table] = dict(count=len(rows), sha256=digest(canonical(serialized)))
        result['embedded_chunks'] = conn.execute(text('SELECT count(*) FROM chunks WHERE embedding IS NOT NULL')).scalar_one()
        result['embedding_type'] = conn.execute(text("SELECT format_type(atttypid,atttypmod) FROM pg_attribute WHERE attrelid='chunks'::regclass AND attname='embedding'")).scalar_one()
        assert result['embedding_type'] == 'vector(1024)' and result['embedded_chunks'] == 0
        assert [result[t]['count'] for t in ('documents','pages','page_extractions','chunks','analysis_runs')] == [1,9,9,583,0]
        doc, saved_pages = page_objects()
        for page, raw in saved_pages:
            row = conn.execute(text('SELECT * FROM pages WHERE id=:id'), {'id': page.id}).mappings().one()
            for field in ('document_id', 'page_number', 'native_text', 'ocr_text', 'final_text', 'ocr_error'):
                assert row[field] == getattr(page, field)
            assert row['text_source'] == raw['text_source']
            observation = conn.execute(text('SELECT * FROM page_extractions WHERE page_id=:id'), {'id': page.id}).mappings().one()
            assert canonical({k: observation[k] for k in raw['extraction']}) == canonical(raw['extraction'])
            saved_chunks = {c['id']: c for c in raw['chunks']}
            restored_chunks = list(conn.execute(text('SELECT * FROM chunks WHERE page_id=:id'), {'id': page.id}).mappings())
            assert len(restored_chunks) == len(saved_chunks)
            for chunk in restored_chunks:
                saved = saved_chunks[str(chunk['id'])]
                assert all(chunk[k] == saved[k] for k in ('content', 'char_start', 'char_end'))
                assert chunk['embedding'] is None
        assert conn.execute(text('SELECT count(*) FROM chunks c JOIN pages p ON p.id=c.page_id WHERE c.document_id<>p.document_id OR c.page_number<>p.page_number OR substring(p.final_text FROM c.char_start+1 FOR c.char_end-c.char_start)<>c.content')).scalar_one() == 0
    save(name, result)
    print(json.dumps({k: v['count'] for k, v in result.items() if isinstance(v, dict)}))


def verify_files():
    before = load(BASE / 'files-before.json')
    assert inventory(OLD) == before and inventory(ARCHIVE) == before
    save('files-after.json', before)
    print('2993 original + 2993 archived files unchanged')


if __name__ == '__main__':
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('action', choices=['archive', 'audit', 'migrate', 'restore', 'snapshot', 'verify-files', 'prepare-inputs'])
    cli.add_argument('--snapshot-name', default='snapshot.json')
    args = cli.parse_args()
    if args.action == 'snapshot':
        assert Path(args.snapshot_name).name == args.snapshot_name
        snapshot(args.snapshot_name)
    else:
        {'archive': archive, 'audit': audit, 'migrate': migrate, 'restore': restore,
         'verify-files': verify_files, 'prepare-inputs': prepare_inputs}[args.action]()
