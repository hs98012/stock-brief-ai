"""Query-time comparisons over validated observed cells, never OCR correction."""
from copy import deepcopy
import re

from .evidence_requirements import compact, metric_form, period_form, fact_requirement_match
from .page_layout import overlap, area
from .structured_cells import unit_compatible


def period_identity(raw):
    token=period_form(raw)
    match=re.fullmatch(r'(FY)?(20\d{2})([AEFP])?',token)
    quarter=None;fiscal=False
    if match:
        fiscal=bool(match[1]);year=int(match[2]);qualifier=match[3]
    else:
        match=re.fullmatch(r'([1-4])Q(\d{2})([AEFP])?',token)
        if not match:return None
        quarter=int(match[1]);year=2000+int(match[2]);qualifier=match[3]
    return dict(raw=raw,year=year,quarter=quarter,fiscal=fiscal,qualifier=qualifier,
        status='actual' if qualifier=='A' else 'forecast' if qualifier in {'F','E'}
        else 'preliminary' if qualifier=='P' else 'unspecified')


def _period_key(raw):
    p=period_identity(raw)
    return (p['year'],p['quarter'],p['fiscal'],p['qualifier']) if p else None


def _primitive(fact):
    node=deepcopy(fact)
    node['comparison_cell']=None;node['comparison_basis']=None
    node.pop('comparison_derivation',None)
    node['source_spans']=[s for s in node['source_spans'] if not s['role'].startswith('comparison_')]
    return node


def _same_label(a,b):
    # IDs alone are not geometry proof. The same row needs exact label provenance
    # and overlapping observed label cells (or the shared vertical heading).
    if compact(a['row_label'])!=compact(b['row_label']):return False
    ag,bg=a['cell_geometry'],b['cell_geometry']
    if ag['mode']!=bg['mode']:return False
    rows_a=[s for s in a['source_spans'] if s['role']=='row']
    rows_b=[s for s in b['source_spans'] if s['role']=='row']
    if not rows_a or not rows_b:return False
    if ag['mode']=='vertical':
        return rows_a==rows_b
    if (a.get('row_group_id') or b.get('row_group_id')) and a.get('row_group_id') != b.get('row_group_id'):
        return False
    ownership_a = a.get('metric_context_ownership', {}).get('ownership_id')
    ownership_b = b.get('metric_context_ownership', {}).get('ownership_id')
    if (ownership_a or ownership_b) and ownership_a != ownership_b:
        return False
    membership_a = a.get('metric_context_ownership', {}).get('context_membership')
    membership_b = b.get('metric_context_ownership', {}).get('context_membership')
    if membership_a or membership_b:
        if (not membership_a or not membership_b or
                not membership_a.get('approved') or not membership_b.get('approved') or
                membership_a.get('context_id') != membership_b.get('context_id') or
                membership_a.get('metric_ownership_id') != membership_b.get('metric_ownership_id')):
            return False
    x,y=ag.get('label_cell'),bg.get('label_cell')
    if not x or not y or overlap(x,y)/max(1,min(area(x),area(y)))<.8:return False
    v,w=ag.get('value_cell'),bg.get('value_cell')
    if not v or not w:return False
    return max(0,min(v[3],w[3])-max(v[1],w[1]))/max(1,min(v[3]-v[1],w[3]-w[1]))>.8


def _facet(fact):
    header=fact.get('column_name')
    if _period_key(header):return ''
    # A validated chart may retain a literal short-year header plus a separate
    # full-year confirmation span. That alias is a date, not a New/Old facet.
    short=re.fullmatch(r"['’](\d{2})년",str(header or ''))
    period=period_identity(fact.get('period'))
    if (short and period and str(period['year']).endswith(short[1]) and
            any(s['role']=='period_confirmation' for s in fact['source_spans'])):return ''
    return compact(header)


def relation(a,b):
    same_metric=metric_form(a['metric'])['normalized']==metric_form(b['metric'])['normalized'] and (
        metric_form(a['metric'])['modifier']==metric_form(b['metric'])['modifier'])
    same_table=all(a.get(k)==b.get(k) and a.get(k) is not None
                   for k in ('document_id','page_number','table_id'))
    same_row=same_table and same_metric and _same_label(a,b)
    same_unit=bool(a.get('unit')) and a.get('unit')==b.get('unit')
    compatible=same_unit and unit_compatible(a['metric'],a['unit']) and unit_compatible(b['metric'],b['unit'])
    pa,pb=_period_key(a.get('period')),_period_key(b.get('period'))
    # New/Old, amount/ratio etc must stay in the same subcolumn facet.
    same_facet=_facet(a)==_facet(b)
    return dict(same_table=same_table,same_metric=same_metric,same_row=same_row,
        same_unit=same_unit,compatible_unit=compatible,same_column_facet=same_facet,
        distinct_periods=bool(pa and pb and pa!=pb),
        linkable=bool(same_row and compatible and same_facet and pa and pb and pa!=pb))


