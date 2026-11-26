import re
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import text
from sqlalchemy.orm import Session

from .table_evidence import temporal_context
from .embeddings import EmbeddingProvider
from .citation_display import TRANSLITERATION_ALIASES, has_damaging_ocr_noise, is_metadata_line
from .models import Chunk, Page, Document
from .evidence_facts import economic_facts, matching_text
from .search import SearchFilters, hybrid_search, tokenize

POSITIVE_QUERY = "매출 영업이익 순이익 수익성 판매량 수요 생산성 수주 증가 개선 회복 기대치 상회"
NEGATIVE_QUERY = "비용 원가 충당금 손실 손해율 증가 영업이익 기대치 하회 수요 둔화 가격 하락 위험"
BUSINESS_TERMS = set(tokenize(POSITIVE_QUERY + " " + NEGATIVE_QUERY))
HARD_BOILERPLATE = (
    "종목 투자등급", "산업 투자의견", "투자등급 부여 비중", "compliance notice",
    "조사분석자료의 투자등급", "절대수익률이 기대되는 종목", "법적 책임소재",
)
INTERPRETIVE_TERMS = ("전망", "증가", "감소", "개선", "회복", "둔화", "부진", "적자", "흑자", "성장", "수요", "위험", "영업이익", "매출")
# Compatibility scoring for excerpt previews. Polarity decisions use economic_facts.
STRONG_NEGATIVE_PATTERN = re.compile(r"기대치.{0,20}하회|비용.{0,20}증가|손실.{0,20}증가|수요.{0,20}둔화|위험|적자\s*상태", re.I)
STRONG_POSITIVE_PATTERN = re.compile(r"매출.{0,20}(?:증가|증대)|점유율.{0,20}(?:상승|확대)|수익성.{0,20}개선|가동률.{0,20}상승|적자.{0,20}축소", re.I)
GENERAL_SUMMARY_POSITIVE_PATTERN = STRONG_POSITIVE_PATTERN
QUESTION_STOPWORDS = {"보고서", "읽고", "주식", "초보자", "관점", "호재", "악재", "각각", "최대", "개까지",
    "요약해줘", "설명해줘", "무엇", "무엇이야", "어떤", "확인", "기업", "회사", "분석해줘", "근거", "이유", "제시한"}
GENERIC_FOCUS_TERMS = {"실적", "위험", "요인", "전망", "긍정", "부정", "시장", "기대", "내용"}


def _sentence_spans(source: str) -> list[tuple[int, int]]:
    """Return exact, complete sentence/paragraph ranges within a chunk."""
    ranges: list[tuple[int, int]] = []
    structural = re.compile(r"\n\s*\n|\n(?=(?:[-•·]\s*|주요 이슈|투자포인트|주가전망|요약 실적))")
    block_starts = [0] + [match.end() for match in structural.finditer(source)]
    block_ends = [match.start() for match in structural.finditer(source)] + [len(source)]
    base_blocks = list(zip(block_starts, block_ends, strict=True))
    metadata_ranges = []
    offset = 0
    for line in source.splitlines(keepends=True):
        if is_metadata_line(line):
            metadata_ranges.append((offset, offset + len(line)))
        offset += len(line)
    blocks: list[tuple[int, int]] = []
    for block_start, block_end in base_blocks:
        cursor = block_start
        for metadata_start, metadata_end in metadata_ranges:
            if metadata_end <= cursor or metadata_start >= block_end:
                continue
            if cursor < metadata_start:
                blocks.append((cursor, metadata_start))
            cursor = max(cursor, metadata_end)
        if cursor < block_end:
            blocks.append((cursor, block_end))
    for block_start, block_end in blocks:
        block = source[block_start:block_end]
        # Standalone headings are navigation, not evidence. A bullet marker is not
        # part of the claim but all returned quote text remains an exact substring.
        heading = re.match(r"(?:주요 이슈(?: 및 실적전망)?|투자포인트(?: 및 결론)?|주가전망(?: 및 Valuation)?|요약 실적(?: 및 Valuation)?)\s*\n", block)
        content_start = block_start + (heading.end() if heading else 0)
        while content_start < block_end and source[content_start] in " \t\r\n-•·":
            content_start += 1
        cursor = content_start
        for match in re.finditer(r".+?(?<!\d)[.!?。](?!\d)(?=\s|$)", source[content_start:block_end], re.DOTALL):
            start, end = content_start + match.start(), content_start + match.end()
            while start < end and source[start].isspace():
                start += 1
            if start < end:
                ranges.append((start, end))
            cursor = end
        # PDF extraction often omits a final period before a heading. Keep only a
        # predicate-ending tail; do not accept arbitrary truncated text.
        start, end = cursor, block_end
        while start < end and source[start].isspace():
            start += 1
        while end > start and source[end - 1].isspace():
            end -= 1
        value = source[start:end]
        if len(value) >= 24 and re.search(
                r"(?:예상|전망|판단|기록|시현|확대|상승|하락|감소|증가)(?:됨|된다|될 것으로)?$", value):
            ranges.append((start, end))
    return sorted(set(ranges))


