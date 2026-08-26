import json
import re
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import update
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from .embeddings import EmbeddingProvider
from .citation_display import citation_display
from .generation import GenerationConfigurationError, GenerationOutputError, GenerationProvider
from .models import AnalysisRun, Document, DocumentType, Page
from .analysis_retrieval import collect_analysis_evidence
from .schemas import AnalysisCitation, AnalysisItem, AnalysisRequest, AnalysisResult, GeneratedAnalysis, GeneratedItem

DISCLAIMER = "이 내용은 투자 권유나 매수·매도·보유 추천이 아니며, 원문 근거를 쉽게 읽기 위한 참고 자료입니다."
INSUFFICIENT_NOTE = "근거가 부족해 추가 항목을 제시하지 않았습니다."
SPECIFIC_FACT_TERMS = ("일회성", "충당금", "재고", "hbm", "파운드리", "디램", "dram", "nand", "낸드",
    "인증", "가동률", "출하량", "가격", "경쟁", "bpsi", "bps", "밸류에이션", "시장 기대치")
SUMMARY_PROHIBITED_TERMS = (
    "매력적", "매수", "매도", "투자기회", "목표주가", "주가상승", "주가하락",
    "주가가오를", "주가가내릴", "주가충격", "수익보장", "수익을보장", "확실한수익",
)
SUMMARY_OUTLOOK_TERMS = ("전망", "예상", "판단", "가능성", "긍정요인", "주의할요인")
SUMMARY_ATTRIBUTION_TERMS = ("보고서", "리포트", "증권사", "공시")


class AnalysisValidationError(RuntimeError):
    pass


def _persist_run(db: Session, run_id: UUID, **values) -> None:
    """Persist once more on a fresh, pre-pinged connection without rerunning generation."""
    try:
        db.execute(update(AnalysisRun).where(AnalysisRun.id == run_id).values(**values))
        db.commit()
        return
    except OperationalError:
        db.rollback()
    with Session(bind=db.get_bind(), expire_on_commit=False) as recovery_db:
        recovery_db.execute(update(AnalysisRun).where(AnalysisRun.id == run_id).values(**values))
        recovery_db.commit()


def _provider_trace(provider: GenerationProvider) -> dict:
    trace = getattr(provider, "generation_trace", {})
    return dict(trace) if isinstance(trace, dict) else {}


def _record_failure(db: Session, run_id: UUID, reason: str, provider: GenerationProvider) -> None:
    _persist_run(db, run_id, status="failed", error_reason=reason[:2000], generated_at=datetime.now(timezone.utc),
        generation_provider=provider.provider_name, generation_model=provider.model,
        result={"_evaluation_trace": {"generation": _provider_trace(provider)}})


def _stored_result(result: AnalysisResult, evidence_results: list[dict], generated: GeneratedAnalysis | None,
    provider: GenerationProvider | None = None) -> dict:
    payload = result.model_dump(mode="json")
    payload["_evaluation_trace"] = {
        "candidates": [{"chunk_id": str(row["chunk_id"]), "page_number": row["page_number"],
            "perspective": row["analysis_perspective"], "quote": row["quote"]} for row in evidence_results],
        "generated_selection": {
            "positive": [str(chunk_id) for item in generated.positives for chunk_id in item.evidence_chunk_ids] if generated else [],
            "negative": [str(chunk_id) for item in generated.negatives for chunk_id in item.evidence_chunk_ids] if generated else [],
        },
        "validated_selection": {
            "positive": [str(chunk_id) for item in result.positives for chunk_id in item.evidence_chunk_ids],
            "negative": [str(chunk_id) for item in result.negatives for chunk_id in item.evidence_chunk_ids],
        },
        "generation": _provider_trace(provider) if provider else {},
    }
    return payload


