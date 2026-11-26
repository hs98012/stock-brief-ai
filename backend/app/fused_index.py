"""Search representation for fused pages; source chunks/quotes never change."""
import re


def observation(page):
    obs=getattr(page,'extraction',None)
    return obs if obs is not None and obs.parser_version.startswith('fact-fusion-') else None


def searchable(chunk,page):
    obs=observation(page)
    if obs is None:return True
    return any(chunk.char_start <= g['anchor']['char_start'] < chunk.char_end
        for g in obs.provenance.get('dependency_groups', [])) or any(s.get('kind') in ('paragraph','fact_quote')
        and chunk.char_start<=s['char_start']<chunk.char_end
        for s in obs.provenance.get('index_segments',[]))


def retrieval_text(chunk,page):
    obs=observation(page)
    if obs is None:return chunk.content
    # Normalizing word spacing is only for the search representation, never the quote.
    content=re.sub(r'(?<=[가-힣])\s+(?=[가-힣])','',chunk.content)
    facts=[*obs.table_facts,*obs.provenance.get('numeric_evidence',[])]
    descriptions=[]
    descriptions.extend(g['search_text'] for g in obs.provenance.get('dependency_groups', [])
        if chunk.char_start <= g['anchor']['char_start'] < chunk.char_end)
    for fact in facts:
        if chunk.char_start<=fact['char_start']<chunk.char_end:
            descriptions.append(' '.join(re.sub(r'\s+','',str(fact.get(k) or '')) for k in
                ('row_label','metric','period','status','comparison_basis','unit','value')))
    return '\n'.join([content,*descriptions])