def _span_quality(value: str) -> tuple[str, str | None]:
    if not value.strip():
        return "excluded", "empty"
    if is_metadata_line(value) or any(is_metadata_line(line) for line in value.splitlines()):
        return "excluded", "contact_or_metadata"
    if is_boilerplate(value):
        return "excluded", "boilerplate"
    if has_damaging_ocr_noise(value) or any(re.fullmatch(r"\s*(?:be|eens)\s*", line, re.I) for line in value.splitlines()):
        return "excluded", "ocr_noise"
    if is_contextless_numeric_fragment(value):
        return "excluded", "contextless_numeric_fragment"
    return "valid", None


def evidence_spans(result: dict, query: str, *, table_excerpt: str | None = None) -> list[dict]:
    """Split one retrieval chunk into traceable sentence/table evidence spans."""
    source = result["quote"]
    source_chunk_id = result["chunk_id"]
    chunk_start = int(result.get("chunk_char_start", 0))
    candidates: list[tuple[int, int, str]] = [(start, end, "text") for start, end in _sentence_spans(source)]
    line_offset = 0
    for line in source.splitlines(keepends=True):
        if is_metadata_line(line):
            candidates.append((line_offset, line_offset + len(line.rstrip("\r\n")), "metadata"))
        line_offset += len(line)
    if table_excerpt and table_excerpt in source:
        local_start = source.index(table_excerpt)
        candidates.append((local_start, local_start + len(table_excerpt), "table"))
    spans: list[dict] = []
    for local_start, local_end, span_kind in sorted(set(candidates)):
        quote = source[local_start:local_end].strip()
        trim_start = source[local_start:local_end].find(quote) if quote else 0
        local_start += max(trim_start, 0)
        local_end = local_start + len(quote)
        quality_status, exclusion_reason = _span_quality(quote)
        if span_kind == "table" and table_excerpt is not None:
            # Only document_candidates can certify a fully aligned table row.
            quality_status, exclusion_reason = "excluded", "table_structure"
        facts = economic_facts(quote)
        directions = {fact["polarity"] for fact in facts if fact["polarity"] != "ambiguous"}
        perspectives = [next(iter(directions)) if len(directions) == 1 else "ambiguous" if facts else "neutral"]
        for perspective in perspectives:
            span_id = uuid5(NAMESPACE_URL,
                f"stock-brief-ai:{source_chunk_id}:{local_start}:{local_end}:{perspective}")
            spans.append({**result, "chunk_id": span_id, "source_chunk_id": source_chunk_id,
                "char_start": chunk_start + local_start, "char_end": chunk_start + local_end,
                "quote": quote, "display_quote": matching_text(quote), "span_kind": span_kind, "facts": facts,
                "table_verified": False, "temporal_context": temporal_context(quote, chunk_start + local_start),
                "analysis_perspective": perspective, "quality_status": quality_status,
                "exclusion_reason": exclusion_reason})
    accepted = [span for span in spans if span["quality_status"] == "valid"]
    # Preserve legacy IDs when the chunk yields one usable span. Multi-span chunks
    # use deterministic IDs so disjoint evidence can be selected independently.
    if len(accepted) == 1:
        accepted[0]["chunk_id"] = source_chunk_id
    return spans


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
        "실적 전망", "전년 대비", "증감률", "주요 가정", "영업이익", "영업이익률"))
    return percent_count >= 5 and numeric_ratio >= 0.42 and not has_table_context


