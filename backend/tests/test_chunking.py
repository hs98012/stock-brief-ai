import pytest

from app.chunking import split_page

SAMPLE = " ".join(f"문장{index}은 영업이익 {index}억원을 설명한다." for index in range(80))


def test_zero_overlap_matches_default_output() -> None:
    assert split_page(SAMPLE, 200, overlap=0) == split_page(SAMPLE, 200)


def test_overlap_spans_keep_original_offsets() -> None:
    for span in split_page(SAMPLE, 200, overlap=60):
        assert SAMPLE[span.char_start:span.char_end] == span.content


def test_overlap_spans_overlap_and_start_on_word_boundary() -> None:
    spans = split_page(SAMPLE, 200, overlap=60)
    assert len(spans) > 1
    for previous, current in zip(spans, spans[1:]):
        assert current.char_start < previous.char_end
        assert current.char_start > previous.char_start
        assert SAMPLE[current.char_start - 1].isspace()


def test_overlap_spans_cover_all_text() -> None:
    spans = split_page(SAMPLE, 200, overlap=60)
    assert spans[0].char_start == 0 and spans[-1].char_end == len(SAMPLE.rstrip())
    covered_until = 0
    for span in spans:
        assert not SAMPLE[covered_until:span.char_start].strip()
        covered_until = max(covered_until, span.char_end)


def test_overlap_ignores_trailing_whitespace_at_page_end() -> None:
    assert split_page(SAMPLE + "\n\n   ", 200, overlap=60) == split_page(SAMPLE, 200, overlap=60)


def test_overlap_never_emits_two_spans_with_same_end() -> None:
    page = "가나다 라마바 사아자 차카타 파하\n\n" * 40 + "  \n"
    ends = [span.char_end for span in split_page(page, 120, overlap=40)]
    assert len(ends) == len(set(ends))


def test_overlap_must_be_less_than_half_of_max_chars() -> None:
    with pytest.raises(ValueError):
        split_page(SAMPLE, 200, overlap=100)
