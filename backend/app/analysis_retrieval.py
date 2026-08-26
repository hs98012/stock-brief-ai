import re
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from .embeddings import EmbeddingProvider
from .models import Chunk, Page
from .search import SearchFilters, hybrid_search, tokenize

POSITIVE_QUERY = "실적 매출 영업이익 성장 증가 개선 회복 수요 가격 점유율 HBM AI 파운드리 Foundry LSI 수익성 전망"
NEGATIVE_QUERY = "위험 악재 둔화 하락 감소 부진 적자 손실 지연 경쟁 불확실성 재고 비용 수익성 기대 하회 인증 과제 충당금 일회성 파운드리 Foundry LSI"
BUSINESS_TERMS = set(tokenize(POSITIVE_QUERY + " " + NEGATIVE_QUERY))
HARD_BOILERPLATE = (
    "종목 투자등급", "산업 투자의견", "투자등급 부여 비중", "compliance notice",
    "조사분석자료의 투자등급", "절대수익률이 기대되는 종목", "법적 책임소재",
)
INTERPRETIVE_TERMS = ("전망", "증가", "감소", "개선", "회복", "둔화", "부진", "적자", "흑자", "성장", "수요", "위험", "영업이익", "매출")
STRONG_NEGATIVE_PATTERN = re.compile(
    r"기대치.{0,20}하회|기대를.{0,20}하회|이익 쇼크|일회성 비용|충당금|저조|더딘 회복|"
    r"인증.{0,20}과제|불확실|가격 저항|FCF 악화|Capex 감소|적자\s*상태|"
    r"영업이익(?:률)?[\s\S]{0,700}Foundry/LS[\s\S]{0,160}-\d", re.IGNORECASE)
STRONG_POSITIVE_PATTERN = re.compile(
    r"가격 상승|출하량 증가|이익 개선|실적 개선|가동률 상승|적자 축소|수요 증가|점유율 상승|"
    r"점유율.{0,20}(?:상승|확대)|매출.{0,20}증대|HBM4.{0,20}판매|풀스택 제조 역량|"
    r"턴키.{0,40}(?:확대|확장|기대 요인)|ASP.{0,20}(?:상승|증가)", re.IGNORECASE)
GENERAL_SUMMARY_POSITIVE_PATTERN = re.compile(r"하반기.{0,30}실적 모멘텀|밸류.{0,10}갭.{0,10}축소|악재.{0,15}해소")
QUESTION_STOPWORDS = {"보고서", "읽고", "주식", "초보자", "관점", "호재", "악재", "각각", "최대", "개까지",
    "요약해줘", "설명해줘", "무엇", "무엇이야", "어떤", "확인", "기업", "회사", "분석해줘", "근거", "이유", "제시한"}
GENERIC_FOCUS_TERMS = {"실적", "위험", "요인", "전망", "긍정", "부정", "시장", "기대", "내용"}


def is_boilerplate(text: str) -> bool:
    lowered = text.casefold()
    if any(term in lowered for term in HARD_BOILERPLATE):
        return True
    rating_terms = sum(term in lowered for term in ("buy(매수)", "hold(보유)", "sell(매도)", "목표주가", "투자의견"))
    has_business_context = any(term in lowered for term in INTERPRETIVE_TERMS)
    return rating_terms >= 2 and not has_business_context


def is_contextless_numeric_fragment(text: str) -> bool:
    compact = re.sub(r"\s+", "", text)
    if not compact:
        return True
    numeric = len(re.findall(r"[\d%.,+\-]", compact))
    numeric_ratio = numeric / len(compact)
    percent_count = text.count("%")
    has_table_context = any(term in text for term in (
        "실적 전망", "전년 대비", "증감률", "주요 가정", "영업이익", "영업이익률", "Foundry/LS"))
    return percent_count >= 5 and numeric_ratio >= 0.42 and not has_table_context


def _is_standalone_ocr_noise(value: str) -> bool:
    compact = value.strip()
    return bool(compact and len(compact) <= 5 and re.fullmatch(r"[A-Za-z가-힣]+", compact))