def _prompt(document: Document, question: str, evidence: dict[str, list[dict]]) -> str:
    metadata = {
        "company_name": document.company_name,
        "stock_code": document.stock_code,
        "document_type": document.document_type.value,
        "issuer": document.issuer,
        "published_at": document.published_at.isoformat(),
    }
    return (
        "당신은 한국 주식 초보자를 위한 금융 문서 분석가입니다. 출력의 summary, title, reason, insufficient_evidence_note는 모두 자연스러운 한국어로만 작성하세요. "
        "아래 evidence packet에 있는 사실만 사용하세요. 호재와 악재는 해당 기업의 실적, 제품, 시장 수요, 가격, 점유율, 수익성 또는 구체적 위험과 직접 연결될 때만 작성하세요. "
        "추상적인 산업 일반론, 데이터가 있다는 사실 자체, 투자등급 정의, 매수·매도 비중, 산업 의견 산정 방식, 면책 문구는 근거로 사용하지 마세요. "
        "원문의 높음/낮음, 증가/감소, 개선/악화 방향을 절대로 뒤집지 말고, 근거 발췌에 직접 쓰인 의미만 설명하세요. "
        "매수·매도·보유 추천, 목표주가 산출, 수익 보장 표현을 하지 마세요. 인용문을 만들지 말고 evidence_chunk_ids에는 "
        "제공된 UUID 문자열만 접두사나 설명 없이 정확히 복사하세요. Buy/Sell/Hold 등급이나 목표주가 자체를 호재·악재로 선정하거나 출력하지 마세요. "
        "각 항목의 reason은 '문서에서 확인된 사실 → 초보자에게 왜 호재 또는 악재인지' 구조의 1~2문장으로 쓰세요. 서로 다른 항목에 같은 chunk_id를 중복 사용하지 마세요. "
        "'초보 투자자에게 긍정적이다'처럼 서비스가 투자 가치를 판단하는 문장은 쓰지 말고, 반드시 '보고서는 … 언급합니다/제시합니다'처럼 문서에 귀속하세요. "
        "각 항목은 자신이 지정한 evidence_chunk_ids의 text만 사용하고, 다른 evidence의 일회성 비용·HBM·파운드리·인증·재고 같은 구체 사실을 섞지 마세요. "
        "positives는 positive_candidates의 ID만, negatives는 negative_candidates의 ID만 사용하세요. neutral_candidates는 summary 문맥에만 사용하세요. "
        "질문이 긍정 요인이나 개선 전망을 묻고 positive_candidates에 질문과 직접 일치하는 근거가 있으면 그 근거로 positive를 작성하세요. "
        "질문이 위험·부진·손실을 묻고 negative_candidates에 질문과 직접 일치하는 근거가 있으면 그 근거로 negative를 작성하세요. 직접 근거가 없을 때는 만들지 마세요. "
        "질문이 문서 전체의 호재와 악재를 함께 요약해 달라는 범용 질문이면, positive_candidates와 negative_candidates 중 해당 기업에 직접 연결된 유효 근거가 있는 관점은 최소 1개 항목으로 설명하세요. 후보가 단순 표 조각·일반론이거나 직접 근거가 없으면 작성하지 마세요. "
        "각 호재·악재는 최소 1개 근거가 있어야 하며 최대 3개입니다. 근거가 부족하면 수를 채우지 말고 "
        f"insufficient_evidence_note에 '{INSUFFICIENT_NOTE}'라고 쓰세요. 증권사 수치와 견해는 증권사 전망 또는 리포트 해석임을 분명히 하세요. "
        "summary는 '확인된 사실 + 초보자 관점의 의미'만 2~4문장으로 쓰세요. 서비스의 판단처럼 매력적이다, 매수·매도, 투자 기회, 목표주가, "
        "주가 상승·하락 예상, 주가 충격 제한, 확정적 수익·성과 전망을 말하지 마세요. 리포트의 해석이나 전망을 설명하는 문장은 반드시 "
        "'보고서는 … 언급합니다' 또는 '보고서는 … 제시합니다'처럼 출처를 문장 안에 귀속하세요. 예를 들어 '현재 주가가 매력적입니다'나 "
        "'주가 충격은 제한적일 것입니다'라고 쓰지 말고, 확인된 실적·제품·수익성 사실과 그 의미를 중립적으로 설명하세요.\n"
        f"질문: {question}\n문서 메타데이터: {json.dumps(metadata, ensure_ascii=False)}\n"
        f"evidence packet: {json.dumps(evidence, ensure_ascii=False)}\n"
        "최종 확인: summary에는 확인된 사실과 초보자 관점의 의미만 쓰고, 매력적·매수·매도·투자 기회·목표주가·주가 상승/하락 예상·"
        "주가 충격 제한 표현을 쓰지 마세요. 전망이나 판단은 반드시 '보고서는 … 언급합니다/제시합니다' 형식으로 귀속하세요."
    )


