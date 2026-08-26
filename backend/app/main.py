from datetime import date
from uuid import UUID

import os

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from .database import get_db
from .embedding_service import embed_document, embedding_counts
from .embeddings import EmbeddingConfigurationError, EmbeddingProvider, get_embedding_provider
from .generation import (GenerationConfigurationError, GenerationOutputError, GenerationProvider,
    get_generation_provider)
from .analysis_service import AnalysisValidationError, analyze_document
from .models import AnalysisRun, Chunk, Document, DocumentType, EmbeddingStatus, Page
from .schemas import (AnalysisRequest, AnalysisResult, DocumentList, DocumentMetadataPatch,
    DocumentSummary, DocumentUploadResult, EmbeddingRunResult, EmbeddingStatusResult, PageResult,
    SearchRequest, SearchResponse)
from .search import SearchFilters, hybrid_search
from .service import ingest_document

app = FastAPI(
    title="Stock Brief AI API",
    description="Evidence-preserving financial PDF ingestion and hybrid retrieval API. It does not generate investment advice.",
    version="0.4.0",
)
app.add_middleware(CORSMiddleware, allow_origins=[item.strip() for item in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",") if item.strip()],
    allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


@app.get("/health", tags=["system"])
def health() -> dict[str, str]:
    """Report whether the API process is available."""
    return {"status": "ok"}


@app.post("/api/v1/documents", response_model=DocumentUploadResult, tags=["documents"])
def upload_document(
    file: UploadFile = File(...), company_name: str = Form(..., min_length=1), stock_code: str = Form(..., min_length=1, max_length=12),
    document_type: DocumentType = Form(...), issuer: str = Form(..., min_length=1), published_at: date = Form(...), db: Session = Depends(get_db),
) -> DocumentUploadResult:
    document, duplicate = ingest_document(db, file, company_name.strip(), stock_code.strip(), document_type, issuer.strip(), published_at)
    return DocumentUploadResult(document_id=document.id, status=document.status, page_count=document.total_pages, duplicate=duplicate)


@app.get("/api/v1/documents", response_model=DocumentList, tags=["documents"])
def list_documents(db: Session = Depends(get_db)) -> DocumentList:
    documents = db.query(Document).order_by(Document.created_at.desc()).all()
    return DocumentList(items=[DocumentSummary.model_validate(item) for item in documents])


@app.get("/api/v1/documents/{document_id}", response_model=DocumentSummary, tags=["documents"])
def get_document(document_id: UUID, db: Session = Depends(get_db)) -> Document:
    document = db.get(Document, document_id)
    if not document:
        raise HTTPException(404, "문서를 찾을 수 없습니다.")
    return document


@app.patch("/api/v1/documents/{document_id}/metadata", response_model=DocumentSummary, tags=["documents"], summary="문서 메타데이터 수정")
def update_document_metadata(document_id: UUID, request: DocumentMetadataPatch, db: Session = Depends(get_db)) -> Document:
    document = db.get(Document, document_id)
    if not document:
        raise HTTPException(404, "문서를 찾을 수 없습니다.")
    changes = request.model_dump(exclude_unset=True)
    for field in ("company_name", "document_type", "issuer", "published_at"):
        if field in changes and changes[field] is None:
            raise HTTPException(422, f"{field}은 null일 수 없습니다.")
    for field in ("company_name", "issuer"):
        if field in changes:
            changes[field] = changes[field].strip()
            if not changes[field]:
                raise HTTPException(422, f"{field}은 공백일 수 없습니다.")
    for field, value in changes.items():
        setattr(document, field, value)
    db.commit(); db.refresh(document)
    return document


@app.get("/api/v1/documents/{document_id}/pages/{page_number}", response_model=PageResult, tags=["documents"])
def get_page(document_id: UUID, page_number: int, db: Session = Depends(get_db)) -> PageResult:
    if page_number < 1:
        raise HTTPException(422, "page_number는 1 이상이어야 합니다.")
    page = db.query(Page).filter(Page.document_id == document_id, Page.page_number == page_number).one_or_none()
    if not page:
        raise HTTPException(404, "페이지를 찾을 수 없습니다.")
    return PageResult(document_id=document_id, page_number=page.page_number, final_text=page.final_text, text_source=page.text_source, ocr_error=page.ocr_error)