def _page_table_excerpt(db: Session, chunk_id: UUID, source: str) -> str | None:
    if not hasattr(db, "get") or "Foundry/LS" not in source:
        return None
    chunk = db.get(Chunk, chunk_id)
    if chunk is None:
        return None
    page = db.get(Page, chunk.page_id)
    if page is None:
        return None
    page_text = page.final_text
    foundry_start = page_text.find("Foundry/LS", chunk.char_start)
    if foundry_start < 0:
        return None
    line_end = page_text.find("\n", foundry_start)
    line_end = len(page_text) if line_end < 0 else line_end
    window_start = max(0, foundry_start - 3500)
    prefix = page_text[window_start:foundry_start]
    table_markers = [prefix.rfind(marker) for marker in ("표 2.", "표 1.", "Table 2", "Table 1")]
    marker = max(table_markers)
    if marker < 0:
        return None
    table_start = window_start + marker
    table_prefix = page_text[table_start:foundry_start]
    has_period = bool(re.search(r"20\d{2}|\dQ\d{2}", table_prefix, re.IGNORECASE))
    if not has_period:
        return None
    # A whole OCR table is unreadable. Prefer the first operating-profit metric and its
    # immediately following Foundry/LS row; this remains one exact, contiguous DB substring.
    profit_match = re.search(r"(?:^|\n)영업이익(?!률)", page_text[table_start:foundry_start])
    profit_start = table_start + profit_match.start() + (1 if profit_match and profit_match.group().startswith("\n") else 0) if profit_match else -1
    if profit_start >= 0:
        profit_row = page_text.find("Foundry/LS", profit_start)
        margin_start = page_text.find("영업이익률", profit_start)
        if profit_row >= 0 and (margin_start < 0 or profit_row < margin_start):
            profit_end = page_text.find("\n", profit_row)
            profit_end = len(page_text) if profit_end < 0 else profit_end
            excerpt = page_text[profit_start:profit_end].strip()
            if len(excerpt) <= 700 and re.search(r"Foundry/LS[\s|]*-\d", excerpt, re.IGNORECASE):
                return excerpt
    return None


