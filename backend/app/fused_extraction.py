"""Three independent extraction paths with per-candidate validation and fusion."""
import re
import fitz
from PIL import Image
from .fact_fusion import (PARSER_VERSION, reading_groups, serialize_groups, missing_regions,
                          box_of, safe_word, fuse_candidates, sentence_groups)
from .page_layout import area, overlap
from .layout_tables import extract_layout_facts
from .native_tables import observe_tables, topology_matches, extract_native_facts
from .models import TextSource
from .paddle_structure import extract_structure


def fact_source(source):
    return 'native_text' if source=='native' else 'paddle_structure' if source=='paddle_structure' else 'ocr_text'


def _numeric(text, words, segments, number):
    from .numeric_evidence import _METRIC, _VALUE
    period_re=re.compile(r'(?<!\d)(?:[1-4]Q\d{2}[FEAP]?|20\d{2}\s*년\s*[1-4]\s*분\s*기|[1-4]\s*분\s*기|20\d{2}[FEAP])(?![A-Za-z0-9])',re.I)
    facts=[]
    from .period_binding import sentence_segments, paragraph_binding, explicit_claim_gap
    for segment in sentence_segments(text, segments):
        a,b=segment['char_start'],segment['char_end'];quote=text[a:b]
        periods=list(period_re.finditer(quote));metrics=list(_METRIC.finditer(quote))
        if len(periods) != 1 or not metrics or len({re.sub(r'\s+', '', m.group()) for m in metrics}) != 1:continue
        if not explicit_claim_gap(quote[periods[0].end():metrics[0].start()]):continue
        basis_pattern=r'컨\s*센\s*서\s*스|시\s*장\s*(?:예\s*상\s*치|기\s*대\s*치)'
        values = list(_VALUE.finditer(quote))
        dates = list(re.finditer(r'20\d{2}|[1-4]\s*Q\s*\d{2}|\d{2}\s*년|[1-4]\s*분\s*기', quote, re.I))
        if any(not (periods[0].start() <= date.start() and date.end() <= periods[0].end())
               and not any(v.start() <= date.start() and date.end() <= v.end() for v in values)
               for date in dates):
            continue
        by_unit = {}
        for value in values:
            by_unit.setdefault(re.sub(r'\s+', '', value.group(2)), []).append(value)
        if any(not re.search(basis_pattern, quote[left.end():right.start()])
               for peers in by_unit.values() for left, right in zip(peers, peers[1:])):
            continue
        forecast=bool(re.search(r'예\s*상|전\s*망|추\s*정|Preview',quote,re.I))
        actual=bool(re.search(r'기\s*록|실\s*제|확\s*정|실\s*적\s*Review',quote,re.I))
        if forecast==actual:continue
        qualifier = re.search(r'[AEFP]$', re.sub(r'\s+', '', periods[0].group()), re.I)
        if qualifier and ((qualifier[0].upper() == 'A' and forecast)
                          or (qualifier[0].upper() in {'E', 'F'} and actual)
                          or qualifier[0].upper() == 'P'):
            continue
        for value in values:
            preceding=[m for m in metrics if m.end()<=value.start()]
            if not preceding:continue
            metric=preceding[-1]
            if not explicit_claim_gap(quote[metric.end():value.start()], prior_values=True):continue
            preceding_periods=[p for p in periods if p.end()<=metric.start()]
            if not preceding_periods:continue
            period=preceding_periods[-1]
            # Never inherit a metric/period across another sentence.
            if re.search(r'다\s*\.',quote[metric.end():value.start()]):continue
            roles=[('period',period.start(),period.end()),('metric',metric.start(),metric.end()),
                   ('value',value.start(1),value.end(1)),('unit',value.start(2),value.end(2))]
            spans=[];valid=True
            for role,start,end in roles:
                contributors=[w for w in words if w['char_start']<a+end and w['char_end']>a+start]
                if not contributors or not all(safe_word(w) for w in contributors):valid=False
                spans.append(dict(role=role,char_start=a+start,char_end=a+end,quote=quote[start:end],
                    boxes=[w['bbox'] for w in contributors],sources=sorted({w['source'] for w in contributors})))
            if not valid:continue
            between=list(re.finditer(basis_pattern,quote[metric.end():value.start()]))
            basis=between[-1] if between else None
            basis_offset=metric.end()
            if basis is None:
                prefix=quote[period.end():metric.start()]
                preceding=list(re.finditer(basis_pattern,prefix))
                if preceding and re.fullmatch(r'\s*[(:]?\s*',prefix[preceding[-1].end():]):
                    basis=preceding[-1];basis_offset=period.end()
            predicate=re.search(r'예\s*상|전\s*망|추\s*정|Preview' if forecast else
                                r'기\s*록|실\s*제|확\s*정|실\s*적\s*Review',quote,re.I)
            extras=[('status',predicate.start(),predicate.end())]
            if basis:
                offset=basis_offset
                extras.append(('basis',offset+basis.start(),offset+basis.end()))
            for role,start,end in extras:
                contributors=[w for w in words if w['char_start']<a+end and w['char_end']>a+start]
                if not contributors or not all(safe_word(w) for w in contributors):valid=False
                spans.append(dict(role=role,char_start=a+start,char_end=a+end,quote=quote[start:end],
                    boxes=[w['bbox'] for w in contributors],sources=sorted({w['source'] for w in contributors})))
            if not valid:continue
            # The quote is the literal metric/value fragment; period, basis and predicate
            # remain separate proofs, so unrelated low-quality prose is never a citation.
            start,end=a+metric.start(),a+value.end()
            contributing=[w for w in words if w['char_start']<end and w['char_end']>start]
            if not all(safe_word(w) for w in contributing):continue
            binding = paragraph_binding(text, number, segment, spans)
            if binding is None:continue
            facts.append(dict(period_binding=binding, kind='text_numeric',metric=re.sub(r'\s+','',metric.group()),
                period=re.sub(r'\s+','',period.group()),value=value.group(1),unit=re.sub(r'\s+','',value.group(2)),
                status='forecast' if forecast else 'actual',comparison_basis=re.sub(r'\s+','',basis.group()) if basis else None,
                page_number=number,char_start=start,char_end=end,quote=text[start:end],source_spans=spans,
                bbox=box_of([w for w in contributing if w['char_start']<a+value.end(1) and w['char_end']>a+value.start(1)]),
                claim_bbox=segment['bbox'],source=fact_source(segment['source']),
                confidence=min(w['confidence'] for w in contributing),processing_version=PARSER_VERSION))
    return facts


