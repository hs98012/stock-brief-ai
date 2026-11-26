"""Versioned, source-preserving admission of verified primitive dependencies.

Physical chunks remain exact page slices. Groups reference those slices; only
one metric anchor per group exposes a separate search representation.
"""
from copy import deepcopy
import hashlib
import json
from types import SimpleNamespace as NS

from .extraction_provenance import validated_stored_facts
from .metric_annotations import annotation_spans, annotation_valid
from .primitive_graph import primitive_graph
from .query_scope import scope_selection

CONTRACT_VERSION = 'verified-dependencies-v1'


def _stored_candidates(page):
    obs = page.extraction
    archived = obs.provenance.get('primitive_cells', [])
    if not archived:
        return list(obs.table_facts)
    from .structured_cells import extract_cell_facts
    from .fact_fusion import PARSER_VERSION
    pro = obs.provenance
    derived = extract_cell_facts(page.final_text, pro.get('selected_words', []),
        pro.get('native_tables', []) + pro.get('paddle_tables', []), page.page_number,
        scope_contract=obs.parser_version == PARSER_VERSION)
    stripped = {'comparison_cell', 'comparison_basis', 'comparison_derivation'}
    # The archive intentionally omits parser comparison metadata. Restore only
    # an exact archived primitive preimage, then run all normal validators.
    def legacy_view(fact, record):
        # Old observations remain usable only through the same full source
        # rederivation; absence of additive metadata is never authority.
        result = {k: v for k, v in fact.items()
                  if k not in {'period_binding', 'unit_binding', 'scope_binding'} or k in record}
        if record.get('processing_version') == obs.parser_version:
            result['processing_version'] = obs.parser_version
        return result
    restored = [legacy_view(f, record) for f in derived for record in archived
        if record == {k: v for k, v in legacy_view(f, record).items() if k not in stripped}
        or record == legacy_view(f, record)]
    return [*obs.table_facts, *restored]


