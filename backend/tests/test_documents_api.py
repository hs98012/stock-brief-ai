from fastapi.testclient import TestClient

from app.models import Chunk, Page
from .helpers import make_pdf, metadata


def test_text_pdf_ingestion_and_page_number(client: TestClient, db) -> None:
    first = "This is a plain document extraction test sentence. " * 4
    second = "The second page keeps its original page number and exact text offsets. " * 3
    response = client.post("/api/v1/documents", data=metadata(), files={"file": ("report.pdf", make_pdf(first, second), "application/pdf")})
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "completed" and payload["page_count"] == 2 and payload["duplicate"] is False
    page = client.get(f"/api/v1/documents/{payload['document_id']}/pages/2").json()
    assert page["page_number"] == 2 and page["text_source"] == "native"
    stored_page = db.query(Page).filter(Page.page_number == 2).one()
    for chunk in db.query(Chunk).filter(Chunk.page_id == stored_page.id):
        assert chunk.page_number == 2
        assert stored_page.final_text[chunk.char_start:chunk.char_end] == chunk.content


def test_duplicate_hash_is_not_ingested_twice(client: TestClient) -> None:
    pdf = make_pdf("Duplicate detection uses the exact same bytes. " * 4)
    first = client.post("/api/v1/documents", data=metadata(), files={"file": ("one.pdf", pdf, "application/pdf")}).json()
    second = client.post("/api/v1/documents", data=metadata(), files={"file": ("two.pdf", pdf, "application/pdf")}).json()
    assert first["document_id"] == second["document_id"]
    assert second["duplicate"] is True
    assert len(client.get("/api/v1/documents").json()["items"]) == 1


def test_rejects_wrong_extension_and_corrupt_pdf(client: TestClient) -> None:
    wrong = client.post("/api/v1/documents", data=metadata(), files={"file": ("notes.txt", b"text", "text/plain")})
    corrupt = client.post("/api/v1/documents", data=metadata(), files={"file": ("broken.pdf", b"%PDF-not-valid", "application/pdf")})
    assert wrong.status_code == 415
    assert corrupt.status_code == 400
    assert "PDF" in wrong.json()["detail"] and "PDF" in corrupt.json()["detail"]

