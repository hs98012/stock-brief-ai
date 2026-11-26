#!/usr/bin/env python3
"""Score pinned development evidence packs without invoking a generator."""
import argparse
import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path

from pinned_manifest import digest
from verify_pinned_shadow import score, validate_binding, _matches

ROOT = Path(__file__).resolve().parents[1]


def compact(value):
    return re.sub(r'\s+', '', str(value)).casefold()


def pack_proves(item, unit, revision, manifest):
    pages = {page['page_number']: page for page in revision['pages']}
    chunks = {str(chunk['id']): chunk for chunk in revision['chunks']}
    manifest_pages = {page['page_number']: page for page in manifest['pages']}
    number = unit['page_number']
    if number != item.get('page_number') or number not in pages or number not in manifest_pages:
        return False
    page = pages[number]
    manifest_page = manifest_pages[number]
    chunk = chunks.get(str(item['chunk_id']))
    if (not chunk or chunk['page_id'] != page['id'] or
            page['final_text'][chunk['char_start']:chunk['char_end']] != chunk['content'] or
            manifest_page['ocr_source'] != 'paddle' or manifest_page['fallback'] or
            page['provenance'].get('paddle_fingerprint_sha256') != manifest['worker_fingerprint']['sha256']):
        return False
    if item['rank_source'] == 'hybrid_rrf' and item['quote'] != chunk['content']:
        return False
    spans = item.get('source_spans') or []
    if not spans:
        return False
    for span in spans:
        start, end = span.get('char_start'), span.get('char_end')
        if (not isinstance(start, int) or not isinstance(end, int) or
                not (0 <= start < end <= len(page['final_text'])) or
                page['final_text'][start:end] != span.get('quote') or
                not span.get('bbox', span.get('boxes')) or
                (span.get('source') or span.get('sources')) not in ('paddle_structure', ['paddle_structure'])):
            return False
    if not all(compact(condition) in compact(item['quote'])
               for condition in unit.get('literal_conditions', [])):
        return False
    for kind in ('table', 'numeric'):
        expected = unit.get(kind)
        if not expected:
            continue
        expected_facts = expected if isinstance(expected, list) else [expected]
        actual = item.get(kind + '_evidence', [])
        if actual and item['quote'] not in [fact.get('quote') for fact in actual]:
            return False
        for gold in expected_facts:
            matches = [fact for fact in actual if _matches(fact, gold)]
            if not matches or not any(any(evidence['fact_sha256'] == digest({
                    key: value for key, value in fact.items() if key not in {'document_id', 'page_id'}})
                for evidence in manifest_page['evidence']) for fact in matches):
                return False
    return True


def evaluate(data, binding, baseline, baseline_binding, gold):
    validate_binding(data, binding)
    validate_binding(baseline, baseline_binding)
    before = score(baseline, baseline_binding, gold)
    original = score(data, binding, gold)
    if data['active_before'] != data['active_after'] or data['active_before'] != baseline['active_before']:
        raise ValueError('Active data hash changed')
    baseline_cases = {case['id']: case for case in baseline['cases']}
    cases = {case['id']: case for case in data['cases']}
    revisions = {revision['document_id']: (revision, manifest)
                 for revision, manifest in zip(data['revisions'], data['manifests'], strict=True)}
    compound_cases = {case_id for case_id, case in cases.items()
                      if {'narrative', 'table'} <= {r['kind'] for r in case['shadow'].get('requirements') or []}}
    regressions = []
    for case_id, case in cases.items():
        if case_id in compound_cases:
            continue
        old = baseline_cases[case_id]
        signature = lambda value: [(str(hit['chunk_id']), hit['quote'], hit['table_evidence'])
                                   for hit in value['shadow']['results']]
        if signature(case) != signature(old):
            regressions.append(case_id)
    if regressions:
        raise ValueError('Single-fact top-5 regression: ' + ', '.join(regressions))
    units = []
    grouped = defaultdict(list)
    for original_unit, gold_unit in zip(original['units'], gold['units'], strict=True):
        unit = dict(original_unit)
        if unit['case'] in compound_cases:
            case = cases[unit['case']]
            if case['scope'] != 'shadow_revision' or case['document_id'] not in revisions:
                raise ValueError('Compound case lacks a pinned shadow revision')
            revision, manifest = revisions[case['document_id']]
            pack = case['shadow'].get('evidence_pack') or []
            if len(pack) > 5:
                raise ValueError('Evidence pack exceeds five items')
            unit['hit'] = bool(case['shadow'].get('coverage_complete') and any(
                pack_proves(item, gold_unit, revision, manifest) for item in pack))
            grouped[unit['case']].append(unit['hit'])
        units.append(unit)
    candidate = [unit for unit in units if unit['scope'] == 'paddle_candidate']
    control = [unit for unit in units if unit['scope'] == 'active_control']
    covered = sum(all(hits) for hits in grouped.values())
    before_grouped = defaultdict(list)
    baseline_revisions = {revision['document_id']: (revision, manifest)
                          for revision, manifest in zip(baseline['revisions'], baseline['manifests'], strict=True)}
    for unit, gold_unit in zip(before['units'], gold['units'], strict=True):
        if unit['case'] in compound_cases:
            old_case = baseline_cases[unit['case']]
            old_search = old_case['shadow']
            hit = unit['hit']
            if old_search.get('evidence_pack') is not None:
                revision, manifest = baseline_revisions[old_case['document_id']]
                hit = bool(old_search.get('coverage_complete') and any(
                    pack_proves(item, gold_unit, revision, manifest)
                    for item in old_search['evidence_pack']))
            before_grouped[unit['case']].append(hit)
    complete = sum(bool(cases[case_id]['shadow'].get('coverage_complete')) for case_id in grouped)
    return {'classic_before': before['combined_comparison_recall@5'],
            'classic_after': original['combined_comparison_recall@5'],
            'paddle_candidate_recall@5': [sum(unit['hit'] for unit in candidate), len(candidate)],
            'invariant_control_recall@5': [sum(unit['hit'] for unit in control), len(control)],
            'combined_comparison_recall@5': [sum(unit['hit'] for unit in units), len(units)],
            'compound_evidence_coverage@5_before': [sum(all(hits) for hits in before_grouped.values()), len(grouped)],
            'compound_evidence_coverage@5_after': [covered, len(grouped)],
            'evidence_pack_complete_rate': [complete, len(grouped)],
            'single_fact_regression': regressions, 'units': units,
            'active_hash_unchanged': data['active_before'] == data['active_after'] == baseline['active_before'],
            'holdout_cases_sha256': hashlib.sha256((ROOT/'evals/holdout-cases.json').read_bytes()).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('artifact', type=Path)
    parser.add_argument('--binding', type=Path, required=True)
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--baseline-binding', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    data = json.loads(args.artifact.read_text())
    baseline = json.loads(args.baseline.read_text())
    metrics = evaluate(data, json.loads(args.binding.read_text()), baseline,
        json.loads(args.baseline_binding.read_text()),
        json.loads((ROOT/'evals/pinned-gold.json').read_text()))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x') as stream:
        json.dump(metrics, stream, ensure_ascii=False, indent=2)
    print(' '.join(f'{key}={value[0]}/{value[1]}' for key, value in metrics.items()
                   if key in {'paddle_candidate_recall@5','invariant_control_recall@5',
                              'combined_comparison_recall@5','compound_evidence_coverage@5_after'}))
    print('single_fact_regression=' + str(len(metrics['single_fact_regression'])))


if __name__ == '__main__':
    main()
