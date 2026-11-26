import re
from dataclasses import dataclass

WHITESPACE = re.compile(r"\s")

@dataclass(frozen=True)
class ChunkSpan:
    content: str
    char_start: int
    char_end: int


def _next_start(text: str, cursor: int, end: int, overlap: int) -> int:
    """With overlap, restart after the first whitespace inside the last `overlap` chars."""
    if not overlap or end >= len(text):
        return end
    if not text[end:].strip():
        return len(text)
    boundary = WHITESPACE.search(text, end - overlap, end)
    return max(boundary.end() if boundary else end, cursor + 1)


def split_page(text: str, max_chars: int = 1200, overlap: int = 0) -> list[ChunkSpan]:
    """Split one page without rewriting text; offsets index the original final_text.

    overlap > 0 (evaluation option) repeats up to `overlap` trailing chars of a span
    at the start of the next one, starting on a word boundary.
    """
    if not 0 <= overlap < max_chars // 2:
        raise ValueError("overlap must be >= 0 and less than half of max_chars")
    if not text.strip():
        return []
    spans: list[ChunkSpan] = []
    cursor = 0
    length = len(text)
    while cursor < length:
        while cursor < length and text[cursor].isspace():
            cursor += 1
        if cursor >= length:
            break
        limit = min(cursor + max_chars, length)
        end = limit
        if limit < length:
            candidates = [text.rfind(mark, cursor + max_chars // 2, limit) for mark in ("\n\n", "\n", ". ", "다. ", "요. ", " ")]
            boundary = max(candidates)
            if boundary > cursor:
                marker_length = 2 if text[boundary:boundary + 2] in {"\n\n", ". ", "다.", "요."} else 1
                end = boundary + marker_length
        while end > cursor and text[end - 1].isspace():
            end -= 1
        if end <= cursor:
            end = limit
        spans.append(ChunkSpan(text[cursor:end], cursor, end))
        cursor = _next_start(text, cursor, end, overlap)
    return spans



def structured_spans(text: str, provenance: dict, max_chars: int = 1200) -> list[ChunkSpan]:
    """Only admitted source ranges; do not bridge unverified text or paragraph boundaries."""
    if not provenance.get('parser_version', '').startswith('fact-fusion-'):
        return split_page(text, max_chars)
    ranges=sorted({(s['char_start'],s['char_end']) for s in provenance.get('index_segments', [])
                   if 0<=s['char_start']<s['char_end']<=len(text)})
    merged=[]
    for a,b in ranges:
        # New dependency slices may touch across owners; do not turn adjacency
        # into a shared evidence unit. Legacy frozen ranges retain their shape.
        joins = a < merged[-1][1] if merged else False
        if not provenance.get('index_admission_contract') and merged:
            joins = a <= merged[-1][1]
        if joins:
            merged[-1]=(merged[-1][0],max(b,merged[-1][1]))
        else:merged.append((a,b))
    result=[]
    for a,b in merged:
        for span in split_page(text[a:b],max_chars):
            result.append(ChunkSpan(span.content,a+span.char_start,a+span.char_end))
    return result
