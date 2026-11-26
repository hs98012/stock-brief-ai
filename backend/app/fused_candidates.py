"""New-parser numeric retrieval only; legacy pages do not enter this path."""
import re
from .extraction_provenance import extraction_matches_page, trusted_page_span
from .evidence_integrity import span_is_covered
from .fact_fusion import safe_word


def period_key(period):
    compact=re.sub(r'\s+','',period).upper()
    match=re.fullmatch(r'20(\d{2})년([1-4])분기',compact)
    return f'{match[2]}Q{match[1]}' if match else compact


def verified_numeric_candidates(rows, query):
    compact=re.sub(r'\s+','',query).casefold()
    pages={}
    for chunk,page,document in rows:
        pages.setdefault(page.id,(page,[]))[1].append(chunk)
    result=[]
    requested_rows=set()
    for page,_ in pages.values():
        observation=getattr(page,'extraction',None)
        if observation is None or not observation.parser_version.startswith('fact-fusion-'):continue
        from .extraction_provenance import validated_stored_facts
        for fact in validated_stored_facts(page):
            row=re.sub(r'\s+','',fact['row_label']).casefold()
            metric=re.sub(r'\s+','',fact['metric']).casefold()
            if row!=metric and row in compact:requested_rows.add(row)
    for page,chunks in pages.values():
        obs=getattr(page,'extraction',None)
        if obs is None or not obs.parser_version.startswith('fact-fusion-') or not extraction_matches_page(page):continue
        for fact in obs.provenance.get('numeric_evidence',[]):
            from .period_binding import numeric_binding_valid
            if fact.get('document_id') is not None and str(fact['document_id']) != str(page.document_id):continue
            if not numeric_binding_valid(fact, page):continue
            from .unit_validation import validate_unit
            if not validate_unit(fact, page.final_text,
                    obs.provenance.get('selected_words', []))['approved']:
                continue
            if fact.get('processing_version')!=obs.parser_version or fact.get('page_number')!=page.page_number:continue
            if fact['metric'].casefold() not in compact:continue
            if requested_rows and not any(row in re.sub(r'\s+','',fact['quote']).casefold() for row in requested_rows):continue
            # Literal period requests only; absence or semantic guess is not promotion.
            if period_key(fact['period']).casefold() not in compact and fact['period'].casefold() not in compact:continue
            a,b=fact['char_start'],fact['char_end']
            covering=[c for c in chunks if c.char_start<b and c.char_end>a]
            if not trusted_page_span(page,a,b) or not span_is_covered(page,covering,a,b,fact['quote']):continue
            valid=True;groups={}
            for span in fact['source_spans']:
                start,end=span['char_start'],span['char_end']
                if not (0<=start<end<=len(page.final_text)) or page.final_text[start:end]!=span['quote']:
                    valid=False;break
                words=[w for w in obs.provenance['selected_words'] if w['char_start']<end and w['char_end']>start]
                if not words or not all(safe_word(w) for w in words) or [w['bbox'] for w in words]!=span['boxes']:
                    valid=False;break
                support=[c for c in chunks if c.char_start<end and c.char_end>start]
                if not span_is_covered(page,support,start,end,span['quote']):valid=False;break
                covering.extend(c for c in support if c not in covering)
                groups[span['role']]=re.sub(r'\s+','',span['quote'])
            if not valid or any(groups.get(k)!=fact[k] for k in ('metric','period','unit','value')):continue
            status_span=groups.get('status','')
            if fact['status']=='forecast' and not re.fullmatch(r'예상|전망|추정|Preview',status_span,re.I):continue
            if fact['status']=='actual' and not re.fullmatch(r'기록|실제|확정|실적Review',status_span,re.I):continue
            if fact.get('comparison_basis')!=groups.get('basis'):continue
            anchor=next((c for c in covering if c.char_start<=a<c.char_end),None)
            if anchor:
                result.append((anchor.id,{**fact,'document_id':page.document_id,'page_id':page.id,
                    'source_chunk_ids':[c.id for c in covering]}))
    return result


def deduplicate_verified(pool):
    """One representative per identical new-parser fact; retain every legacy candidate."""
    result=[];positions={}
    priority={'native_table':4,'native_text':3,'ocr_table':2,'ocr_text':1}
    for anchor,fact in pool:
        if not fact.get('processing_version','').startswith('fact-fusion-'):
            result.append((anchor,fact));continue
        key=(str(fact['document_id']),fact['page_number'],*(re.sub(r'\s+','',str(fact.get(k) or '')).casefold()
              for k in ('row_label','metric','unit','value','comparison_basis','status')),period_key(fact.get('period') or ''))
        quality=(priority.get(fact.get('source'),0),fact.get('confidence',0))
        if key not in positions:
            positions[key]=(len(result),quality);result.append((anchor,fact))
        elif quality>positions[key][1]:
            index,_=positions[key];result[index]=(anchor,fact);positions[key]=(index,quality)
    return result
