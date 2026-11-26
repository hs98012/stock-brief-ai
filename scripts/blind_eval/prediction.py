"""Prediction worker: document/question/config only, no scorer imports or DB."""
import hashlib
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace as NS
from uuid import UUID, uuid5

from .isolation import install_guard, validate_input


def prepare_rows(metadata, extract, provider, scratch):
    from app.chunking import structured_spans
    from app.fact_fusion import PARSER_VERSION
    from app.fused_index import retrieval_text
    doc_id = UUID(metadata['document_id'])
    document = NS(id=doc_id, filename=metadata['original_filename'],
        company_name=metadata['company_name'], stock_code=metadata['stock_code'],
        issuer=metadata['issuer'], published_at=metadata['published_at'], document_type='broker_report')
    path = Path(metadata['pdf_path'])
    if hashlib.sha256(path.read_bytes()).hexdigest() != metadata['sha256']:
        raise ValueError('Document fingerprint mismatch')
    extracted = extract(path, scratch)
    rows, pages = [], []
    for item in extracted:
        if getattr(item, 'ocr_error', None):
            raise RuntimeError('OCR extraction failed')
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
                section_title=None, embedding=None, embedding_provider=provider.provider_name,
                embedding_model=provider.model, embedding_dimensions=provider.dimensions)
            chunks.append(chunk)
            rows.append((chunk, page, document))
        page.extraction.table_facts = [{**fact, 'source_chunk_ids': sorted({str(chunk.id)
            for span in fact['source_spans'] for chunk in chunks
            if chunk.char_start < span['char_end'] and chunk.char_end > span['char_start']})}
            for fact in item.table_facts]
        pages.append(dict(page_number=item.page_number, final_text=item.final_text,
            extraction=page.extraction.__dict__))
    for start in range(0, len(rows), 8):
        batch = rows[start:start+8]
        vectors = provider.embed([retrieval_text(chunk, page) for chunk, page, _ in batch])
        for (chunk, _, _), vector in zip(batch, vectors, strict=True):
            chunk.embedding = vector
    return rows, pages


def predict(question, rows, config, provider, *, rank=None, generate=None):
    if set(question) != {'id', 'document_id', 'question'}:
        raise ValueError('Question contains labels')
    if rank is None:
        from app.search import rank_rows
        rank = rank_rows
    result = {'id': question['id'], 'document_id': question['document_id'],
        'status': 'ERROR', 'answer': None, 'answer_metrics': 'NOT_VERIFIED',
        'search': None, 'errors': []}
    try:
        execution = rank(rows, question['question'], config['top_k'], provider,
            rerank=config['rerank'], diagnostics=config['diagnostics'])
        result['search'] = execution.__dict__.copy()
        result['search']['evidence_pack'] = [dict(item, document_id=question['document_id'])
            for item in execution.evidence_pack or []]
        if execution.vector_search_unavailable_reason:
            raise RuntimeError('Vector retrieval unavailable')
        result['status'] = 'COMPLETE' if execution.coverage_complete is True else 'HOLD'
        if result['status'] == 'HOLD':
            result['answer'] = '확인할 수 없습니다'
        # The sealed policy's first phase is retrieval/evidence only.
        # The generation seam is tested synthetically, never enabled by first-run CLI.
        if generate is not None:
            if result['status'] == 'HOLD':
                result['answer'] = '확인할 수 없습니다'
            else:
                result['answer'] = generate(question['question'], execution.evidence_pack)
            result['answer_metrics'] = 'GENERATED_UNSCORED'
    except Exception as exc:
        result.update(status='ERROR', answer=None)
        result['errors'].append({'type': type(exc).__name__, 'message': str(exc)})
    return result


def main(stage):
    root = Path(__file__).resolve().parents[2]
    stage = Path(stage).resolve()
    install_guard(root, stage)
    data = json.loads((stage/'input.json').read_text())
    validate_input(data)
    config = data['configuration']
    for key, value in config['effective_environment'].items():
        os.environ[key] = str(value)
    os.environ['OLLAMA_BASE_URL'] = config['transport']['ollama_base_url']
    os.environ['PADDLE_STRUCTURE_URL'] = config['transport']['paddle_structure_url']
    sys.path.insert(0, str(root/'backend'))
    from app.embeddings import OllamaEmbeddingProvider
    from app.pdf_pipeline import extract_pdf
    provider = OllamaEmbeddingProvider()
    for metadata in data['documents']:
        questions = [q for q in data['questions'] if q['document_id'] == metadata['document_id']]
        try:
            rows, pages = prepare_rows(metadata, extract_pdf, provider, stage/'scratch')
            with (stage/(metadata['document_id']+'-pages.json')).open('x') as stream:
                json.dump(pages, stream, default=str, ensure_ascii=False)
        except Exception as exc:
            for question in questions:
                result = {'id': question['id'], 'document_id': question['document_id'],
                    'status': 'ERROR', 'answer': None, 'answer_metrics': 'NOT_VERIFIED',
                    'search': None, 'errors': [{'type': type(exc).__name__, 'message': str(exc)}]}
                write_result(stage, result)
            continue
        for question in questions:
            write_result(stage, predict(question, rows, config, provider))


def write_result(stage, result):
    # Exclusive per-question records survive a worker crash; never retry a question.
    with (stage/(result['id']+'.prediction.json')).open('x') as stream:
        json.dump(result, stream, default=str, ensure_ascii=False)


if __name__ == '__main__':
    main(sys.argv[1])
