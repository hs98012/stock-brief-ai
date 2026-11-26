#!/usr/bin/env python3
"""Fail-closed, cohort-separated scoring of a source-pinned shadow run."""
import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
from pinned_manifest import digest, file_hash, verify_manifest


def binding_for(data):
    return {'cases_sha256': file_hash(ROOT/'evals/audit-cases.json'),
            'gold_sha256': file_hash(ROOT/'evals/pinned-gold.json'),
            'evaluation_code': data['evaluation_code'],
            'revisions': [{
                'revision_id': m['revision_id'], 'manifest_sha256': m['sha256'],
                'worker_image_id': m['worker_image_id'],
                'pip_freeze_sha256': m['worker_fingerprint']['pip_freeze_sha256'],
                'model_files_sha256': digest(m['worker_fingerprint']['model_files']),
                'worker_fingerprint_sha256': m['worker_fingerprint']['sha256'],
                'parser_version': m['parser_version'], 'pdf_sha256': m['pdf_sha256']}
                for m in data['manifests']]}


def validate_binding(data, binding):
    if not data.get('manifests') or binding != binding_for(data):
        raise ValueError('Missing or changed worker/dependency/model/parser/input/review binding')
    if len(data['manifests']) != len(data['revisions']):
        raise ValueError('Revision manifest count mismatch')
    if not data.get('evaluation_code', {}).get('working_tree_diff_sha256'):
        raise ValueError('Evaluation code hash missing')
    source_hashes = {entry['sha256']: ROOT/'holdout-v1'/entry['filename']
                     for entry in json.loads((ROOT/'evals/audit-documents.json').read_text())}
    for revision, manifest in zip(data['revisions'], data['manifests'], strict=True):
        verify_manifest(revision, manifest)
        if (manifest['cases_sha256'] != file_hash(ROOT/'evals/audit-cases.json') or
                manifest['gold_sha256'] != file_hash(ROOT/'evals/pinned-gold.json')):
            raise ValueError('Evaluation inputs differ from pinned run')
        if manifest['pdf_sha256'] not in source_hashes or file_hash(source_hashes[manifest['pdf_sha256']]) != manifest['pdf_sha256']:
            raise ValueError('Original PDF differs from pinned run')
        fingerprint = manifest['worker_fingerprint']
        required = ('paddlepaddle_version','paddleocr_version','python_version',
                    'pip_freeze_sha256','model_files','model','options','sha256')
        if (not all(fingerprint.get(key) for key in required) or
                digest({key: value for key, value in fingerprint.items() if key != 'sha256'}) != fingerprint['sha256'] or
                not manifest.get('worker_image_id', '').startswith('sha256:') or
                not manifest.get('git_head') or not manifest.get('working_tree_diff_sha256')):
            raise ValueError('Incomplete Paddle execution provenance')
    if data['active_before'] != data['active_after']:
        raise ValueError('Active data changed')


def _compact(value):
    return re.sub(r'\s+', '', str(value))


def _matches(fact, expected):
    return all(_compact(fact.get(key)) == _compact(value) for key, value in expected.items())


def _paddle_proof(hit, page, gold, manifest_page, fingerprint_sha256):
    table_facts = ([fact for fact in hit['table_evidence'] if _matches(fact, gold['table'])]
                   if gold.get('table') else [])
    if gold.get('table') and not table_facts:
        return False
    numeric_facts = []
    for expected in gold.get('numeric', []):
        facts = [fact for fact in hit.get('numeric_evidence', []) if _matches(fact, expected)]
        if not facts:
            return False
        numeric_facts.extend(facts)
    if not all(_compact(token) in _compact(hit['quote'])
               for token in gold.get('literal_conditions', [])):
        return False
    if (manifest_page['ocr_source'] != 'paddle' or manifest_page['fallback'] or
            page['provenance'].get('paddle_fingerprint_sha256') != fingerprint_sha256):
        raise ValueError('Fallback/native evidence cannot count as Paddle')
    words = [word for word in page['provenance']['selected_words']
             if word['char_start'] < hit['chunk_char_end'] and word['char_end'] > hit['chunk_char_start']]
    if not words or any(word['source'] != 'paddle_structure' or not word.get('bbox') for word in words):
        raise ValueError('Candidate quote has non-Paddle or unpositioned text')
    if table_facts:
        for fact in table_facts:
            if fact['source'] != 'paddle_structure' or not fact['source_spans']:
                raise ValueError('Fallback table fact offered as Paddle')
            for span in fact['source_spans']:
                if span['source'] != 'paddle_structure' or not span.get('bbox'):
                    raise ValueError('Fallback table span offered as Paddle')
    for fact in numeric_facts:
        if fact['source'] != 'paddle_structure' or not fact.get('bbox'):
            raise ValueError('Fallback numeric fact offered as Paddle')
        for span in fact['source_spans']:
            if not span.get('boxes') or 'paddle_structure' not in span.get('sources', []):
                raise ValueError('Fallback numeric span offered as Paddle')
    return True


