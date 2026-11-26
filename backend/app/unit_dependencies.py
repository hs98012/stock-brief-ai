"""Source components of an already verified semantic unit; no unit dictionary."""
from copy import deepcopy
import hashlib
import json

from .page_layout import area, overlap


def unit_dependency(fact, audit, text, words):
    if not audit.get('approved') or not audit.get('unit_span'):
        return None
    span = audit['unit_span']
    start, end = span['char_start'], span['char_end']
    if text[start:end] != audit['unit_surface']:
        return None
    contributors = sorted([w for w in words if w.get('source') == span['source']
        and w.get('char_start', -1) < end and w.get('char_end', -1) > start],
        key=lambda w: (w['char_start'], w['char_end']))
    association = audit['unit_association']
    cell = association.get('unit_cell')
    owner = fact.get('metric_context_ownership') or {}
    if owner and not owner.get('approved'):
        return None
    membership = owner.get('context_membership') or {}
    binding = dict(page_number=fact.get('page_number'), table_id=fact.get('table_id'),
        row_id=fact.get('row_id'), row_group_id=fact.get('row_group_id'),
        ownership_id=owner.get('ownership_id'), context_id=membership.get('context_id'),
        cell_id=([cell['row'], cell['column']] if cell else None),
        source=span['source'], char_start=start, char_end=end)
    identity = dict(binding)
    # Verified header declarations may serve several metric rows, as allowed by
    # verified-dependencies-v1. Their source unit has one identity; each group's
    # binding still records its independently verified metric owner.
    if audit.get('unit_source') == 'column_header':
        for key in ('row_id', 'row_group_id', 'ownership_id', 'context_id'):
            identity.pop(key)
    proof_id = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    components = []
    cursor = start
    for word in contributors:
        a, b = max(start, word['char_start']), min(end, word['char_end'])
        # Overlapping observations imply ambiguous membership, even when their
        # strings/bboxes agree. Whitespace gaps are typography, not components.
        if a < cursor or text[cursor:a].strip() or text[word['char_start']:word['char_end']] != word['text']:
            return None
        if not word.get('bbox') or (cell and overlap(cell['bbox'], word['bbox']) / max(1, area(word['bbox'])) <= .8):
            return None
        for key in ('ownership_id', 'table_id', 'row_id', 'row_group_id', 'context_id'):
            if key in word and word[key] != binding[key]:
                return None
        if 'unit_primitive_id' in word and word['unit_primitive_id'] != proof_id:
            return None
        if 'cell_id' in word and word['cell_id'] != binding['cell_id']:
            return None
        components.append(dict(role='unit_component', char_start=a, char_end=b,
            quote=text[a:b], bbox=deepcopy(word['bbox']), source=word['source'],
            source_span=dict(char_start=word['char_start'], char_end=word['char_end'],
                quote=word['text'], bbox=deepcopy(word['bbox'])),
            **{k: v for k, v in binding.items() if k not in {'source', 'char_start', 'char_end'}},
            unit_primitive_id=proof_id, component_index=len(components)))
        cursor = b
    if not components or text[cursor:end].strip():
        return None
    proof = dict(contract='semantic-unit-components-v1', unit_primitive_id=proof_id,
        kind='atomic' if len(components) == 1 else 'composite',
        raw_text=audit['unit_surface'], canonical_unit=audit['canonical_unit'],
        span=deepcopy(span), binding=binding, association=deepcopy(association),
        components=components)
    if 'unit_dependency' in fact and fact['unit_dependency'] != proof:
        return None
    return proof


def unit_is_covered(page, chunks, proof):
    """Search text cannot stand in for any required original source component."""
    from .evidence_integrity import span_is_covered
    spans = [proof['span'], *proof['components']]
    return all(span_is_covered(page, [c for c in chunks if c.char_start < s['char_end']
        and c.char_end > s['char_start']], s['char_start'], s['char_end'], s['quote']) for s in spans)
