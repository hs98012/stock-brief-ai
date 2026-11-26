"""Scoring-only entry point. Labels never leave this process for prediction."""
import argparse
import json
from pathlib import Path


def schema_only(path):
    """Return field names/types only; no label values or question text."""
    def shape(value):
        if isinstance(value, dict):
            return {key: shape(item) for key, item in value.items()}
        if isinstance(value, list):
            return [shape(value[0])] if value else []
        return type(value).__name__
    return shape(json.loads(path.read_text()))


def compact(value):
    return ''.join(str(value).split())


def overlaps(a, b):
    return (len(a) == len(b) == 4 and min(a[2], b[2]) > max(a[0], b[0])
            and min(a[3], b[3]) > max(a[1], b[1]))


def fact_check(item, fact, document_id, pages):
    """A shared page or matching scalar alone never establishes strict proof."""
    if item.get('document_id') != document_id or item.get('page_number') != fact['source_page']:
        return False
    candidates = item.get('table_evidence', []) + item.get('numeric_evidence', [])
    exact = [candidate for candidate in candidates if all(
        compact(candidate.get(key)) == compact(fact[key])
        for key in ('metric', 'period', 'scope', 'unit', 'value', 'value_status', 'estimate_version')
        if key in fact and fact[key] is not None)]
    if not exact:
        return False
    page = pages.get(fact['source_page'])
    if page is None:
        return None
    for candidate in exact:
        spans = candidate.get('source_spans', [])
        if not spans or not all(isinstance(span.get('char_start'), int)
            and isinstance(span.get('char_end'), int)
            and 0 <= span['char_start'] < span['char_end'] <= len(page['final_text'])
            and page['final_text'][span['char_start']:span['char_end']] == span.get('quote')
            and span.get('bbox') for span in spans):
            continue
        if all(proof['page'] == fact['source_page'] and any(
            compact(proof['quote']) == compact(span['quote'])
            and overlaps(proof['bbox_pdf_points'], span['bbox']) for span in spans)
            for proof in fact['proof']):
            return True
    # Token splitting/geometry differences require original-PDF review, never PASS.
    return None


def score_case(prediction, gold, pages):
    expected_hold = not gold.get('facts') and gold.get('expected_response') == '확인할 수 없습니다'
    status = prediction['status']
    search = prediction.get('search') or {}
    facts = gold.get('facts', [])
    pack = search.get('evidence_pack') or []
    checks = [next((True for item in pack if fact_check(item, fact, gold['document_id'], pages) is True),
        None if any(fact_check(item, fact, gold['document_id'], pages) is None for item in pack) else False)
        for fact in facts]
    strict = bool(facts) and all(check is True for check in checks)
    complete = status == 'COMPLETE' or search.get('coverage_complete') is True
    verdict = ('ERROR' if status == 'ERROR' else 'HOLD' if status == 'HOLD'
        else 'PASS' if strict and not expected_hold else 'REVIEW')
    return {'id': prediction['id'], 'verdict': verdict,
        'coverage_completeness': strict and search.get('coverage_complete') is True,
        'source_page_accuracy': [any(item.get('document_id') == gold['document_id']
            and item.get('page_number') == fact['source_page'] for item in pack) for fact in facts],
        'scope_unit_correctness': [any(any(all(compact(candidate.get(key)) == compact(fact[key])
            for key in ('metric', 'period', 'value', 'scope', 'unit'))
            for candidate in item.get('table_evidence', [])+item.get('numeric_evidence', []))
            for item in pack) for fact in facts],
        'correct': (expected_hold if verdict == 'HOLD' else strict if verdict == 'PASS' else False),
        'hold_correct': status == 'HOLD' and expected_hold,
        'false_hold': status == 'HOLD' and not expected_hold,
        'false_complete': bool(complete and (expected_hold or not strict)),
        'factual_correctness': 'NOT_VERIFIED', 'answer_hold': 'NOT_VERIFIED',
        'citation_accuracy': checks, 'strict_evidence_validity': strict,
        'review_required': verdict == 'REVIEW', 'manual_accepted': False,
        'retrieval_proof_at_5': [any(fact_check(item, fact, gold['document_id'], pages) is True
            for item in search.get('results', [])[:5]) for fact in facts]}


