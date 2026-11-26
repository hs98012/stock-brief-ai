"""Read-only page coverage for analysis; no embeddings or provider calls."""
import re
from uuid import NAMESPACE_URL, uuid5

from .citation_display import extract_table_facts
from .extraction_provenance import trusted_page_span, validated_stored_facts
from .models import Chunk, Document, Page
from .evidence_integrity import chunk_matches_page, span_is_covered


def document_candidates(db, document_id):
    from .analysis_retrieval import evidence_spans

    document = db.get(Document, document_id)
    if document is None:
        return []
    pages = db.query(Page).filter(Page.document_id == document_id).order_by(Page.page_number).all()
    chunks = db.query(Chunk).filter(Chunk.document_id == document_id).all()
    candidates = []
    for page in pages:
        page_chunks = sorted([chunk for chunk in chunks if chunk_matches_page(chunk, page)],
            key=lambda chunk: (chunk.char_start, chunk.char_end, str(chunk.id)))
        if not page_chunks:
            continue
        base = {"chunk_id": page_chunks[0].id, "document_id": document.id,
            "document_name": document.filename, "company_name": document.company_name,
            "publisher": document.issuer, "published_at": document.published_at,
            "document_type": document.document_type, "page_number": page.page_number,
            "section_title": None, "quote": page.final_text, "chunk_char_start": 0}
        spans = evidence_spans(base, "")
        for fact in validated_stored_facts(page):
            spans.append({**base, "quote": fact["quote"], "char_start": fact["char_start"],
                "char_end": fact["char_end"], "span_kind": "structured_table",
                "quality_status": "valid", "exclusion_reason": None, "analysis_perspective": "neutral",
                "table_verified": True, "table_evidence": [fact], "facts": []})
        # Verified metric/row combinations use the existing strict table-facts
        # validator. Rows are discovered from text layout, not industry names.
        metric_start = None
        offset = 0
        for line in (page.final_text if getattr(page, "extraction", None) is None else "").splitlines(keepends=True):
            if re.match(r"^\s*(?:영업이익률|영업이익|매출액)\b", line):
                metric_start = offset
            elif re.match(r"^\s*(?:표\s*\d+|EBITDA|Capex|QoQ/YoY)", line, re.I):
                metric_start = None
            row = re.match(r"^\s*([가-힣A-Za-z][가-힣A-Za-z /·_-]*?)\s+[-+]?\d", line)
            if metric_start is not None and row and offset > metric_start:
                end = offset + len(line.rstrip())
                quote = page.final_text[metric_start:end]
                facts = extract_table_facts(page.final_text, quote, row.group(1))
                if facts:
                    negative_profit = facts["metric"] in {"영업이익", "영업이익률"} and all(
                        value["value"].startswith("-") for value in facts["values"])
                    polarity = "negative" if negative_profit else "ambiguous"
                    spans.append({**base, "quote": quote, "display_quote": None,
                        "char_start": metric_start, "char_end": end, "span_kind": "table",
                        "quality_status": "valid", "exclusion_reason": None,
                        "analysis_perspective": polarity, "table_verified": True, "table_facts": facts,
                        "facts": [{"subject": facts["row_label"], "metric": facts["metric"],
                            "metric_type": "benefit", "direction": "음수", "comparison": None,
                            "polarity": polarity, "source_phrase": facts["row_label"], "certainty": "reported"}]})
            offset += len(line)
        for span in spans:
            if not trusted_page_span(page, span['char_start'], span['char_end']):
                continue
            overlapping = [chunk for chunk in page_chunks
                if chunk.char_start < span["char_end"] and chunk.char_end > span["char_start"]]
            if not span_is_covered(page, overlapping, span["char_start"], span["char_end"], span["quote"]):
                continue
            # A complete page sentence may cross an old chunk boundary. Preserve
            # every contributing chunk, with the first as the legacy source ID.
            span["source_chunk_id"] = overlapping[0].id
            span["source_chunk_ids"] = [chunk.id for chunk in overlapping]
            if span.get("table_evidence"):
                span["table_source_chunk_ids"] = sorted({str(c.id) for fact in span["table_evidence"]
                    for proof in fact["source_spans"] for c in page_chunks
                    if c.char_start < proof["char_end"] and c.char_end > proof["char_start"]})
                if any(not span_is_covered(page, [c for c in page_chunks if c.char_start < proof["char_end"]
                    and c.char_end > proof["char_start"]], proof["char_start"], proof["char_end"], proof["quote"])
                    for fact in span["table_evidence"] for proof in fact["source_spans"]):
                    continue
            span["chunk_id"] = uuid5(NAMESPACE_URL,
                f"evidence:{document_id}:{page.page_number}:{span['char_start']}:{span['char_end']}:{span['span_kind']}")
            if span.get("table_evidence"):
                fact = span["table_evidence"][0]
                span["chunk_id"] = uuid5(NAMESPACE_URL, f"table:{document_id}:{page.page_number}:{span['char_start']}:{fact['column_name']}:{fact['metric']}")
            if page.final_text[span["char_start"]:span["char_end"]] != span["quote"]:
                continue
            if len(overlapping) == 1 and span["quote"] == overlapping[0].content:
                span["chunk_id"] = overlapping[0].id
            candidates.append(span)
    return candidates
