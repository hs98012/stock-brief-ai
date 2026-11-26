#!/usr/bin/env python3
"""Build isolated revisions and measure retrieval only. Raw JSON goes to stdout."""
import hashlib
import json
import sys
import time
import argparse
import re
from datetime import date
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'backend'))
from sqlalchemy import text, select
from app.database import SessionLocal
from app.models import Document
from app.embeddings import OllamaEmbeddingProvider
from app.search import hybrid_search, SearchFilters
from app.shadow_revision import create_revision, embed_revision, search_revision
from app.shadow_models import ShadowRevision, ShadowPage, ShadowChunk
from app.pdf_pipeline import PARSER_VERSION


def snapshot(db):
    result = {}
    for table in ('documents', 'pages', 'chunks', 'analysis_runs', 'page_extractions'):
        values = db.execute(text(f'SELECT row_to_json(t) FROM {table} t')).scalars().all()
        encoded = json.dumps(sorted(values, key=lambda x: str(x.get('id', x.get('page_id')))),
                             sort_keys=True, ensure_ascii=False, default=str).encode()
        result[table] = {'count': len(values), 'sha256': hashlib.sha256(encoded).hexdigest()}
    return result


def prior_shadows(db, exclude_version=PARSER_VERSION):
    result={}
    for table in ('shadow_revisions','shadow_pages','shadow_chunks'):
        condition=('t.parser_version != :version' if table=='shadow_revisions' else
                   't.revision_id IN (SELECT id FROM shadow_revisions WHERE parser_version != :version)')
        values=db.execute(text(f'SELECT row_to_json(t) FROM {table} t WHERE {condition}'),
                          {'version':exclude_version}).scalars().all()
        encoded=json.dumps(sorted(values,key=lambda x:str(x['id'])),sort_keys=True,
                           ensure_ascii=False,default=str).encode()
        result[table]={'count':len(values),'sha256':hashlib.sha256(encoded).hexdigest()}
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reuse-paddle-version',help='Replay stored, original-hash-bound Paddle observations; no OCR rerun')
    parser.add_argument('--replay-source-artifact',type=Path,help='Pinned source artifact proving replayed Paddle observations')
    parser.add_argument('--existing-version',help='Read and score ready revisions without parsing or embedding')
    parser.add_argument('--pinned-run-id',help='Create a new, source-bound shadow-only revision namespace')
    parser.add_argument('--manifest-source',help='Reuse and validate manifests from a pinned artifact')
    parser.add_argument('--output',type=Path,help='Write raw JSON exclusively; never overwrite a prior run')
    args=parser.parse_args()
    if args.pinned_run_id and (not re.fullmatch(r'[a-z0-9-]{8,24}',args.pinned_run_id)
                               or args.existing_version):
        raise ValueError('Invalid pinned run arguments')
    if bool(args.replay_source_artifact) != bool(args.reuse_paddle_version and args.pinned_run_id):
        if args.replay_source_artifact or args.reuse_paddle_version and args.pinned_run_id:
            raise ValueError('Pinned replay requires a source artifact and a new pinned run ID')
    if args.pinned_run_id and not args.output:
        raise ValueError('Pinned run requires an exclusive output path')
    if args.manifest_source and not args.existing_version:
        raise ValueError('Manifest replay requires an existing revision')
    if args.output and args.output.exists():
        raise FileExistsError(args.output)
    pinned_version = f'{PARSER_VERSION}+pin-{args.pinned_run_id}' if args.pinned_run_id else None
    if pinned_version and len(pinned_version)>64:
        raise ValueError('Pinned revision version exceeds database limit')
    pinned_worker = pinned_head = pinned_diff = None
    if pinned_version:
        from pinned_manifest import worker_identity, code_identity
        if args.replay_source_artifact:
            from pinned_manifest import verify_manifest, file_hash
            source=json.loads(args.replay_source_artifact.read_text())
            if not source.get('manifests') or len(source['manifests'])!=len(source['revisions']):
                raise ValueError('Unpinned replay source')
            for revision,manifest in zip(source['revisions'],source['manifests'],strict=True):
                verify_manifest(revision,manifest)
                if revision['parser_version']!=args.reuse_paddle_version:
                    raise ValueError('Replay source parser version mismatch')
            first=source['manifests'][0]
            if any((m['worker_image_id'],m['worker_fingerprint']['sha256'])!=
                   (first['worker_image_id'],first['worker_fingerprint']['sha256'])
                   for m in source['manifests']):
                raise ValueError('Replay source worker mismatch')
            pinned_worker={'image_id':first['worker_image_id'],
                'container_id':first['worker_container_id'],
                'fingerprint':first['worker_fingerprint']}
            replay_source_sha256=file_hash(args.replay_source_artifact)
        else:
            pinned_worker=worker_identity()
        pinned_head,pinned_diff=code_identity()
    if args.reuse_paddle_version:
        from app import fused_extraction
        from app.paddle_structure import decode_page_result
        from pinned_manifest import digest
        source_pages = ({(revision['file_hash'],page['page_number']): page
            for revision,manifest in zip(source['revisions'],source['manifests'],strict=True)
            for page in manifest['pages']} if args.replay_source_artifact else None)
        observations={}
        with SessionLocal() as source_db:
            for revision,page in source_db.execute(select(ShadowRevision,ShadowPage).join(
                    ShadowPage,ShadowPage.revision_id==ShadowRevision.id).where(
                    ShadowRevision.parser_version==args.reuse_paddle_version,ShadowRevision.status=='ready')):
                raw=page.provenance.get('paddle_structure')
                if raw:
                    if source_pages is not None and (revision.file_hash,page.page_number) not in source_pages:
                        raise ValueError('Replay page missing from pinned source')
                    if source_pages is not None and digest(raw)!=source_pages[revision.file_hash,page.page_number]['raw_paddle_sha256']:
                        raise ValueError('Live Paddle observation differs from pinned source')
                    observations[revision.file_hash,page.page_number]={
                        'result':raw,'width':raw['width'],'height':raw['height'],
                        'model':page.provenance['paddle_model'],
                        'fingerprint_sha256':page.provenance['paddle_fingerprint_sha256']}
        def replay(page):
            digest=hashlib.sha256(Path(page.parent.name).read_bytes()).hexdigest()
            key=(digest,page.number+1)
            if key not in observations:
                raise RuntimeError('No original-hash-bound Paddle observation for page')
            return decode_page_result(observations[key],page)
        fused_extraction.extract_structure=replay
    base_provider = OllamaEmbeddingProvider()
    if not base_provider.available:
        raise RuntimeError(base_provider.unavailable_reason)
    cases = json.loads((ROOT/'evals/audit-cases.json').read_text())
    class CachedProvider:
        provider_name=base_provider.provider_name; model=base_provider.model; dimensions=base_provider.dimensions
        available=True; unavailable_reason=None
        def __init__(self): self.cache={}
        def preload(self, texts): self.cache.update(zip(texts,base_provider.embed(texts),strict=True))
        def embed(self,texts): return [self.cache[t] for t in texts]
    provider=CachedProvider()
    provider.preload([c['question'] for c in cases])
    output = {'generation_called': False, 'activation_available': False, 'cases': [], 'revisions': []}
    output['reused_paddle_version']=args.reuse_paddle_version
    with SessionLocal() as db:
        output['active_before'] = snapshot(db)
        output['prior_shadows_before'] = prior_shadows(db,pinned_version or args.existing_version or PARSER_VERSION)
        db.rollback()
        for case in cases:
            doc = db.query(Document).filter_by(company_name=case['company_name'],
                published_at=date.fromisoformat(case['published_at'])).one()
            db.execute(text('SET LOCAL enable_indexscan = off'))
            db.execute(text('SET LOCAL enable_bitmapscan = off'))
            started=time.monotonic()
            result = hybrid_search(db, case['question'], 5, SearchFilters(document_id=doc.id), provider, diagnostics=True)
            output['cases'].append({'id': case['id'], 'question': case['question'],
                                    'active': result.__dict__, 'active_seconds':round(time.monotonic()-started,4), 'document_id': str(doc.id)})
        db.rollback()
        revisions = {}
        for source in json.loads((ROOT/'evals/audit-documents.json').read_text()):
            doc = db.query(Document).filter_by(file_hash=source['sha256']).one()
            if args.existing_version:
                rev = db.scalar(select(ShadowRevision).where(ShadowRevision.document_id==doc.id,
                    ShadowRevision.file_hash==doc.file_hash,ShadowRevision.parser_version==args.existing_version))
                if rev is None or rev.status!='ready':raise RuntimeError('Existing shadow revision is not ready')
            else:
                rev = create_revision(db, doc, ROOT/'holdout-v1'/source['filename'],
                                      revision_version=pinned_version)
                db.commit()
                embed_revision(db, rev.id, base_provider)
                db.commit()
            revisions[str(doc.id)] = rev
            pages = db.scalars(select(ShadowPage).where(ShadowPage.revision_id == rev.id).order_by(ShadowPage.page_number)).all()
            chunks = db.scalars(select(ShadowChunk).where(ShadowChunk.revision_id == rev.id).order_by(ShadowChunk.page_id,ShadowChunk.char_start)).all()
            output['revisions'].append({'id': str(rev.id), 'created_at': rev.created_at,
                'document_id': str(doc.id),
                'file_hash': rev.file_hash, 'parser_version': rev.parser_version, 'status': rev.status,
                'pages': [{c.name: getattr(p, c.name) for c in ShadowPage.__table__.columns} for p in pages],
                'chunks': [{c.name: getattr(ch, c.name) for c in ShadowChunk.__table__.columns if c.name != 'embedding'} for ch in chunks],
                'embedded_count': sum(ch.embedding is not None for ch in chunks)})
        for item in output['cases']:
            rev = revisions.get(item['document_id'])
            if rev is None:
                item['shadow'] = item['active']; item['scope'] = 'unchanged_active_control'
            else:
                doc = db.get(Document, rev.document_id)
                started=time.monotonic()
                item['shadow'] = search_revision(db, rev, doc, item['question'], provider).__dict__
                item['shadow_seconds']=round(time.monotonic()-started,4)
                item['scope'] = 'shadow_revision'
        output['active_after'] = snapshot(db)
        output['prior_shadows_after'] = prior_shadows(db,pinned_version or args.existing_version or PARSER_VERSION)
        assert output['prior_shadows_before'] == output['prior_shadows_after'], 'Prior shadow data changed'
        assert output['active_before'] == output['active_after'], 'Active data changed'
        db.rollback()
    if pinned_version or args.manifest_source:
        from pinned_manifest import (worker_identity, revision_manifest, verify_manifest,
                                     file_hash, code_identity, ROOT as MANIFEST_ROOT)
        if pinned_version:
            if not args.replay_source_artifact and worker_identity()!=pinned_worker:
                raise RuntimeError('OCR worker changed during pinned run')
            if args.replay_source_artifact:
                output['replayed_from']={'artifact_sha256':replay_source_sha256,
                    'parser_version':args.reuse_paddle_version,
                    'worker_image_id':pinned_worker['image_id']}
            output['manifests']=[revision_manifest(revision,run_id=args.pinned_run_id,
                worker=pinned_worker,git_head=pinned_head,diff_hash=pinned_diff,
                cases_sha256=file_hash(MANIFEST_ROOT/'evals/audit-cases.json'),
                gold_sha256=file_hash(MANIFEST_ROOT/'evals/pinned-gold.json'))
                for revision in output['revisions']]
        else:
            old=json.loads(Path(args.manifest_source).read_text())
            output['manifests']=old['manifests']
        for revision,manifest in zip(output['revisions'],output['manifests'],strict=True):
            verify_manifest(revision,manifest)
        evaluation_head,evaluation_diff=code_identity()
        output['evaluation_code']={'git_head':evaluation_head,
                                   'working_tree_diff_sha256':evaluation_diff}
    serialized=json.dumps(output,ensure_ascii=False,default=str)
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        with args.output.open('x') as target:
            target.write(serialized+'\n')
        print(f'Wrote {args.output} (exclusive)')
    else:
        print(serialized)


if __name__ == '__main__':
    main()
