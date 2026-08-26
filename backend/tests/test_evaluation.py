import json
from pathlib import Path
from uuid import uuid4

import pytest

from app.evaluation import DocumentSelector, evaluate_case, forbidden_evidence_reason, match_document, validate_fixture


FIXTURE_DIR = Path(__file__).resolve().parents[2] / "evals" / "fixtures"
FIXTURE = FIXTURE_DIR / "samsung-electronics-2025-07-09.json"


def test_versioned_fixture_is_valid_and_has_five_cases() -> None:
    fixture = validate_fixture(json.loads(FIXTURE.read_text(encoding="utf-8")))
    assert len(fixture["cases"]) == 5
    assert {case["expected_polarity"] for case in fixture["cases"]} == {"positive", "negative", "insufficient"}
    assert "id" not in fixture["document"] and "f23493fe" not in FIXTURE.read_text(encoding="utf-8")


def test_all_samsung_fixtures_are_valid_metadata_matched_and_page_grounded() -> None:
    fixture_paths = sorted(FIXTURE_DIR.glob("samsung-electronics-*.json"))
    assert len(fixture_paths) == 5
    fixtures = [validate_fixture(json.loads(path.read_text(encoding="utf-8"))) for path in fixture_paths]
    assert sum(len(fixture["cases"]) for fixture in fixtures) == 17

    selectors = [DocumentSelector(**fixture["document"]) for fixture in fixtures]
    documents = [{**fixture["document"], "id": str(uuid4())} for fixture in fixtures]
    for fixture, selector in zip(fixtures, selectors, strict=True):
        assert match_document(documents, selector)["filename"] == fixture["document"]["filename"]
        polarities = {case["expected_polarity"] for case in fixture["cases"]}
        assert {"positive", "negative", "insufficient"}.issubset(polarities)
        for case in fixture["cases"]:
            if case["expected_polarity"] == "insufficient":
                assert case["expected_pages"] == []
            else:
                assert case["expected_pages"]

    fixture_text = "".join(path.read_text(encoding="utf-8") for path in fixture_paths)
    assert "document_id" not in fixture_text
    assert not any(document_id in fixture_text for document_id in (
        "54831d2c-3a41-4abd-b577-8e698918f450",
        "339509a7-4b4c-4d21-a5be-4f73856fb3ed",
        "8fcb63b3-ac02-48f6-9665-a964a51b7467",
        "caac424d-737d-45b3-95b5-8242a1de2709",
    ))


def test_document_matching_uses_stable_metadata_and_detects_duplicates() -> None:
    selector = DocumentSelector(filename="report.pdf", company_name="삼성전자",
        published_at="2025-07-09", document_type="broker_report")
    matching = {"id": str(uuid4()), "filename": "report.pdf", "company_name": "삼성전자",
        "published_at": "2025-07-09", "document_type": "broker_report"}
    assert match_document([matching, {**matching, "filename": "other.pdf"}], selector) == matching
    assert match_document([], selector) is None
    with pytest.raises(ValueError, match="둘 이상"):
        match_document([matching, {**matching, "id": str(uuid4())}], selector)


def analysis_response(polarity="positive", page=1, quote="HBM 출하 증가가 실적 개선 요인으로 언급됩니다."):
    chunk_id = str(uuid4())
    item = {"title": "HBM 실적 개선", "reason": "보고서는 HBM 출하 증가를 긍정 요인으로 언급합니다.",
        "evidence_chunk_ids": [chunk_id]}
    return {"analysis_status": "completed", "summary": "보고서는 실적 요인을 분석합니다.",
        "positives": [item] if polarity == "positive" else [], "negatives": [item] if polarity == "negative" else [],
        "citations": [{"chunk_id": chunk_id, "page_number": page, "quote": quote}],
        "insufficient_evidence_note": None}


