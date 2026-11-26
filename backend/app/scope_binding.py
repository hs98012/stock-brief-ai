"""Literal scope owners and explicit structural inheritance; no default scope."""
from copy import deepcopy
from hashlib import sha256
import re

CONTRACT = 'source-owned-scope-v1'


def scope_literal(text):
    from .query_scope import query_scope, TOKEN
    parsed = query_scope(text)
    residual = TOKEN.sub('', text)
    return bool(parsed['scope'] and not parsed['scope_ambiguous'] and
                re.fullmatch(r'[\s():\[\]기준부문사업]*', residual))


def _declarations(text, words, table, source):
    from .unit_validation import located, _cells
    from .query_scope import query_scope, TOKEN
    from .structured_cells import row_groups, metric_type
    groups=row_groups(table)
    group_map={id(g['cell']):g for g in groups}
    tokens={id(c):[] for c in table['cells']}
    for word in words:
        if word['source']!=source:continue
        owners=_cells(word,table)
        if len(owners)==1:tokens[id(owners[0])].append(word)
    owned_groups={group_map[id(c)]['row_group_id'] for c in table['cells']
        if any(metric_type(w['text']) is not None and not scope_literal(w['text'])
               for w in tokens[id(c)])}
    result = []
    for cell in table['cells']:
        observed=tokens[id(cell)]
        scopes = [w for w in observed if scope_literal(w['text'])]
        if not scopes and not TOKEN.search(cell.get('text','')):continue
        group=group_map[id(cell)]
        row_owned=bool(group['row_group_id'] and group['row_group_id'] in owned_groups)
        for w in scopes:
            span = located(text, [v for v in words if v['source'] == source], w['char_start'], w['char_end'])
            if not span:
                continue
            result.append(dict(scope=query_scope(w['text'])['scope'], cell=cell, span=span,row_owned=row_owned))
        # A recognized declaration with missing/unsafe source proof is not absent.
        if TOKEN.search(cell.get('text', '')) and not scopes:
            result.append(dict(scope=None,cell=cell,span=None,row_owned=row_owned))
    return result


def _path(declarations):
    from .query_scope import DIMENSION
    if any(not d['scope'] or '/' in d['scope'] for d in declarations):
        return None
    if len({DIMENSION[d['scope']] for d in declarations}) != len(declarations):
        return None
    return [d['scope'] for d in declarations]


