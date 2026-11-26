"""Literal numeric prose spans, deliberately separate from table/UI facts."""
import re
from .page_layout import group_lines

_METRIC = re.compile(r'영\s*업\s*이\s*익|순\s*이\s*익|매\s*출\s*액|보\s*험\s*손\s*익')
_PERIOD = re.compile(r'(?<!\d)(?:[1-4]\s*분\s*기|[1-4]Q\d{2}[FEAP]?|20\d{2}[FEAP])(?![A-Za-z0-9])', re.I)
_VALUE = re.compile(r'(?<![\d.,])([-+]?\d+(?:,\d{3})*(?:\.\d+)?)\s*(십\s*억\s*원|백\s*만\s*원|억\s*원|조\s*원|%)')


def extract_numeric_evidence(text, words, page_number, unsafe):
    result = []
    for line in group_lines(words):
        a,b = min(w['char_start'] for w in line),max(w['char_end'] for w in line)
        quote = text[a:b]
        if '\n' in quote or any(a < s['char_end'] and b > s['char_start'] for s in unsafe):
            continue
        periods,metrics = list(_PERIOD.finditer(quote)),list(_METRIC.finditer(quote))
        if len(periods)!=1 or len(metrics)!=1:
            continue
        period,metric = periods[0],metrics[0]
        values = list(_VALUE.finditer(quote))
        if not values:
            continue
        # Requiring a prose predicate prevents reclassifying ordinary table rows.
        forecast = bool(re.search(r'예\s*상|전\s*망|추\s*정',quote))
        actual = bool(re.search(r'기\s*록|실\s*제|확\s*정',quote))
        if not forecast and not actual:
            continue
        for value in values:
            if value.start() < metric.end():
                continue
            roles = [('period',period.start(),period.end()),('metric',metric.start(),metric.end()),
                     ('value',value.start(1),value.end(1)),('unit',value.start(2),value.end(2))]
            spans = []
            trustworthy = True
            for role,start,end in roles:
                contributors = [w for w in line if w['char_start'] < a+end and w['char_end'] > a+start]
                threshold = 80 if role in ('value','period') else 65
                if not contributors or any(w['source']=='ocr' and w['confidence'] < threshold and not w.get('confirmed_exact') for w in contributors):
                    trustworthy = False
                spans.append({'role':role,'char_start':a+start,'char_end':a+end,'quote':quote[start:end],
                    'boxes':[w['bbox'] for w in contributors], 'sources':sorted({w['source'] for w in contributors})})
            if not trustworthy:
                continue
            result.append({'kind':'text_numeric','metric':re.sub(r'\s+','',metric.group()),
                'period':re.sub(r'\s+','',period.group()),'value':value.group(1),
                'unit':re.sub(r'\s+','',value.group(2)), 'status':'forecast' if forecast and not actual else 'actual' if actual and not forecast else 'unspecified',
                'comparison_basis':'컨센서스' if '컨센서스' in quote[metric.end():value.start()] else None,
                'page_number':page_number,'char_start':a,'char_end':b,'quote':quote,'source_spans':spans})
    from .unit_validation import validate_unit, metadata
    approved = []
    for fact in result:
        audit = validate_unit(fact, text, words)
        if audit['approved']:
            approved.append({**fact, **metadata(audit)})
    return approved