def _unsafe_text(value: str) -> bool:
    normalized = value.replace(" ", "").casefold()
    prohibited = ("매수하세요", "매도하세요", "보유하세요", "매수를추천", "매도를추천", "매수등급", "매도의견", "보유의견",
        "buyrating", "sellrating", "holdrating", "buyrecommendation", "sellrecommendation", "targetprice",
        "수익을보장", "수익보장", "목표주가를산출", "목표주가를계산")
    return any(term in normalized for term in prohibited)


def _has_hangul(value: str) -> bool:
    return bool(re.search(r"[가-힣]", value))


def _summary_is_safe(value: str, require_korean: bool) -> bool:
    if _unsafe_text(value) or (require_korean and not _has_hangul(value)):
        return False
    compact = re.sub(r"\s+", "", value).casefold()
    if any(term in compact for term in SUMMARY_PROHIBITED_TERMS):
        return False
    if re.search(r"(?:수익|성과).{0,10}(?:확정|보장)", compact):
        return False
    for sentence in re.split(r"(?<=[.!?。])\s+|\n+", value):
        normalized = re.sub(r"\s+", "", sentence).casefold()
        if (any(term in normalized for term in SUMMARY_OUTLOOK_TERMS)
                and not any(term in normalized for term in SUMMARY_ATTRIBUTION_TERMS)):
            return False
    return True


def _item_tone_is_safe(value: str, require_attribution: bool = False) -> bool:
    compact = re.sub(r"\s+", "", value).casefold()
    prohibited = ("초보투자자에게긍정", "투자자에게긍정", "긍정적인요소로작용", "매력적",
        "투자기회", "주가전망", "매수", "매도")
    if _unsafe_text(value) or any(term in compact for term in prohibited):
        return False
    if not require_attribution:
        return True
    for sentence in re.split(r"(?<=[.!?。])\s+|\n+", value):
        normalized = re.sub(r"\s+", "", sentence).casefold()
        if (any(term in normalized for term in ("긍정", "부정", "호재", "악재", "부담", "시사"))
                and not any(term in normalized for term in ("보고서", "리포트", "원문", "증권사전망"))):
            return False
    return True


def _item_supported_by_quotes(item, allowed: dict) -> bool:
    claim = f"{item.title} {item.reason}".casefold()
    evidence_text = " ".join(allowed[chunk_id]["quote"] for chunk_id in item.evidence_chunk_ids).casefold()
    mentioned_specifics = {term for term in SPECIFIC_FACT_TERMS if term in claim}
    aliases = {"파운드리": ("파운드리", "foundry"), "디램": ("디램", "dram"),
        "낸드": ("낸드", "nand")}
    if not all(any(alias in evidence_text for alias in aliases.get(term, (term,)))
            for term in mentioned_specifics):
        return False
    if "파운드리" in claim and "foundry/ls" in evidence_text and re.search(r"-\d", evidence_text):
        return "영업이익" in evidence_text
    return True


def _is_general_summary_question(question: str) -> bool:
    return "호재" in question and "악재" in question and "요약" in question


def _grounded_polarity_fallback(evidence_results: list[dict], perspective: str,
    used_ids: set[UUID], label: str) -> AnalysisItem | None:
    candidate = next((row for row in evidence_results
        if row["analysis_perspective"] == perspective and row["chunk_id"] not in used_ids), None)
    if candidate is None:
        return None
    quote = candidate["quote"].casefold()
    if perspective == "negative" and ("foundry/ls" in quote or "파운드리" in quote):
        if not ("영업이익" in quote and re.search(r"foundry/ls[\s|]*-\d", quote, re.IGNORECASE)):
            return None
        title = "파운드리 수익성 부담"
        reason = ("보고서는 인용된 원문에서 파운드리/LS 부문의 음수 영업이익 또는 영업이익률 수치를 제시합니다. "
            "이는 해당 부문의 수익성 부담을 보여주는 리포트 해석입니다.")
    elif perspective == "positive":
        if "hbm" in quote and "dram" in quote:
            title = "DRAM 수급·HBM 가격 전망"
        elif "hbm" in quote:
            title = "HBM 관련 전망"
        elif "실적" in quote and any(term in quote for term in ("개선", "성장", "증익")):
            title = "실적 개선 전망"
        elif "수요" in quote:
            title = "수요 관련 전망"
        else:
            title = "보고서에서 확인된 긍정 요인"
        reason = ("보고서는 아래 원문에서 증가·개선·수요 확대와 관련된 내용을 제시합니다. "
            "이는 DB 원문에 근거해 긍정 요인으로 분류한 리포트 해석입니다.")
    else:
        title = "보고서에서 확인된 위험 요인"
        reason = ("보고서는 아래 원문에서 감소·부진·손실 또는 불확실성과 관련된 내용을 제시합니다. "
            "이는 DB 원문에 근거해 주의할 요인으로 분류한 리포트 해석입니다.")
    used_ids.add(candidate["chunk_id"])
    return AnalysisItem(title=title, reason=reason, evidence_chunk_ids=[candidate["chunk_id"]],
        interpretation_label=label)


