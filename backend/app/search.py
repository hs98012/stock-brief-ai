import math
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from uuid import UUID

from rank_bm25 import BM25Okapi
from sqlalchemy.orm import Query, Session

from .embeddings import EmbeddingConfigurationError, EmbeddingProvider
from .models import Chunk, Document, DocumentStatus, DocumentType, Page
from .evidence_integrity import chunk_matches_page
from .table_evidence import verified_table_candidates
from .verification_cache import request_verified

TOKEN_PATTERN = re.compile(r"[가-힣]+|[A-Za-z]+(?:-[A-Za-z0-9]+)*|\d+")
HANGUL_RUN = re.compile(r"[가-힣]+")


def tokenize(text: str) -> list[str]:
    return [token.casefold() for token in TOKEN_PATTERN.findall(text)]


def char_bigram_tokenize(text: str) -> list[str]:
    """Evaluation candidate: Hangul runs become overlapping character bigrams so a
    term still matches with a particle attached (영업이익 / 영업이익이)."""
    tokens: list[str] = []
    for token in tokenize(text):
        if len(token) > 1 and HANGUL_RUN.fullmatch(token):
            tokens.extend(token[index:index + 2] for index in range(len(token) - 1))
        else:
            tokens.append(token)
    return tokens


@dataclass(frozen=True)
class SearchFilters:
    document_id: UUID | None = None
    ticker: str | None = None; company_name: str | None = None; document_type: DocumentType | None = None
    publisher: str | None = None; published_from: date | None = None; published_to: date | None = None


@dataclass(frozen=True)
class SearchExecution:
    results: list[dict]
    vector_search_used: bool
    vector_search_unavailable_reason: str | None
    diagnostics: dict | None = None
    evidence_pack: list[dict] | None = None
    requirements: list[dict] | None = None
    coverage_complete: bool | None = None


def _filtered_query(db: Session, filters: SearchFilters) -> Query:
    query = db.query(Chunk, Page, Document).join(Page, Chunk.page_id == Page.id).join(Document, Chunk.document_id == Document.id)
    query = query.filter(Document.status.in_([DocumentStatus.completed, DocumentStatus.completed_with_errors]), Chunk.content != "")
    if filters.document_id: query = query.filter(Document.id == filters.document_id)
    if filters.ticker: query = query.filter(Document.stock_code == filters.ticker)
    if filters.company_name: query = query.filter(Document.company_name.ilike(f"%{filters.company_name}%"))
    if filters.document_type: query = query.filter(Document.document_type == filters.document_type)
    if filters.publisher: query = query.filter(Document.issuer.ilike(f"%{filters.publisher}%"))
    if filters.published_from: query = query.filter(Document.published_at >= filters.published_from)
    if filters.published_to: query = query.filter(Document.published_at <= filters.published_to)
    return query


def reciprocal_rank_fusion(bm25_ids: list[UUID], vector_ids: list[UUID], k: int = 60, *, bm25_weight: float = 1.0) -> list[tuple[UUID, float, int | None, int | None]]:
    """bm25_weight multiplies only the BM25 term; 1.0 (default) is the production behaviour."""
    if bm25_weight <= 0:
        raise ValueError("bm25_weight must be positive")
    bm25_ranks = {item: rank for rank, item in enumerate(bm25_ids, 1)}
    vector_ranks = {item: rank for rank, item in enumerate(vector_ids, 1)}
    ids = set(bm25_ranks) | set(vector_ranks)
    fused = [(item, (bm25_weight / (k + bm25_ranks[item]) if item in bm25_ranks else 0) + (1 / (k + vector_ranks[item]) if item in vector_ranks else 0), bm25_ranks.get(item), vector_ranks.get(item)) for item in ids]
    return sorted(fused, key=lambda item: (-item[1], item[2] or 10**9, item[3] or 10**9, str(item[0])))


def _cosine_distance(left: list[float], right: list[float]) -> float:
    denominator = math.sqrt(sum(x * x for x in left)) * math.sqrt(sum(x * x for x in right))
    return 1 - (sum(x * y for x, y in zip(left, right, strict=True)) / denominator) if denominator else 1.0


