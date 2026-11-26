"""Checks for additive new-upload metadata. Legacy pages keep their exact behavior."""
import hashlib
import re
from .layout_tables import UNIT_TOKEN, status


def extraction_matches_page(page):
    observation = getattr(page, 'extraction', None)
    return observation is None or observation.final_text_sha256 == hashlib.sha256(page.final_text.encode()).hexdigest()


def trusted_page_span(page, start, end):
    observation = getattr(page, 'extraction', None)
    if observation is None:
        return True
    return extraction_matches_page(page) and not any(start < s['char_end'] and end > s['char_start']
        for s in observation.provenance.get('unsafe_spans', []))


def validated_stored_facts(page, *, unit_audit=None):
    from .verification_cache import active, fingerprint, memoized, object_fingerprint
    observation = getattr(page, 'extraction', None)
    if unit_audit is not None or observation is None or not active():
        return _validated_stored_facts(page, unit_audit=unit_audit)
    scalars = (str(getattr(page, 'document_id', None)), str(getattr(page, 'id', None)), page.page_number,
        observation.final_text_sha256, observation.parser_version)
    key = object_fingerprint(page,
        (page, page.final_text, observation, observation.provenance, observation.table_facts),
        (*scalars, len(observation.provenance), len(observation.table_facts)),
        lambda: fingerprint([scalars[0], scalars[1], page.page_number, page.final_text, observation.final_text_sha256,
            observation.parser_version, observation.provenance, observation.table_facts]))
    return memoized('stored_facts', key, lambda: _validated_stored_facts(page))


def _validated_stored_facts(page, *, unit_audit=None):
    observation = getattr(page, 'extraction', None)
    if observation is None or not extraction_matches_page(page):
        return []
    words = observation.provenance.get('selected_words', [])
    facts = []
    derived = None
    if observation.parser_version.startswith('fact-fusion-'):
        from .layout_tables import extract_layout_facts
        from .native_tables import extract_native_facts
        streams={}
        for word in words:
            key=(word['source'],word.get('ocr_stream',str(word.get('ocr_psm',6))))
            streams.setdefault(key,[]).append(word)
        derived=[]
        for stream in streams.values():
            derived.extend(extract_layout_facts(page.final_text,stream,page.page_number,
                                                observation.provenance.get('unsafe_spans',[])))
        derived.extend(extract_native_facts(page.final_text,words,
            observation.provenance.get('native_tables',[]),page.page_number))
        from .paddle_tables import extract_paddle_facts
        derived.extend(extract_paddle_facts(page.final_text,words,
            observation.provenance.get('paddle_tables',[]),page.page_number))
        from .spatial_tables import extract_spatial_facts
        derived.extend(extract_spatial_facts(page.final_text,words,page.page_number))
        from .structured_cells import extract_cell_facts
        from .fact_fusion import PARSER_VERSION
        derived.extend(extract_cell_facts(page.final_text,words,
            observation.provenance.get('native_tables',[]) + observation.provenance.get('paddle_tables',[]),
            page.page_number, scope_contract=observation.parser_version == PARSER_VERSION))
    for fact in observation.table_facts:
        from .scope_binding import namespace_valid
        if not namespace_valid(fact,page):
            continue
        if fact.get('document_id') is not None and str(fact['document_id']) != str(getattr(page, 'document_id', None)):
            continue
        from .unit_validation import validate_unit
        tables = observation.provenance.get('native_tables', []) + observation.provenance.get('paddle_tables', [])
        audit = validate_unit(fact, page.final_text, words,
            () if fact.get('cell_geometry', {}).get('mode') == 'vertical' or
                  fact.get('verification') in {'coordinate_aligned', 'spatial_multilevel_grid'} else tables)
        if unit_audit is not None:
            unit_audit.append(dict(metric=fact.get('metric'), period=fact.get('period'),
                value=fact.get('value'), selected_unit=fact.get('unit'), **audit))
        if not audit['approved']:
            continue
        from .fact_fusion import PARSER_VERSION
        if (fact.get('processing_version') == PARSER_VERSION and
                fact.get('cell_geometry',{}).get('mode') != 'cell'):
            from .query_scope import TOKEN
            bounds=audit.get('unit_association',{}).get('table_bbox')
            if any(t['bbox']==bounds and any(TOKEN.search(c.get('text',''))
                   for c in t['cells']) for t in tables):
                continue
        if derived is not None:
            fields=('row_label','metric','period','column_name','unit','value','status')
            signature=lambda f:sorted((s['role'],s['char_start'],s['char_end']) for s in f['source_spans'])
            if not any(all(candidate.get(k)==fact.get(k) for k in fields)
                       and signature(candidate)==signature(fact) for candidate in derived):
                continue
        if fact.get('page_number') != page.page_number or fact.get('processing_version') != observation.parser_version:
            continue
        groups = {}
        good = True
        for span in fact.get('source_spans', []):
            a,b = span.get('char_start',-1),span.get('char_end',-1)
            if not (0<=a<b<=len(page.final_text)) or page.final_text[a:b] != span.get('quote') or not trusted_page_span(page,a,b):
                good = False
                break
            matching = [w for w in words if w['char_start']==a and w['char_end']==b and w['text']==span['quote']
                        and w['bbox']==span.get('bbox') and w['source']==span.get('source')]
            if len(matching)!=1:
                from .unit_validation import located
                located_span = located(page.final_text,
                    [w for w in words if w['source'] == span.get('source')], a, b)
                if span['role'] not in {'unit', 'value', 'comparison_unit', 'comparison_value'} or not located_span or located_span['bbox'] != span.get('bbox'):
                    good = False
                    break
                contributors = [w for w in words if w['source'] == span.get('source')
                                and w['char_start'] < b and w['char_end'] > a]
                matching = [{**contributors[0], 'confidence': min(w.get('confidence', 0) for w in contributors)}]
            word = matching[0]
            threshold = 80 if span['role'] in ('value','columns') else 65
            if word['source']!='native' and word['confidence'] < threshold and not word.get('confirmed_exact'):
                good = False
                break
            groups.setdefault(span['role'],[]).append(span['quote'])
        if not good or not {'row','metric','columns','unit','value'} <= groups.keys():
            continue
        if groups['value'] != [fact['value']] or groups['columns'] != [fact['column_name']]:
            continue
        spatial = fact.get('verification') == 'spatial_multilevel_grid'
        structured = fact.get('verification') == 'structured_primitive_cell'
        if fact['period'] is not None and fact['period'] != fact['column_name'] and not (spatial or structured):
            continue
        unit_match = UNIT_TOKEN.fullmatch(''.join(groups['unit']).strip('()[] '))
        expected_unit = '%' if fact['value'].endswith('%') else unit_match.group(1) if unit_match else None
        if fact['status'] != status(fact['period']):
            continue
        if structured:
            from .structured_cells import cell_fact_valid
            if not cell_fact_valid(fact,page.final_text,words,
                observation.provenance.get('native_tables',[]) + observation.provenance.get('paddle_tables',[]),
                derived=derived):
                continue
        elif spatial:
            from .spatial_tables import spatial_fact_valid
            if not spatial_fact_valid(fact):
                continue
        elif fact['unit'] != expected_unit:
            continue
        if re.sub(r'^[-•·ㆍ“]\s*','',' '.join(groups['row'])) != fact['row_label'] or ' '.join(groups['metric']) != fact['metric']:
            continue
        facts.append(fact)
    return facts