def analyze_document(
    db: Session,
    document: Document,
    request: AnalysisRequest,
    embedding_provider: EmbeddingProvider,
    generation_provider: GenerationProvider,
) -> AnalysisResult:
    run = AnalysisRun(document_id=document.id, question=request.question, status="processing",
        generation_provider=generation_provider.provider_name, generation_model=generation_provider.model)
    db.add(run)
    db.commit()
    run_id = run.id

    evidence_results = collect_analysis_evidence(db, document.id, request.question, request.top_k, embedding_provider)
    # Retrieval opens a transaction. Release its connection before the potentially long Ollama call.
    db.commit()
    now = datetime.now(timezone.utc)
    if not evidence_results:
        result = AnalysisResult(analysis_status="insufficient_evidence", generation_model=None, generated_at=now,
            summary="확인할 수 없습니다", positives=[], negatives=[], citations=[],
            insufficient_evidence_note=INSUFFICIENT_NOTE, disclaimer=DISCLAIMER)
        _persist_run(db, run_id, status=result.analysis_status, generated_at=now,
            result=_stored_result(result, [], None))
        return result

    allowed = {row["chunk_id"]: row for row in evidence_results}
    packet = {"positive_candidates": [], "negative_candidates": [], "neutral_candidates": []}
    for row in evidence_results:
        candidate = {"chunk_id": str(row["chunk_id"]), "page_number": row["page_number"],
            "section_title": row["section_title"], "text": row["quote"]}
        packet[f"{row['analysis_perspective']}_candidates"].append(candidate)
    try:
        if not generation_provider.available:
            raise GenerationConfigurationError(generation_provider.unavailable_reason or "Ollama 답변 생성을 사용할 수 없습니다.")
        generated: GeneratedAnalysis = generation_provider.generate(_prompt(document, request.question, packet))
        supplied_ids = [chunk_id for item in generated.positives + generated.negatives for chunk_id in item.evidence_chunk_ids]
        invalid = sorted({str(item) for item in supplied_ids if item not in allowed})
        if invalid:
            raise AnalysisValidationError(f"검색 결과에 없는 evidence_chunk_id가 포함되었습니다: {', '.join(invalid)}")

        label = "증권사 리포트 해석" if document.document_type == DocumentType.broker_report else "DART 공시 사실"
        require_korean = _has_hangul(request.question)
        used_across_items: set[UUID] = set()
        perspective_ids = {
            "positive": {row["chunk_id"] for row in evidence_results if row["analysis_perspective"] == "positive"},
            "negative": {row["chunk_id"] for row in evidence_results if row["analysis_perspective"] == "negative"},
        }

        def validated_items(items, perspective: str) -> list[AnalysisItem]:
            validated = []
            for item in items:
                if not _item_tone_is_safe(item.title):
                    continue
                working_item = item
                if not _item_tone_is_safe(item.reason, require_attribution=True):
                    working_item = GeneratedItem(title=item.title,
                        reason=f"보고서는 인용된 원문에서 {item.title} 관련 내용을 제시합니다.",
                        evidence_chunk_ids=item.evidence_chunk_ids)
                if require_korean and (not _has_hangul(item.title) or not _has_hangul(item.reason)):
                    continue
                if _is_general_summary_question(request.question):
                    claim = f"{working_item.title} {working_item.reason}".casefold()
                    evidence_text = " ".join(allowed[chunk_id]["quote"]
                        for chunk_id in working_item.evidence_chunk_ids).casefold()
                    direction_terms = ("증가", "상승", "개선", "확대", "감소", "하락", "악화", "축소")
                    if any(term in claim and term not in evidence_text for term in direction_terms):
                        continue
                if not _item_supported_by_quotes(working_item, allowed):
                    continue
                unique_ids = [chunk_id for chunk_id in dict.fromkeys(working_item.evidence_chunk_ids)
                    if chunk_id not in used_across_items and chunk_id in perspective_ids[perspective]]
                if not unique_ids:
                    continue
                used_across_items.update(unique_ids)
                validated.append(AnalysisItem(title=working_item.title, reason=working_item.reason,
                    evidence_chunk_ids=unique_ids, interpretation_label=label))
            return validated

        positives = validated_items(generated.positives, "positive")
        negatives = validated_items(generated.negatives, "negative")
        generation_items_changed = (len(positives) != len(generated.positives)
            or len(negatives) != len(generated.negatives)
            or any(not _item_tone_is_safe(item.reason, require_attribution=True)
                for item in generated.positives + generated.negatives))
        if _is_general_summary_question(request.question):
            if not positives:
                fallback = _grounded_polarity_fallback(evidence_results, "positive", used_across_items, label)
                if fallback:
                    positives.append(fallback)
                    generation_items_changed = True
            if not negatives:
                fallback = _grounded_polarity_fallback(evidence_results, "negative", used_across_items, label)
                if fallback:
                    negatives.append(fallback)
                    generation_items_changed = True
        used_ids = list(dict.fromkeys(chunk_id for item in positives + negatives for chunk_id in item.evidence_chunk_ids))
        claim_hints = {chunk_id: f"{item.title} {item.reason}" for item in positives + negatives
            for chunk_id in item.evidence_chunk_ids}
        needed_pages = {allowed[chunk_id]["page_number"] for chunk_id in used_ids}
        page_texts = {page.page_number: page.final_text for page in db.query(Page).filter(
            Page.document_id == document.id, Page.page_number.in_(needed_pages)).all()}
        citations = []
        for chunk_id in used_ids:
            row = allowed[chunk_id]
            display = citation_display(row["quote"], row["page_number"],
                page_texts.get(row["page_number"]), claim_hints.get(chunk_id, ""))
            citations.append(AnalysisCitation(chunk_id=chunk_id, filename=row["document_name"],
                company_name=row["company_name"], published_at=row["published_at"],
                issuer=row["publisher"], document_type=row["document_type"],
                page_number=row["page_number"], quote=row["quote"], display_kind=display.kind,
                citation_type=display.kind,
                display_quote=display.display_quote, table_labels=display.table_labels,
                display_note=display.note, table_facts=display.table_facts))
        insufficient = generated.insufficient_evidence_note
        if len(positives) < 3 or len(negatives) < 3:
            insufficient = INSUFFICIENT_NOTE
        status = "completed" if positives or negatives else "insufficient_evidence"
        summary_is_safe = _summary_is_safe(generated.summary, require_korean)
        if (citations and not generation_items_changed and summary_is_safe
                and generated.summary.strip() != "확인할 수 없습니다"):
            summary = generated.summary
        elif citations:
            parts = []
            if positives:
                parts.append(f"보고서는 {', '.join(item.title for item in positives)} 관련 내용을 긍정 요인으로 제시합니다.")
            if negatives:
                parts.append(f"보고서는 {', '.join(item.title for item in negatives)} 관련 내용을 주의할 요인으로 제시합니다.")
            candidate_summary = " ".join(parts)
            summary = (candidate_summary if candidate_summary and _summary_is_safe(candidate_summary, require_korean)
                else "보고서는 인용된 원문을 바탕으로 기업의 실적·제품·수익성과 관련된 요인을 제시합니다.")
        else:
            summary = "확인할 수 없습니다"
        result = AnalysisResult(analysis_status=status, generation_model=generation_provider.model, generated_at=now,
            summary=summary, positives=positives, negatives=negatives, citations=citations,
            insufficient_evidence_note=insufficient, disclaimer=DISCLAIMER)
    except (GenerationConfigurationError, GenerationOutputError, AnalysisValidationError) as exc:
        _record_failure(db, run_id, str(exc), generation_provider)
        raise

    _persist_run(db, run_id, status=result.analysis_status, generated_at=now,
        generation_provider=generation_provider.provider_name, generation_model=generation_provider.model,
        result=_stored_result(result, evidence_results, generated, generation_provider))
    return result
