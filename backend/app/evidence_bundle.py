"""Conservative, document-scoped evidence packs for compound questions."""
import re

from .evidence_integrity import chunk_matches_page
from .extraction_provenance import extraction_matches_page, trusted_page_span
from .evidence_requirements import PERIOD, METRIC, table_requirements, fact_requirement_match, period_form

CAUSE = re.compile(r"이유|원인|배경|영향|근거|왜|기여")
TABLE = re.compile(r"표|수치|금액|실적치|추정치")
CONNECTOR = re.compile(r"그리고|함께|및|(?:이유|원인|배경|영향|근거)(?:와|과)\b|(?:와|과)\s+\S+표")
EXPLANATION = re.compile(r"영향|효과|때문|기여|등으로|따라|덕분|요인")
OUTCOME = re.compile(r"개선|증가|상승|감소|하락|확대|축소|둔화|회복|변화|악화|전망|예상")
STOPWORDS = {'페이지', '부문', '실적', '개선', '이유', '원인', '배경', '영향', '근거',
             '표', '수치', '금액', '함께', '알려줘', '설명해줘', '보고서', '영업이익'}


def requirements_for(question: str) -> list[dict]:
    """Scope explicit requirements to their own clauses, preserving literal dates."""
    cause = CAUSE.search(question)
    table = TABLE.search(question)
    if not (cause and table and PERIOD.search(question) and CONNECTOR.search(question)):
        return (table_requirements(question) if PERIOD.search(question)
                and (re.search(r'표(?:의|에서|\s|\d)', question) or '얼마' in question) else [])
    narrative_clause = question[:cause.start()]
    from .search import tokenize
    narrative_clause = PERIOD.sub('', re.sub(r'\d+\s*페이지', '', narrative_clause))
    factors = re.split(r'\s*(?:및|그리고)\s*|[·/]|\s+(?:와|과)\s+', narrative_clause)
    narratives = []
    for factor in factors:
        focus = []
        for term in tokenize(factor):
            for suffix in ('에서', '으로', '에게', '까지', '에', '와', '과', '을', '를', '은', '는', '이', '가', '의'):
                if term.endswith(suffix) and len(term) > len(suffix) + 1:
                    term = term[:-len(suffix)]
                    break
            if term not in STOPWORDS | {'년', '미친', '보고서'} and not term.isdigit():
                focus.append(term)
        if focus:
            narratives.append({'id': f'narrative_{len(narratives)+1}', 'kind': 'narrative',
                'focus_terms': focus, 'clause': factor,
                'financial_outcome_required': bool(re.search(r'실적|이익|매출', factor))})
    tail = re.sub(r'^(?:와|과)\s*', '', question[cause.end():])
    structured = table_requirements(tail, kind='table' if '표' in tail else 'numeric')
    return narratives + structured if narratives else []


def requirement_resolution(question: str) -> dict:
    """Parsing is separate from evidence verification; empty is never verified."""
    try:
        requirements = requirements_for(question)
        if (not requirements and PERIOD.search(question) and METRIC.search(question)
                and re.search(r'[?？]|알려|설명|수치|금액|단위', question)):
            requirements = table_requirements(question)
    except Exception:
        return {'status': 'requirement_generation_error', 'requirements': []}
    if requirements:
        # Unsupported extra clauses must not disappear behind a supported metric.
        unsupported = bool(re.search(r'직원|임직원|인원|주가|목표주가|시가총액|증감률', question))
        if CAUSE.search(question) and not any(r['kind'] == 'narrative' for r in requirements):
            unsupported = True
        status = 'unsupported_requirement' if unsupported else 'supported_requirement'
    elif METRIC.search(question) and re.search(r'[?？]|알려|얼마|수치|금액|단위', question) and not re.search(r'요약|전망|이유|원인|배경|근거|개선|증가|감소|긍정|부정', question):
        status = 'ambiguous_requirement'
    elif re.search(r'수익성|경쟁력|성장성', question) and not re.search(r'얼마|수치|금액|단위|[?？]', question):
        status = 'no_factual_requirement_applicable'
    elif METRIC.search(question) and not re.search(r'[?？]|알려|얼마|수치|금액|단위|설명', question):
        status = 'no_factual_requirement_applicable'
    elif PERIOD.search(question) or re.search(r'얼마|수치|금액|단위|직원|임직원|인원|주가', question):
        status = 'unsupported_requirement'
    elif re.search(r'호재|악재|요약|위험|전망|이유|원인|배경|근거|개선|부진', question):
        status = 'no_factual_requirement_applicable'
    else:
        # Topic-only requests have no explicit numeric contract. They still
        # pass the existing sentence, polarity and citation validators.
        status = 'no_factual_requirement_applicable'
    return {'status': status, 'requirements': requirements}