def readable_excerpt(text: str, query: str, max_chars: int = 320, focus_query: str | None = None,
    preferred_pattern: re.Pattern | None = None) -> str | None:
    source = text.strip()
    if not source or is_contextless_numeric_fragment(source):
        return None
    contains_rating_text = any(term in source for term in ("목표주가", "투자의견", "Buy", "Sell", "Hold"))
    if len(source) <= max_chars and "\n" not in source and not contains_rating_text:
        return source
    if preferred_pattern is STRONG_NEGATIVE_PATTERN and "Foundry/LS" in source:
        match = preferred_pattern.search(source)
        if match:
            foundry_start = source.find("Foundry/LS", match.start())
            line_end = source.find("\n", foundry_start)
            line_end = len(source) if line_end < 0 else line_end
            header_positions = [source.rfind(header, 0, foundry_start)
                for header in ("영업이익률", "영업이익")]
            header_start = max(header_positions)
            if header_start >= 0 and line_end - header_start <= 700:
                table_excerpt = source[header_start:line_end].strip()
                if table_excerpt in text:
                    return table_excerpt
    focus_terms = set(tokenize(focus_query or query))
    terms = focus_terms | BUSINESS_TERMS
    spans = [match for match in re.finditer(r".+?(?:(?<!\d)[.!?。](?!\d)|\n|$)", source) if match.group().strip()]
    if not spans:
        return source[:max_chars].strip()

    def score(match) -> tuple[int, int]:
        value = match.group()
        value_tokens = tokenize(value)
        overlap = sum(token in terms for token in value_tokens)
        focus_overlap = sum(token in focus_terms for token in value_tokens)
        interpretation = sum(term in value for term in INTERPRETIVE_TERMS)
        perspective_match = 1 if preferred_pattern and preferred_pattern.search(value) else 0
        hangul = len(re.findall(r"[가-힣]", value))
        return focus_overlap * 8 + overlap * 2 + interpretation * 4 + perspective_match * 30 + min(hangul // 20, 5), -match.start()

    best = max(spans, key=score)
    if score(best)[0] <= 0:
        return None
    best_index = spans.index(best)
    start, end = best.start(), best.end()
    for neighbor_index in range(best_index - 1, -1, -1):
        candidate = spans[neighbor_index]
        if (_is_standalone_ocr_noise(candidate.group()) or end - candidate.start() > max_chars
                or any(term in candidate.group() for term in ("목표주가", "투자의견", "Buy", "Sell", "Hold"))):
            break
        start = candidate.start()
        if end - start >= 160:
            break
    for neighbor_index in range(best_index + 1, len(spans)):
        candidate = spans[neighbor_index]
        if (_is_standalone_ocr_noise(candidate.group()) or candidate.end() - start > max_chars
                or any(term in candidate.group() for term in ("목표주가", "투자의견", "Buy", "Sell", "Hold"))):
            break
        end = candidate.end()
        if end - start >= 220:
            break
    excerpt = source[start:end].strip()
    if len(excerpt) > max_chars:
        # Keep the highest-scoring sentence in view. Generic negative terms before it must not crop out HBM/foundry context.
        center = ((best.start() + best.end()) // 2) - start
        local_start = max(0, min(center - max_chars // 2, len(excerpt) - max_chars))
        excerpt = excerpt[local_start:local_start + max_chars].strip()
    return excerpt if excerpt and excerpt in text else None


def question_focus_terms(question: str) -> set[str]:
    normalized = []
    for token in tokenize(question):
        for suffix in ("에서", "으로", "에게", "까지", "와", "과", "을", "를", "은", "는", "이", "가", "의"):
            if token.endswith(suffix) and len(token) > len(suffix) + 1:
                token = token[:-len(suffix)]
                break
        if token not in QUESTION_STOPWORDS and len(token) >= 2:
            normalized.append(token)
    return set(normalized)


def collect_analysis_evidence(db: Session, document_id: UUID, question: str, top_k: int,
    provider: EmbeddingProvider) -> list[dict]:
    # Three document-scoped queries are small enough for exact cosine scans. This avoids the local
    # ARM pgvector HNSW backend-process exits observed during long evaluation runs without changing
    # embeddings, cosine distance, BM25 candidates, document filters or RRF fusion.
    bind = getattr(db, "bind", None)
    if bind is not None and bind.dialect.name == "postgresql":
        db.execute(text("SET LOCAL enable_indexscan = off"))
        db.execute(text("SET LOCAL enable_bitmapscan = off"))
    general_summary_question = "호재" in question and "악재" in question and "요약" in question
    queries = ((question, POSITIVE_QUERY, NEGATIVE_QUERY) if general_summary_question
        else (question, f"{question} {POSITIVE_QUERY}", f"{question} {NEGATIVE_QUERY}"))
    combined: dict[UUID, dict] = {}
    scores: dict[UUID, float] = {}
    candidate_k = min(20, max(15, top_k))
    focus_terms = question_focus_terms(question)
    for query in queries:
        execution = hybrid_search(db, query, candidate_k, SearchFilters(document_id=document_id), provider)
        for result in execution.results:
            chunk_id = result["chunk_id"]
            combined[chunk_id] = result
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1 / (20 + result["rank"])

    has_pure_positive = any(STRONG_POSITIVE_PATTERN.search(result["quote"])
        and not STRONG_NEGATIVE_PATTERN.search(result["quote"]) for result in combined.values())

    ranked = []
    for chunk_id, result in combined.items():
        original = result["quote"]
        if is_boilerplate(original):
            continue
        positive_match = STRONG_POSITIVE_PATTERN.search(original)
        negative_match = STRONG_NEGATIVE_PATTERN.search(original)
        asks_positive = any(term in question for term in ("긍정", "호재", "개선 전망", "경쟁력"))
        asks_negative = any(term in question for term in ("부정", "악재", "위험", "부진", "손실", "적자", "부담"))
        mixed_prefers_negative = bool(general_summary_question and positive_match and negative_match
            and has_pure_positive)
        if mixed_prefers_negative:
            excerpt_query = f"{question} {NEGATIVE_QUERY}"
            perspective = "negative"
            preferred_pattern = STRONG_NEGATIVE_PATTERN
        elif positive_match and ((asks_positive and not asks_negative) or general_summary_question):
            excerpt_query = f"{question} {POSITIVE_QUERY}"
            perspective = "positive"
            preferred_pattern = STRONG_POSITIVE_PATTERN
        elif negative_match:
            excerpt_query = f"{question} {NEGATIVE_QUERY}"
            perspective = "negative"
            preferred_pattern = STRONG_NEGATIVE_PATTERN
        elif positive_match:
            excerpt_query = f"{question} {POSITIVE_QUERY}"
            perspective = "positive"
            preferred_pattern = STRONG_POSITIVE_PATTERN
        else:
            excerpt_query = question
            perspective = "neutral"
            preferred_pattern = None
        scoring_pattern = (GENERAL_SUMMARY_POSITIVE_PATTERN
            if general_summary_question and perspective == "positive" and GENERAL_SUMMARY_POSITIVE_PATTERN.search(original)
            else preferred_pattern)
        excerpt = readable_excerpt(original, excerpt_query, focus_query=question, preferred_pattern=scoring_pattern)
        if perspective == "negative" and "Foundry/LS" in original:
            excerpt = _page_table_excerpt(db, chunk_id, original) or excerpt
        if not excerpt:
            continue
        company_terms = set(tokenize(str(result.get("company_name", ""))))
        required_focus = focus_terms - company_terms - GENERIC_FOCUS_TERMS
        perspective_requested = ((perspective == "positive" and asks_positive)
            or (perspective == "negative" and asks_negative))
        semantically_direct = bool(perspective_requested and preferred_pattern and preferred_pattern.search(excerpt))
        if required_focus and not (set(tokenize(excerpt)) & required_focus) and not semantically_direct:
            continue
        direct_terms = len(set(tokenize(excerpt)) & BUSINESS_TERMS)
        if direct_terms == 0:
            continue
        item = dict(result)
        item["quote"] = excerpt
        item["analysis_perspective"] = perspective
        item["analysis_relevance_score"] = scores[chunk_id] + direct_terms / 100
        ranked.append(item)
    ranked.sort(key=lambda item: (-item["analysis_relevance_score"], item["page_number"], str(item["chunk_id"])))
    if general_summary_question:
        positive = [item for item in ranked if item["analysis_perspective"] == "positive"][:3]
        negative = [item for item in ranked if item["analysis_perspective"] == "negative"][:3]
        selected_ids = {item["chunk_id"] for item in positive + negative}
        remainder = [item for item in ranked if item["chunk_id"] not in selected_ids]
        return (positive + negative + remainder)[:top_k]
    return ranked[:top_k]