def bind(fact, text, words, tables):
    from .unit_validation import _cells
    from .structured_cells import row_groups
    if not fact.get('unit_binding', {}).get('approved') or not fact.get('period_binding', {}).get('approved'):
        return None
    spans = fact['source_spans']
    metric = [s for s in spans if s['role'] == 'metric']
    value = [s for s in spans if s['role'] == 'value']
    if len(metric) != 1 or len(value) != 1:
        return None
    matches = []
    for table in tables:
        if table['bbox'] != fact['context_bbox']:
            continue
        mc, vc = _cells(metric[0], table), _cells(value[0], table)
        if len(mc) != 1 or len(vc) != 1 or mc[0]['row'] != vc[0]['row']:
            continue
        mc, vc = mc[0], vc[0]
        declarations = _declarations(text, words, table, metric[0]['source'])
        existing_owner=fact.get('metric_context_ownership') or {}
        def member(d):
            from .query_scope import query_scope
            parsed=query_scope(' '.join(s['quote'] for s in existing_owner.get('context_membership',{}).get('context_spans',[])))
            return bool(parsed['scope']==d['scope'] and not parsed['scope_ambiguous'] and existing_owner.get('approved') and existing_owner.get('context_bbox')==d['cell']['bbox']
                and existing_owner.get('ownership_id') == existing_owner.get('context_membership',{}).get('metric_ownership_id'))
        local = [d for d in declarations if member(d) or d['cell'] is mc or
            d['cell']['column'] < mc['column'] and d['cell']['row'] <= mc['row'] <
            d['cell']['row']+d['cell'].get('rowspan',1) and
            d['cell']['bbox'][1] <= metric[0]['bbox'][1] and metric[0]['bbox'][3] <= d['cell']['bbox'][3]]
        sections = [d for d in declarations if d['cell']['column'] == 0 and
            d['cell'].get('colspan',1) == table['column_count'] and d['cell'].get('rowspan',1) == 1]
        prior = [d for d in sections if d['cell']['row'] < mc['row']]
        if prior:
            boundary = max(d['cell']['row'] for d in prior)
            local.extend(d for d in prior if d['cell']['row'] == boundary)
        # An intervening section boundary is literal topology, not proximity.
        local = list({(d['cell']['row'],d['cell']['column'],
                       d['span']['char_start'] if d['span'] else None):d for d in local}.values())
        local.sort(key=lambda d:(d['cell']['column'],d['cell']['row']))
        path = _path(local)
        if path is None:
            continue
        edges=[]
        valid=True
        for parent,child in zip(local,local[1:]):
            a,b=parent['cell'],child['cell']
            section = parent in sections
            nested = (a['column']+a.get('colspan',1) == b['column'] and
                a['row'] <= b['row'] and b['row']+b.get('rowspan',1) <= a['row']+a.get('rowspan',1)
                and a['bbox'][2] == b['bbox'][0] and a['bbox'][1] <= b['bbox'][1]
                and b['bbox'][3] <= a['bbox'][3])
            if not (section or nested):
                valid=False;break
            edges.append(dict(parent=deepcopy(parent),child=deepcopy(child),
                relationship='section_member' if section else 'nested_rowspan'))
        if not valid:
            continue
        groups=row_groups(table)
        for declaration in local:
            cell=declaration['cell']
            if declaration in sections:
                if (cell['bbox'][0] != table['bbox'][0] or cell['bbox'][2] != table['bbox'][2]
                        or cell['bbox'][3] > mc['bbox'][1]):valid=False
            elif cell is not mc:
                if (cell['bbox'][2] > mc['bbox'][0] or cell['column'] >= mc['column']):valid=False
                if cell.get('rowspan',1)==1:
                    group=next(g for g in groups if g['cell'] is cell)
                    if not member(declaration) and (group['rejection_reason'] or group['row_group_id'] != fact.get('row_group_id')):valid=False
                # The innermost context must prove independent metric membership.
                if declaration is local[-1] and cell.get('rowspan',1)>1:
                    owner=fact.get('metric_context_ownership') or {}
                    if not owner.get('approved') or owner.get('context_bbox') != cell['bbox']:valid=False
        if not valid:
            continue
        # Scope declarations on another value/header column cannot silently be
        # treated as unscoped facts within this same observed metric row.
        foreign=[d for d in declarations if d not in local and d not in sections and
            (d['cell']['row'] <= mc['row'] < d['cell']['row']+d['cell'].get('rowspan',1) or
             d['cell']['column'] < mc['column'] and d['cell']['bbox'][1] <= metric[0]['bbox'][1]
             and metric[0]['bbox'][3] <= d['cell']['bbox'][3])]
        # Native tables may omit rowspan while retaining a bounded context box.
        # Reuse independent membership proof to certify that an earlier context ended.
        from .structured_cells import context_membership, metric_type
        from .unit_validation import located
        metric_candidates=[located(text,words,w['char_start'],w['char_end']) for w in words
            if w['source']==metric[0]['source'] and metric_type(w['text']) is not None
            and not scope_literal(w['text'])]
        metric_candidates=[s for s in metric_candidates if s]
        expired=[]
        for d in declarations:
            if d in local or d in sections or not d['span']:continue
            if d['cell']['bbox'][3] > mc['bbox'][1]:continue
            membership=context_membership(text,words,d['cell'],metric_candidates,[table])
            if membership['approved']:
                expired.append(dict(declaration=deepcopy(d),membership=membership))
        orphan=[d for d in declarations if d not in local and d not in sections
            and d['cell']['row'] < mc['row'] and not d['row_owned']
            and d['cell'].get('rowspan',1)==1
            and not any(e['declaration']==d for e in expired)]
        if foreign or orphan:
            continue
        section_interval=None
        if prior:
            start=max(d['cell']['row'] for d in prior)
            following=[d for d in sections if d['cell']['row']>start]
            end=min(d['cell']['row'] for d in following) if following else table['row_count']
            boundary=[d for d in following if d['cell']['row']==end]
            if len(boundary)>1 or any(not d['span'] for d in boundary):
                continue
            section_interval=dict(start_row=start,end_row=end,
                boundary_span=deepcopy(boundary[0]['span']) if boundary else None)
        mode = ('unscoped' if not local else 'parent_child' if len(local)>1 else
                'row' if local[0]['cell'] is mc else 'section' if local[0] in sections else
                'merged_context' if local[0]['cell'].get('rowspan',1)>1 or member(local[0])
                and existing_owner.get('context_membership',{}).get('status')=='shared_metric_context_verified' else 'scope_column')
        identity=dict(source=metric[0]['source'],table_id=fact['table_id'],row_id=fact['row_id'],
            row_group_id=fact.get('row_group_id'),metric_span=metric[0])
        owner=fact.get('metric_context_ownership') or {}
        ownership_id=owner.get('ownership_id') or sha256(repr(identity).encode()).hexdigest()
        matches.append(dict(contract=CONTRACT,approved=True,scope='/'.join(path) if path else None,
            path=path,mode=mode,source_text_sha256=sha256(text.encode()).hexdigest(),
            page_number=fact['page_number'],table_id=fact['table_id'],table_bbox=deepcopy(table['bbox']),
            row_id=fact['row_id'],row_group_id=fact.get('row_group_id'),
            column_id=fact['column_id'],context_id=owner.get('context_membership',{}).get('context_id') or sha256(repr(local).encode()).hexdigest(),
            context_membership=deepcopy(owner.get('context_membership')),
            ownership_id=ownership_id,metric_span=deepcopy(metric[0]),value_span=deepcopy(value[0]),
            metric_cell=deepcopy(mc),value_cell=deepcopy(vc),
            declarations=deepcopy(local),parent_child=edges,section_interval=section_interval,
            expired_contexts=expired,
            period_binding=deepcopy(fact['period_binding']),unit_binding=deepcopy(fact['unit_binding'])))
    return matches[0] if len(matches)==1 else None