@request_verified
def hybrid_search(db: Session, query_text: str, top_k: int, filters: SearchFilters, provider: EmbeddingProvider, *, rerank: bool = True, diagnostics: bool = False, strict_requirements: bool = False, use_bm25: bool = True, bm25_tokenizer: Callable[[str], list[str]] = tokenize, bm25_weight: float = 1.0) -> SearchExecution:
    rows = [row for row in _filtered_query(db, filters).all()
        if chunk_matches_page(row[0], row[1])]
    return rank_rows(rows, query_text, top_k, provider, db=db, filters=filters,
                     rerank=rerank, diagnostics=diagnostics, strict_requirements=strict_requirements,
                     use_bm25=use_bm25, bm25_tokenizer=bm25_tokenizer, bm25_weight=bm25_weight)


CANDIDATE_LIMIT_FLOOR = 20
RRF_K = 60  # reciprocal_rank_fusion default; reported in diagnostics


def _candidate_limit(top_k: int) -> int:
    return max(top_k * 4, CANDIDATE_LIMIT_FLOOR)


@dataclass(frozen=True)
class _Candidates:
    """BM25/vector candidate lists for one query, before fusion."""
    by_id: dict
    searchable_rows: list
    bm25_ids: list[UUID]
    bm25_matches: list[tuple[UUID, float]]
    bm25_ran: bool
    vector_ids: list[UUID]
    vector_used: bool
    unavailable_reason: str | None
    query_vector: list[float] | None


def _bm25_ranked(matches: list[tuple[UUID, float]]) -> list[UUID]:
    return [item for item, _ in sorted(matches, key=lambda item: (-item[1], str(item[0])))]


def _bm25_candidates(searchable_rows, query_text, top_k, use_bm25, bm25_tokenizer):
    """Returns (top BM25 ids, all scored matches, whether BM25 ran)."""
    from .fused_index import retrieval_text
    query_tokens = bm25_tokenizer(query_text)
    tokenized = [bm25_tokenizer(retrieval_text(chunk,page)) for chunk, page, _ in searchable_rows]
    if not (use_bm25 and bool(query_tokens) and bool(tokenized)):
        return [], [], False
    scores = BM25Okapi(tokenized).get_scores(query_tokens)
    matches = [(chunk.id, float(score)) for (chunk, _, _), tokens, score in zip(searchable_rows, tokenized, scores, strict=True) if set(query_tokens) & set(tokens)]
    return _bm25_ranked(matches)[:_candidate_limit(top_k)], matches, True


def _cosine_ranked(searchable_rows, provider, query_vector) -> list[UUID]:
    """Exact cosine over rows embedded by this provider/model/dimensions."""
    embedded = [(chunk.id, _cosine_distance(chunk.embedding, query_vector)) for chunk, _, _ in searchable_rows
        if chunk.embedding is not None and chunk.embedding_provider == provider.provider_name
        and chunk.embedding_model == provider.model and chunk.embedding_dimensions == provider.dimensions]
    return [item for item, _ in sorted(embedded, key=lambda item: (item[1], str(item[0])))]


def _pgvector_ids(db, filters, provider, query_vector, top_k, row_count, searchable_ids, by_id):
    """pgvector cosine; returns (ids, by_id refreshed with the vector query's rows)."""
    distance = Chunk.embedding.cosine_distance(query_vector)
    vector_query = _filtered_query(db, filters).filter(Chunk.embedding.is_not(None),
        Chunk.embedding_provider == provider.provider_name, Chunk.embedding_model == provider.model,
        Chunk.embedding_dimensions == provider.dimensions)
    if len(searchable_ids) != row_count:
        vector_query = vector_query.filter(Chunk.id.in_(searchable_ids))
    vector_rows = vector_query.order_by(distance).limit(_candidate_limit(top_k)).all()
    vector_rows = [row for row in vector_rows if row[0].id in by_id]
    return [chunk.id for chunk, _, _ in vector_rows], {**by_id, **{row[0].id: row for row in vector_rows}}


def _vector_candidates(db, filters, provider, query_text, top_k, rows, searchable_rows, by_id):
    """Returns (ids, used, unavailable_reason, query_vector, by_id)."""
    if not provider.available:
        return [], False, provider.unavailable_reason or "Ollama vector 검색을 사용할 수 없습니다.", None, by_id
    try:
        query_vector = provider.embed([query_text])[0]
        if db is not None and db.bind is not None and db.bind.dialect.name == "postgresql":
            searchable_ids = {row[0].id for row in searchable_rows}
            vector_ids, by_id = _pgvector_ids(db, filters, provider, query_vector, top_k, len(rows),
                searchable_ids, by_id)
        else:
            vector_ids = _cosine_ranked(searchable_rows, provider, query_vector)[:_candidate_limit(top_k)]
    except EmbeddingConfigurationError as exc:
        return [], False, str(exc), None, by_id
    return vector_ids, True, None, query_vector, by_id


