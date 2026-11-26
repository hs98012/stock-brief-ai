from types import SimpleNamespace
import hashlib


def test_geometry_uses_only_literal_source_boxes_and_rejects_tampering():
    from app.citation_geometry import citation_geometry
    text = '매출 증가'
    page = SimpleNamespace(final_text=text, extraction=SimpleNamespace(
        final_text_sha256=hashlib.sha256(text.encode()).hexdigest(), provenance={
            'page_size': [100, 200], 'selected_words': [
                {'text': '매출', 'char_start': 0, 'char_end': 2, 'bbox': [10, 20, 30, 40]},
                {'text': '증가', 'char_start': 3, 'char_end': 5, 'bbox': [31, 20, 50, 40]}]}))
    geometry = citation_geometry(page, {'char_start': 0, 'char_end': 5, 'quote': text})
    assert geometry['source_boxes'] == [[10, 20, 30, 40], [31, 20, 50, 40]]
    page.extraction.provenance['selected_words'][0]['text'] = '허위'
    assert citation_geometry(page, {'char_start': 0, 'char_end': 5, 'quote': text}) == {}


def test_missing_geometry_is_not_estimated():
    from app.citation_geometry import citation_geometry
    assert citation_geometry(SimpleNamespace(extraction=None), {}) == {}