def _is_standalone_ocr_noise(value: str) -> bool:
    compact = value.strip()
    return bool(compact and len(compact) <= 5 and re.fullmatch(r"[A-Za-z가-힣]+", compact))


def readable_excerpt(text: str, query: str, max_chars: int = 320, focus_query: str | None = None,
    preferred_pattern: re.Pattern | None = None) -> str | None:
    source = text.strip()
    if not source or is_contextless_numeric_fragment(source):
        return None
    contains_rating_text = any(term in source for term in ("목표주가", "투자의견", "Buy", "Sell", "Hold"))
    if len(source) <= max_chars and "\n" not in source and not contains_rating_text:
        return source
    focus_terms = set(tokenize(focus_query or query))
    terms = focus_terms | BUSINESS_TERMS
    metadata_ranges = []
    offset = 0
    for line in source.splitlines(keepends=True):
        if is_metadata_line(line):
            metadata_ranges.append((offset, offset + len(line)))
        offset += len(line)
    spans = []
    for match in re.finditer(r".+?(?<!\d)[.!?。](?!\d)(?=\s|$)", source, re.DOTALL):
        start, end = match.start(), match.end()
        overlapping = [range_end for range_start, range_end in metadata_ranges if range_start < end and range_end > start]
        if overlapping:
            start = max(overlapping)
        while start < end and source[start].isspace():
            start += 1
        if start < end and source[start:end].strip():
            spans.append((start, end))
    if not spans:
        return None

    def score(span) -> tuple[int, int]:
        value = source[span[0]:span[1]]
        value_tokens = tokenize(value)
        overlap = sum(token in terms for token in value_tokens)
        focus_overlap = sum(token in focus_terms for token in value_tokens)
        interpretation = sum(term in value for term in INTERPRETIVE_TERMS)
        perspective_match = 1 if preferred_pattern and preferred_pattern.search(value) else 0
        hangul = len(re.findall(r"[가-힣]", value))
        return focus_overlap * 8 + overlap * 2 + interpretation * 4 + perspective_match * 30 + min(hangul // 20, 5), -span[0]

    best = max(spans, key=score)
    if score(best)[0] <= 0:
        return None
    best_index = spans.index(best)
    start, end = best
    for neighbor_index in range(best_index - 1, -1, -1):
        candidate = spans[neighbor_index]
        candidate_text = source[candidate[0]:candidate[1]]
        if (any(_is_standalone_ocr_noise(line) for line in candidate_text.splitlines()) or end - candidate[0] > max_chars
                or any(term in candidate_text for term in ("목표주가", "투자의견", "Buy", "Sell", "Hold"))):
            break
        start = candidate[0]
        if end - start >= 160:
            break
    for neighbor_index in range(best_index + 1, len(spans)):
        candidate = spans[neighbor_index]
        candidate_text = source[candidate[0]:candidate[1]]
        if (any(_is_standalone_ocr_noise(line) for line in candidate_text.splitlines()) or candidate[1] - start > max_chars
                or any(term in candidate_text for term in ("목표주가", "투자의견", "Buy", "Sell", "Hold"))):
            break
        end = candidate[1]
        if end - start >= 220:
            break
    excerpt = source[start:end].strip()
    if len(excerpt) > max_chars or has_damaging_ocr_noise(excerpt):
        best_excerpt = source[best[0]:best[1]].strip()
        excerpt = best_excerpt if len(best_excerpt) <= max_chars and not has_damaging_ocr_noise(best_excerpt) else ""
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


def _focus_term_in(term: str, text: str) -> bool:
    """Literal match, or the same word in the other script (existing transliteration table only)."""
    if term in text:
        return True
    for english, korean in TRANSLITERATION_ALIASES.items():
        if term == korean and re.search(rf"(?<![a-z]){english}(?![a-z])", text):
            return True
        if term == english and korean in text:
            return True
    return False


def explicit_years(value: str) -> set[int]:
    years = {int(year) for year in re.findall(r"(?<!\d)(20\d{2})(?!\d)", value)}
    years.update(2000 + int(year) for year in re.findall(r"(?:[1-4]Q|FY)(\d{2})(?!\d)", value, re.I))
    return years


from .verification_cache import request_verified


def _note_early_exit(diagnostics: dict | None, reason: str) -> None:
    if diagnostics is not None:
        diagnostics["early_exit"] = reason


def _note_exclusion(diagnostics: dict | None, span: dict, filter_name: str, reason: str | None) -> None:
    # Evaluation-only bookkeeping; never read by retrieval or selection.
    if diagnostics is None:
        return
    diagnostics.setdefault("filter_exclusions", []).append(
        {"page_number": span["page_number"], "filter": filter_name, "reason": reason})
    counts = diagnostics.setdefault("filter_counts", {})
    counts[filter_name] = counts.get(filter_name, 0) + 1


@request_verified
def collect_analysis_evidence(db: Session, document_id: UUID, question: str, top_k: int,
    provider: EmbeddingProvider, diagnostics: dict | None = None) -> list[dict]:
    from .evidence_bundle import requirement_resolution
    resolution = requirement_resolution(question)
    if diagnostics is not None:
        diagnostics['requirement_resolution'] = resolution
    if resolution['status'] not in {'supported_requirement', 'no_factual_requirement_applicable'}:
        if diagnostics is not None:
            diagnostics['coverage_complete'] = False
        _note_early_exit(diagnostics, 'requirement_unsupported')
        return []
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
    compound_pack = None
    for index, query in enumerate(queries):
        options = {'strict_requirements': True} if index == 0 and resolution['requirements'] else {}
        execution = hybrid_search(db, query, candidate_k, SearchFilters(document_id=document_id), provider, **options)
        if index == 0 and resolution['requirements'] and not execution.requirements:
            if diagnostics is not None:
                diagnostics['coverage_complete'] = False
            _note_early_exit(diagnostics, 'requirement_unmatched')
            return []
        if index == 0 and execution.requirements:
            compound_pack = execution.evidence_pack or []
            if diagnostics is not None:
                diagnostics['coverage_complete'] = execution.coverage_complete
                diagnostics['requirements'] = execution.requirements
            if not execution.coverage_complete:
                _note_early_exit(diagnostics, 'coverage_incomplete')
                return []
        for result in execution.results:
            chunk_id = result["chunk_id"]
            combined[chunk_id] = result
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1 / (20 + result["rank"])

    from .document_candidates import document_candidates
    if hasattr(db, "query"):
        candidates = document_candidates(db, document_id)
    else:
        candidates = [span for row in combined.values() for span in evidence_spans(row, question)]
    # Lexical overlap such as 목표 -> 목표주가 cannot establish a requested
    # future year's facts. Missing explicit years must fail closed, even when
    # a nearby business fact is otherwise valid. This is a necessary condition,
    # not proof that matching-year evidence answers the question.
    requested_years = explicit_years(question)
    source_years = explicit_years(" ".join(row["quote"] + " " + " ".join(
        fact.get("period") or "" for fact in row.get("table_evidence", []) if row.get("table_verified"))
        for row in candidates))
    if requested_years - source_years:
        if diagnostics is not None:
            diagnostics["missing_requested_years"] = sorted(requested_years - source_years)
        _note_early_exit(diagnostics, 'missing_years')
        return []
    from .table_evidence import fact_matches_query
    structured = [span for span in candidates if span.get("table_verified") and
                  any(fact_matches_query(fact, question) for fact in span.get("table_evidence", []))]
    ranked = []
    if diagnostics is not None:
        diagnostics.setdefault("filter_exclusions", [])
        diagnostics.setdefault("filter_counts", {})
        diagnostics["required_focus_terms"] = [] if general_summary_question else sorted(
            focus_terms - GENERIC_FOCUS_TERMS)
    for span in candidates:
        perspective = span["analysis_perspective"]
        if span["quality_status"] != "valid":
            if (diagnostics is not None and perspective in ("positive", "negative")
                    and span["exclusion_reason"] in {"ocr_noise", "contextless_numeric_fragment", "table_structure"}):
                diagnostics.setdefault("excluded_pages", {}).setdefault(perspective, set()).add(span["page_number"])
            _note_exclusion(diagnostics, span, "quality", span["exclusion_reason"])
            continue
        if perspective not in ("positive", "negative"):
            _note_exclusion(diagnostics, span, "perspective", perspective)
            continue
        company_terms = set(tokenize(str(span.get("company_name", ""))))
        required_focus = focus_terms - company_terms - GENERIC_FOCUS_TERMS
        if not general_summary_question and required_focus:
            if diagnostics is not None:
                diagnostics["required_focus_terms"] = sorted(required_focus)
            span_text = matching_text(span["quote"]).casefold()
            if not any(_focus_term_in(term.casefold(), span_text) for term in required_focus):
                _note_exclusion(diagnostics, span, "focus", "focus_terms_missing")
                continue
        source_ids = span.get("source_chunk_ids", [span.get("source_chunk_id", span["chunk_id"])])
        span["analysis_relevance_score"] = max((scores.get(source_id, 0) for source_id in source_ids), default=0)
        span["analysis_relevance_score"] += 0.05 * sum(bool(fact.get("comparison")) for fact in span["facts"])
        ranked.append(span)
    ranked.sort(key=lambda item: (-item["analysis_relevance_score"], item["page_number"], item["char_start"]))
    if diagnostics is not None:
        diagnostics["candidate_count"] = len(candidates)
        diagnostics["valid_count"] = len(ranked)
    # Select diverse complete facts, not repeated chunks. Scan coverage is independent
    # of retrieval top-k; top-k limits only the generation packet.
    selected = []
    seen = set()
    ordered = []
    positive = [row for row in ranked if row["analysis_perspective"] == "positive"]
    negative = [row for row in ranked if row["analysis_perspective"] == "negative"]
    for index in range(max(len(positive), len(negative))):
        for group in (positive, negative):
            if index < len(group):
                ordered.append(group[index])
    for span in ordered:
        key = re.sub(r"\s+", "", span["quote"]).casefold()
        if key in seen:
            continue
        if any(span["page_number"] == old["page_number"] and
               max(span["char_start"], old["char_start"]) < min(span["char_end"], old["char_end"])
               for old in selected):
            continue
        selected.append(span)
        seen.add(key)
        if len(selected) >= top_k:
            break
    packet = (structured + selected)[:top_k]
    if compound_pack:
        source_ids = {str(source_id) for row in packet for source_id in
                      row.get('source_chunk_ids', [row.get('source_chunk_id', row['chunk_id'])])}
        if any(str(item['chunk_id']) not in source_ids for item in compound_pack):
            if diagnostics is not None:
                diagnostics['coverage_complete'] = False
            _note_early_exit(diagnostics, 'compound_pack_incomplete')
            return []
    return packet