def _collect_candidates(rows, query_text, top_k, provider, db, filters, use_bm25, bm25_tokenizer) -> _Candidates:
    from .fused_index import searchable
    by_id = {chunk.id: (chunk, page, document) for chunk, page, document in rows}
    searchable_rows = [row for row in rows if searchable(row[0], row[1])]
    bm25_ids, matches, bm25_ran = _bm25_candidates(searchable_rows, query_text, top_k, use_bm25, bm25_tokenizer)
    vector_ids, vector_used, unavailable_reason, query_vector, by_id = _vector_candidates(
        db, filters, provider, query_text, top_k, rows, searchable_rows, by_id)
    return _Candidates(by_id, searchable_rows, bm25_ids, matches, bm25_ran,
                       vector_ids, vector_used, unavailable_reason, query_vector)


def _group_by_anchor(pairs) -> dict:
    grouped: dict = {}
    for anchor_id, fact in pairs:
        grouped.setdefault(anchor_id, []).append(fact)
    return grouped


def _verified_facts(rows, query_text, rerank):
    """Returns (table pool, table facts by chunk, numeric facts by chunk)."""
    # Do not change BM25/vector pool size or RRF weights. Promote only cells
    # satisfying row+metric+period, with exact page/chunk provenance.
    from .fused_candidates import deduplicate_verified
    table_pool = deduplicate_verified(verified_table_candidates(rows, query_text)) if rerank else []
    from .fused_candidates import verified_numeric_candidates
    numeric = deduplicate_verified(verified_numeric_candidates(rows, query_text)) if rerank else []
    return table_pool, _group_by_anchor(table_pool), _group_by_anchor(numeric)


def _promote_fused(all_fused, promoted_ids, top_k):
    """Promoted chunks first (in RRF order), then the rest; returns (promoted, fused_by_id, top_k fused)."""
    fused_by_id = {item[0]: item for item in all_fused}
    promoted = sorted(promoted_ids, key=lambda item: (
        next((rank for rank, row in enumerate(all_fused) if row[0] == item), len(all_fused)), str(item)))
    fused = ([fused_by_id.get(item, (item, 0.0, None, None)) for item in promoted]
             + [item for item in all_fused if item[0] not in promoted_ids])[:top_k]
    return promoted, fused_by_id, fused


def _query_requirements(query_text, rerank, strict_requirements):
    from .evidence_bundle import requirements_for
    if rerank and strict_requirements:
        from .evidence_bundle import requirement_resolution
        return requirement_resolution(query_text)['requirements']
    return requirements_for(query_text) if rerank else []


def _evidence_pack(query_text, requirements, all_fused, fused_by_id, promoted, by_id, facts_by_chunk, numeric_by_chunk):
    """Returns (requirements with coverage, evidence pack, coverage complete, selection audit)."""
    from .evidence_bundle import build_evidence_pack
    pool = all_fused[:20]
    included = {item[0] for item in pool}
    pool += [fused_by_id.get(item, (item, 0.0, None, None)) for item in promoted if item not in included]
    rrf_ranks = {item[0]: index for index, item in enumerate(all_fused, 1)}
    selection_audit: dict = {}
    evidence_pack, coverage_complete = build_evidence_pack(query_text, requirements,
        [(rank_data, *by_id[rank_data[0]], rrf_ranks.get(rank_data[0], len(all_fused) + 1))
         for rank_data in pool if rank_data[0] in by_id],
        facts_by_chunk, numeric_by_chunk, audit=selection_audit)
    coverage = {item['requirement_id']: item for item in selection_audit['coverage']}
    requirements = [{**requirement, 'coverage': coverage.get(requirement['id'])}
                    for requirement in requirements]
    return requirements, evidence_pack, coverage_complete, selection_audit


def _rrf_rank(all_fused, chunk_id):
    return next((i for i, row in enumerate(all_fused, 1) if row[0] == chunk_id), None)


