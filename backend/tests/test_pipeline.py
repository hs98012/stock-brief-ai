from pathlib import Path
from types import SimpleNamespace

from app.models import TextSource
from app.pdf_pipeline import extract_pdf, needs_ocr, OCRPage
from .helpers import make_pdf


def test_short_complete_native_page_does_not_need_ocr(tmp_path: Path, monkeypatch):
    assert needs_ocr('')
    assert not needs_ocr('short')
    pdf_path=tmp_path/'short.pdf'
    pdf_path.write_bytes(make_pdf('short'))
    monkeypatch.setattr('app.pdf_pipeline.ocr_page',lambda *args: (_ for _ in ()).throw(AssertionError('unnecessary OCR')))
    pages=extract_pdf(pdf_path,tmp_path/'images')
    assert pages[0].text_source==TextSource.native and pages[0].ocr_error is None


def test_force_ocr_for_revision_preserves_native_and_records_failure(tmp_path,monkeypatch):
    native='Readable native text'
    pdf_path=tmp_path/'native.pdf'
    pdf_path.write_bytes(make_pdf(native))
    calls=[]
    def fail(*args):
        calls.append(args[1]); raise RuntimeError('fixture failure')
    monkeypatch.setattr('app.pdf_pipeline.ocr_page',fail)
    assert extract_pdf(pdf_path,tmp_path/'images')[0].ocr_error is None
    page=extract_pdf(pdf_path,tmp_path/'images',force_ocr=True)[0]
    assert calls==[1] and page.final_text==native
    assert page.ocr_error and page.provenance['ocr_reasons']==['explicit_inactive_audit']
