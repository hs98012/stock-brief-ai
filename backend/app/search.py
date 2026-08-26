import math
import re
from dataclasses import dataclass
from datetime import date
from uuid import UUID

from rank_bm25 import BM25Okapi
from sqlalchemy.orm import Query, Session

from .embeddings import EmbeddingConfigurationError, EmbeddingProvider
from .models import Chunk, Document, DocumentStatus, DocumentType, Page

TOKEN_PATTERN = re.compile(r"[가-힣]+|[A-Za-z]+(?:-[A-Za-z0-9]+)*|\d+")


def tokenize(text: str) -> list[str]:
    return [token.casefold() for token in TOKEN_PATTERN.findall(text)]


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


def reciprocal_rank_fusion(bm25_ids: list[UUID], vector_ids: list[UUID], k: int = 60) -> list[tuple[UUID, float, int | None, int | None]]:
    bm25_ranks = {item: rank for rank, item in enumerate(bm25_ids, 1)}
    vector_ranks = {item: rank for rank, item in enumerate(vector_ids, 1)}
    ids = set(bm25_ranks) | set(vector_ranks)
    fused = [(item, (1 / (k + bm25_ranks[item]) if item in bm25_ranks else 0) + (1 / (k + vector_ranks[item]) if item in vector_ranks else 0), bm25_ranks.get(item), vector_ranks.get(item)) for item in ids]
    return sorted(fused, key=lambda item: (-item[1], item[2] or 10**9, item[3] or 10**9, str(item[0])))


def _cosine_distance(left: list[float], right: list[float]) -> float:
    denominator = math.sqrt(sum(x * x for x in left)) * math.sqrt(sum(x * x for x in right))
    return 1 - (sum(x * y for x, y in zip(left, right, strict=True)) / denominator) if denominator else 1.0


def hybrid_search(db: Session, query_text: str, top_k: int, filters: SearchFilters, provider: EmbeddingProvider) -> SearchExecution:
    rows = _filtered_query(db, filters).all()
    if not rows:
        return SearchExecution([], False, provider.unavailable_reason if not provider.available else None)
    by_id = {chunk.id: (chunk, page, document) for chunk, page, document in rows}
    query_tokens = tokenize(query_text)
    tokenized = [tokenize(chunk.content) for chunk, _, _ in rows]
    bm25_ids: list[UUID] = []
    if query_tokens:
        scores = BM25Okapi(tokenized).get_scores(query_tokens)
        matches = [(chunk.id, float(score)) for (chunk, _, _), tokens, score in zip(rows, tokenized, scores, strict=True) if set(query_tokens) & set(tokens)]
        bm25_ids = [item for item, _ in sorted(matches, key=lambda item: (-item[1], str(item[0])))[:max(top_k * 4, 20)]]
    vector_ids: list[UUID] = []; vector_used = False; unavailable_reason = None
    if provider.available:
        try:
            query_vector = provider.embed([query_text])[0]
            if db.bind is not None and db.bind.dialect.name == "postgresql":
                distance = Chunk.embedding.cosine_distance(query_vector)
                vector_rows = _filtered_query(db, filters).filter(Chunk.embedding.is_not(None),
                    Chunk.embedding_provider == provider.provider_name, Chunk.embedding_model == provider.model,
                    Chunk.embedding_dimensions == provider.dimensions).order_by(distance).limit(max(top_k * 4, 20)).all()
                vector_ids = [chunk.id for chunk, _, _ in vector_rows]
                for row in vector_rows:
                    by_id[row[0].id] = row
            else:
                embedded = [(chunk.id, _cosine_distance(chunk.embedding, query_vector)) for chunk, _, _ in rows if chunk.embedding is not None
                    and chunk.embedding_provider == provider.provider_name and chunk.embedding_model == provider.model and chunk.embedding_dimensions == provider.dimensions]
                vector_ids = [item for item, _ in sorted(embedded, key=lambda item: (item[1], str(item[0])))[:max(top_k * 4, 20)]]
            vector_used = True
        except EmbeddingConfigurationError as exc:
            unavailable_reason = str(exc)
    else:
        unavailable_reason = provider.unavailable_reason or "Ollama vector 검색을 사용할 수 없습니다."
    fused = reciprocal_rank_fusion(bm25_ids, vector_ids)[:top_k]
    results = []
    for rank, (chunk_id, score, bm25_rank, vector_rank) in enumerate(fused, 1):
        chunk, page, document = by_id[chunk_id]
        quote = page.final_text[chunk.char_start:chunk.char_end]
        if quote != chunk.content:
            continue
        results.append({"rank": rank, "rrf_score": score, "bm25_rank": bm25_rank, "vector_rank": vector_rank,
            "chunk_id": chunk.id, "document_id": document.id, "document_name": document.filename, "company_name": document.company_name,
            "ticker": document.stock_code, "publisher": document.issuer, "published_at": document.published_at, "document_type": document.document_type,
            "page_number": page.page_number, "section_title": chunk.section_title, "quote": quote})
    return SearchExecution(results, vector_used, unavailable_reason)