def score(data, binding, gold):
    validate_binding(data, binding)
    cases = {case['id']: case for case in data['cases']}
    revisions = {revision['document_id']: (revision, manifest)
                 for revision, manifest in zip(data['revisions'], data['manifests'], strict=True)}
    outcome = []
    for unit in gold['units']:
        case = cases[unit['case']]
        scope = unit['source_scope']
        if scope == 'active_control':
            if case['scope'] != 'unchanged_active_control' or case['shadow'] != case['active']:
                raise ValueError('Active control presented as Paddle candidate')
            hit = any(result['page_number'] == unit['page_number']
                for result in case['active']['results'])
        else:
            if case['scope'] != 'shadow_revision' or case['document_id'] not in revisions:
                raise ValueError('Paddle candidate is not a revision result')
            revision, manifest = revisions[case['document_id']]
            pages = {page['page_number']: page for page in revision['pages']}
            chunks = {str(chunk['id']): chunk for chunk in revision['chunks']}
            manifest_pages = {page['page_number']: page for page in manifest['pages']}
            hit = False
            for result in case['shadow']['results']:
                if result['rank'] > 5 or result['page_number'] != unit['page_number']:
                    continue
                page = pages[result['page_number']]
                chunk = chunks[str(result['chunk_id'])]
                if (chunk['page_id'] != page['id'] or
                        page['final_text'][chunk['char_start']:chunk['char_end']] != result['quote']):
                    raise ValueError('Quote/chunk/page integrity failure')
                if _paddle_proof(result, page, unit, manifest_pages[page['page_number']],
                                 manifest['worker_fingerprint']['sha256']):
                    hit = True
                    break
        outcome.append({'case': unit['case'], 'unit': unit['unit'], 'scope': scope, 'hit': hit})
    candidate = [unit for unit in outcome if unit['scope'] == 'paddle_candidate']
    control = [unit for unit in outcome if unit['scope'] == 'active_control']
    return {'paddle_candidate_recall@5': [sum(u['hit'] for u in candidate), len(candidate)],
            'invariant_control_recall@5': [sum(u['hit'] for u in control), len(control)],
            'combined_comparison_recall@5': [sum(u['hit'] for u in outcome), len(outcome)],
            'units': outcome}


def compare_runs(first, second):
    validate_binding(second, binding_for(first))
    if first['active_before'] != second['active_before']:
        raise ValueError('Active database snapshot differs between runs')
    def signature(case, key):
        return [(str(result['chunk_id']),result['page_number'],result['quote'],
                 result['table_evidence'],result.get('numeric_evidence', []))
                for result in case[key]['results']]
    for left, right in zip(first['cases'],second['cases'],strict=True):
        if (left['id'] != right['id'] or left['question'] != right['question'] or
                signature(left,'active') != signature(right,'active') or
                signature(left,'shadow') != signature(right,'shadow')):
            raise ValueError('Top-5 or evidence spans differ across pinned replays')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('artifact',type=Path)
    parser.add_argument('--binding',type=Path)
    parser.add_argument('--repeat',type=Path,action='append',default=[])
    args = parser.parse_args()
    data = json.loads(args.artifact.read_text())
    if args.binding is None:
        raise ValueError('A prospectively reviewed manifest binding is required')
    binding = json.loads(args.binding.read_text())
    gold = json.loads((ROOT/'evals/pinned-gold.json').read_text())
    result = score(data,binding,gold)
    for path in args.repeat:
        repeat = json.loads(path.read_text())
        compare_runs(data,repeat)
        if score(repeat,binding,gold) != result:
            raise ValueError('Pinned result changed on repeat')
    print(' '.join(f'{key}={value[0]}/{value[1]}' for key,value in result.items() if key != 'units'))
    print('failures='+','.join(unit['unit'] for unit in result['units'] if not unit['hit']))


if __name__ == '__main__':
    main()
