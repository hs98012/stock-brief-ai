from app.analysis_retrieval import STRONG_NEGATIVE_PATTERN, evidence_spans, readable_excerpt
from app.analysis_service import (_grounded_polarity_fallback, _item_tone_is_safe,
    _spans_overlap, _title_is_specific)
from uuid import uuid4
from app.citation_display import citation_display, has_damaging_ocr_noise, normalize_display_quote


def test_hyundai_2026_07_31_removes_investment_title_contact_and_mid_sentence_cut() -> None:
    source = ("AMD 등 주요 가속기 업체로의 매출 증대가 예상되며, HBM 시장 점유율도\n"
        "가파르게 상승할 것으로 예상\n주요 이슈 및 실적전망\n- 놀라운 실적 성장에도 불구하고 동사 주가는 "
        "1) 북미 CSP업체들의 FCF 악화 속에\n향후 AIDC Capex 감소, 2) 메모리 가격 급등에 따른 소비자 제품 거래선의 가격\n"
        "저항, 3) 중국 메모리와 장비 산업의 부각 등으로 크게 하락. 다만 Google, Meta")
    excerpt = readable_excerpt(source, "악재 위험", preferred_pattern=STRONG_NEGATIVE_PATTERN)
    assert excerpt and excerpt.endswith("하락.") and not excerpt.endswith("Google, Meta")
    assert not _item_tone_is_safe("주가 하락 가능성")
    fallback = _grounded_polarity_fallback([{"chunk_id": uuid4(), "analysis_perspective": "negative",
        "quote": "북미 CSP업체들의 FCF 악화 속에 향후 AIDC Capex 감소 위험을 언급합니다."}],
        "negative", set(), "증권사 리포트 해석")
    assert fallback is None  # unvalidated raw chunks cannot become fallback cards
    display = normalize_display_quote("삼성전자\nAnalyst 노근창 greg@hmsec.com\nHBM 시장 점유율 확대가 예상됩니다.")
    assert "Analyst" not in display and "@" not in display and "HBM" in display


def test_hyundai_2026_07_31_keeps_disjoint_polarities_from_one_raw_chunk() -> None:
    chunk_id = uuid4()
    source = ("AMD 등 주요 가속기 업체로의 매출 증대가 예상되며, HBM 시장 점유율도 가파르게 상승할 것으로 예상. "
        "북미 CSP업체들의 FCF 악화 속에 향후 AIDC Capex 감소 위험이 있다.")
    spans = evidence_spans({"chunk_id": chunk_id, "quote": source, "page_number": 1,
        "chunk_char_start": 120}, "기본 호재 악재 요약")
    accepted = [span for span in spans if span["quality_status"] == "valid"]
    positive = next(span for span in accepted if span["analysis_perspective"] == "positive")
    negative = next(span for span in accepted if span["analysis_perspective"] == "negative")
    assert positive["source_chunk_id"] == negative["source_chunk_id"] == chunk_id
    assert positive["char_end"] <= negative["char_start"]
    assert not _spans_overlap(positive, negative)


def test_noisy_contact_span_does_not_remove_clean_neighbor() -> None:
    chunk_id = uuid4()
    source = ("Analyst 노근창 greg@hmsec.com.\n"
        "HBM 시장 점유율이 가파르게 상승할 것으로 예상.\n"
        "Bae enue 2001 SSS.")
    spans = evidence_spans({"chunk_id": chunk_id, "quote": source, "page_number": 1}, "HBM 호재")
    accepted = [span for span in spans if span["quality_status"] == "valid"]
    excluded = [span for span in spans if span["quality_status"] == "excluded"]
    assert any("HBM 시장 점유율" in span["quote"] for span in accepted)
    assert {span["exclusion_reason"] for span in excluded} >= {"contact_or_metadata", "ocr_noise"}