def test_case_evaluation_checks_polarity_page_citation_korean_and_topic() -> None:
    case = {"id": "hbm", "question": "HBM은?", "expected_topic": "HBM|실적",
        "expected_polarity": "positive", "expected_pages": [1], "notes": "본문"}
    response = analysis_response()
    chunk_id = response["citations"][0]["chunk_id"]
    trace = {"candidates": [{"chunk_id": chunk_id, "page_number": 1, "perspective": "positive",
        "quote": "HBM 출하 증가가 실적 개선 요인입니다."}],
        "generated_selection": {"positive": [chunk_id], "negative": []}}
    result = evaluate_case(case, response, trace)
    assert result["passed"] and all(result["checks"].values())
    assert result["diagnostics"]["stage"] == "selected"
    wrong_page = evaluate_case(case, analysis_response(page=2))
    assert not wrong_page["passed"] and wrong_page["failures"] == ["expected_page"]


def test_insufficient_case_rejects_forced_items() -> None:
    case = {"id": "none", "question": "없는 내용", "expected_topic": "탄소",
        "expected_polarity": "insufficient", "expected_pages": [], "notes": "근거 없음"}
    forced = evaluate_case(case, analysis_response())
    assert not forced["passed"] and {"polarity", "citation"}.issubset(forced["failures"])
    empty = {"analysis_status": "insufficient_evidence", "summary": "확인할 수 없습니다",
        "positives": [], "negatives": [], "citations": [], "insufficient_evidence_note": "근거가 부족합니다."}
    assert evaluate_case(case, empty)["passed"]


def test_failure_stage_distinguishes_retrieval_generation_and_validation() -> None:
    case = {"id": "hbm", "question": "HBM 위험", "expected_topic": "HBM|파운드리",
        "expected_polarity": "negative", "expected_pages": [1], "notes": "본문"}
    empty = {"analysis_status": "insufficient_evidence", "summary": "확인할 수 없습니다",
        "positives": [], "negatives": [], "citations": [], "insufficient_evidence_note": "근거 부족"}
    excluded = {"candidates": [], "generated_selection": {"positive": [], "negative": []}}
    assert evaluate_case(case, empty, excluded)["diagnostics"]["stage"] == "retrieval_candidate_excluded"
    candidate = {"chunk_id": "chunk-1", "page_number": 1, "perspective": "negative", "quote": "HBM 출하 저조"}
    not_selected = {"candidates": [candidate], "generated_selection": {"positive": [], "negative": []}}
    assert evaluate_case(case, empty, not_selected)["diagnostics"]["stage"] == "generation_not_selected"
    removed = {"candidates": [candidate], "generated_selection": {"positive": [], "negative": ["chunk-1"]}}
    assert evaluate_case(case, empty, removed)["diagnostics"]["stage"] == "output_validation_removed"


def test_topic_matching_normalizes_pdf_line_break_whitespace() -> None:
    case = {"id": "gap", "question": "긍정 요인", "expected_topic": "밸류 갭 축소|하반기 개선",
        "expected_polarity": "positive", "expected_pages": [1], "notes": "줄바꿈"}
    response = analysis_response(quote="경쟁사와의 밸류 갭 축소 움직임 기대")
    response["positives"][0]["title"] = "밸류갭 축소"
    chunk_id = response["citations"][0]["chunk_id"]
    trace = {"candidates": [{"chunk_id": chunk_id, "page_number": 1, "perspective": "positive",
        "quote": "경쟁사와의 밸류 갭 축소 움직임 기대"}],
        "generated_selection": {"positive": [chunk_id], "negative": []}}
    assert evaluate_case(case, response, trace)["passed"]


@pytest.mark.parametrize("quote", [
    "[ 종목 투자등급 ] 당사는 Buy 의견을 제시합니다. 투자의견 정의",
    "10% 20% 30% 40% 50% 60% 70% 80% 90%",
])
def test_forbidden_evidence_is_detected(quote) -> None:
    assert forbidden_evidence_reason(quote)