def _result_rows(fused, by_id, all_fused, facts_by_chunk, numeric_by_chunk) -> list[dict]:
    results = []
    for rank, (chunk_id, score, bm25_rank, vector_rank) in enumerate(fused, 1):
        chunk, page, document = by_id[chunk_id]
        quote = page.final_text[chunk.char_start:chunk.char_end]
        if quote != chunk.content:
            continue
        results.append({"rank": rank, "rrf_score": score, "bm25_rank": bm25_rank, "vector_rank": vector_rank,
            "chunk_id": chunk.id, "document_id": document.id, "document_name": document.filename, "company_name": document.company_name,
            "ticker": document.stock_code, "publisher": document.issuer, "published_at": document.published_at, "document_type": document.document_type,
            "page_number": page.page_number, "section_title": chunk.section_title, "quote": quote,
            "chunk_char_start": chunk.char_start, "chunk_char_end": chunk.char_end,
            "rrf_rank": _rrf_rank(all_fused, chunk_id),
            "retrieval_reason": "verified_table_conditions" if chunk_id in facts_by_chunk else "verified_numeric_conditions" if chunk_id in numeric_by_chunk else "hybrid_rrf",
            "table_evidence": facts_by_chunk.get(chunk_id, []),
            **({"numeric_evidence": numeric_by_chunk[chunk_id]} if chunk_id in numeric_by_chunk else {})})
    return results


def _diagnostics_trace(rows, candidates: _Candidates, provider, table_pool, top_k, all_fused, selection_audit) -> dict:
    bm_all = _bm25_ranked(candidates.bm25_matches) if candidates.bm25_ran else []
    vec_all = (_cosine_ranked(candidates.searchable_rows, provider, candidates.query_vector)
               if candidates.vector_used else [])
    trace = {"table_candidate_count": len(table_pool), "candidate_limit": _candidate_limit(top_k), "rrf_k": RRF_K, "chunks": [
        {"chunk_id": chunk.id, "page_number": page.page_number, "char_start": chunk.char_start,
         "char_end": chunk.char_end, "bm25_rank": bm_all.index(chunk.id)+1 if chunk.id in bm_all else None,
         "vector_rank": vec_all.index(chunk.id)+1 if chunk.id in vec_all else None,
         "rrf_rank": _rrf_rank(all_fused, chunk.id)}
        for chunk, page, _ in rows]}
    if selection_audit is not None:
        trace['selection'] = selection_audit
    return trace


@request_verified
def rank_rows(rows, query_text, top_k, provider, *, db=None, filters=None,
              rerank=True, diagnostics=False, strict_requirements=False, use_bm25=True,
              bm25_tokenizer=tokenize, bm25_weight=1.0) -> SearchExecution:
    """Shared ranking; isolated callers supply only their own validated rows.

    With no DB, exact cosine uses only those rows, never the active index.
    use_bm25=False, bm25_tokenizer and bm25_weight are evaluation-only switches
    for ablation; the defaults are the production behaviour.

    Stages: candidates (BM25, vector) -> RRF fusion -> verified-fact promotion
    -> evidence pack (when the query has requirements) -> result rows (+ trace).
    """
    rows = [row for row in rows if chunk_matches_page(row[0], row[1])]
    if not rows:
        return SearchExecution([], False, provider.unavailable_reason if not provider.available else None)
    candidates = _collect_candidates(rows, query_text, top_k, provider, db, filters, use_bm25, bm25_tokenizer)
    all_fused = reciprocal_rank_fusion(candidates.bm25_ids, candidates.vector_ids, bm25_weight=bm25_weight)
    table_pool, facts_by_chunk, numeric_by_chunk = _verified_facts(rows, query_text, rerank)
    promoted, fused_by_id, fused = _promote_fused(all_fused, set(facts_by_chunk) | set(numeric_by_chunk), top_k)
    requirements = _query_requirements(query_text, rerank, strict_requirements)
    evidence_pack = coverage_complete = selection_audit = None
    if requirements:
        requirements, evidence_pack, coverage_complete, selection_audit = _evidence_pack(
            query_text, requirements, all_fused, fused_by_id, promoted, candidates.by_id,
            facts_by_chunk, numeric_by_chunk)
    results = _result_rows(fused, candidates.by_id, all_fused, facts_by_chunk, numeric_by_chunk)
    trace = (_diagnostics_trace(rows, candidates, provider, table_pool, top_k, all_fused, selection_audit)
             if diagnostics else None)
    return SearchExecution(results, candidates.vector_used, candidates.unavailable_reason, trace,
                           evidence_pack, requirements or None, coverage_complete)
