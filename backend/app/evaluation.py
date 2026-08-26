import re
from dataclasses import dataclass
from datetime import date
from typing import Any
from uuid import UUID


VALID_POLARITIES = {"positive", "negative", "insufficient"}
BOILERPLATE_PATTERNS = (
    "투자의견 정의", "투자의견 및 목표주가", "매수 비중", "매도 비중",
    "산업별 의견", "의견 산정", "면책", "본 자료는", "투자자 자신의 판단",
)


@dataclass(frozen=True)
class DocumentSelector:
    filename: str
    company_name: str
    published_at: str
    document_type: str


def validate_fixture(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("schema_version") != 1:
        raise ValueError("schema_version은 1이어야 합니다.")
    document = payload.get("document")
    if not isinstance(document, dict):
        raise ValueError("document 객체가 필요합니다.")
    required_document = ("filename", "company_name", "published_at", "document_type")
    if any(not document.get(field) for field in required_document):
        raise ValueError(f"document에는 {', '.join(required_document)}가 필요합니다.")
    date.fromisoformat(document["published_at"])
    cases = payload.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("cases는 하나 이상의 평가 케이스 배열이어야 합니다.")
    required_case = ("id", "question", "expected_topic", "expected_polarity", "expected_pages", "notes")
    seen_ids: set[str] = set()
    for case in cases:
        if not isinstance(case, dict) or any(field not in case for field in required_case):
            raise ValueError(f"각 case에는 {', '.join(required_case)}가 필요합니다.")
        if not all(isinstance(case[field], str) and case[field].strip()
                for field in ("id", "question", "expected_topic", "expected_polarity", "notes")):
            raise ValueError("case 문자열 필드는 비어 있을 수 없습니다.")
        if case["id"] in seen_ids:
            raise ValueError(f"중복 case id: {case['id']}")
        seen_ids.add(case["id"])
        if case["expected_polarity"] not in VALID_POLARITIES:
            raise ValueError("expected_polarity는 positive, negative, insufficient 중 하나여야 합니다.")
        pages = case["expected_pages"]
        if not isinstance(pages, list) or any(not isinstance(page, int) or page < 1 for page in pages):
            raise ValueError("expected_pages는 1 이상의 정수 배열이어야 합니다.")
        if case["expected_polarity"] != "insufficient" and not pages:
            raise ValueError("positive/negative case에는 expected_pages가 필요합니다.")
    return payload


def match_document(documents: list[dict[str, Any]], selector: DocumentSelector) -> dict[str, Any] | None:
    matches = [document for document in documents
        if document.get("filename") == selector.filename
        and document.get("company_name") == selector.company_name
        and document.get("published_at") == selector.published_at
        and document.get("document_type") == selector.document_type]
    if len(matches) > 1:
        raise ValueError("문서 식별 정보와 일치하는 DB 문서가 둘 이상입니다. --document-id를 사용하세요.")
    return matches[0] if matches else None


def _has_korean(value: str) -> bool:
    return bool(re.search(r"[가-힣]", value))


def _numeric_percent_fragment(value: str) -> bool:
    tokens = re.findall(r"\S+", value)
    if len(tokens) < 8:
        return False
    numeric = sum(bool(re.fullmatch(r"[-+]?\(?[\d,.]+%?\)?", token)) for token in tokens)
    alpha = sum(bool(re.search(r"[가-힣A-Za-z]", token)) for token in tokens)
    return numeric / len(tokens) >= 0.65 and alpha < 3


def forbidden_evidence_reason(quote: str) -> str | None:
    compact = re.sub(r"\s+", " ", quote).casefold()
    for pattern in BOILERPLATE_PATTERNS:
        if pattern.casefold() in compact:
            return f"일반 안내/면책 근거 포함: {pattern}"
    if _numeric_percent_fragment(quote):
        return "문맥 없는 숫자·백분율 나열 근거 포함"
    return None


def _topic_terms(case: dict[str, Any]) -> list[str]:
    return [term.strip().casefold() for term in re.split(r"[|/]", case["expected_topic"]) if term.strip()]


def _topic_matches(terms: list[str], value: str) -> bool:
    compact_value = re.sub(r"\s+", "", value).casefold()
    return any(re.sub(r"\s+", "", term) in compact_value for term in terms)


def classify_failure_stage(case: dict[str, Any], trace: dict[str, Any] | None,
    final_selected_ids: set[str]) -> dict[str, Any]:
    if case["expected_polarity"] == "insufficient" or not trace:
        return {"stage": "not_applicable" if case["expected_polarity"] == "insufficient" else "trace_unavailable"}
    expected = case["expected_polarity"]
    terms = _topic_terms(case)
    candidates = trace.get("candidates", [])
    relevant = [row for row in candidates if row.get("page_number") in case["expected_pages"]
        and _topic_matches(terms, str(row.get("quote", "")))]
    expected_candidates = [row for row in relevant if row.get("perspective") == expected]
    generated_ids = set(trace.get("generated_selection", {}).get(expected, []))
    relevant_ids = {str(row.get("chunk_id")) for row in expected_candidates}
    if not relevant:
        stage = "retrieval_candidate_excluded"
    elif not expected_candidates:
        stage = "retrieval_wrong_perspective"
    elif not generated_ids.intersection(relevant_ids):
        stage = "generation_not_selected"
    elif not final_selected_ids.intersection(relevant_ids):
        stage = "output_validation_removed"
    else:
        stage = "selected"
    return {"stage": stage, "relevant_candidate_pages": sorted({row["page_number"] for row in relevant}),
        "expected_perspective_candidate_ids": sorted(relevant_ids),
        "generated_selected_ids": sorted(generated_ids), "validated_selected_ids": sorted(final_selected_ids)}


def evaluate_case(case: dict[str, Any], response: dict[str, Any], trace: dict[str, Any] | None = None) -> dict[str, Any]:
    polarity = case["expected_polarity"]
    items = response.get("positives", []) if polarity == "positive" else response.get("negatives", [])
    citations_by_id = {str(row.get("chunk_id")): row for row in response.get("citations", [])}
    selected_ids = {str(chunk_id) for item in items for chunk_id in item.get("evidence_chunk_ids", [])}
    selected_citations = [citations_by_id[chunk_id] for chunk_id in selected_ids if chunk_id in citations_by_id]
    exposed_text = " ".join([str(response.get("summary", ""))]
        + [str(item.get(field, "")) for item in response.get("positives", []) + response.get("negatives", [])
            for field in ("title", "reason")]
        + [str(response.get("insufficient_evidence_note") or "")])
    analysis_success = response.get("analysis_status") in {"completed", "insufficient_evidence"}
    korean_output = _has_korean(exposed_text)
    if polarity == "insufficient":
        polarity_ok = not response.get("positives") and not response.get("negatives")
        citation_ok = not response.get("citations")
        page_ok = True
        topic_ok = True
    else:
        polarity_ok = bool(items)
        citation_ok = bool(selected_citations) and len(selected_citations) == len(selected_ids)
        actual_pages = {int(row["page_number"]) for row in selected_citations}
        page_ok = bool(actual_pages.intersection(case["expected_pages"]))
        topic_terms = _topic_terms(case)
        topic_text = " ".join([str(item.get("title", "")) + " " + str(item.get("reason", "")) for item in items]
            + [str(row.get("quote", "")) for row in selected_citations]).casefold()
        topic_ok = _topic_matches(topic_terms, topic_text)
    forbidden = [reason for row in selected_citations if (reason := forbidden_evidence_reason(str(row.get("quote", ""))))]
    checks = {
        "analysis_success": analysis_success,
        "korean_output": korean_output,
        "polarity": polarity_ok,
        "citation": citation_ok,
        "expected_page": page_ok,
        "topic": topic_ok,
        "forbidden_evidence_absent": not forbidden,
    }
    diagnostics = classify_failure_stage(case, trace, selected_ids)
    return {
        "id": case["id"], "question": case["question"], "expected_polarity": polarity,
        "expected_pages": case["expected_pages"], "actual_pages": sorted({row.get("page_number") for row in selected_citations}),
        "passed": all(checks.values()), "checks": checks, "failures": [name for name, passed in checks.items() if not passed],
        "forbidden_reasons": forbidden, "diagnostics": diagnostics,
    }


def validate_document_id(value: str) -> str:
    return str(UUID(value))
