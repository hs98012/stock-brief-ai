#!/usr/bin/env python3
"""Explicit future first retrieval/evidence run; no gold loading, generation or DB."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import subprocess
import tempfile
from types import SimpleNamespace as NS
from uuid import UUID, uuid5

from verify_sealed_holdout import ROOT, verify


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--manifest', type=Path, required=True)
    cli.add_argument('--output-dir', type=Path, required=True)
    cli.add_argument('--execute-first-run', action='store_true',
                     help='Explicitly allow the first model retrieval run after seal verification')
    args = cli.parse_args()
    manifest = verify(args.manifest)
    if not args.execute_first_run:
        print('Seal verified. No extraction, embedding, retrieval or generation executed.')
        return
    bundle = ROOT/manifest['bundle_path']
    output = args.output_dir.resolve()
    if output != (ROOT/manifest['first_run_output']).resolve():
        raise ValueError('First-run output must match the preregistered manifest path')
    if output.is_relative_to(bundle.resolve()) or bundle.resolve().is_relative_to(output):
        raise ValueError('Results must be outside the sealed bundle')
    if output.exists():
        raise FileExistsError(output)
    config = json.loads((bundle/'configuration.json').read_text())
    for key, value in config['effective_environment'].items():
        os.environ[key] = str(value)
    # Transport addresses select local equivalents, never a different model or rank policy.
    os.environ['OLLAMA_BASE_URL'] = config['transport']['ollama_base_url']
    os.environ['PADDLE_STRUCTURE_URL'] = config['transport']['paddle_structure_url']
    sys.path.insert(0, str(ROOT/'backend'))
    from app.chunking import structured_spans
    from app.embeddings import OllamaEmbeddingProvider
    from app.fact_fusion import PARSER_VERSION
    from app.fused_index import retrieval_text
    from app.pdf_pipeline import extract_pdf
    from app.search import rank_rows
    provider = OllamaEmbeddingProvider()
    if not provider.available:
        raise RuntimeError(provider.unavailable_reason)
    tags = provider.client.get('/api/tags').json()
    embedding_runtime = [m for m in tags.get('models', []) if m.get('name') in
                         {provider.model, provider.model+':latest'}]
    if len(embedding_runtime) != 1 or embedding_runtime[0].get('digest') != config['embedding']['digest']:
        raise RuntimeError('Sealed embedding model fingerprint mismatch')
    image = subprocess.check_output(['docker', 'inspect', config['worker']['container_name'],
                                     '--format', '{{.Image}}'], text=True).strip()
    if image != config['worker']['image_id']:
        raise RuntimeError('Sealed OCR worker image mismatch')
    import httpx
    health = httpx.get(config['transport']['paddle_structure_url']+'/health', timeout=5)
    health.raise_for_status()
    fingerprint = httpx.get(config['transport']['paddle_structure_url']+'/fingerprint', timeout=5)
    fingerprint.raise_for_status()
    # A first-attempt ledger is reserved atomically. Failure never overwrites or hides a run.
    output.mkdir(parents=True, exist_ok=False)
    started = datetime.now(timezone.utc).isoformat()
    report = dict(manifest_sha256=hashlib.sha256(args.manifest.read_bytes()).hexdigest(),
        started_at=started, status='RUNNING', generator_called=False, db_called=False,
        gold_loaded=False, gold_scoring='Separate manual/offline review after output is frozen',
        parser_version=PARSER_VERSION, configuration=config, embedding_runtime=embedding_runtime,
        worker_image_id=image, worker_runtime_fingerprint=fingerprint.json(), cases=[])
    result_path = output/'retrieval.json'
    def save():
        temporary = output/'retrieval.json.tmp'
        temporary.write_text(json.dumps(report, ensure_ascii=False, default=str, indent=2)+'\n')
        temporary.replace(result_path)
    save()
    try:
        questions = json.loads((bundle/'questions.json').read_text())
        documents = json.loads((bundle/'documents.json').read_text())
        for metadata in documents:
            doc_id = UUID(metadata['document_id'])
            document = NS(id=doc_id, filename=metadata['original_filename'],
                company_name=metadata['company_name'], stock_code=metadata['stock_code'],
                issuer=metadata['issuer'], published_at=metadata['published_at'], document_type='broker_report')
            rows = []
            with tempfile.TemporaryDirectory(dir=output) as directory:
                extracted = extract_pdf(ROOT/metadata['path'], Path(directory))
            pages = []
            for item in extracted:
                page_id = uuid5(doc_id, str(item.page_number))
                page = NS(id=page_id, document_id=doc_id, page_number=item.page_number,
                    final_text=item.final_text, extraction=NS(parser_version=PARSER_VERSION,
                        final_text_sha256=hashlib.sha256(item.final_text.encode()).hexdigest(),
                        provenance=item.provenance, table_facts=item.table_facts))
                chunks = []
                for span in structured_spans(item.final_text, item.provenance):
                    chunk = NS(id=uuid5(page_id, f'{span.char_start}:{span.char_end}'),
                        document_id=doc_id, page_id=page_id, page_number=item.page_number,
                        content=span.content, char_start=span.char_start, char_end=span.char_end,
                        section_title=None, embedding=None, embedding_provider='ollama',
                        embedding_model=provider.model, embedding_dimensions=provider.dimensions)
                    chunks.append(chunk)
                    rows.append((chunk, page, document))
                page.extraction.table_facts = [{**f, 'source_chunk_ids': sorted({str(c.id)
                    for s in f['source_spans'] for c in chunks
                    if c.char_start < s['char_end'] and c.char_end > s['char_start']})}
                    for f in item.table_facts]
                pages.append(dict(page_number=page.page_number, final_text=page.final_text,
                    extraction=page.extraction.__dict__, chunks=[c.__dict__ for c in chunks]))
            for start in range(0, len(rows), 8):
                batch = rows[start:start+8]
                vectors = provider.embed([retrieval_text(c, p) for c, p, _ in batch])
                for (chunk, _, _), vector in zip(batch, vectors, strict=True):
                    chunk.embedding = vector
            (output/(metadata['slug']+'-index.json')).write_text(
                json.dumps(pages, ensure_ascii=False, default=str)+'\n')
            for question in questions:
                if question['document_id'] != str(doc_id):
                    continue
                result = rank_rows(rows, question['question'], config['top_k'], provider,
                    rerank=config['rerank'], diagnostics=config['diagnostics'])
                report['cases'].append(dict(id=question['id'], document_id=question['document_id'],
                    question=question['question'], search=result.__dict__))
                save()
        verify(args.manifest)
        report.update(status='COLLECTED_NOT_SCORED', finished_at=datetime.now(timezone.utc).isoformat())
        save()
        hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in output.iterdir() if p.is_file()}
        (output/'outputs.sha256.json').write_text(json.dumps(hashes, indent=2)+'\n')
    except Exception as exc:
        report.update(status='FAILED', error=type(exc).__name__+': '+str(exc))
        save()
        raise


if __name__ == '__main__':
    main()