def _located(page, start: int, end: int) -> list[dict]:
    if not trusted_page_span(page, start, end) or not extraction_matches_page(page):
        return []
    observation = getattr(page, 'extraction', None)
    if observation is None:
        return []
    words = sorted((word for word in observation.provenance.get('selected_words', [])
                    if word['char_start'] < end and word['char_end'] > start),
                   key=lambda word: (word['char_start'], word['char_end']))
    cursor = start
    for word in words:
        a, b = word['char_start'], word['char_end']
        if (a < cursor and b <= cursor) or (a > cursor and page.final_text[cursor:a].strip()):
            return []
        if (not word.get('bbox') or len(word['bbox']) != 4 or
                page.final_text[a:b] != word.get('text') or
                word.get('source') not in {'native', 'native_text', 'native_table',
                                          'ocr_text', 'ocr_table', 'paddle_structure'}):
            return []
        cursor = max(cursor, b)
    if not words or (cursor < end and page.final_text[cursor:end].strip()):
        return []
    return [{'char_start': max(start, word['char_start']),
             'char_end': min(end, word['char_end']), 'bbox': word['bbox'],
             'source': word['source'],
             'quote': page.final_text[max(start, word['char_start']):min(end, word['char_end'])]}
            for word in words]


def _fact_spans(page, fact: dict, *, table: bool, requirement=None) -> list[dict]:
    if requirement is not None and not fact_requirement_match(requirement, fact)[0]:
        return []
    from .scope_binding import namespace_valid
    if not namespace_valid(fact,page):
        return []
    from .unit_validation import validate_unit
    observation = getattr(page, 'extraction', None)
    if observation is None:
        return []
    tables = observation.provenance.get('native_tables', []) + observation.provenance.get('paddle_tables', [])
    if not validate_unit(fact, page.final_text, observation.provenance.get('selected_words', []),
            tables if table and fact.get('verification') not in {'coordinate_aligned', 'spatial_multilevel_grid'}
            and fact.get('cell_geometry', {}).get('mode') != 'vertical' else ())['approved']:
        return []
    if fact.get('page_number') != page.page_number:
        return []
    if not table and fact.get('processing_version', '').startswith('fact-fusion-'):
        from .period_binding import numeric_binding_valid
        if not numeric_binding_valid(fact, page):
            return []
    from .metric_annotations import annotation_valid, annotation_spans
    if not annotation_valid(fact, page, requirement):
        return []
    spans = fact.get('source_spans') or []
    from .scope_binding import source_spans
    extra_spans = [*annotation_spans(fact), *source_spans(fact)]
    if extra_spans:
        spans = [*spans, *extra_spans]
    graph = table and fact.get('verification') == 'primitive_graph_comparison'
    structured = table and fact.get('verification') == 'structured_primitive_cell'
    if graph:
        from .primitive_graph import comparison_fact_valid
        if not comparison_fact_valid(fact, page):
            return []
    spatial = table and fact.get('verification') == 'spatial_multilevel_grid'
    if structured:
        from .structured_cells import cell_fact_valid
        observation = getattr(page, 'extraction', None)
        if observation is None or not cell_fact_valid(fact, page.final_text,
                observation.provenance.get('selected_words', []),
                observation.provenance.get('native_tables', []) + observation.provenance.get('paddle_tables', [])):
            return []
    if spatial:
        from .spatial_tables import spatial_fact_valid
        if not spatial_fact_valid(fact):
            return []
    if table and fact.get('verification') == 'coordinate_aligned':
        from .extraction_provenance import validated_stored_facts
        if not any(all(fact.get(k) == value for k, value in stored.items()
                       if k != 'source_chunk_ids') for stored in validated_stored_facts(page)):
            return []
    roles = {span.get('role') for span in spans}
    required = {'row', 'metric', 'columns', 'unit', 'value'} if table else {'metric', 'period', 'unit', 'value'}
    if spatial or structured or graph:
        required.add('period')
    if not required <= roles:
        return []
    by_role = {role: [span['quote'] for span in spans if span.get('role') == role]
               for role in required}
    compact = lambda value: re.sub(r'\s+', '', value).casefold()
    for role, key in (('value', 'value'), ('metric', 'metric'),
                      ('period' if spatial or structured or graph or not table else 'columns', 'period')):
        if compact(str(fact.get(key) or '')) not in [compact(value) for value in by_role[role]]:
            return []
    if (not any(compact(str(fact.get('unit') or '')) in compact(value) for value in by_role['unit'])
            or table and not any(compact(str(fact.get('row_label') or '')) in compact(value)
                                 for value in by_role['row'])):
        return []
    for span in spans:
        a, b = span.get('char_start'), span.get('char_end')
        if (not isinstance(a, int) or not isinstance(b, int) or not (0 <= a < b <= len(page.final_text))
                or page.final_text[a:b] != span.get('quote') or not span.get('bbox', span.get('boxes'))
                or not _located(page, a, b)):
            return []
    comparison = fact.get('comparison_cell')
    if comparison:
        comp_spans = comparison.get('source_spans') or []
        if not comp_spans or any(span not in spans for span in comp_spans):
            return []
        for key, role in (('label', 'comparison_columns'), ('value', 'comparison_value')):
            if not any(span.get('role') == role and compact(span['quote']) == compact(comparison.get(key))
                       for span in comp_spans):
                return []
        if compact(comparison.get('unit')) != compact(fact.get('unit')):
            return []
        if period_form(comparison.get('period')) != period_form(fact.get('period')) and not any(
                span.get('role') in {'comparison_period', 'comparison_columns'} and
                period_form(span['quote']) == period_form(comparison.get('period')) for span in comp_spans):
            return []
    return spans


