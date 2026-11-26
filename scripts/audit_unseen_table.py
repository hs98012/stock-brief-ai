#!/usr/bin/env python3
"""Read-only, in-memory evaluation of reports frozen after implementation."""
import argparse
import hashlib
import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from uuid import NAMESPACE_URL, uuid5, UUID

from dotenv import dotenv_values
from sqlalchemy.engine import URL, make_url

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
config = dotenv_values(ROOT / '.env')
url = config.get('DATABASE_URL')
database = (make_url(url).set(host='localhost', port=int(config.get('POSTGRES_HOST_PORT') or 5432))
    if url else URL.create('postgresql+psycopg', username=config.get('POSTGRES_USER') or 'stock_brief',
        password=config.get('POSTGRES_PASSWORD') or 'change-me-for-local-development',
        host='localhost', port=int(config.get('POSTGRES_HOST_PORT') or 5432),
        database=config.get('POSTGRES_DB') or 'stock_brief'))
os.environ['DATABASE_URL'] = database.render_as_string(hide_password=False)
os.environ['OLLAMA_BASE_URL'] = 'http://localhost:11434'
os.environ['PADDLE_STRUCTURE_URL'] = 'http://127.0.0.1:8090'

from app.chunking import structured_spans
from app.database import SessionLocal
from app.embeddings import OllamaEmbeddingProvider
from app.fused_index import retrieval_text
from app.pdf_pipeline import PARSER_VERSION, extract_pdf
from app.search import rank_rows
from app.extraction_provenance import validated_stored_facts
from audit_shadow import snapshot


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def freeze_rows(rows):
    pages = {str(page.id): {**page.__dict__, 'extraction': page.extraction.__dict__}
             for _, page, _ in rows}
    documents = {str(doc.id): doc.__dict__ for _, _, doc in rows}
    return {'pages': list(pages.values()), 'documents': list(documents.values()),
            'chunks': [{**chunk.__dict__, 'embedding':
                [float(value) for value in chunk.embedding] if chunk.embedding is not None else None}
                for chunk, _, _ in rows]}


def thaw_rows(index):
    def record(values):
        values = dict(values)
        for key in ('id', 'page_id', 'document_id'):
            if values.get(key):
                values[key] = UUID(values[key])
        return SimpleNamespace(**values)
    documents = {item['id']: record(item) for item in index['documents']}
    pages = {}
    for item in index['pages']:
        page = record(item)
        page.extraction = SimpleNamespace(**item['extraction'])
        pages[item['id']] = page
    rows = [(record(item), pages[item['page_id']], documents[item['document_id']])
            for item in index['chunks']]
    return rows, {page.page_number: page for page in pages.values()}


def strict(case, result, pages):
    selected = result.evidence_pack if result.evidence_pack is not None else result.results
    if result.coverage_complete is False:
        for gold in case['gold_fact_bundle']:
            if gold['kind'] != 'narrative' and not any(matches_gold(fact, gold)
                    for fact in validated_stored_facts(pages[gold['physical_page']])):
                return False, 'table_extraction'
        return False, 'evidence_selection'
    for gold in case['gold_fact_bundle']:
        page = pages[gold['physical_page']]
        items = [item for item in selected if item['page_number'] == gold['physical_page']]
        if gold['kind'] == 'narrative':
            if not gold.get('required_terms'):
                return False, 'narrative_review_required'
            if not any(all(token in ''.join(span['quote'] for span in item.get('source_spans', []))
                           for token in gold['required_terms']) for item in items):
                return False, 'narrative_retrieval_or_selection'
            continue
        facts = [fact for item in items for fact in item.get('table_evidence', [])]
        matches = [fact for fact in facts if matches_gold(fact, gold)]
        if not any(all(page.final_text[span['char_start']:span['char_end']] == span['quote']
                       and span.get('bbox') for span in fact['source_spans']) for fact in matches):
            available = validated_stored_facts(page)
            if any(matches_gold(fact, gold) for fact in available):
                return False, 'evidence_selection'
            return False, 'table_extraction'
    return True, None


