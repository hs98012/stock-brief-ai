from datetime import date

from app.models import DocumentType
from tests.test_hybrid_search import seed_chunk


def test_document_metadata_patch(client, db) -> None:
    document, _ = seed_chunk(db, "metadata")
    payload = {"company_name": "삼성전자", "stock_code": "005930", "document_type": "broker_report",
        "issuer": "한화리서치", "published_at": "2025-07-09"}
    response = client.patch(f"/api/v1/documents/{document.id}/metadata", json=payload)
    assert response.status_code == 200
    assert response.json()["stock_code"] == "005930" and response.json()["published_at"] == "2025-07-09"
    db.refresh(document)
    assert document.company_name == "삼성전자" and document.issuer == "한화리서치"


def test_stock_code_must_be_six_digits_or_null(client, db) -> None:
    document, _ = seed_chunk(db, "validation")
    assert client.patch(f"/api/v1/documents/{document.id}/metadata", json={"stock_code": "string"}).status_code == 422
    response = client.patch(f"/api/v1/documents/{document.id}/metadata", json={"stock_code": None})
    assert response.status_code == 200 and response.json()["stock_code"] is None


def test_metadata_patch_rejects_immutable_or_null_required_fields(client, db) -> None:
    document, _ = seed_chunk(db, "immutable")
    assert client.patch(f"/api/v1/documents/{document.id}/metadata", json={"filename": "changed.pdf"}).status_code == 422
    assert client.patch(f"/api/v1/documents/{document.id}/metadata", json={"published_at": None}).status_code == 422


def test_analysis_migration_contract() -> None:
    from pathlib import Path
    migration = (Path(__file__).parents[1] / "alembic/versions/20260823_0004_analyses.py").read_text()
    assert "analysis_runs" in migration and "nullable=True" in migration
