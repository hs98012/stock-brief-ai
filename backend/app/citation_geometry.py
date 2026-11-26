"""Literal extraction geometry in unrotated PDF points; never guess boxes."""
import math

from .extraction_provenance import extraction_matches_page, trusted_page_span


def citation_geometry(page, row):
    observation = getattr(page, 'extraction', None)
    if observation is None or not extraction_matches_page(page):
        return {}
    size = observation.provenance.get('page_size', [])
    if len(size) != 2 or not all(isinstance(x, (int, float)) and math.isfinite(x) and x > 0 for x in size):
        return {}
    start, end = row.get('char_start', -1), row.get('char_end', -1)
    if not (0 <= start < end <= len(page.final_text)) or page.final_text[start:end] != row.get('quote'):
        return {}
    if not trusted_page_span(page, start, end):
        return {}
    words = sorted((w for w in observation.provenance.get('selected_words', [])
                    if w['char_start'] < end and w['char_end'] > start), key=lambda w: w['char_start'])
    cursor = start
    boxes = []
    for word in words:
        a, b = word['char_start'], word['char_end']
        box = word.get('bbox', [])
        if (page.final_text[a:b] != word.get('text') or len(box) != 4
            or not all(isinstance(x, (int, float)) and math.isfinite(x) for x in box)
            or not (0 <= box[0] < box[2] <= size[0] and 0 <= box[1] < box[3] <= size[1])
            or a > cursor and page.final_text[cursor:a].strip()):
            return {}
        boxes.append(box)
        cursor = max(cursor, b)
    if not boxes or cursor < end and page.final_text[cursor:end].strip():
        return {}
    return {'source_boxes': [list(box) for box in dict.fromkeys(tuple(b) for b in boxes)],
            'page_size': size, 'coordinate_system': 'unrotated_pdf_points'}