def score_run(run, manifest_path):
    from scripts.verify_sealed_holdout import ROOT, verify, digest
    from .ledger import verify_artifacts, exclusive_json
    manifest = verify(manifest_path)
    verify_artifacts(run)
    metadata = json.loads((run/'run.json').read_text())
    if metadata['manifest_sha256'] != digest(manifest_path):
        raise ValueError('Prediction manifest mismatch')
    bundle = ROOT/manifest['bundle_path']
    # These are the only semantic label reads, exclusively in the scoring process.
    gold = json.loads((bundle/'gold.json').read_text())
    policy = json.loads((bundle/'criteria.json').read_text())
    predictions = {item['id']: item for path in (run/'predictions').glob('*.prediction.json')
        for item in [json.loads(path.read_text())]}
    if len(gold) != policy['counts']['total_cases'] or len({g['question_id'] for g in gold}) != len(gold):
        raise ValueError('Gold inventory mismatch')
    if set(predictions) != {g['question_id'] for g in gold}:
        raise ValueError('Prediction inventory mismatch; failures must have ERROR records')
    results = []
    inputs = json.loads((run/'predictions/input.json').read_text())
    document_hashes = {d['document_id']: d['sha256'] for d in inputs['documents']}
    for case in gold:
        if case['source_sha256'] != document_hashes.get(case['document_id']):
            raise ValueError('Gold/prediction source fingerprint mismatch')
        path = run/'predictions'/(case['document_id']+'-pages.json')
        pages = {p['page_number']: p for p in json.loads(path.read_text())} if path.exists() else {}
        results.append(score_case(predictions[case['question_id']], case, pages))
    holds = sum(p['status'] == 'HOLD' for p in predictions.values())
    correct_holds = sum(r['hold_correct'] for r in results)
    report = {'schema_version': 1, 'run_id': metadata['run_id'], 'phase': 'retrieval_evidence',
        'policy_sha256': manifest['criteria_sha256'], 'fixed_denominators': policy['counts'],
        'results': results, 'false_complete': sum(r['false_complete'] for r in results),
        'false_hold': sum(r['false_hold'] for r in results),
        'hold_precision': [correct_holds, holds] if holds else None,
        'hold_recall': [correct_holds, policy['counts']['expected_hold']],
        'errors': sum(r['verdict'] == 'ERROR' for r in results),
        'reviews': sum(r['review_required'] for r in results),
        'answer_metrics': 'NOT_VERIFIED', 'manual_accepted': 0,
        'coverage_completeness': [sum(r['coverage_completeness'] for r in results), policy['counts']['answerable']],
        'strict_evidence_validity': [sum(r['strict_evidence_validity'] for r in results), policy['counts']['answerable']],
        'source_page_accuracy': [sum(sum(r['source_page_accuracy']) for r in results), policy['counts']['factual_units']],
        'scope_unit_correctness': [sum(sum(r['scope_unit_correctness']) for r in results), policy['counts']['factual_units']],
        'retrieval_evidence_recall_at_5': [sum(sum(r['retrieval_proof_at_5']) for r in results), policy['counts']['factual_units']]}
    exclusive_json(run/'scoring.json', report)
    exclusive_json(run/'scoring.sha256.json', {'scoring.json': digest(run/'scoring.json')})


if __name__ == '__main__':
    cli = argparse.ArgumentParser()
    cli.add_argument('--schema-only', type=Path)
    cli.add_argument('--run-dir', type=Path)
    cli.add_argument('--manifest', type=Path)
    args = cli.parse_args()
    if args.schema_only:
        print(json.dumps(schema_only(args.schema_only), ensure_ascii=False))
    elif args.run_dir and args.manifest:
        score_run(args.run_dir.resolve(), args.manifest)
    else:
        cli.error('Require --run-dir and --manifest')
