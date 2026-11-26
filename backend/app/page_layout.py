"""Deterministic extraction observations and source selection in PDF point coordinates."""
import re
from statistics import median

from PIL import Image, ImageChops, ImageDraw
import fitz

PARSER_VERSION = 'mixed-layout-v1'
OCR_MIN_CONFIDENCE = 80.0


def area(box):
    return max(0, box[2]-box[0]) * max(0, box[3]-box[1])


def overlap(left, right):
    return area([max(left[0], right[0]), max(left[1], right[1]),
                 min(left[2], right[2]), min(left[3], right[3])])


def native_observation(page, text):
    words = [{'text': w[4], 'bbox': list(w[:4]), 'line_id': f'n:{w[5]}:{w[6]}',
              'source': 'native', 'confidence': 100.0} for w in page.get_text('words', sort=False)]
    pix = page.get_pixmap(matrix=fitz.Matrix(1, 1), colorspace=fitz.csGRAY, alpha=False)
    rendered = Image.frombytes('L', (pix.width, pix.height), pix.samples)
    ink = rendered.point(lambda value: 255 if value < 180 else 0)
    cover = Image.new('L', rendered.size)
    draw = ImageDraw.Draw(cover)
    # PDF word boxes include glyph ascent/descent; small padding covers antialiasing.
    for word in words:
        x0,y0,x1,y1 = fitz.Rect(word['bbox']) * page.rotation_matrix
        draw.rectangle((x0-1, y0-1, x1+1, y1+1), fill=255)
    ink_count = ink.histogram()[255]
    uncovered = ImageChops.subtract(ink, cover).histogram()[255]
    bad = sum(c == '\ufffd' or (ord(c) < 32 and c not in '\n\r\t') for c in text)
    drawings = page.get_drawings()
    rules = sum(len(d.get('items', [])) for d in drawings if d.get('type') in ('s','fs'))
    metrics = {'native_chars': len(text), 'native_words': len(words), 'ink_pixels': ink_count,
               'uncovered_ink_pixels': uncovered, 'uncovered_ink_ratio': uncovered/max(1,ink_count),
               'damaged_char_ratio': bad/max(1,len(text)), 'drawing_segments': rules,
               'native_numeric_words': sum(bool(re.search(r'\d', w['text'])) for w in words)}
    reasons = []
    if not words and ink_count:
        reasons.append('rendered_ink_without_native_words')
    if uncovered >= 200 and metrics['uncovered_ink_ratio'] >= .35:
        reasons.append('rendered_regions_missing_from_native')
    if metrics['damaged_char_ratio'] > .01:
        reasons.append('damaged_native_characters')
    if rules >= 6 and metrics['native_numeric_words'] == 0 and uncovered >= 200:
        reasons.append('ruled_regions_without_native_numbers')
    return words, metrics, reasons


def ocr_words(data, scale_x, scale_y):
    result = []
    for i, token in enumerate(data['text']):
        token = token.strip()
        if not token:
            continue
        x,y,w,h = (data[k][i] for k in ('left','top','width','height'))
        result.append({'text': token, 'bbox': [x*scale_x,y*scale_y,(x+w)*scale_x,(y+h)*scale_y],
                       'line_id': 'o:'+':'.join(str(data[k][i]) for k in ('block_num','par_num','line_num')),
                       'source': 'ocr', 'confidence': float(data['conf'][i])})
    return result


def group_lines(words):
    groups = {}
    for word in words:
        groups.setdefault(word['line_id'], []).append(word)
    return list(groups.values())


def serialize_ocr(words):
    parts = []
    for line in group_lines(words):
        parts.append(' '.join(w['text'] for w in sorted(line, key=lambda w:w['bbox'][0])))
    return '\n'.join(parts)


def select_sources(native, native_words, recognized, damaged_native=False):
    """Keep usable native text, supplement uncovered OCR words; never choose by length.

    Native/OCR disagreement remains a conflict, not a numeric correction. Both
    observations remain in provenance; conflicts and low-confidence OCR numeric
    spans are ineligible as answer/table evidence.
    """
    final = native
    selected = []
    native_unsafe = []
    cursor = 0
    for original in native_words:
        word = dict(original)
        start = final.find(word['text'], cursor)
        if start < 0:
            continue
        word.update(char_start=start, char_end=start+len(word['text']))
        cursor = word['char_end']
        if any(c=='\ufffd' or (ord(c)<32 and c not in '\n\r\t') for c in word['text']):
            native_unsafe.append({'char_start':start,'char_end':cursor,'reason':'damaged_native_token'})
            continue
        selected.append(word)
    conflicts = []
    supplement = []
    for original in recognized:
        covers = [w for w in selected if w['source']=='native' and overlap(w['bbox'], original['bbox']) / max(1,area(original['bbox'])) > .5]
        if covers:
            raw = ''.join(w['text'] for w in covers)
            if re.search(r'\d', original['text']) and re.sub(r'\s+', '', raw) != original['text']:
                conflicts.extend({'char_start': w['char_start'], 'char_end': w['char_end'],
                                  'reason': 'native_ocr_numeric_disagreement'} for w in covers)
            continue
        supplement.append(dict(original))
    for line in group_lines(supplement):
        if final and not final.endswith('\n'):
            final += '\n'
        for i, word in enumerate(sorted(line, key=lambda w:w['bbox'][0])):
            if i:
                final += ' '
            start = len(final)
            final += word['text']
            word.update(char_start=start, char_end=len(final))
            selected.append(word)
        final += '\n'
    unsafe = native_unsafe + conflicts
    for word in selected:
        if word['source']=='ocr' and word['confidence'] < OCR_MIN_CONFIDENCE and not word.get('confirmed_exact') and re.search(r'\d', word['text']):
            unsafe.append({'char_start':word['char_start'], 'char_end':word['char_end'], 'reason':'uncertain_ocr_number'})
    sources = {w['source'] for w in selected}
    mode = 'mixed' if len(sources)>1 else next(iter(sources), 'none')
    return final, selected, unsafe, mode


def geometric_rows(words):
    """Cluster word baselines; column/row validation happens separately."""
    rows = []
    for word in sorted(words, key=lambda w: ((w['bbox'][1]+w['bbox'][3])/2, w['bbox'][0])):
        center = (word['bbox'][1]+word['bbox'][3])/2
        height = word['bbox'][3]-word['bbox'][1]
        match = next((row for row in reversed(rows) if abs(center-row['y']) <= .6*max(height,row['height'])), None)
        if match is None:
            rows.append({'y':center, 'height':height, 'words':[word]})
        else:
            match['words'].append(word)
            match['height'] = max(match['height'], height)
            match['y'] = median((w['bbox'][1]+w['bbox'][3])/2 for w in match['words'])
    return [sorted(row['words'], key=lambda w:w['bbox'][0]) for row in rows]
