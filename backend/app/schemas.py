from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .models import DocumentStatus, DocumentType, EmbeddingStatus, TextSource


class DocumentSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID; company_name: str; stock_code: str | None; document_type: DocumentType; issuer: str
    published_at: date; filename: str; status: DocumentStatus; error_reason: str | None
    total_pages: int | None; created_at: datetime


class DocumentUploadResult(BaseModel):
    document_id: UUID; status: DocumentStatus; page_count: int | None; duplicate: bool


class DocumentList(BaseModel):
    items: list[DocumentSummary]


class PageResult(BaseModel):
    document_id: UUID; page_number: int; final_text: str; text_source: TextSource; ocr_error: str | None


class Citation(BaseModel):
    filename: str; published_at: date; page_number: int; quote: str


class EmbeddingRunResult(BaseModel):
    document_id: UUID; embedding_status: EmbeddingStatus; embedding_provider: str; embedding_model: str; embedding_dimensions: int
    processed_chunk_count: int; skipped_chunk_count: int; failed_chunk_count: int


class EmbeddingStatusResult(BaseModel):
    document_id: UUID; embedding_status: EmbeddingStatus; embedding_provider: str | None; embedding_model: str | None; embedding_dimensions: int | None
    embedding_completed_at: datetime | None; failure_reason: str | None; failure_chunk_id: UUID | None
    total_chunk_count: int; embedded_chunk_count: int; failed_chunk_count: int


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    top_k: int = Field(default=5, ge=1, le=20)
    ticker: str | None = Field(default=None, max_length=12)
    company_name: str | None = Field(default=None, max_length=200)
    document_type: DocumentType | None = None
    publisher: str | None = Field(default=None, max_length=200)
    published_from: date | None = None; published_to: date | None = None

    @model_validator(mode="after")
    def validate_dates(self):
        if self.published_from and self.published_to and self.published_from > self.published_to:
            raise ValueError("published_from은 published_to보다 늦을 수 없습니다.")
        self.query = self.query.strip()
        if not self.query:
            raise ValueError("query는 공백일 수 없습니다.")
        return self


class SearchResultItem(BaseModel):
    rank: int; rrf_score: float; bm25_rank: int | None; vector_rank: int | None
    chunk_id: UUID; document_id: UUID; document_name: str; company_name: str; ticker: str | None
    publisher: str; published_at: date; document_type: DocumentType; page_number: int
    section_title: str | None; quote: str


class SearchResponse(BaseModel):
    query: str; status: str; applied_filters: dict[str, object]
    vector_search_used: bool; vector_search_unavailable_reason: str | None; results: list[SearchResultItem]


class DocumentMetadataPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    company_name: str | None = Field(default=None, min_length=1, max_length=200)
    stock_code: str | None = Field(default=None, pattern=r"^\d{6}$")
    document_type: DocumentType | None = None
    issuer: str | None = Field(default=None, min_length=1, max_length=200)
    published_at: date | None = None


DEFAULT_ANALYSIS_QUESTION = "이 보고서를 읽고 주식 초보자 관점에서 호재와 악재를 각각 최대 3개까지 요약해줘."


class AnalysisRequest(BaseModel):
    document_id: UUID
    question: str = Field(default=DEFAULT_ANALYSIS_QUESTION, min_length=1, max_length=1000)
    top_k: int = Field(default=10, ge=1, le=15)


class GeneratedItem(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    reason: str = Field(min_length=1, max_length=1000)
    evidence_chunk_ids: list[UUID]


class GeneratedAnalysis(BaseModel):
    summary: str = Field(min_length=1, max_length=2000)
    positives: list[GeneratedItem] = Field(max_length=3)
    negatives: list[GeneratedItem] = Field(max_length=3)
    insufficient_evidence_note: str | None = Field(default=None, max_length=500)


class AnalysisItem(GeneratedItem):
    interpretation_label: str


class TableFactValue(BaseModel):
    period: str
    value: str


class TableFacts(BaseModel):
    table_title: str | None = None
    metric: str
    row_label: str
    unit: str
    values: list[TableFactValue]
    interpretation: str | None = None


class AnalysisCitation(BaseModel):
    chunk_id: UUID; filename: str; company_name: str; published_at: date; issuer: str
    document_type: DocumentType; page_number: int; quote: str
    display_kind: Literal["text", "table"] = "text"
    citation_type: Literal["text", "table"] = "text"
    display_quote: str | None = None
    table_labels: list[str] = Field(default_factory=list)
    display_note: str | None = None
    table_facts: TableFacts | None = None


class AnalysisResult(BaseModel):
    analysis_status: str; generation_model: str | None; generated_at: datetime
    summary: str; positives: list[AnalysisItem]; negatives: list[AnalysisItem]
    citations: list[AnalysisCitation]; insufficient_evidence_note: str | None
    disclaimer: str