def test_mirae_2026_08_10_rejects_broken_ocr_but_keeps_industry_terms() -> None:
    broken = "Bea enue 750 테슬라향 2001 SSS 시작 wlex2M"
    assert has_damaging_ocr_noise(broken)
    assert not has_damaging_ocr_noise("AMD와 CSP의 HBM·DRAM·NAND 수요, Foundry/LS 생산 전망")


def test_mirae_verified_foundry_table_span_survives_noise_in_other_rows() -> None:
    chunk_id = uuid4()
    table = ("영업이익 53.7 89.2 117.2 123.4 2025 2026F 2027F\n"
        "DRAI 43.2 70.4 ng\nFoundry/LS -1.4 -2.2 -7.6 -5.1 -2.8")
    spans = evidence_spans({"chunk_id": chunk_id, "quote": table, "page_number": 4},
        "파운드리 수익성 부담", table_excerpt=table)
    table_spans = [span for span in spans if span["span_kind"] == "table"]
    assert table_spans and all(span["quality_status"] == "excluded" for span in table_spans)


def test_hyundai_2026_06_29_sentence_is_not_misclassified_as_table_and_generic_titles_fail() -> None:
    quote = ("병목은 관련 기업들의 수익성 급상승으로 귀결되고 있음. 다만 DRAM의 경우 Greenfield 투자에도 "
        "불구하고 다양한 제약 요인으로 인해 병목이 단계적으로 완화될 것으로 예상됨.")
    display = citation_display(quote, 1)
    assert display.kind == "text" and display.display_quote and display.note is None
    assert not _title_is_specific("수요 관련 전망", quote)
    assert not _title_is_specific("보고서에서 확인된 위험 요인", quote)
    assert not _title_is_specific("DRAM 공급 병목과 가격 전망", quote + " 메모리 가격")
    fallback = _grounded_polarity_fallback([{"chunk_id": uuid4(), "analysis_perspective": "positive",
        "quote": quote + " 메모리 가격 흐름을 설명합니다."}], "positive", set(), "증권사 리포트 해석")
    assert fallback is None  # missing certified fact/offsets


def test_hanwha_2025_07_09_removes_valuation_title_and_keeps_specific_performance_title() -> None:
    valuation = "낮은 주가 레벨을 고려하면 경쟁사 대비 단기 매력은 더 높을 수 있다고 판단"
    performance = "2Q25 영업이익 4.6조원으로 시장 기대치를 하회하는 실적 기록."
    assert not _item_tone_is_safe("경쟁사 대비 단기 매력")
    assert not _title_is_specific("경쟁사 대비 단기 매력", valuation)
    assert _item_tone_is_safe("2분기 실적 하회")
    assert _title_is_specific("영업이익 시장 기대치 하회", performance)


def test_hanwha_contact_lines_do_not_remove_following_2q25_miss_span() -> None:
    chunk_id = uuid4()
    source = ("Buy(유지)\n목표주가 79,000원\n▶Analyst 김광진 analyst@example.com 02-0000-0000\n\n"
        "2Q25 잠정실적: 악재를 해소하고 가는 분기\n"
        "2Q25 잠정실적은 매출액 74조원(-6% QoQ), 영업이익 4.6조원(-31% QoQ)으로 "
        "시장 기대치(영업이익 6.2조원)를 하\n회하는 실적 기록.")
    spans = evidence_spans({"chunk_id": chunk_id, "quote": source, "page_number": 1,
        "chunk_char_start": 50}, "기본 호재 악재 요약")
    negative = [span for span in spans if span["quality_status"] == "valid"
        and span["analysis_perspective"] == "negative"]
    assert negative and "2Q25 잠정실적은" in negative[0]["quote"]
    assert "Analyst" not in negative[0]["quote"] and "목표주가" not in negative[0]["quote"]
    fallback = _grounded_polarity_fallback(negative, "negative", set(), "증권사 리포트 해석")
    assert fallback and fallback.title == "영업이익 시장 기대치 하회"
