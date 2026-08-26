from app.citation_display import citation_display, extract_table_facts, normalize_display_quote


def test_display_quote_repairs_only_broken_korean_lines_and_removes_noise() -> None:
    raw = "HBM 가격 인상 효\n과를 주도로 DRAM ASP 상승세를 이어간다.\n안정성\n에 대해 설명한다.\nbe\neens"
    display = normalize_display_quote(raw)
    assert "인상 효과를" in display and "안정성에 대해" in display
    assert "be" not in display and "eens" not in display
    assert raw.startswith("HBM 가격 인상 효\n과를")


def test_table_fragment_without_headers_hides_numeric_blob() -> None:
    raw = ("영업이익 53.7 89.2 117.2 123.4 131.3 137.9\nDRAM 43.2 70.4 90.6\n"
        "NAND 11.9 21.0 27.5\nFoundry/LS -1.4 -2.2 -0.9 -0.6")
    display = citation_display(raw, 3)
    assert display.kind == "table" and display.display_quote is None and display.table_labels == []
    assert display.note == "표 수치는 원문 PDF 3페이지에서 확인할 수 있습니다."


def test_table_labels_are_shown_only_when_title_and_period_exist_in_source() -> None:
    raw = ("표 2. DS 부문 실적\n(조원, %)\n1Q26 2Q26 3Q26F 4Q26F\n"
        "영업이익 53.7 89.2 117.2 123.4\nDRAM 43.2 70.4\nNAND 11.9 21.0\nFoundry/LS -1.4 -2.2")
    display = citation_display(raw, 3)
    assert display.kind == "table" and "표 2. DS 부문 실적" in display.table_labels
    assert "(조원, %)" in display.table_labels and "3Q26F" in display.table_labels
    assert display.display_quote is None


def test_verified_annual_row_values_become_table_facts_without_guessing_title() -> None:
    page = """표 2. 05 부문 실적 (조원 %)
1026 2026 3Q26F 4Q26F 1Q27F 2Q27F 3Q27F 4Q27F 2024 2025 2026F 2027F
영업이익 53.7 89.2 1172 1234 1313 1379 141.2 1299 15.1 249 3835 5403
DRAM 43.2 70.4 90.6 94.1 1018 1077 1104 1048 168 304 2983 4247
NAND 11.9 21.0 275 29.8 30.2 31.3 31.2 257 35 2.0 90.2 118.5
Foundry/LS -14 -2.2 -0.9 -0.6 -0.6 -1.2 -0.5 -0.6 -5.3 -7.6 -5.1 -2.8
Q00/YoY 227.0 66.2 31.4 5.3"""
    quote = "영업이익 53.7 89.2 1172 1234 1313 1379 141.2 1299 15.1 249 3835 5403\nFoundry/LS -14 -2.2 -0.9 -0.6 -0.6 -1.2 -0.5 -0.6 -5.3 -7.6 -5.1 -2.8"
    facts = extract_table_facts(page, quote, "파운드리 수익성 부담")
    assert facts and facts["table_title"] is None
    assert facts["metric"] == "영업이익" and facts["row_label"] == "Foundry/LS" and facts["unit"] == "조원"
    assert facts["values"] == [{"period": "2025", "value": "-7.6"},
        {"period": "2026F", "value": "-5.1"}, {"period": "2027F", "value": "-2.8"}]
    assert facts["interpretation"].startswith("보고서는")


def test_ambiguous_table_structure_returns_no_facts() -> None:
    page = "영업이익 10 20 30\nFoundry/LS -1 -2 -3"
    assert extract_table_facts(page, page, "파운드리 부담") is None
