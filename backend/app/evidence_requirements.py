"""Literal selection requirements; never infer missing source facts."""
import re

PERIOD = re.compile(r'(?<![A-Za-z0-9])(?:FY20\d{2}[FEAP]?|[1-4]Q\d{2}[FEAP]?|20\d{2}[FEAP]?)(?![A-Za-z0-9])', re.I)
UNIT = re.compile(r'million\s*USD|USD|십\s*억\s*원|백\s*만\s*원|조\s*원|억\s*원|천\s*원|백만달러|달러|%|원')
ROOTS = ('영업이익', '당기순이익', '순이익', '매출액', '매출', '보험손익',
         '지분가치', 'EBITDA', 'EPS', 'BPS', '배당', '리스크인수', '가치',
         r'(?:영업|투자|재무)활동(?:으로\s*인한\s*|\s*)현금흐름')
METRIC = re.compile(r'(?:' + '|'.join(ROOTS) + r')(?:\s*(?:증가율|성장률|감소율|률|율))?', re.I)
MONEY = {'millionusd', 'usd', '십억원', '백만원', '조원', '억원', '천원', '원', '백만달러', '달러'}


def compact(value):
    return re.sub(r'\s+', '', str(value or '')).casefold()


def metric_form(surface):
    value = compact(surface)
    modifier = 'amount'
    for suffix in ('증가율', '성장률', '감소율'):
        if value.endswith(suffix):
            value, modifier = value[:-len(suffix)], suffix
            break
    else:
        if value.endswith(('률', '율')):
            value, modifier = value[:-1], 'ratio'
    value = {'매출': '매출액', '당기순이익': '순이익'}.get(value, value)
    return {'surface': surface, 'normalized': value, 'modifier': modifier,
            'is_rate': modifier != 'amount', 'is_growth': modifier in {'증가율', '성장률', '감소율'}}


def period_form(value):
    # Whitespace/case/year particles are typographic; FY, quarter and suffix stay literal.
    return compact(value).removesuffix('년').upper()


def comparison_target(clause):
    if re.search(r'컨센서스|시장\s*(?:기대치|예상치|추정치)', clause):
        return 'consensus'
    if re.search(r'기존\s*추정치|\bOld\b', clause, re.I):
        return 'old'
    if re.search(r'전년\s*(?:동기\s*)?대비|\bYoY\b', clause, re.I):
        return 'yoy'
    if re.search(r'전분기\s*대비|\bQoQ\b', clause, re.I):
        return 'qoq'
    return None


def table_requirements(clause, *, kind='table'):
    from .query_scope import query_scope, TOKEN
    scope = query_scope(clause)
    mentions = list(METRIC.finditer(clause))
    periods = [period_form(m.group()) for m in PERIOD.finditer(clause)]
    comparison = comparison_target(clause)
    # A two-period comparison requires a literal target, never a fabricated cell.
    relative = bool(re.search(r'비교|대비', clause))
    period_pair = list(dict.fromkeys(periods)) if comparison is None and relative and len(set(periods)) == 2 else []
    if not mentions:
        return [{'id': 'structured_1', 'kind': kind, 'metric': None,
                 'period': periods[0] if len(periods) == 1 else None,
                 'period_required': bool(periods), 'numeric_value_required': True,
                 'comparison_required': bool(comparison or relative),
                 'comparison_target': comparison, 'unit': None, 'unit_family': None,
                 'entity': None, 'clause': clause, **scope}]
    requirements = []
    for mention in mentions:
        metric = metric_form(mention.group())
        prefix = clause[:mention.start()]
        period_mentions = list(PERIOD.finditer(prefix))
        if period_mentions:
            prefix = prefix[period_mentions[-1].end():]
            # Keep the year suffix attached to its date, rather than treating
            # it as part of the following business/metric row requirement.
            if re.fullmatch(r'20\d{2}', period_mentions[-1].group()):
                prefix = re.sub(r'^년\s*', '', prefix)
        prefix = TOKEN.sub('', prefix)
        prefix = re.sub(r'\d+\s*페이지|표\s*\d*(?:에서|의)?', '', prefix).strip(' ·:')
        prefix = re.sub(r'^\s*기준\s*', '', prefix)
        entity = prefix if prefix and not re.fullmatch(r'와|과|및|그리고', prefix) else None
        tail = clause[mention.end():]
        explicit_unit = next((compact(m.group()) for m in UNIT.finditer(tail)
            if re.match(r'\s*(?:단위|으로|로|기준)', tail[m.end():])
            or tail[:m.start()].rstrip().endswith('(') and tail[m.end():].lstrip().startswith(')')), None)
        # Periods are all mandatory, not interchangeable choices. Clause-local
        # scopes prevent a narrative forecast from supplying a table's date.
        for period in dict.fromkeys(periods or [None]):
            requirements.append({'id': f'structured_{len(requirements)+1}', 'kind': kind,
                'metric': metric, 'period': period, 'period_required': period is not None,
                'requested_periods': period_pair or ([period] if period else []), 'unit': explicit_unit,
                'unit_family': 'ratio' if metric['is_rate'] else 'money',
                'numeric_value_required': True, 'comparison_required': bool(comparison or relative),
                'comparison_target': next((p for p in period_pair if p != period), comparison),
                'entity': entity, 'clause': clause, **scope})
    return requirements