def primitive_graph(page):
    from .extraction_provenance import validated_stored_facts
    nodes={}
    for validated in validated_stored_facts(page):
        if validated.get('verification')!='structured_primitive_cell':continue
        # Strip legacy parser comparisons. Only this validated cell becomes a node;
        # do not import an unvalidated second cell from nested metadata.
        node=_primitive(validated)
        if (not all(node.get(k) for k in ('table_id','row_id','column_id','cell_fact_id','cell_geometry'))
                or not period_identity(node.get('period')) or not node.get('unit')):continue
        node['document_id']=getattr(page,'document_id',None)
        node['page_id']=getattr(page,'id',None)
        node['normalized_period']=period_identity(node['period'])
        nodes.setdefault(node['cell_fact_id'],node)
    from .metric_annotations import annotate_metric_facts
    ordered=annotate_metric_facts(page,sorted(nodes.values(),key=lambda f:(f['table_id'],f['cell_fact_id'])))
    edges=[];groups={}
    for node in ordered:
        metric=metric_form(node['metric'])
        key=(node['table_id'],metric['normalized'],metric['modifier'],compact(node['row_label']),node['unit'])
        groups.setdefault(key,[]).append(node)
    for group in groups.values():
      for i,a in enumerate(group):
        for b in group[i+1:]:
            rel=relation(a,b)
            if not rel['linkable']:continue
            low,high=sorted((a['cell_geometry'].get('column',0),b['cell_geometry'].get('column',0)))
            between=[n for n in group if low<n['cell_geometry'].get('column',0)<high
                     and relation(a,n)['same_row'] and relation(a,n)['same_column_facet']]
            edges.append(dict(lhs=a['cell_fact_id'],rhs=b['cell_fact_id'],
                              relations={**rel,'adjacent_period':not between}))
    return dict(nodes=ordered,edges=edges)


def _assemble(a,b,edge,periods):
    fact=deepcopy(a)
    mapping={'columns':'comparison_column_alias','period':'comparison_columns',
        'unit':'comparison_unit','value':'comparison_value','row':'comparison_row',
        'metric':'comparison_metric','row_subject':'comparison_row_subject'}
    spans=[{**s,'role':mapping.get(s['role'],'comparison_'+s['role'])} for s in b['source_spans']]
    fact['source_spans']+=spans
    fact['comparison_basis']=b['period']
    fact['comparison_cell']=dict(label=b['period'],period=b['period'],unit=b['unit'],value=b['value'],
        bbox=b['bbox'],source_spans=spans,table_id=b['table_id'],row_id=b['row_id'],
        column_id=b['column_id'],cell_fact_id=b['cell_fact_id'])
    fact['verification']='primitive_graph_comparison'
    fact['graph_comparison']=dict(lhs=a['cell_fact_id'],rhs=b['cell_fact_id'],
        requested_periods=periods,lhs_period=a['normalized_period'],rhs_period=b['normalized_period'],
        relations=edge['relations'])
    fact['comparison_derivation']=dict(operation='query_requested_period_pair',
        primitive_cells=[a,b],lhs=a['cell_fact_id'],rhs=b['cell_fact_id'])
    return fact


def comparison_candidates(page,requirements):
    requests=[r for r in requirements if r.get('kind')=='table' and r.get('comparison_required')
              and len(r.get('requested_periods',[]))==2]
    if not requests:return []
    graph=primitive_graph(page);nodes={n['cell_fact_id']:n for n in graph['nodes']};result=[];seen=set()
    for request in requests:
        periods=request['requested_periods']
        for edge in graph['edges']:
            for lhs,rhs in [(edge['lhs'],edge['rhs']),(edge['rhs'],edge['lhs'])]:
                a,b=nodes[lhs],nodes[rhs]
                if _period_key(a['period'])!=_period_key(request['period']):continue
                target=request.get('comparison_target')
                if _period_key(b['period'])!=_period_key(target):continue
                facets={_facet(n) for n in graph['nodes'] if relation(a,n)['same_row']
                        and _period_key(n['period']) in {_period_key(p) for p in periods}}
                if len(facets)>1 and (not _facet(a) or not re.search(
                    r'(?<![A-Za-z0-9])'+re.escape(_facet(a))+r'(?![A-Za-z0-9])',
                    compact(request.get('clause')))):
                    continue
                fact=_assemble(a,b,edge,periods)
                if fact_requirement_match(request,fact)[0] and (lhs,rhs) not in seen:
                    result.append(fact);seen.add((lhs,rhs))
    return result


def comparison_fact_valid(fact,page):
    comparison=fact.get('graph_comparison')
    if fact.get('verification')!='primitive_graph_comparison' or not comparison:return False
    graph=primitive_graph(page);nodes={n['cell_fact_id']:n for n in graph['nodes']}
    a,b=nodes.get(comparison.get('lhs')),nodes.get(comparison.get('rhs'))
    if a is None or b is None:return False
    periods=comparison.get('requested_periods') or []
    if len(periods)!=2 or {_period_key(p) for p in periods}!={_period_key(a['period']),_period_key(b['period'])}:return False
    edge=next((e for e in graph['edges'] if {e['lhs'],e['rhs']}=={a['cell_fact_id'],b['cell_fact_id']}),None)
    if edge is None:return False
    rebuilt=_assemble(a,b,edge,periods)
    return all(fact.get(k)==value for k,value in rebuilt.items() if k not in {'source_chunk_ids'})
