from pathlib import Path

from app.models import TextSource
from app.pdf_pipeline import extract_pdf, needs_ocr
from .helpers import make_pdf


def test_ocr_decision_and_mocked_ocr(tmp_path: Path, monkeypatch) -> None:
    assert needs_ocr("") is True
    assert needs_ocr("x" * 100) is False
    pdf_path = tmp_path / "short.pdf"
    pdf_path.write_bytes(make_pdf("short"))
    monkeypatch.setattr("app.pdf_pipeline.ocr_page", lambda *args: ("OCR restored text", str(tmp_path / "page.png")))
    pages = extract_pdf(pdf_path, tmp_path / "images")
    assert pages[0].text_source == TextSource.ocr
    assert pages[0].final_text == "OCR restored text"