def matches_gold(fact, gold):
    # Cell-label whitespace is typography; metric suffixes, periods and numeric
    # strings retain their exact meaning. Do not alter the frozen gold fixture.
    compact = lambda value: ''.join(str(value or '').split())
    if compact(fact.get('row_label')) != compact(gold['row']):
        return False
    def numeric(value, unit):
        literal=compact(value)
        # A literal percent suffix and a separate verified percent unit are the
        # same representation, with no rounding, scaling or numeric correction.
        return literal[:-1] if unit == '%' and literal.endswith('%') else literal
    if any(compact(fact.get(key)) != compact(gold[key]) for key in ('period', 'unit') if key in gold):
        return False
    if numeric(fact.get('value'),fact.get('unit')) != numeric(gold.get('value'),gold.get('unit')):
        return False
    comparison = fact.get('comparison_cell') or {}
    return gold.get('comparison_value') is None or all(
        (numeric(comparison.get(key),comparison.get('unit')) == numeric(value,gold.get('unit'))
         if key == 'value' else compact(comparison.get(key)) == compact(value)) for key, value in
        (('value', gold['comparison_value']), ('unit', gold['unit']), ('label', gold['comparison_basis'])))


def main():
    global rank_rows
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cases', type=Path, default=ROOT / 'evals/table-integrity-unseen-cases.json')
    parser.add_argument('--pdf-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--write-index', type=Path, help='Immutable, Git-ignored evaluation index')
    parser.add_argument('--read-index', type=Path, help='Replay exactly the saved extraction and embeddings')
    parser.add_argument('--selection-runtime', type=Path, help='Frozen baseline search/bundle source directory')
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    runtime_hashes = {}
    if args.selection_runtime:
        for name in ('evidence_bundle', 'search'):
            path = args.selection_runtime / f'before-{name}.py'
            spec = importlib.util.spec_from_file_location(f'app.{name}', path)
            module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = module
            spec.loader.exec_module(module)
            runtime_hashes[name] = digest(path)
        rank_rows = module.rank_rows
    case_hash = digest(args.cases)
    cases = json.loads(args.cases.read_text())
    if args.write_index and args.write_index.exists():
        raise FileExistsError(args.write_index)
    cached = json.loads(args.read_index.read_text()) if args.read_index else None
    if cached and (cached['cases_sha256'] != case_hash or cached['parser_version'] != PARSER_VERSION
                   or cached['embedding'] != ['ollama', 'bge-m3', 1024]):
        raise ValueError('Evaluation index identity changed')
    frozen = {'cases_sha256': case_hash, 'parser_version': PARSER_VERSION,
              'embedding': ['ollama', 'bge-m3', 1024], 'cases': {}}
    provider = OllamaEmbeddingProvider()
    if not provider.available:
        raise RuntimeError(provider.unavailable_reason)
    output = {'cases_sha256_before': case_hash, 'parser_version': PARSER_VERSION,
              'generator_called': False, 'selection_runtime_hashes': runtime_hashes, 'cases': []}
    with SessionLocal() as db:
        output['active_before'] = snapshot(db)
        db.rollback()
    for case in cases:
        pdf = args.pdf_dir / case['filename']
        if digest(pdf) != case['pdf_sha256']:
            raise ValueError('PDF hash mismatch: ' + case['id'])
        if cached:
            stored = cached['cases'][case['id']]
            if stored['pdf_sha256'] != case['pdf_sha256']:
                raise ValueError('Cached PDF hash mismatch')
            rows, pages = thaw_rows(stored['index'])
            result = rank_rows(rows, case['question'], 5, provider, diagnostics=True)
            passed, failure = strict(case, result, pages)
            output['cases'].append({'id': case['id'], 'pdf_sha256': case['pdf_sha256'],
                'question': case['question'], 'strict_pass': passed, 'failure_stage': failure,
                'page_count': len(pages), 'chunk_count': len(rows), 'search': result.__dict__})
            continue
        with tempfile.TemporaryDirectory() as directory:
            extracted = extract_pdf(pdf, Path(directory))
        document_id = uuid5(NAMESPACE_URL, case['pdf_sha256'])
        document = SimpleNamespace(id=document_id, filename=pdf.name,
            company_name=pdf.stem, stock_code=None, issuer='source PDF', published_at=None,
            document_type='broker_report')
        pages = {}
        rows = []
        for item in extracted:
            page_id = uuid5(document_id, str(item.page_number))
            page = SimpleNamespace(id=page_id, document_id=document_id,
                page_number=item.page_number, final_text=item.final_text,
                extraction=SimpleNamespace(parser_version=PARSER_VERSION,
                    final_text_sha256=hashlib.sha256(item.final_text.encode()).hexdigest(),
                    provenance=item.provenance, table_facts=item.table_facts))
            pages[item.page_number] = page
            chunks = []
            for span in structured_spans(item.final_text, item.provenance):
                chunk = SimpleNamespace(id=uuid5(page_id, f'{span.char_start}:{span.char_end}'),
                    page_id=page_id, document_id=document_id, page_number=item.page_number,
                    char_start=span.char_start, char_end=span.char_end, content=span.content,
                    section_title=None, embedding=None, embedding_provider='ollama',
                    embedding_model='bge-m3', embedding_dimensions=1024)
                chunks.append(chunk)
                rows.append((chunk, page, document))
            page.extraction.table_facts = [{**fact, 'source_chunk_ids': sorted({str(chunk.id)
                for span in fact['source_spans'] for chunk in chunks
                if chunk.char_start < span['char_end'] and chunk.char_end > span['char_start']})}
                for fact in item.table_facts]
        for start in range(0, len(rows), 8):
            batch = rows[start:start+8]
            vectors = provider.embed([retrieval_text(chunk, page) for chunk, page, _ in batch])
            for (chunk, _, _), vector in zip(batch, vectors, strict=True):
                chunk.embedding = vector
        result = rank_rows(rows, case['question'], 5, provider, diagnostics=True)
        frozen['cases'][case['id']] = {'pdf_sha256': case['pdf_sha256'], 'index': freeze_rows(rows)}
        passed, failure = strict(case, result, pages)
        output['cases'].append({'id': case['id'], 'pdf_sha256': case['pdf_sha256'],
            'question': case['question'], 'strict_pass': passed, 'failure_stage': failure,
            'page_count': len(pages), 'chunk_count': len(rows), 'search': result.__dict__,
            'gold_page_text_sha256': {gold['physical_page']:
                pages[gold['physical_page']].extraction.final_text_sha256
                for gold in case['gold_fact_bundle']}})
    with SessionLocal() as db:
        output['active_after'] = snapshot(db)
        db.rollback()
    output['cases_sha256_after'] = digest(args.cases)
    if args.read_index:
        output['evaluation_index_sha256'] = digest(args.read_index)
    if args.write_index:
        args.write_index.parent.mkdir(parents=True, exist_ok=True)
        with args.write_index.open('x') as stream:
            json.dump(frozen, stream, ensure_ascii=False, default=str)
        output['evaluation_index_sha256'] = digest(args.write_index)
    if output['active_before'] != output['active_after'] or case_hash != output['cases_sha256_after']:
        raise ValueError('Active data or frozen cases changed')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, default=str))
    print('strict=' + str(sum(case['strict_pass'] for case in output['cases'])) + '/' + str(len(cases)))
    print('failures=' + ','.join(case['id'] + ':' + str(case['failure_stage'])
                               for case in output['cases'] if not case['strict_pass']))


if __name__ == '__main__':
    main()
