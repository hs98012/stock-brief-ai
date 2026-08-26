import fitz


def make_pdf(*page_texts: str) -> bytes:
    document = fitz.open()
    for text in page_texts:
        page = document.new_page()
        page.insert_textbox(fitz.Rect(40, 40, 550, 800), text, fontsize=11)
    data = document.tobytes()
    document.close()
    return data


def metadata() -> dict[str, str]:
    return {"company_name": "Example Company", "stock_code": "000000", "document_type": "dart_filing", "issuer": "Example Issuer", "published_at": "2026-08-23"}

