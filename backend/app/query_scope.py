"""Explicit reporting scope, grounded in query literals and context membership."""
import re

# Bounded reporting vocabulary; individual/separate accounts share one scope.
TOKEN = re.compile(r'(?<![A-Za-z가-힣])(?:연결|별도|개별|consolidated|separate|standalone|국내|해외|domestic|overseas)(?![A-Za-z가-힣])', re.I)
ALIASES = {'연결': 'consolidated', 'consolidated': 'consolidated',
           '별도': 'separate', '개별': 'separate', 'separate': 'separate', 'standalone': 'separate', '국내':'domestic','domestic':'domestic',
           '해외':'overseas','overseas':'overseas'}
DIMENSION={'consolidated':'reporting','separate':'reporting','domestic':'region','overseas':'region'}


def query_scope(text):
    proofs = [dict(char_start=m.start(), char_end=m.end(), quote=m.group(),
                   scope=ALIASES[m.group().casefold()]) for m in TOKEN.finditer(text)]
    scopes = {p['scope'] for p in proofs}
    ambiguous = len({DIMENSION[s] for s in scopes}) != len(scopes)
    ordered = sorted(scopes, key=lambda s: (0 if DIMENSION[s]=='reporting' else 1, s))
    return dict(scope='/'.join(ordered) if scopes and not ambiguous else None,
                scope_proof=proofs, scope_ambiguous=ambiguous)


def source_memberships(page, table, rows):
    from .structured_cells import context_membership, row_groups
    from .unit_validation import unit_candidates
    from .page_layout import area, overlap
    from .extraction_provenance import trusted_page_span
    words = page.extraction.provenance.get('selected_words', [])
    scope_words = [w for w in words if TOKEN.search(w['text'])
        and overlap(table['bbox'], w['bbox']) / max(1, area(w['bbox'])) > .8]
    if not scope_words:
        return {}
    groups = row_groups(table)
    candidates = []
    for row in rows:
        span = row['raw_span']
        owners = [g for g in groups if overlap(g['cell']['bbox'], span['bbox']) / max(1, area(span['bbox'])) > .8]
        if len(owners) != 1 or owners[0]['rejection_reason'] == 'merged_row_membership_unverified':
            continue
        observed = [w for w in words if w['source'] == span['source'] and
            overlap(owners[0]['cell']['bbox'], w['bbox']) / max(1, area(w['bbox'])) > .8]
        if any(u['char_start'] <= span['char_start'] and span['char_end'] <= u['char_end']
               for u in unit_candidates(page.final_text, observed)):
            continue
        candidates.append(span)
    proofs = {}
    for cell in table['cells']:
        box = cell['bbox']
        literal_words = [w for w in scope_words if candidates and w['source'] == candidates[0]['source']
            and overlap(box, w['bbox']) / max(1, area(w['bbox'])) > .8]
        if not query_scope(' '.join(w['text'] for w in literal_words))['scope']:
            continue
        membership = context_membership(page.final_text, words, cell, candidates, [table])
        if not membership['approved'] or any(not trusted_page_span(page, s['char_start'], s['char_end'])
                                             for s in membership['context_spans']):
            continue
        parsed = query_scope(' '.join(s['quote'] for s in membership['context_spans']))
        if not parsed['scope'] or parsed['scope_ambiguous']:
            continue
        for member in membership['members']:
            span = member['metric_span']
            if box[2] > span['bbox'][0]:
                continue
            proofs.setdefault(span['char_start'], []).append(dict(scope=parsed['scope'],
                membership={**membership, 'metric_ownership_id': member['metric_ownership_id']}))
    return {start: candidates[0] for start, candidates in proofs.items() if len(candidates) == 1}


def _membership_identity(membership):
    if not membership:
        return None
    return {**membership, 'members': [{**m, 'metric_span': {k: m['metric_span'].get(k)
        for k in ('char_start', 'char_end', 'quote', 'bbox', 'source')}}
        for m in membership.get('members', [])]}


def scope_selection(requirement, fact):
    """Self-consistency here; publication rederives identity from the source page."""
    expected = query_scope(requirement.get('clause', ''))
    if any(requirement.get(k) != v for k, v in expected.items()):
        return False, 'query_scope_proof_invalid'
    if expected['scope_ambiguous']:
        return False, 'query_scope_ambiguous'
    if fact.get('scope_binding'):
        from .scope_binding import selection
        return selection(requirement, fact)
    identity = fact.get('metric_identity') or {}
    rows = identity.get('scope_metrics', [])
    compact = lambda s: re.sub(r'\s+', '', str(s or '')).casefold()
    label = compact(identity.get('canonical_label') or fact.get('metric'))
    candidates = [r for r in rows if compact(r['candidate_label']) == label]
    if not expected['scope']:
        return (False, 'metric_scope_ambiguous') if len(candidates) > 1 else (True, 'matched')
    source = identity.get('source_scope')
    if not source:
        return False, 'source_scope_unverified'
    membership = source['membership']
    ownership = fact.get('metric_context_ownership') or {}
    if (not ownership.get('approved') or _membership_identity(ownership.get('context_membership')) != _membership_identity(membership)
            or ownership.get('ownership_id') != membership.get('metric_ownership_id')):
        return False, 'source_scope_membership_invalid'
    if source['scope'] != expected['scope']:
        return False, 'metric_scope_mismatch'
    # Unknown competing membership cannot safely be assigned to another scope.
    if any(not r.get('source_scope') for r in candidates):
        return False, 'source_scope_unverified'
    selected = [r for r in candidates if r['source_scope']['scope'] == expected['scope']]
    if len(selected) != 1:
        return False, 'metric_scope_ambiguous'
    if selected[0]['raw_span'] != identity.get('raw_span'):
        return False, 'source_scope_membership_invalid'
    return True, 'matched'