@app.post("/api/v1/documents/{document_id}/embeddings", response_model=EmbeddingRunResult, tags=["search"], summary="문서 청크 임베딩 생성")
def create_embeddings(document_id: UUID, db: Session = Depends(get_db), provider: EmbeddingProvider = Depends(get_embedding_provider)) -> EmbeddingRunResult:
    document = db.get(Document, document_id)
    if not document:
        raise HTTPException(404, "문서를 찾을 수 없습니다.")
    if not provider.available:
        raise HTTPException(503, provider.unavailable_reason or "Ollama 임베딩을 사용할 수 없습니다.")
    try:
        run = embed_document(db, document, provider)
    except EmbeddingConfigurationError as exc:
        raise HTTPException(503, str(exc)) from exc
    return EmbeddingRunResult(document_id=document.id, embedding_status=run.document.embedding_status, embedding_provider=provider.provider_name,
        embedding_model=provider.model, embedding_dimensions=provider.dimensions,
        processed_chunk_count=run.processed, skipped_chunk_count=run.skipped, failed_chunk_count=run.failed)


@app.get("/api/v1/documents/{document_id}/embedding-status", response_model=EmbeddingStatusResult, tags=["search"], summary="문서 임베딩 상태 조회")
def get_embedding_status(document_id: UUID, db: Session = Depends(get_db)) -> EmbeddingStatusResult:
    document = db.get(Document, document_id)
    if not document:
        raise HTTPException(404, "문서를 찾을 수 없습니다.")
    total, embedded, failed = embedding_counts(db, document.id, document.embedding_provider, document.embedding_model, document.embedding_dimensions)
    return EmbeddingStatusResult(document_id=document.id, embedding_status=document.embedding_status, embedding_provider=document.embedding_provider,
        embedding_model=document.embedding_model, embedding_dimensions=document.embedding_dimensions,
        embedding_completed_at=document.embedding_completed_at, failure_reason=document.embedding_failure_reason,
        failure_chunk_id=document.embedding_failure_chunk_id, total_chunk_count=total, embedded_chunk_count=embedded, failed_chunk_count=failed)


@app.post("/api/v1/search", response_model=SearchResponse, tags=["search"], summary="BM25와 pgvector 하이브리드 검색")
def search_documents(request: SearchRequest, db: Session = Depends(get_db), provider: EmbeddingProvider = Depends(get_embedding_provider)) -> SearchResponse:
    filters = SearchFilters(ticker=request.ticker, company_name=request.company_name, document_type=request.document_type,
        publisher=request.publisher, published_from=request.published_from, published_to=request.published_to)
    execution = hybrid_search(db, request.query, request.top_k, filters, provider)
    applied = {key: value for key, value in {
        "ticker": request.ticker, "company_name": request.company_name,
        "document_type": request.document_type.value if request.document_type else None, "publisher": request.publisher,
        "published_from": request.published_from, "published_to": request.published_to}.items() if value is not None}
    return SearchResponse(query=request.query, status="evidence_found" if execution.results else "no_evidence", applied_filters=applied,
        vector_search_used=execution.vector_search_used, vector_search_unavailable_reason=execution.vector_search_unavailable_reason,
        results=execution.results)


@app.post("/api/v1/analyses", response_model=AnalysisResult, tags=["analysis"], summary="선택 문서의 근거 기반 초보자용 분석")
def create_analysis(request: AnalysisRequest, db: Session = Depends(get_db),
    embedding_provider: EmbeddingProvider = Depends(get_embedding_provider),
    generation_provider: GenerationProvider = Depends(get_generation_provider)) -> AnalysisResult:
    document = db.get(Document, request.document_id)
    if not document:
        raise HTTPException(404, "문서를 찾을 수 없습니다.")
    embedded_count = db.query(Chunk).filter(Chunk.document_id == document.id, Chunk.embedding.is_not(None)).count()
    if document.embedding_status != EmbeddingStatus.completed or embedded_count == 0:
        raise HTTPException(409, "문서 임베딩이 아직 생성되지 않았습니다. 먼저 문서 임베딩 생성 API를 호출하세요.")
    try:
        return analyze_document(db, document, request, embedding_provider, generation_provider)
    except GenerationConfigurationError as exc:
        raise HTTPException(503, str(exc)) from exc
    except (GenerationOutputError, AnalysisValidationError) as exc:
        raise HTTPException(502, f"안전한 분석 결과를 만들지 못했습니다: {exc}") from exc


@app.post("/internal/evaluations/analysis-trace", include_in_schema=False)
def evaluation_analysis_trace(request: AnalysisRequest, db: Session = Depends(get_db)) -> dict:
    """Local evaluation diagnostics; never included in the user analysis response or OpenAPI."""
    run = db.query(AnalysisRun).filter(AnalysisRun.document_id == request.document_id,
        AnalysisRun.question == request.question).order_by(AnalysisRun.created_at.desc()).first()
    trace = run.result.get("_evaluation_trace") if run and isinstance(run.result, dict) else None
    if not trace:
        raise HTTPException(404, "평가 진단 정보를 찾을 수 없습니다.")
    return trace