def dependency_groups(page):
    """Revalidate stored primitives; neither supplied IDs nor proximity authorize admission."""
    obs = page.extraction
    candidates = _stored_candidates(page)
    view = NS(id=getattr(page, 'id', None), document_id=getattr(page, 'document_id', None),
        page_number=page.page_number, final_text=page.final_text,
        extraction=NS(parser_version=obs.parser_version, final_text_sha256=obs.final_text_sha256,
                      provenance=obs.provenance, table_facts=candidates))
    graph = primitive_graph(view)
    groups = []
    for node in graph['nodes']:
        identity = node.get('metric_identity') or {}
        scope_binding = node.get('scope_binding') or {}
        source_scope = identity.get('source_scope')
        verified_scope = scope_binding.get('scope') if scope_binding else source_scope['scope'] if source_scope else None
        requirement = None
        if verified_scope:
            from .evidence_requirements import table_requirements
            literal = ' '.join(d['span']['quote'] for d in scope_binding['declarations']) if scope_binding else ' '.join(s['quote'] for s in source_scope['membership']['context_spans'])
            requirement = table_requirements(f"표의 {literal} {node['period']} {identity['canonical_label']} 값은 얼마인가?")[0]
            if not scope_selection(requirement, node)[0]:
                continue
        if not annotation_valid(node, view, requirement):
            continue
        ownership = node.get('metric_context_ownership') or {}
        if ownership and not ownership.get('approved'):
            continue
        # Strip parser comparison spans: each graph node proves exactly one cell.
        # A comparison is a union of these groups along already verified edges.
        from .scope_binding import source_spans
        spans = [*node['source_spans'], *annotation_spans(node), *source_spans(node)]
        from .unit_validation import validate_unit
        audit = validate_unit(node, page.final_text, obs.provenance.get('selected_words', []),
            () if node.get('cell_geometry', {}).get('mode') == 'vertical' else
            obs.provenance.get('native_tables', []) + obs.provenance.get('paddle_tables', []))
        if not audit['approved']:
            continue
        unit_proof = audit['unit_dependency']
        spans.extend(unit_proof['components'])
        if not {'metric', 'unit', 'period', 'value'} <= {s['role'] for s in spans}:
            continue
        key = dict(table_id=node['table_id'], row_id=node['row_id'],
            primitive_id=node['cell_fact_id'], ownership_id=ownership.get('ownership_id'),
            context_id=ownership.get('context_membership', {}).get('context_id'),
            scope=verified_scope,
            page_number=page.page_number)
        group_id = hashlib.sha256(json.dumps(key, sort_keys=True).encode()).hexdigest()
        context = ' '.join(s['quote'] for s in spans if s['role'] == 'metric_context')
        raw = node['metric']
        canonical = identity.get('canonical_label') or raw
        search_text = ' | '.join(filter(None, [context, raw,
            canonical if canonical != raw else '', node['unit'], f"{node['period']} {node['value']}"]))
        groups.append(dict(**key, group_id=group_id,
            anchor=dict(char_start=node['char_start'], char_end=node['char_end']),
            dependencies=deepcopy(spans), search_text=search_text,
            unit_dependency=deepcopy(unit_proof),
            period_binding=deepcopy(node.get('period_binding')),
            unit_binding=deepcopy(node.get('unit_binding')),
            scope_binding=deepcopy(node.get('scope_binding')),
            metric_raw=raw, metric_canonical=canonical, annotation=deepcopy(identity),
            ownership=deepcopy(ownership)))
    # A value source may have only one row/metric owner; shared headers, units,
    # contexts and footnotes can be referenced by several groups.
    owners = {}
    for group in groups:
        for span in group['dependencies']:
            if span['role'] != 'value':
                continue
            key = (span['char_start'], span['char_end'], span.get('source'))
            owners.setdefault(key, set()).add((group['table_id'], group['row_id'], group['ownership_id']))
    groups = [g for g in groups if all(len(owners[(s['char_start'], s['char_end'], s.get('source'))]) == 1
        for s in g['dependencies'] if s['role'] == 'value')]
    unit_owners = {}
    for group in groups:
        for span in group['unit_dependency']['components']:
            original = span['source_span']
            key = (original['char_start'], original['char_end'], span['source'])
            unit_owners.setdefault(key, set()).add(span['unit_primitive_id'])
    groups = [g for g in groups if all(len(unit_owners[(s['source_span']['char_start'],
        s['source_span']['char_end'], s['source'])]) == 1
        for s in g['unit_dependency']['components'])]
    return sorted({g['group_id']: g for g in groups}.values(), key=lambda g: g['group_id'])


def admit_dependencies(page):
    """Add a new extraction's minimum proof slices, idempotently; never touch source text."""
    obs = page.extraction
    groups = dependency_groups(page)
    segments = [s for s in obs.provenance.get('index_segments', [])
                if s.get('kind') != 'verified_dependency']
    references = {}
    for group in groups:
        for span in group['dependencies']:
            key = (span['char_start'], span['char_end'])
            entry = references.setdefault(key, dict(char_start=key[0], char_end=key[1],
                kind='verified_dependency', page_number=page.page_number,
                source=span.get('source'), bbox=span.get('bbox'), group_ids=[]))
            if group['group_id'] not in entry['group_ids']:
                entry['group_ids'].append(group['group_id'])
    obs.provenance.update(index_admission_contract=CONTRACT_VERSION,
        dependency_groups=groups, index_segments=segments + list(references.values()))
    # A verified primitive previously retained outside fusion now remains visible
    # to downstream fact validation too. No unvalidated or rejected node is added.
    ids = {g['primitive_id'] for g in groups}
    view = NS(page_number=page.page_number, final_text=page.final_text,
        extraction=NS(parser_version=obs.parser_version, final_text_sha256=obs.final_text_sha256,
            provenance=obs.provenance, table_facts=_stored_candidates(page)))
    seen = {f.get('cell_fact_id') for f in obs.table_facts}
    for fact in validated_stored_facts(view):
        if fact.get('cell_fact_id') in ids and fact['cell_fact_id'] not in seen:
            obs.table_facts.append(fact)
            seen.add(fact['cell_fact_id'])
    return groups