def fact_requirement_match(requirement, fact):
    checks = []
    def check(component, required, matched, reason):
        checks.append({'component': component, 'required': required,
                       'matched': bool(matched), 'reason': 'matched' if matched else reason})
    wanted = requirement.get('metric')
    from .metric_annotations import query_label
    from .query_scope import scope_selection
    scope_valid, scope_reason = scope_selection(requirement, fact)
    if not scope_valid or requirement.get('scope') or requirement.get('scope_ambiguous'):
        check('reporting_scope', True, scope_valid, scope_reason)
    label, identity_valid = query_label(fact, requirement)
    actual = metric_form(label)
    if fact.get('metric_identity'):
        identity = fact['metric_identity']
        identity_valid = identity_valid and bool(wanted) and metric_form(wanted.get('surface', '')) == wanted
        check('metric_annotation', True, identity_valid, identity.get('rejection_reason') or 'metric_annotation_unverified')
        check('canonical_metric', True, wanted and compact(label) == compact(wanted.get('surface')), 'canonical_metric_mismatch')
    check('metric', True, identity_valid and wanted and actual['normalized'] == wanted['normalized']
          and actual['modifier'] == wanted['modifier'], 'metric_mismatch' if wanted else 'metric_unspecified')
    entity = requirement.get('entity')
    observed_subject=(fact.get('row_subject') if fact.get('verification') in {'structured_primitive_cell', 'primitive_graph_comparison'}
                      and any(s.get('role')=='row_subject' and s.get('quote')==fact.get('row_subject')
                              for s in fact.get('source_spans',[])) else None)
    check('entity', bool(entity), not entity or compact(fact.get('row_label')) == compact(entity)
          or bool(observed_subject) and compact(observed_subject)==compact(entity),
          'entity_mismatch')
    check('period', requirement.get('period_required', False),
          not requirement.get('period_required') or period_form(fact.get('period')) == requirement['period'],
          'period_mismatch')
    unit, family = compact(fact.get('unit')), requirement.get('unit_family')
    unit_valid = (unit == requirement['unit'] if requirement.get('unit') else
                  unit == '%' if family == 'ratio' else unit in MONEY if family == 'money' else bool(unit))
    check('unit', True, unit_valid, 'unit_mismatch')
    if 'canonical_unit' in fact or 'unit_surface' in fact:
        check('unit_surface', True,
              compact(fact.get('canonical_unit')) == unit == compact(fact.get('unit_surface'))
              and bool(fact.get('value_span')) and bool(fact.get('unit_span'))
              and fact.get('unit_source') in {'same_cell', 'same_row', 'column_header'}
              and bool(fact.get('unit_association')), 'unit_association_unverified')
    check('value', requirement.get('numeric_value_required', True),
          bool(re.fullmatch(r'[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?%?', str(fact.get('value') or ''))),
          'numeric_value_missing')
    target = requirement.get('comparison_target')
    comparison = fact.get('comparison_cell') or {}
    label = compact(comparison.get('label'))
    target_valid = (label in {'컨센서스', '시장예상치', '시장기대치', '시장추정치'} if target == 'consensus' else
                    label in {'old', '기존', '기존추정치'} if target == 'old' else
                    label in {'yoy', '전년대비', '전년동기대비'} if target == 'yoy' else
                    label in {'qoq', '전분기대비'} if target == 'qoq' else
                    bool(target) and period_form(comparison.get('period')) == target)
    comparison_valid = (bool(comparison) and target_valid and compact(comparison.get('unit')) == unit
        and bool(re.fullmatch(r'[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?%?', str(comparison.get('value') or '')))
        and bool(comparison.get('source_spans'))
        and (target not in {'consensus', 'old'} or period_form(comparison.get('period')) == period_form(fact.get('period'))))
    ownership = fact.get('metric_context_ownership') or {}
    membership = ownership.get('context_membership') or {}
    if membership.get('status') == 'shared_metric_context_verified':
        # Include literal sibling candidates even when their downstream chains
        # were rejected; surviving values do not make a row label unique.
        semantic_rows = {r['raw_span']['char_start']: r for r in fact.get('metric_identity', {}).get('scope_metrics', [])}
        candidates = [metric_form(semantic_rows.get(m['metric_span']['char_start'], {}).get('canonical_label',
            m['metric_span']['quote'])) for m in membership.get('members', [])]
        matching_rows = [m for m in candidates if wanted and
            m['normalized'] == wanted['normalized'] and m['modifier'] == wanted['modifier']]
        check('metric_row', True, len(matching_rows) == 1,
              'shared_context_query_metric_ambiguous')
        owner = ownership.get('ownership_id')
        primitives = fact.get('comparison_derivation', {}).get('primitive_cells', [])
        chain_valid = bool(owner and ownership.get('approved'))
        if comparison:
            chain_valid = chain_valid and len(primitives) == 2 and all(
                p.get('metric_context_ownership', {}).get('ownership_id') == owner
                and metric_form(p.get('metric', '')) == metric_form(fact.get('metric', '')) for p in primitives)
            peers = [p for p in primitives if p.get('cell_fact_id') == comparison.get('cell_fact_id')]
            chain_valid = chain_valid and len(peers) == 1 and all(
                peers[0].get(k) == comparison.get(k) for k in ('period', 'unit', 'value'))
        check('metric_chain', True, chain_valid, 'shared_context_metric_chain_ambiguous')
    check('comparison', requirement.get('comparison_required', False),
          not requirement.get('comparison_required') or comparison_valid, 'comparison_missing_or_mismatch')
    return all(c['matched'] for c in checks if c['required']), checks