def source_spans(fact):
    proof=fact.get('scope_binding',{})
    spans=[{**d['span'],'role':'scope'} for d in proof.get('declarations',[])]
    spans += [{**e['declaration']['span'],'role':'scope_boundary'} for e in proof.get('expired_contexts',[])]
    boundary=(proof.get('section_interval') or {}).get('boundary_span')
    return [*spans, *([{**boundary,'role':'scope_boundary'}] if boundary else [])]


def selection(requirement, fact):
    from .query_scope import query_scope
    expected=query_scope(requirement.get('clause',''))
    if any(requirement.get(k)!=v for k,v in expected.items()) or expected['scope_ambiguous']:
        return False,'query_scope_proof_invalid'
    proof=fact['scope_binding']
    if not proof.get('approved'):
        return False,'source_scope_unverified'
    wanted=(expected['scope'] or '').split('/') if expected['scope'] else []
    def matches(path):return all(s in path for s in wanted)
    rows=proof.get('metric_candidates',[])
    identity=fact.get('metric_identity') or {}
    canonical={r['raw_span']['char_start']:r['candidate_label'] for r in identity.get('scope_metrics',[])}
    label=re.sub(r'\s+','',identity.get('canonical_label') or fact['metric']).casefold()
    relevant=[r for r in rows if re.sub(r'\s+','',canonical.get(r['raw_span']['char_start'],r['metric'])).casefold()==label]
    if any(not r.get('approved') for r in relevant):
        return False,'source_scope_unverified'
    if not wanted:
        if len({tuple(r['path']) for r in relevant})>1:
            return False,'metric_scope_ambiguous'
    elif not matches(proof['path']):
        return False,'metric_scope_mismatch'
    selected=[r for r in relevant if matches(r['path'])]
    if len({r['row_id'] for r in selected}) != 1:
        return False,'metric_scope_ambiguous'
    if any(not r.get('approved') for r in selected):
        return False,'source_scope_unverified'
    leaves=fact.get('comparison_derivation',{}).get('primitive_cells',[])
    if any(p.get('scope_binding',{}).get('path') != proof['path'] for p in leaves):
        return False,'cross_scope_contamination'
    return True,'matched'


def enrich(facts, text, words, tables, page_number):
    from types import SimpleNamespace as NS
    from .metric_annotations import _rows
    from .fact_fusion import PARSER_VERSION
    result=[]
    for fact in facts:
        if fact.get('cell_geometry',{}).get('mode') != 'cell':
            result.append(fact);continue
        proof=bind(fact,text,words,tables)
        if proof is not None:
            result.append({**fact,'scope_binding':proof})
    for fact in result:
        proof=fact.get('scope_binding')
        if not proof:continue
        table=next(t for t in tables if t['bbox']==proof['table_bbox'])
        page=NS(final_text=text,extraction=NS(parser_version=PARSER_VERSION,final_text_sha256=sha256(text.encode()).hexdigest(),
            provenance=dict(selected_words=words,unsafe_spans=[])))
        rows=_rows(page,table,proof['metric_span']['source'])
        candidates=[]
        for row in rows:
            peers=[f for f in result if f.get('table_id')==fact['table_id'] and
                f.get('metric_span',{}).get('char_start')==row['raw_span']['char_start']]
            peer=peers[0] if peers else None
            # Canonical annotations remain independently governed by their
            # existing source-note validator; never strip a suffix here.
            label=re.sub(r'\s+','',row['raw_label']).casefold()
            candidates.append(dict(metric=label,row_id=peer['row_id'] if peer else
                sha256(repr(row['raw_span']).encode()).hexdigest(),
                path=peer['scope_binding']['path'] if peer else [],approved=bool(peer),
                raw_span=deepcopy(row['raw_span'])))
        proof['metric_candidates']=candidates
    return result



def namespace_valid(fact, page):
    namespace=fact.get('scope_binding',{}).get('namespace')
    if namespace is None:
        return True  # Stored extraction proof is completed by its owning page.
    return namespace == dict(document_id=str(getattr(page,'document_id',None)),
                             page_id=str(getattr(page,'id',None)))


def with_namespace(fact, page):
    if not fact.get('scope_binding'):
        return fact
    result=deepcopy(fact)
    result['scope_binding']['namespace']=dict(document_id=str(getattr(page,'document_id',None)),
                                              page_id=str(getattr(page,'id',None)))
    return result
