#!/usr/bin/env python3
"""One-shot, shadow-only holdout retrieval; never scores development cases."""
import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

from dotenv import dotenv_values
from sqlalchemy.engine import URL, make_url

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'backend'))
configuration = dotenv_values(ROOT/'.env')
url = configuration.get('DATABASE_URL')
if url:
    parsed = make_url(url)
    if parsed.host not in ('postgres', 'localhost', '127.0.0.1'):
        raise RuntimeError('Unexpected local database host')
    parsed = parsed.set(host='localhost', port=int(configuration.get('POSTGRES_HOST_PORT') or 5432))
else:
    parsed = URL.create('postgresql+psycopg', username=configuration.get('POSTGRES_USER') or 'stock_brief',
        password=configuration.get('POSTGRES_PASSWORD') or 'change-me-for-local-development',
        host='localhost', port=int(configuration.get('POSTGRES_HOST_PORT') or 5432),
        database=configuration.get('POSTGRES_DB') or 'stock_brief')
os.environ['DATABASE_URL'] = parsed.render_as_string(hide_password=False)
os.environ['PADDLE_STRUCTURE_URL'] = 'http://127.0.0.1:8090'

from app.database import SessionLocal
from app.embeddings import OllamaEmbeddingProvider
from app.models import Document
from app.pdf_pipeline import PARSER_VERSION
from app.shadow_revision import create_revision, embed_revision, search_revision
from app.shadow_models import ShadowRevision, ShadowPage, ShadowChunk
from audit_shadow import snapshot
from pinned_manifest import code_identity, file_hash, revision_manifest, verify_manifest, worker_identity
from sqlalchemy import select


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--existing-version', help='Read-only search of ready shadow revisions')
    parser.add_argument('--manifest-source', type=Path, help='Original immutable revision manifests')
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    if bool(args.existing_version) != bool(args.manifest_source):
        raise ValueError('Existing revisions require their original manifest artifact')
    version = args.existing_version or PARSER_VERSION + '+pin-' + args.run_id
    if len(version) > 64:
        raise ValueError('Run ID exceeds parser version limit')
    cases_path = ROOT/'evals/holdout-cases.json'
    cases_hash = file_hash(cases_path)
    cases = json.loads(cases_path.read_text())
    worker = None if args.existing_version else worker_identity()
    existing_manifests = (json.loads(args.manifest_source.read_text())['manifests']
                          if args.manifest_source else [])
    head, diff = code_identity()
    provider = OllamaEmbeddingProvider(base_url='http://localhost:11434')
    if not provider.available or (provider.provider_name, provider.model, provider.dimensions) != ('ollama', 'bge-m3', 1024):
        raise RuntimeError('Holdout requires local bge-m3 1024')
    output = {'run_id': args.run_id, 'holdout_cases_sha256_before': cases_hash,
              'git_head': head, 'working_tree_diff_sha256': diff, 'cases': [], 'manifests': []}
    with SessionLocal() as db:
        output['active_before'] = snapshot(db)
        for case in cases:
            pdf = ROOT/'holdout-v1'/case['filename']
            if file_hash(pdf) != case['pdf_sha256']:
                raise ValueError('Holdout PDF hash mismatch')
            doc = db.query(Document).filter_by(file_hash=case['pdf_sha256']).one()
            if args.existing_version:
                revision = db.scalar(select(ShadowRevision).where(
                    ShadowRevision.document_id == doc.id,
                    ShadowRevision.parser_version == version))
                if revision is None or revision.status != 'ready':
                    raise ValueError('Ready shadow revision missing')
            else:
                revision = create_revision(db, doc, pdf, revision_version=version)
                db.commit()
                embed_revision(db, revision.id, provider)
                db.commit()
            pages = db.scalars(select(ShadowPage).where(ShadowPage.revision_id == revision.id)
                .order_by(ShadowPage.page_number)).all()
            chunks = db.scalars(select(ShadowChunk).where(ShadowChunk.revision_id == revision.id)
                .order_by(ShadowChunk.page_id, ShadowChunk.char_start)).all()
            stored = {'id': str(revision.id), 'created_at': revision.created_at,
                'document_id': str(doc.id), 'file_hash': revision.file_hash,
                'parser_version': revision.parser_version, 'status': revision.status,
                'pages': [{column.name: getattr(page, column.name) for column in ShadowPage.__table__.columns}
                          for page in pages],
                'chunks': [{column.name: getattr(chunk, column.name) for column in ShadowChunk.__table__.columns
                            if column.name != 'embedding'} for chunk in chunks]}
            manifest = (next((item for item in existing_manifests
                              if item['revision_id'] == str(revision.id)), None)
                        if args.existing_version else revision_manifest(stored,
                            run_id=args.run_id, worker=worker, git_head=head,
                            diff_hash=diff, cases_sha256=cases_hash, gold_sha256=cases_hash))
            if manifest is None:
                raise ValueError('Revision manifest missing')
            verify_manifest(stored, manifest)
            output['manifests'].append(manifest)
            result = search_revision(db, revision, doc, case['question'], provider)
            output['cases'].append({'id': case['id'], 'question': case['question'],
                'document_id': str(doc.id), 'pdf_sha256': case['pdf_sha256'],
                'revision_id': str(revision.id), 'page_count': len(pages),
                'chunk_count': len(chunks), 'search': result.__dict__,
                'page_text_sha256': {page.page_number: page.final_text_sha256 for page in pages},
                'pack_source_pages': {str(page.page_number): page.final_text for page in pages
                    if result.evidence_pack and page.page_number in
                       {item['page_number'] for item in result.evidence_pack}}})
        output['active_after'] = snapshot(db)
        db.rollback()
    output['holdout_cases_sha256_after'] = file_hash(cases_path)
    if output['active_before'] != output['active_after'] or cases_hash != output['holdout_cases_sha256_after']:
        raise ValueError('Active data or holdout cases changed')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x') as stream:
        json.dump(output, stream, ensure_ascii=False, default=str)
    print('holdout_cases=' + str(len(output['cases'])))
    print('coverage_complete=' + str(sum(bool(case['search']['coverage_complete']) for case in output['cases'])))


if __name__ == '__main__':
    main()