def build_evidence_pack(question: str, requirements: list[dict], candidate_rows: list[tuple],
                        facts_by_chunk: dict, numeric_by_chunk: dict, *, limit: int = 5,
                        audit: dict | None = None) -> tuple[list[dict], bool]:
    """Choose proof-bearing sources independently of global top-k presentation."""
    # Bind scope proof to the submitted question, including parser-output tampering.
    from .query_scope import query_scope
    parsed = {r['id']: r for r in requirements_for(question) if r['kind'] != 'narrative'}
    for requirement in requirements:
        if requirement['kind'] == 'narrative':
            continue
        original = parsed.get(requirement['id'])
        if original is not None and query_scope(original['clause']) != query_scope(requirement.get('clause', '')):
            if audit is not None:
                audit.update(coverage=[], candidates=[dict(reason='query_scope_proof_invalid', matched=False)])
            return [], False
    if not requirements:
        return [], True
    by_document = {}
    for row in candidate_rows:
        by_document.setdefault(row[3].id, []).append(row)
    options = []
    for rows in by_document.values():
        detail = {}
        pack, complete = _pack_for_document(question, requirements, rows, facts_by_chunk,
                                           numeric_by_chunk, limit=limit, audit=detail)
        options.append((pack, complete, detail))
    if not options:
        if audit is not None:
            audit.update(coverage=[{'requirement_id': r['id'], 'matched': False,
                                   'evidence_id': None, 'reason': 'no_candidates'} for r in requirements],
                         candidates=[])
        return [], False
    chosen = max(options, key=lambda option: (option[1], len(option[0]),
        -sum(item['global_rank'] for item in option[0])))
    if audit is not None:
        audit.update(chosen[2])
        audit['candidates'] = [c for option in options for c in option[2]['candidates']]
    return chosen[0], chosen[1]


