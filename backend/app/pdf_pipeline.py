import os
from dataclasses import dataclass
from pathlib import Path

import fitz
import pytesseract
from pdf2image import convert_from_path

from .models import TextSource

MIN_NATIVE_TEXT_CHARS = int(os.getenv("OCR_MIN_NATIVE_TEXT_CHARS", "80"))


@dataclass
class ExtractedPage:
    page_number: int; native_text: str | None; ocr_text: str | None; final_text: str
    text_source: TextSource; page_image_path: str | None; ocr_error: str | None


def needs_ocr(native_text: str | None, minimum: int = MIN_NATIVE_TEXT_CHARS) -> bool:
    return len((native_text or "").strip()) < minimum


def ocr_page(pdf_path: Path, page_number: int, image_dir: Path) -> tuple[str, str]:
    image_dir.mkdir(parents=True, exist_ok=True)
    images = convert_from_path(str(pdf_path), dpi=200, first_page=page_number, last_page=page_number, fmt="png")
    if not images:
        raise RuntimeError("페이지 이미지를 생성할 수 없습니다.")
    image_path = image_dir / f"page-{page_number:04d}.png"
    images[0].save(image_path, "PNG")
    return pytesseract.image_to_string(images[0], lang="kor+eng"), str(image_path)


def extract_pdf(pdf_path: Path, image_dir: Path) -> list[ExtractedPage]:
    try:
        document = fitz.open(pdf_path)
    except Exception as exc:
        raise ValueError("손상되었거나 읽을 수 없는 PDF입니다.") from exc
    if not document.is_pdf or document.page_count < 1:
        document.close()
        raise ValueError("유효한 PDF 문서가 아닙니다.")
    results: list[ExtractedPage] = []
    try:
        for index, page in enumerate(document):
            page_number = index + 1
            native = page.get_text("text") or ""
            ocr_text = None; image_path = None; ocr_error = None
            if needs_ocr(native):
                try:
                    ocr_text, image_path = ocr_page(pdf_path, page_number, image_dir)
                except Exception as exc:
                    ocr_error = f"OCR 처리 실패: {type(exc).__name__}"
            if (ocr_text or "").strip() and len(ocr_text.strip()) > len(native.strip()):
                final, source = ocr_text, TextSource.ocr
            elif native.strip():
                final, source = native, TextSource.native
            elif (ocr_text or "").strip():
                final, source = ocr_text or "", TextSource.ocr
            else:
                final, source = "", TextSource.none
            results.append(ExtractedPage(page_number, native or None, ocr_text, final, source, image_path, ocr_error))
    finally:
        document.close()
    return results