def extract_page(page, number, pdf_path, image_dir, *, force_ocr=False):
    from . import pdf_pipeline as pipeline
    raw_words=page.get_text('words',sort=False)
    native_preview=' '.join(w[4] for w in raw_words)
    native,metrics,reasons=pipeline.native_observation(page,native_preview)
    tables,table_errors=observe_tables(page,native)
    native_groups=reading_groups(native)
    native_text,native_positioned,_=serialize_groups(native_groups)
    recognized=[];image_path=ocr_error=ocr_text=None;regions=[];structure=None;paddle_error=None
    covered=[w['bbox'] for w in native if safe_word(w)]
    if force_ocr:reasons.append('explicit_inactive_audit')
    if table_errors or any(not any(c.get('text') for c in t.get('cells',[])) for t in tables):
        reasons.append('native_table_extraction_incomplete')
    if tables and not extract_native_facts(native_text,native_positioned,tables,number):
        reasons.append('native_table_relation_unverified')
    if len(native_groups)>1 and any(a[0]['bbox'][0]+80<b[0]['bbox'][0]
            for a,b in zip(native_groups,native_groups[1:]) if a and b):
        reasons.append('multiple_text_columns')
    if reasons:
        pix=page.get_pixmap(matrix=fitz.Matrix(1,1),colorspace=fitz.csGRAY,alpha=False)
        image=Image.frombytes('L',(pix.width,pix.height),pix.samples)
        regions=missing_regions(image,[list(fitz.Rect(b)*page.rotation_matrix) for b in covered])
        if force_ocr and not regions:
            regions=[[0,0,page.rect.width,page.rect.height]]
        try:
            structure=extract_structure(page)
            recognized=structure.words
            ocr_text='\n\n'.join(' '.join(w['text'] for w in g) for g in structure.groups)
        except Exception as exc:
            paddle_error=f'{type(exc).__name__}: Paddle structure unavailable or invalid'
        try:
            if structure is None and regions:
                observation=pipeline.ocr_page(pdf_path,number,image_dir,regions,covered)
                recognized=observation.words;ocr_text=observation.text;image_path=observation.image_path
        except Exception as exc:
            ocr_error=f'OCR 처리 실패: {type(exc).__name__}'
    # Independent streams, grouped within a region. No mixed paragraph and no native replacement.
    ocr_groups=[]
    if structure is not None:ocr_groups=structure.groups
    for stream_id,region_id in ([] if structure is not None else dict.fromkeys((w.get('ocr_stream',str(w.get('ocr_psm',6))),w.get('region_id',0)) for w in recognized)):
        ocr_groups.extend(reading_groups([w for w in recognized if
            (w.get('ocr_stream',str(w.get('ocr_psm',6))),w.get('region_id',0))==(stream_id,region_id)]))
    text,words,segments=serialize_groups(sentence_groups(native_groups+ocr_groups))
    unsafe=[dict(char_start=w['char_start'],char_end=w['char_end'],reason='unverified_word')
            for w in words if not safe_word(w)]
    candidates=extract_native_facts(text,words,tables,number)
    primitive_observations=[]
    if structure is not None:
        from .paddle_tables import extract_paddle_facts
        from .spatial_tables import extract_spatial_facts
        candidates.extend(extract_paddle_facts(text,words,structure.tables,number))
        candidates.extend(extract_spatial_facts(text,words,number,observations=primitive_observations))
    from .structured_cells import extract_cell_facts, merge_cell_facts, unit_compatible
    cell_facts=extract_cell_facts(text,words,
        tables + (structure.tables if structure is not None else []),number)
    streams=[('native',None)]+[('paddle_structure' if structure is not None else 'ocr',s) for s in dict.fromkeys(
        w.get('ocr_stream',str(w.get('ocr_psm',6))) for w in recognized)]
    for source,stream_id in streams:
        if source=='paddle_structure':continue  # Cell topology, not prose alignment, supplies Paddle tables.
        stream=[w for w in words if w['source']==source and (source=='native' or
            w.get('ocr_stream',str(w.get('ocr_psm',6)))==stream_id)]
        for fact in extract_layout_facts(text,stream,number,unsafe):
            label=re.sub(r'\s+','',fact['row_label'])
            explicit=re.search(r'\((원|주|%|배)\)',label)
            if (explicit and explicit[1]!=fact['unit']) or ('주식수' in label and fact['unit']!='주'):
                continue
            supporting=[s['bbox'] for s in fact['source_spans']]
            path='native_text' if source=='native' else 'paddle_structure' if source=='paddle_structure' else 'ocr_table'
            matching=[t for t in tables if topology_matches(fact,t)] if source=='native' else []
            if matching:path='native_table'
            fact.update(kind='table',source=path,processing_version=PARSER_VERSION,
                bbox=next(s['bbox'] for s in fact['source_spans'] if s['role']=='value'),
                context_bbox=[min(b[0] for b in supporting),min(b[1] for b in supporting),max(b[2] for b in supporting),max(b[3] for b in supporting)],
                confidence=min(s['confidence'] for s in fact['source_spans']),ocr_stream=stream_id)
            if matching:fact['native_cell_table']=matching[0]
            candidates.append(fact)
    numeric=_numeric(text,words,segments,number)
    # A validated table and a paragraph have different identities; never label prose as a table.
    candidates=merge_cell_facts(candidates,cell_facts)
    candidates=[f for f in candidates if unit_compatible(f['metric'],f['unit'])]
    facts,rejected=fuse_candidates(candidates+numeric)
    for item in rejected:
        if item['reason']=='equal_priority_conflict':
            roles=set()
            for field in item.get('conflicting_fields', ['value']):
                roles.update({'period':('period','columns'),'row_label':('row',),
                              'comparison_basis':('basis',)}.get(field,(field,)))
            unsafe.extend(dict(char_start=s['char_start'],char_end=s['char_end'],reason='conflicting_fact')
                for s in item['candidate']['source_spans'] if s['role'] in roles)
    facts=[f for f in facts if not any(s['char_start']<u['char_end'] and s['char_end']>u['char_start']
        for s in f['source_spans'] for u in unsafe)]
    for fact in facts:
        if fact['source']=='paddle_structure' and structure is not None:fact['model']=structure.model
    tables_fused=[f for f in facts if f['kind']=='table']
    numeric_fused=[f for f in facts if f['kind']=='text_numeric']
    index_segments=[]
    for segment in segments:
        contributors=[w for w in words if segment['char_start']<=w['char_start']<segment['char_end']]
        grid_like=(sum(bool(re.fullmatch(r'[-+]?\d[\d,.%]*',w['text'])) for w in contributors)>=3
                   and not re.search(r'다\.|예\s*상|전\s*망|추\s*정|했다|이다',text[segment['char_start']:segment['char_end']]))
        prose=text[segment['char_start']:segment['char_end']]
        has_claim=len(prose)>=20 and bool(re.search(r'다\.|[A-Za-z]{2,}[^\n]+[.!?]$',prose))
        if contributors and has_claim and not grid_like and all(safe_word(w) for w in contributors) and not any(
                segment['char_start']<u['char_end'] and segment['char_end']>u['char_start'] for u in unsafe):
            index_segments.append({**segment,'kind':'paragraph','page_number':number,
                'source':fact_source(segment['source']),
                'confidence':min(w['confidence'] for w in contributors),'processing_version':PARSER_VERSION})
    # Verified source spans remain indexable even when surrounding OCR is uncertain.
    for fact in facts:
        index_segments.append(dict(char_start=fact['char_start'],char_end=fact['char_end'],
            kind='fact_quote',source=fact['source'],bbox=fact['bbox']))
        for span in fact['source_spans']:
            index_segments.append(dict(char_start=span['char_start'],char_end=span['char_end'],
                kind='fact_span',source=fact['source'],bbox=span.get('bbox',fact['bbox'])))
    mode='mixed' if native and recognized else 'native' if native else 'ocr' if recognized else 'none'
    provenance=dict(parser_version=PARSER_VERSION,selection_mode=mode,selection_reason='independent_fact_fusion',
        ocr_reasons=reasons,metrics=metrics,ocr_confirmation_limits={'numeric':16,'labels':16},
        ocr_dpi=216 if structure is not None else pipeline.OCR_DPI if regions else None,
        coordinate_system='unrotated PDF points; physical page index + 1',rotation=page.rotation,
        page_size=[page.rect.width,page.rect.height],native_words=native,
        native_blocks=[dict(bbox=list(b[:4]),text=b[4]) for b in page.get_text('blocks') if b[6]==0],
        native_tables=tables,native_table_errors=table_errors,ocr_regions=regions,ocr_words=recognized,
        selected_words=words,unsafe_spans=unsafe,numeric_evidence=numeric_fused,
        paddle_structure=structure.raw if structure is not None else None,
        paddle_tables=structure.tables if structure is not None else [],
        paddle_model=structure.model if structure is not None else None,
        paddle_fingerprint_sha256=structure.fingerprint_sha256 if structure is not None else None,
        paddle_error=paddle_error,
        primary_engine='paddle_structure' if structure is not None else 'tesseract_fallback' if recognized else 'native',
        table_fact_count=len(tables_fused),paragraph_segments=segments,index_segments=index_segments,rejected_candidates=rejected,
        primitive_cells=[{k:v for k,v in fact.items() if k not in
            {'comparison_cell','comparison_basis','comparison_derivation'}} for fact in cell_facts],
        unresolved_cell_observations=primitive_observations)
    from types import SimpleNamespace as NS
    import hashlib
    from .index_admission import admit_dependencies
    admission_page = NS(page_number=number, final_text=text, extraction=NS(
        parser_version=PARSER_VERSION, final_text_sha256=hashlib.sha256(text.encode()).hexdigest(),
        provenance=provenance, table_facts=tables_fused))
    admit_dependencies(admission_page)
    source=TextSource.native if native else TextSource.ocr if recognized else TextSource.none
    return pipeline.ExtractedPage(number,native_text or None,ocr_text,text,source,image_path,ocr_error,provenance,tables_fused)