def _pack_for_document(question, requirements, candidate_rows, facts_by_chunk,
                       numeric_by_chunk, *, limit, audit):
    selected = []
    trace, coverage = [], []
    for requirement in requirements:
        options = []
        for rank_data, chunk, page, document, global_rank in candidate_rows:
            chunk_id, _, bm25_rank, vector_rank = rank_data
            if not chunk_matches_page(chunk, page):
                continue
            base = {'requirement_id': requirement['id'], 'chunk_id': chunk_id,
                    'page_number': page.page_number, 'global_rank': global_rank,
                    'rrf_rank': global_rank if bm25_rank or vector_rank else None,
                    'bm25_rank': bm25_rank, 'vector_rank': vector_rank,
                    'rank_source': 'hybrid_rrf', 'quote': chunk.content,
                    'source_spans': []}
            if requirement['kind'] == 'narrative':
                text = chunk.content
                compact = re.sub(r'\s+', '', text).casefold()
                company_terms = {term.casefold() for term in re.findall(r'[가-힣]+|[A-Za-z]+', str(document.company_name or ''))}
                focus = [term for term in requirement['focus_terms'] if term not in company_terms]
                overlap = sum(term in compact for term in focus)
                lexical = bool(focus) and overlap == len(focus)
                financial = (not requirement.get('financial_outcome_required') or
                             re.search(r'실적|영업이익|순이익|매출|보험손익', text))
                from .analysis_retrieval import is_boilerplate
                spans = _located(page, chunk.char_start, chunk.char_end) if lexical else []
                checks = [{'component': key, 'required': required, 'matched': bool(value),
                           'reason': 'matched' if value else key + '_missing'}
                          for key, required, value in (
                              ('focus_terms', True, lexical),
                              ('financial_outcome', requirement.get('financial_outcome_required', False), financial),
                              ('explanation', True, EXPLANATION.search(text)),
                              ('outcome', True, OUTCOME.search(text)),
                              ('source_spans', True, spans),
                              ('non_boilerplate', True, not is_boilerplate(text)))]
                matched = all(c['matched'] for c in checks if c['required'])
                trace.append({'requirement_id': requirement['id'], 'evidence_id': str(chunk_id),
                              'page': page.page_number, 'matched': matched, 'checks': checks,
                              'reason': 'lexical_narrative_match' if matched else 'narrative_conditions_missing'})
                if not matched:
                    continue
                if spans:
                    options.append((overlap, -global_rank, {**base, 'source_spans': spans,
                        'requirement_checks': checks}))
            elif requirement['kind'] == 'table':
                for fact in facts_by_chunk.get(chunk_id, []):
                    matched, checks = fact_requirement_match(requirement, fact)
                    from .unit_validation import validate_unit
                    observation = getattr(page, 'extraction', None)
                    provenance = observation.provenance if observation is not None else {}
                    unit_audit = validate_unit(fact, page.final_text, provenance.get('selected_words', []),
                        () if fact.get('cell_geometry', {}).get('mode') == 'vertical' or
                              fact.get('verification') in {'coordinate_aligned', 'spatial_multilevel_grid'} else
                        provenance.get('native_tables', []) + provenance.get('paddle_tables', []))
                    spans = _fact_spans(page, fact, table=True, requirement=requirement) if matched else []
                    checks.append({'component': 'source_spans', 'required': True,
                                   'matched': bool(spans), 'reason': 'matched' if spans else
                                   'source_span_invalid' if matched else 'requirement_not_matched'})
                    trace.append({'requirement_id': requirement['id'], 'evidence_id': str(chunk_id),
                        'page': page.page_number, 'metric': fact.get('metric'), 'period': fact.get('period'),
                        'unit': fact.get('unit'), 'value': fact.get('value'), 'checks': checks,
                        'unit_validation': unit_audit,
                        'matched': bool(matched and spans),
                        'reason': 'matched' if matched and spans else 'source_span_invalid' if matched else 'requirement_mismatch'})
                    if not matched:
                        continue
                    if spans:
                        options.append((1, -global_rank, {**base, 'rank_source': 'verified_table',
                            'quote': fact['quote'], 'source_spans': spans, 'table_evidence': [fact],
                            'requirement_checks': checks}))
            elif requirement['kind'] == 'numeric':
                for fact in numeric_by_chunk.get(chunk_id, []):
                    matched, checks = fact_requirement_match(requirement, fact)
                    if not matched:
                        trace.append({'requirement_id': requirement['id'], 'evidence_id': str(chunk_id),
                                      'matched': False, 'checks': checks, 'reason': 'requirement_mismatch'})
                        continue
                    spans = _fact_spans(page, fact, table=False, requirement=requirement)
                    if spans:
                        options.append((1, -global_rank, {**base, 'rank_source': 'verified_numeric',
                            'quote': fact['quote'], 'source_spans': spans, 'numeric_evidence': [fact],
                            'requirement_checks': checks}))
        # Ranking cannot disambiguate two rows satisfying the same metric
        # requirement in one shared scope, even if their values happen to agree.
        context_owners = {}
        for _, _, item in options:
            for fact in item.get('table_evidence', []):
                proof = fact.get('metric_context_ownership') or {}
                membership = proof.get('context_membership') or {}
                if membership.get('status') == 'shared_metric_context_verified':
                    key = (item['page_number'], fact.get('table_id'), membership['context_id'])
                    context_owners.setdefault(key, set()).add(proof.get('ownership_id'))
        ambiguous = {key for key, owners in context_owners.items() if len(owners) != 1}
        if ambiguous:
            def ambiguous_context(item):
                return any((item['page_number'], f.get('table_id'),
                    f.get('metric_context_ownership', {}).get('context_membership', {}).get('context_id'))
                    in ambiguous for f in item.get('table_evidence', []))
            options = [option for option in options if not ambiguous_context(option[2])]
            trace.append(dict(requirement_id=requirement['id'], matched=False,
                              reason='shared_context_query_metric_ambiguous'))
        # Equivalent, fully verified cells may appear in both the discussion and
        # a repeated financial appendix. Prefer the existing narrative context
        # only for identical facts; never select a different value by proximity.
        def fact_key(item):
            facts = item.get('table_evidence') or []
            if not facts:
                return None
            fact = facts[0]
            comparison = fact.get('comparison_cell') or {}
            normalize = lambda value: re.sub(r'\s+', '', str(value or '')).casefold()
            return tuple(normalize(fact.get(key)) for key in ('metric', 'row_label', 'period', 'unit', 'value')) + tuple(
                normalize(comparison.get(key)) for key in ('label', 'period', 'unit', 'value'))
        narrative_pages = {item['page_number'] for item in selected if item['rank_source'] == 'hybrid_rrf'}
        equivalent_pages = {}
        for _, _, item in options:
            key = fact_key(item)
            if key is not None:
                equivalent_pages.setdefault(key, set()).add(item['page_number'])
        local_keys = {fact_key(item) for _, _, item in options if item['page_number'] in narrative_pages
                      and len(equivalent_pages.get(fact_key(item), set())) > 1}
        options.sort(key=lambda item: (-item[0],
            0 if fact_key(item[2]) in local_keys and item[2]['page_number'] in narrative_pages else 1,
            -item[1], str(item[2]['chunk_id'])))
        for _, _, item in options:
            if len(selected) >= min(limit, 5):
                break
            def cell_pair(candidate):
                facts = candidate.get('table_evidence') or []
                if len(requirement.get('requested_periods', [])) != 2 or not facts:
                    return None
                derivation = facts[0].get('comparison_derivation') or {}
                a, b = derivation.get('lhs'), derivation.get('rhs')
                return frozenset((a, b)) if a and b else None
            duplicate = next((old for old in selected if item['page_number'] == old['page_number']
                              and (cell_pair(item) is not None and cell_pair(item) == cell_pair(old) or
                              item['source_spans'] == old['source_spans']
                              and item.get('table_evidence') == old.get('table_evidence')
                              and item.get('numeric_evidence') == old.get('numeric_evidence')
                              and re.sub(r'\s+', '', item['quote']) == re.sub(r'\s+', '', old['quote']))), None)
            if duplicate:
                for fact in item.get('table_evidence', []):
                    if fact not in duplicate.get('table_evidence', []):
                        duplicate.setdefault('table_evidence', []).append(fact)
                duplicate['source_spans'] += [s for s in item['source_spans'] if s not in duplicate['source_spans']]
                duplicate.setdefault('requirement_ids', [duplicate['requirement_id']]).append(requirement['id'])
                duplicate.setdefault('requirement_matches', {})[requirement['id']] = item['requirement_checks']
                break
            selected.append(item)
            break
        item = next((i for i in selected if requirement['id'] in i.get('requirement_ids', [i['requirement_id']])), None)
        checks = (item.get('requirement_matches', {}).get(requirement['id'], item['requirement_checks']) if item else [])
        coverage.append({'requirement_id': requirement['id'], 'required': True,
            'matched': bool(item and all(c['matched'] for c in checks if c['required'])),
            'evidence_id': str(item['chunk_id']) if item else None,
            'reason': 'matched' if item else 'no_valid_candidate', 'checks': checks})
    audit.update(coverage=coverage, candidates=trace)
    return selected, bool(coverage) and all(result['matched'] for result in coverage)
