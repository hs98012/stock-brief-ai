"""Validate stored offsets and every link in page/chunk provenance."""


def chunk_matches_page(chunk, page) -> bool:
    return (chunk.page_id == page.id and chunk.document_id == page.document_id
        and chunk.page_number == page.page_number
        and 0 <= chunk.char_start < chunk.char_end <= len(page.final_text)
        and page.final_text[chunk.char_start:chunk.char_end] == chunk.content)


def span_is_covered(page, chunks, start: int, end: int, quote: str) -> bool:
    if (not isinstance(start, int) or not isinstance(end, int)
            or not (0 <= start < end <= len(page.final_text)) or page.final_text[start:end] != quote):
        return False
    cursor = start
    for chunk in sorted(chunks, key=lambda row: (row.char_start, row.char_end, str(row.id))):
        if not chunk_matches_page(chunk, page) or chunk.char_end <= start or chunk.char_start >= end:
            return False
        if chunk.char_start > cursor and page.final_text[cursor:min(chunk.char_start, end)].strip():
            return False
        cursor = max(cursor, min(chunk.char_end, end))
    return bool(chunks) and (cursor >= end or not page.final_text[cursor:end].strip())
