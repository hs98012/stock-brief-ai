from dataclasses import dataclass


@dataclass(frozen=True)
class ChunkSpan:
    content: str
    char_start: int
    char_end: int


def split_page(text: str, max_chars: int = 1200) -> list[ChunkSpan]:
    """Split one page without rewriting text; offsets index the original final_text."""
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
        cursor = end
    return spans

